from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from app.budgeter import get_budget_directive

# Number of trailing history messages kept byte-for-byte before the latest user turn.
# Truncated summaries destroy the detail a model needs; recent turns carry most of it.
DEFAULT_VERBATIM_TURNS = 2


def _verbatim_turn_count() -> int:
    try:
        value = int(os.getenv("TOKENSHIELD_VERBATIM_TURNS", str(DEFAULT_VERBATIM_TURNS)))
    except ValueError:
        return DEFAULT_VERBATIM_TURNS
    return max(0, value)


@dataclass(frozen=True)
class ShrinkResult:
    turns_shrunk: int = 0
    applied: bool = False
    budget_mode: str = "saving"
    turns_kept_verbatim: int = 0


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return " ".join(parts)
    return str(content or "")


def _clean_text(text: str) -> str:
    # Drop intermediate <thought> tags or thinking blocks
    cleaned = re.sub(r"<thought>[\s\S]*?</thought>", "", text, flags=re.IGNORECASE)
    return " ".join(cleaned.strip().split())


def _summarize_turn(role: str, text: str) -> str:
    cleaned = _clean_text(text)
    max_len = 90
    if len(cleaned) > max_len:
        truncated = cleaned[:max_len].rsplit(" ", 1)[0] + "..."
    else:
        truncated = cleaned

    if role == "user":
        return f"User: {truncated}"
    if role == "assistant":
        return f"AI: {truncated}"
    return f"{role}: {truncated}"


def shrink_conversation(
    messages: list[dict[str, Any]],
    requested_budget_mode: str | None = None,
    raw_tokens: int = 0,
) -> tuple[list[dict[str, Any]], ShrinkResult]:
    directive, budget_mode = get_budget_directive(requested_budget_mode, raw_tokens)

    if not messages:
        return messages, ShrinkResult(turns_shrunk=0, applied=False, budget_mode=budget_mode)

    # Find the latest user message index
    latest_user_idx = None
    for idx in reversed(range(len(messages))):
        if messages[idx].get("role") == "user":
            latest_user_idx = idx
            break

    # If no user message or only 1-2 messages, we don't shrink turns, but we can inject budget
    if latest_user_idx is None or len(messages) <= 2:
        if not directive:
            return messages, ShrinkResult(turns_shrunk=0, applied=False, budget_mode=budget_mode)

        # Inject budget directive into system message
        cloned = [dict(m) for m in messages]
        if cloned and cloned[0].get("role") == "system":
            sys_text = _extract_text(cloned[0].get("content"))
            cloned[0]["content"] = f"{sys_text}\n\n{directive}".strip()
        else:
            cloned.insert(0, {"role": "system", "content": directive})

        return cloned, ShrinkResult(turns_shrunk=0, applied=False, budget_mode=budget_mode)

    # Multi-turn conversation (> 2 messages)
    history_messages = messages[:latest_user_idx]
    latest_user_msg = dict(messages[latest_user_idx])
    subsequent_messages = [dict(m) for m in messages[latest_user_idx + 1:]]

    original_system_prompts: list[str] = []
    conversation_turns: list[dict[str, Any]] = []

    for msg in history_messages:
        if msg.get("role") == "system":
            content_text = _extract_text(msg.get("content"))
            if content_text:
                original_system_prompts.append(content_text)
        else:
            conversation_turns.append(msg)

    # Keep the most recent turns intact; only older turns get summarized.
    keep = _verbatim_turn_count()
    if keep > 0:
        verbatim_turns = [dict(m) for m in conversation_turns[-keep:]]
        older_turns = conversation_turns[:-keep] if len(conversation_turns) > keep else []
    else:
        verbatim_turns = []
        older_turns = conversation_turns

    turn_summaries = [
        _summarize_turn(msg.get("role", "user"), _extract_text(msg.get("content")))
        for msg in older_turns
    ]

    # Section order matters: stable content first so provider prompt-prefix caching
    # can match across turns. The summary block grows by append, so it comes last.
    sections: list[str] = []
    if original_system_prompts:
        sections.append("[System Instructions]\n" + "\n".join(original_system_prompts))

    if directive:
        sections.append(directive)

    if turn_summaries:
        sections.append("[Earlier Conversation Summary]\n" + "\n".join(f"- {s}" for s in turn_summaries))

    compact_system_text = "\n\n".join(sections).strip()

    shrunk_messages: list[dict[str, Any]] = []
    if compact_system_text:
        shrunk_messages.append({"role": "system", "content": compact_system_text})

    shrunk_messages.extend(verbatim_turns)
    shrunk_messages.append(latest_user_msg)
    shrunk_messages.extend(subsequent_messages)

    turns_shrunk = len(older_turns)
    return shrunk_messages, ShrinkResult(
        turns_shrunk=turns_shrunk,
        applied=bool(turn_summaries),
        budget_mode=budget_mode,
        turns_kept_verbatim=len(verbatim_turns),
    )
