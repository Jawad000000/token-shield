"""
Query-Aware History Filter — prunes off-topic historical turns in multi-turn sessions.

In multi-turn study and coding chats, users often transition between different topics:
  Turn 1: "How do I configure virtualenv in Python?" -> Assistant answers with 300 words.
  Turn 2: "What is the difference between pip and conda?" -> Assistant answers with 200 words.
  Turn 3: "Now let's switch to DBMS: What is a B+ tree?"

By Turn 3, Turn 1 (Python virtualenv) is completely irrelevant to B+ trees.
Carrying hundreds of tokens of old, off-topic turns wastes money and pollutes the LLM context window.

This module scores older historical turns against the *current* user question:
- Keeps the immediate recent exchange verbatim (last turn + current query).
- Keeps older turns that share semantic overlap or domain keywords with the current query.
- Compresses or prunes older turns that are completely orthogonal/superseded.
- Strictly protects the system prompt and the current active user question.
"""
from __future__ import annotations

import re
from typing import Any

# Punctuation stripper for word tokenization
WORD_RE = re.compile(r"[a-zA-Z0-9_]{3,}")

# Common English stopwords to ignore when measuring domain overlap
STOPWORDS = {
    "the", "and", "that", "have", "for", "not", "with", "you", "this",
    "but", "his", "from", "they", "say", "her", "she", "will", "one",
    "all", "would", "there", "their", "what", "out", "about", "who",
    "get", "which", "when", "make", "can", "like", "time", "just",
    "him", "know", "take", "people", "into", "year", "your", "good",
    "some", "could", "them", "see", "other", "than", "then", "now",
    "look", "only", "come", "its", "over", "think", "also", "back",
    "after", "use", "two", "how", "our", "work", "first", "well",
    "way", "even", "new", "want", "because", "any", "these", "give",
    "day", "most", "us", "explain", "please", "help",
}

# Min total messages to bother running history filtering (needs at least 2 full turns + new query)
MIN_MESSAGES_FOR_FILTER = 5
# Protect the most recent turn (user + assistant) + current query
MIN_KEEP_RECENT_MESSAGES = 3


def _extract_keywords(text: str) -> set[str]:
    """Extract informative lowercase keywords (>=3 chars, non-stopword)."""
    words = WORD_RE.findall(text.lower())
    return {w for w in words if w not in STOPWORDS}


def _compute_overlap(keywords_a: set[str], keywords_b: set[str]) -> float:
    """Computes Jaccard keyword overlap ratio between two keyword sets."""
    if not keywords_a or not keywords_b:
        return 0.0
    intersection = keywords_a & keywords_b
    union = keywords_a | keywords_b
    return len(intersection) / len(union) if union else 0.0


def filter_query_aware_history(
    messages: list[dict[str, Any]],
    overlap_threshold: float = 0.08,
) -> tuple[list[dict[str, Any]], int]:
    """
    Evaluates older turns in conversation history against the current user query.
    If an older turn has low relevance / zero keyword overlap with the current question,
    it is compacted to a 1-line topical marker, freeing up massive context window tokens.

    Returns:
        (optimized_messages, count_of_turns_pruned)
    """
    if not messages or len(messages) < MIN_MESSAGES_FOR_FILTER:
        return messages, 0

    # 1. Identify the latest user query
    current_query_msg = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            current_query_msg = msg
            break

    if not current_query_msg or not isinstance(current_query_msg.get("content"), str):
        return messages, 0

    current_query_text = current_query_msg["content"]
    current_keywords = _extract_keywords(current_query_text)

    # If current query has almost no keywords (e.g. "continue" or "ok"), don't prune
    if len(current_keywords) < 2:
        return messages, 0

    optimized: list[dict[str, Any]] = []
    pruned_count = 0
    cutoff_index = len(messages) - MIN_KEEP_RECENT_MESSAGES

    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")

        # Always protect system prompt and the recent exchange verbatim
        if role == "system" or i >= cutoff_index or not isinstance(content, str):
            optimized.append(msg)
            continue

        # Check for code blocks: if message contains code, don't drop if current query mentions code
        has_code = "```" in content
        mentions_code = any(k in current_keywords for k in {"code", "function", "error", "line", "script", "bug", "implement"})

        if has_code and mentions_code:
            optimized.append(msg)
            continue

        # Compute keyword relevance with current user query
        turn_keywords = _extract_keywords(content)
        overlap = _compute_overlap(current_keywords, turn_keywords)

        # If overlap is below threshold, compact this older turn
        if overlap < overlap_threshold:
            first_line = content.strip().split("\n")[0][:60].strip()
            compact_marker = f"[{role.capitalize()} prior context: {first_line}...]"
            
            # Only replace if the marker is actually shorter than original content
            if len(compact_marker) < len(content) * 0.8:
                cloned = dict(msg)
                cloned["content"] = compact_marker
                optimized.append(cloned)
                pruned_count += 1
                continue

        optimized.append(msg)

    return optimized, pruned_count
