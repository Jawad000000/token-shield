"""
Phrase Compactor — replaces verbose English phrases with shorter equivalents.

Every substitution is semantically identical: "in order to" → "to",
"due to the fact that" → "because", etc.  LLMs parse both forms identically.
Only operates on prose outside of fenced code blocks to avoid mutating code strings.
"""
from __future__ import annotations

import copy
import re
from typing import Any

# ── Fenced code block detection ──────────────────────────────────────────────
FENCED_BLOCK_PATTERN = re.compile(r"(```[^\n`]*\n[\s\S]*?```)")

# ── Verbose → Compact phrase map (longest-first for greedy matching) ─────────
# Each tuple: (compiled_regex, replacement_string)
# Sorted by length of original phrase descending so longer matches win
_PHRASE_MAP_RAW: list[tuple[str, str]] = [
    ("in spite of the fact that", "although"),
    ("it is important to note that", "note:"),
    ("due to the fact that", "because"),
    ("at this point in time", "now"),
    ("for the purpose of", "to"),
    ("with respect to", "regarding"),
    ("in the event that", "if"),
    ("on the other hand", "however"),
    ("with regard to", "regarding"),
    ("a large number of", "many"),
    ("in addition to", "besides"),
    ("first and foremost", "first"),
    ("each and every", "every"),
    ("in order to", "to"),
    ("whether or not", "whether"),
    ("as well as", "and"),
    ("the fact that", "that"),
    ("a number of", "several"),
    ("make sure to", "ensure"),
    ("be sure to", "ensure"),
    ("is able to", "can"),
    ("are able to", "can"),
    ("was able to", "could"),
    ("has the ability to", "can"),
    ("have the ability to", "can"),
    ("take into account", "consider"),
    ("take into consideration", "consider"),
    ("at the present time", "currently"),
    ("in the near future", "soon"),
    ("on a regular basis", "regularly"),
    ("in the process of", "currently"),
    ("prior to", "before"),
    ("subsequent to", "after"),
    ("in close proximity to", "near"),
    ("a sufficient number of", "enough"),
    ("in the majority of cases", "usually"),
]

# Pre-compile regexes for case-insensitive word-boundary matching
PHRASE_RULES: list[tuple[re.Pattern, str]] = []
for _phrase, _replacement in sorted(_PHRASE_MAP_RAW, key=lambda x: -len(x[0])):
    # Use word boundaries and case-insensitive matching
    _pattern = re.compile(r"\b" + re.escape(_phrase) + r"\b", re.IGNORECASE)
    PHRASE_RULES.append((_pattern, _replacement))


def compact_phrases_in_segment(text: str) -> tuple[str, int]:
    """
    Applies phrase compaction to a text segment (outside code blocks).
    Returns (compacted_text, substitution_count).
    """
    total_subs = 0

    for pattern, replacement in PHRASE_RULES:
        new_text, count = pattern.subn(replacement, text)
        if count > 0:
            text = new_text
            total_subs += count

    # Clean up: collapse double spaces that might result from substitutions
    if total_subs > 0:
        text = re.sub(r"  +", " ", text)

    return text, total_subs


def compact_phrases_in_text(text: str) -> tuple[str, int]:
    """
    Splits text into code blocks and prose segments.
    Only compacts phrases in prose — code blocks are untouched.
    Returns (optimized_text, total_substitutions).
    """
    if not text:
        return text, 0

    parts = FENCED_BLOCK_PATTERN.split(text)
    new_parts: list[str] = []
    total_subs = 0

    for part in parts:
        if part.startswith("```"):
            # Code block: keep intact
            new_parts.append(part)
        else:
            # Prose: apply phrase compaction
            compacted, subs = compact_phrases_in_segment(part)
            new_parts.append(compacted)
            total_subs += subs

    return "".join(new_parts), total_subs


def compact_phrases_in_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """
    Applies verbose phrase compaction across all messages.
    Returns (optimized_messages, total_phrases_compacted).
    Never mutates input objects.
    """
    optimized: list[dict[str, Any]] = []
    total_compacted = 0

    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and len(content) > 30:
            compacted_text, count = compact_phrases_in_text(content)
            if count > 0:
                total_compacted += count
                cloned = dict(msg)
                cloned["content"] = compacted_text
                optimized.append(cloned)
                continue
        optimized.append(msg)

    return optimized, total_compacted
