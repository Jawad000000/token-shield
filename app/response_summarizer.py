"""
Response Summarizer — compresses old assistant responses in conversation history.

In multi-turn conversations, previous assistant responses are sent back verbatim.
A 500-token AI response from turn 1 is re-sent on turns 2, 3, 4, etc.

This module replaces older assistant responses with concise summaries,
preserving key information (definitions, formulas, enumerations) while
drastically reducing token count.

Only compresses assistant messages that are NOT the most recent one.
Never touches user messages or system messages.
"""
from __future__ import annotations

import copy
import re
from typing import Any

# Fenced code block pattern — extract and preserve inline
FENCED_BLOCK_RE = re.compile(r"```[^\n`]*\n[\s\S]*?```")

# Sentence splitter: captures ". ", "! ", "? " boundaries
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")

# Patterns that indicate a "high-value" sentence worth keeping in summaries
DEFINITION_PATTERNS = [
    re.compile(r"\b(?:is defined as|refers to|is the|means that|is a|are a)\b", re.I),
    re.compile(r"\b(?:definition|formula|equation|theorem|law|principle|rule)\b", re.I),
]
ENUMERATION_PATTERN = re.compile(r"^\s*(?:\d+[.):]|[-•*])\s+", re.MULTILINE)
FORMULA_PATTERN = re.compile(r"[=<>≤≥]+.*[a-zA-Z].*[=<>≤≥+\-*/^]")
KEY_TERM_PATTERN = re.compile(r"\*\*[^*]+\*\*")  # Bold terms in markdown

# Max length for a summarized assistant message (in characters)
DEFAULT_SUMMARY_MAX_CHARS = 200
# Min length of assistant message to bother summarizing
MIN_RESPONSE_LENGTH = 150
# Keep the last N assistant messages verbatim
KEEP_RECENT_ASSISTANT = 1


def _score_sentence(sentence: str) -> float:
    """
    Score a sentence by its information density for study conversations.
    Higher score = more important to keep in the summary.
    """
    score = 0.0
    stripped = sentence.strip()

    if not stripped or len(stripped) < 10:
        return 0.0

    # Definitions and key concepts
    for pattern in DEFINITION_PATTERNS:
        if pattern.search(stripped):
            score += 3.0
            break

    # Formulas (e.g., "F = ma", "E = mc^2")
    if FORMULA_PATTERN.search(stripped):
        score += 4.0

    # Bold/emphasized terms (likely key concepts)
    bold_matches = KEY_TERM_PATTERN.findall(stripped)
    score += len(bold_matches) * 1.5

    # Enumeration items (numbered lists, bullet points)
    if ENUMERATION_PATTERN.match(stripped):
        score += 1.5

    # Sentences with numbers/quantities tend to be factual
    if re.search(r"\d+", stripped):
        score += 0.5

    # Longer sentences get a small bonus (more content)
    if len(stripped) > 80:
        score += 0.5

    # Short filler sentences get penalized
    if len(stripped) < 30:
        score -= 1.0

    return max(0.0, score)


def _extract_code_blocks(text: str) -> list[str]:
    """Extract code blocks from text (these are always preserved in summaries)."""
    return FENCED_BLOCK_RE.findall(text)


def summarize_response(text: str, max_chars: int = DEFAULT_SUMMARY_MAX_CHARS) -> str:
    """
    Summarize an assistant response by keeping the highest-scoring sentences.
    Code blocks are preserved verbatim.
    """
    if len(text) <= max_chars:
        return text

    # Extract and preserve code blocks
    code_blocks = _extract_code_blocks(text)
    # Remove code blocks from text for sentence processing
    prose = FENCED_BLOCK_RE.sub("", text).strip()

    # Split into sentences
    sentences = SENTENCE_END_RE.split(prose)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return text[:max_chars] + "..."

    # Score each sentence
    scored = [(s, _score_sentence(s)) for s in sentences]
    scored.sort(key=lambda x: -x[1])

    # Take highest-scoring sentences until we hit max_chars
    kept: list[str] = []
    char_count = 0
    for sentence, score in scored:
        if char_count + len(sentence) > max_chars and kept:
            break
        kept.append(sentence)
        char_count += len(sentence)

    # Re-order kept sentences by their original position
    original_order = {s: i for i, s in enumerate(sentences)}
    kept.sort(key=lambda s: original_order.get(s, 0))

    summary_text = " ".join(kept)

    # Add code blocks back if they fit
    code_text = "\n".join(code_blocks)
    if code_text:
        summary_text = f"{summary_text}\n{code_text}"

    word_count = len(text.split())
    return f"[AI prior response (~{word_count} words): {summary_text}]"


def summarize_assistant_responses(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """
    Compresses older assistant responses in the conversation history.

    - Finds all assistant messages
    - Keeps the most recent KEEP_RECENT_ASSISTANT messages verbatim
    - Summarizes all older assistant messages

    Returns (optimized_messages, count_of_responses_summarized).
    Never mutates input objects.
    """
    if not messages or len(messages) < 3:
        return messages, 0

    # Find indices of assistant messages
    assistant_indices: list[int] = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant":
            assistant_indices.append(i)

    # If we have fewer than KEEP_RECENT_ASSISTANT + 1 assistant messages,
    # there's nothing old enough to summarize
    if len(assistant_indices) <= KEEP_RECENT_ASSISTANT:
        return messages, 0

    # Indices to summarize = all except the last KEEP_RECENT_ASSISTANT
    indices_to_summarize = set(assistant_indices[:-KEEP_RECENT_ASSISTANT])

    optimized: list[dict[str, Any]] = []
    summarized_count = 0

    for i, msg in enumerate(messages):
        if i in indices_to_summarize:
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > DEFAULT_SUMMARY_MAX_CHARS:
                summary = summarize_response(content)
                if summary != content:
                    cloned = dict(msg)
                    cloned["content"] = summary
                    optimized.append(cloned)
                    summarized_count += 1
                    continue

        optimized.append(msg)

    return optimized, summarized_count
