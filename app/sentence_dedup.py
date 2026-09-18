"""
Sentence-Level Dedup — removes duplicate sentences within a single message.

Students frequently paste or type the same sentence multiple times:
    "A derivative is the rate of change. A derivative is the rate of change."

This module catches those intra-message repetitions that the paragraph-level
dedup in memory.py misses (its 180-char minimum is too high for single sentences).

Only operates on user messages.  Code blocks are left untouched.
"""
from __future__ import annotations

import copy
import re
from typing import Any

# Fenced code block pattern — content inside these is never touched
FENCED_BLOCK_RE = re.compile(r"(```[^\n`]*\n[\s\S]*?```)")

# Sentence boundary splitter: split on ". ", "! ", "? ", or newline
# but keep the delimiter attached to the preceding sentence.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n")

# Minimum length for a sentence to be eligible for dedup.
# Short phrases like "I see." or "OK." should not be collapsed.
MIN_SENTENCE_LEN = 20


def _normalize_sentence(s: str) -> str:
    """Lowercase, collapse whitespace — used only for comparison."""
    return " ".join(s.lower().split())


def dedup_sentences_in_segment(text: str) -> tuple[str, int]:
    """
    Removes duplicate sentences from a prose segment (outside code blocks).
    Returns (deduped_text, removed_count).
    """
    sentences = SENTENCE_SPLIT_RE.split(text)
    if len(sentences) <= 1:
        return text, 0

    seen: dict[str, int] = {}  # normalized → index of first occurrence
    kept: list[str] = []
    counts: dict[int, int] = {}  # index → occurrence count
    removed = 0

    for s in sentences:
        stripped = s.strip()
        if not stripped:
            kept.append(s)
            continue

        if len(stripped) < MIN_SENTENCE_LEN:
            kept.append(s)
            continue

        norm = _normalize_sentence(stripped)
        if norm in seen:
            # Duplicate — increment count, skip the sentence
            first_idx = seen[norm]
            counts[first_idx] = counts.get(first_idx, 1) + 1
            removed += 1
        else:
            seen[norm] = len(kept)
            counts[len(kept)] = 1
            kept.append(s)

    if removed == 0:
        return text, 0

    # Append [×N] markers to sentences that had duplicates
    final_parts: list[str] = []
    for idx, sentence in enumerate(kept):
        count = counts.get(idx, 1)
        if count > 1:
            final_parts.append(f"{sentence.rstrip()} [x{count}]")
        else:
            final_parts.append(sentence)

    return "\n".join(final_parts), removed


def dedup_sentences_in_text(text: str) -> tuple[str, int]:
    """
    Splits text into code blocks and prose segments.
    Only deduplicates sentences in prose — code blocks are untouched.
    """
    if not text or len(text) < MIN_SENTENCE_LEN * 2:
        return text, 0

    parts = FENCED_BLOCK_RE.split(text)
    new_parts: list[str] = []
    total_removed = 0

    for part in parts:
        if part.startswith("```"):
            new_parts.append(part)
        else:
            deduped, count = dedup_sentences_in_segment(part)
            new_parts.append(deduped)
            total_removed += count

    return "".join(new_parts), total_removed


def dedup_sentences_in_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """
    Applies sentence-level deduplication across all user messages.
    Returns (optimized_messages, total_sentences_removed).
    Never mutates input objects.
    """
    optimized: list[dict[str, Any]] = []
    total_removed = 0

    for msg in messages:
        # Only deduplicate user messages — don't touch system or assistant
        if msg.get("role") != "user":
            optimized.append(msg)
            continue

        content = msg.get("content")
        if isinstance(content, str) and len(content) >= MIN_SENTENCE_LEN * 2:
            deduped_text, count = dedup_sentences_in_text(content)
            if count > 0:
                cloned = dict(msg)
                cloned["content"] = deduped_text
                optimized.append(cloned)
                total_removed += count
                continue

        optimized.append(msg)

    return optimized, total_removed
