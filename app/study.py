from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


COMMON_STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "can", "could", "will", "would", "should", "may", "might",
    "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her",
    "what", "why", "how", "when", "where", "which", "who", "whom",
    "explain", "describe", "define", "tell", "give", "show", "help", "me", "about",
    "example", "please", "difference", "between", "versus", "vs", "algorithm",
    "concept", "python", "javascript", "java", "c++", "code", "function", "again",
    "work", "works", "working", "mean", "means", "meaning", "occur", "occurs", "happen", "happens", "use", "used",
}

QUESTION_PREFIX_PATTERNS = [
    r"^(?:can\s+you\s+)?(?:please\s+)?(?:explain|describe|define|tell\s+me\s+about)\s+(?:the\s+)?(?:concept\s+of\s+)?",
    r"^(?:what\s+is|what\s+are|why\s+is|why\s+does|how\s+does|how\s+do|how\s+to)\s+(?:the\s+)?",
    r"^(?:give\s+me\s+an?\s+example\s+of)\s+(?:the\s+)?",
]


def extract_topic(question: str, existing_topics: list[str] | None = None) -> str:
    """
    Extracts a canonical topic name from a question.
    If an existing session topic shares high similarity or word overlap,
    clusters into that existing topic.
    """
    if not question:
        return "general"

    # Remove context fingerprint prefix if present: [Context: ...] Question: ...
    if "Question:" in question:
        question = question.split("Question:", 1)[-1]

    clean = question.strip().lower()
    for pattern in QUESTION_PREFIX_PATTERNS:
        clean = re.sub(pattern, "", clean, flags=re.IGNORECASE).strip()

    # Remove punctuation except hyphens
    clean = re.sub(r"[^\w\s-]", " ", clean)
    clean = " ".join(clean.split())

    if not clean:
        return "general"

    # Check if any existing topic is a substring or superset
    if existing_topics:
        words_in_clean = set(clean.split())
        for existing in existing_topics:
            norm_existing = existing.lower().strip()
            # Direct substring match
            if norm_existing in clean or clean in norm_existing:
                return norm_existing
            # Word overlap match
            existing_words = set(norm_existing.split()) - COMMON_STOPWORDS
            if existing_words and len(existing_words & words_in_clean) >= len(existing_words):
                return norm_existing

    # Filter out stopwords to isolate core technical terms
    tokens = [w for w in clean.split() if w not in COMMON_STOPWORDS and len(w) > 1]
    if tokens:
        # Take the top 1 to 3 words as the topic
        topic = " ".join(tokens[:3])
    else:
        # Fallback to first 2 words if all words were stopwords
        raw_tokens = clean.split()
        topic = " ".join(raw_tokens[:2]) if raw_tokens else "general"

    return topic.strip()


def assess_struggle(events: list[dict[str, Any]], current_topic: str) -> tuple[bool, int]:
    """
    Evaluates whether the student is struggling with the topic:
    Rule:
    - >= 3 related questions in the same topic -> struggling
    - >= 2 cache/soft-cache hits in the same topic -> struggling
    Returns (is_struggling, repeat_count).
    """
    topic_events = [e for e in events if e.get("topic", "").lower() == current_topic.lower()]
    repeat_count = len(topic_events) + 1  # Including the current request

    cache_hits = sum(1 for e in topic_events if bool(e.get("cache_hit")))

    is_struggling = (repeat_count >= 3) or (cache_hits >= 2)
    return is_struggling, repeat_count


def _first_sentence(text: str) -> str:
    cleaned = text.strip()
    match = re.split(r"(?<=[.!?])\s+", cleaned)
    if match and match[0]:
        return match[0].strip()
    return cleaned[:150]


def generate_study_package(
    session_id: str,
    events: list[dict[str, Any]],
    stats: dict[str, Any],
) -> dict[str, Any]:
    """
    Constructs a comprehensive study package for the student at the end of a study session.
    """
    topic_counts: dict[str, int] = {}
    topic_cache_hits: dict[str, int] = {}
    topic_qa: dict[str, list[tuple[str, str]]] = {}

    for e in events:
        t = e.get("topic", "general")
        topic_counts[t] = topic_counts.get(t, 0) + 1
        if e.get("cache_hit"):
            topic_cache_hits[t] = topic_cache_hits.get(t, 0) + 1
        q = e.get("question", "")
        a = e.get("answer", "")
        if q and a:
            topic_qa.setdefault(t, []).append((q, a))

    topics_covered = list(topic_counts.keys())
    weak_topics: list[str] = []
    for t, count in topic_counts.items():
        hits = topic_cache_hits.get(t, 0)
        if count >= 3 or hits >= 2:
            weak_topics.append(t)

    # Flashcards: generate high-yield cards from questions and answers
    flashcards: list[dict[str, str]] = []
    mini_quiz: list[dict[str, Any]] = []

    quiz_id = 1
    for t, qa_list in topic_qa.items():
        for q, a in qa_list:
            key_answer = _first_sentence(a)
            clean_q = q.split("Question:", 1)[-1].strip() if "Question:" in q else q
            flashcards.append({
                "topic": t,
                "question": clean_q,
                "answer": key_answer,
            })
            if quiz_id <= 5:  # Up to 5 quiz questions
                mini_quiz.append({
                    "id": quiz_id,
                    "topic": t,
                    "question": f"In {t}: {clean_q}",
                    "expected_answer": key_answer,
                })
                quiz_id += 1

    # Generate 5-minute revision sheet in Markdown
    revision_lines = [
        f"# 5-Minute Revision Sheet — Session `{session_id}`\n",
        f"**Topics Studied**: {', '.join(topics_covered) if topics_covered else 'None'}\n",
    ]

    if weak_topics:
        revision_lines.append("## ⚠️ Areas Needing Reinforcement (Struggling Topics)")
        for wt in weak_topics:
            revision_lines.append(f"### {wt.title()}")
            qa_items = topic_qa.get(wt, [])
            for q, a in qa_items[:2]:
                q_clean = q.split("Question:", 1)[-1].strip() if "Question:" in q else q
                revision_lines.append(f"- **Q**: {q_clean}")
                revision_lines.append(f"  **Key Takeaway**: {_first_sentence(a)}")
            revision_lines.append("")
    else:
        revision_lines.append("## ✅ Great Job! No persistent struggle patterns detected.\n")

    revision_lines.append("## Quick Reference Summary")
    for t in topics_covered:
        if t not in weak_topics:
            qa_items = topic_qa.get(t, [])
            if qa_items:
                revision_lines.append(f"- **{t.title()}**: {_first_sentence(qa_items[0][1])}")

    revision_sheet = "\n".join(revision_lines)

    total_requests = stats.get("requests", len(events))
    cache_hits = stats.get("cache_hits", sum(1 for e in events if e.get("cache_hit")))
    cache_hit_rate = (cache_hits / total_requests) if total_requests else 0.0

    return {
        "session_id": session_id,
        "total_requests": total_requests,
        "total_saved_tokens": stats.get("saved_tokens", 0),
        "raw_input_tokens": stats.get("raw_input_tokens", 0),
        "upstream_input_tokens": stats.get("upstream_input_tokens", 0),
        "secrets_protected": stats.get("secrets_redacted", 0),
        "pii_protected": stats.get("pii_redacted", 0),
        "cache_hits": cache_hits,
        "cache_hit_rate": round(cache_hit_rate, 4),
        "topics_covered": topics_covered,
        "struggling_topics": weak_topics,
        "flashcards": flashcards,
        "mini_quiz": mini_quiz,
        "revision_sheet": revision_sheet,
    }
