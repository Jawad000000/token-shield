from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.db import Database


CODE_FINGERPRINT_PATTERN = re.compile(r"```([a-zA-Z0-9_-]*)\s*\n([\s\S]*?)```")


def _fingerprint_code_blocks(text: str) -> str:
    """
    Replaces long code blocks with a compact language + hash fingerprint
    in cache query representations so that code keywords don't swamp
    the semantic similarity calculation of the actual question.
    """
    def _replace_block(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = m.group(2)
        code_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()[:8]
        return f"[CodeBlock:{lang}:{code_hash}]"

    return CODE_FINGERPRINT_PATTERN.sub(_replace_block, text)


@dataclass(frozen=True)
class CacheHit:
    entry_id: int
    answer: str
    similarity: float
    provider: str
    model: str
    hit_type: str = "HIT"


def normalize_cache_key(text: str) -> str:
    """Normalizes query text by stripping whitespace, collapsing multiple spaces, and lowercasing."""
    return " ".join(text.strip().lower().split())


def hash_cache_key(text: str) -> str:
    """Returns SHA-256 hex digest of normalized query text."""
    normalized = normalize_cache_key(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError(f"vector dimension mismatch: {len(left)} != {len(right)}")
    return sum(a * b for a, b in zip(left, right))


def _extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return " ".join(parts)
    return str(content or "")


def build_cache_query(messages: list[dict[str, Any]]) -> str:
    """
    Builds a cache query from messages.
    For single-turn queries, returns the user prompt directly (allowing global cache reuse).
    For multi-turn queries, prepends a context fingerprint of prior turns so that generic
    follow-ups (e.g. 'Why?', 'Explain that again', 'Give me an example') do not collide
    across different topics or sessions.
    """
    if not messages:
        return ""

    latest_user_text = ""
    latest_idx = -1
    for i in reversed(range(len(messages))):
        if messages[i].get("role") == "user":
            latest_user_text = _extract_content_text(messages[i].get("content"))
            latest_idx = i
            break

    if not latest_user_text:
        return ""

    if latest_idx <= 0:
        return _fingerprint_code_blocks(latest_user_text)

    prior_turns: list[str] = []
    for m in messages[:latest_idx][-2:]:
        role = m.get("role", "")
        text = " ".join(_fingerprint_code_blocks(_extract_content_text(m.get("content"))).split())[:120]
        if text:
            prior_turns.append(f"{role}: {text}")

    clean_latest = _fingerprint_code_blocks(latest_user_text)
    if prior_turns:
        context_str = " | ".join(prior_turns)
        return f"[Context: {context_str}] Question: {clean_latest}"

    return clean_latest


class SemanticCache:
    def __init__(
        self,
        db: Database,
        threshold: float | None = None,
        *,
        hard_threshold: float = 0.95,
        soft_threshold: float = 0.90,
    ) -> None:
        self.db = db
        if threshold is not None:
            self.hard_threshold = threshold
            self.soft_threshold = min(threshold, soft_threshold)
        else:
            self.hard_threshold = hard_threshold
            self.soft_threshold = soft_threshold
        self.threshold = self.hard_threshold

    def exact_lookup(self, question: str = "", question_hash: str | None = None) -> CacheHit | None:
        q_hash = question_hash or (hash_cache_key(question) if question else "")
        if not q_hash:
            return None
        row = self.db.exact_lookup(q_hash)
        if row:
            self.db.mark_cache_hit(row["id"])
            return CacheHit(
                entry_id=row["id"],
                answer=row["answer"],
                similarity=1.0,
                provider=row["provider"],
                model=row["model"],
                hit_type="EXACT_HIT",
            )
        return None

    def lookup(self, vector: list[float]) -> CacheHit | None:
        best: CacheHit | None = None
        for row in self.db.list_cache_entries():
            candidate = json.loads(row["vector_json"])
            similarity = cosine_similarity(vector, candidate)
            if best is None or similarity > best.similarity:
                best = CacheHit(
                    entry_id=row["id"],
                    answer=row["answer"],
                    similarity=similarity,
                    provider=row["provider"],
                    model=row["model"],
                )
        if best:
            if best.similarity >= self.hard_threshold:
                self.db.mark_cache_hit(best.entry_id)
                return CacheHit(
                    entry_id=best.entry_id,
                    answer=best.answer,
                    similarity=best.similarity,
                    provider=best.provider,
                    model=best.model,
                    hit_type="HIT",
                )
            elif best.similarity >= self.soft_threshold:
                self.db.mark_cache_hit(best.entry_id)
                return CacheHit(
                    entry_id=best.entry_id,
                    answer=best.answer,
                    similarity=best.similarity,
                    provider=best.provider,
                    model=best.model,
                    hit_type="SOFT_HIT",
                )
        return None

    def store(
        self,
        *,
        question: str,
        answer: str,
        vector: list[float],
        provider: str,
        model: str,
        question_hash: str | None = None,
    ) -> int:
        if question_hash is None and question:
            question_hash = hash_cache_key(question)
        return self.db.insert_cache_entry(
            question=question,
            question_hash=question_hash,
            answer=answer,
            vector=vector,
            provider=provider,
            model=model,
        )
