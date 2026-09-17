from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.budgeter import get_budget_directive


@dataclass(frozen=True)
class ShrinkResult:
    turns_shrunk: int = 0
    applied: bool = False
    budget_mode: str = "saving"


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
    turn_summaries: list[str] = []

    for msg in history_messages:
        role = msg.get("role", "user")
        content_text = _extract_text(msg.get("content"))
        if role == "system":
            if content_text:
                original_system_prompts.append(content_text)
        else:
            turn_summaries.append(_summarize_turn(role, content_text))

    # Build compact system context block
    sections: list[str] = []
    if original_system_prompts:
        sections.append("[System Instructions]\n" + "\n".join(original_system_prompts))

    if turn_summaries:
        sections.append("[Previous Session Summary]\n" + "\n".join(f"- {s}" for s in turn_summaries))

    if directive:
        sections.append(directive)

    compact_system_text = "\n\n".join(sections).strip()

    shrunk_messages: list[dict[str, Any]] = []
    if compact_system_text:
        shrunk_messages.append({"role": "system", "content": compact_system_text})

    shrunk_messages.append(latest_user_msg)
    shrunk_messages.extend(subsequent_messages)

    turns_shrunk = len(history_messages)
    return shrunk_messages, ShrinkResult(turns_shrunk=turns_shrunk, applied=True, budget_mode=budget_mode)
