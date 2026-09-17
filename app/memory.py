from __future__ import annotations

import hashlib
import re
from typing import Any

# In-memory store for active session notes: session_id -> {note_hash: note_preview}
_SESSION_NOTES: dict[str, dict[str, str]] = {}
DEDUP_MIN_LENGTH = 180
MAX_SESSIONS = 100


def clear_session_memory(session_id: str | None = None) -> None:
    if session_id:
        _SESSION_NOTES.pop(session_id, None)
    else:
        _SESSION_NOTES.clear()


def _hash_block(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]


def deduplicate_session_notes(
    messages: list[dict[str, Any]], session_id: str
) -> tuple[list[dict[str, Any]], int]:
    if not session_id:
        return messages, 0

    if session_id not in _SESSION_NOTES:
        # Evict oldest session if at capacity
        if len(_SESSION_NOTES) >= MAX_SESSIONS:
            oldest_key = next(iter(_SESSION_NOTES))
            del _SESSION_NOTES[oldest_key]
        _SESSION_NOTES[session_id] = {}

    known_notes = _SESSION_NOTES[session_id]
    dedup_count = 0
    result_messages: list[dict[str, Any]] = []

    for msg in messages:
        cloned = dict(msg)
        content = cloned.get("content")

        if isinstance(content, str):
            # Check for large paragraphs/blocks
            paragraphs = [p for p in re.split(r"\n\s*\n", content) if len(p.strip()) >= DEDUP_MIN_LENGTH]
            modified_content = content
            for para in paragraphs:
                block_hash = _hash_block(para)
                if block_hash in known_notes:
                    snippet = known_notes[block_hash]
                    ref_tag = f"[Reference: note_{block_hash} | Context: \"{snippet}...\"]"
                    modified_content = modified_content.replace(para, ref_tag)
                    dedup_count += 1
                else:
                    clean_p = " ".join(para.strip().split())
                    known_notes[block_hash] = clean_p[:100]

            cloned["content"] = modified_content

        elif isinstance(content, list):
            new_content = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    text_val = item["text"]
                    paragraphs = [p for p in re.split(r"\n\s*\n", text_val) if len(p.strip()) >= DEDUP_MIN_LENGTH]
                    modified_text = text_val
                    for para in paragraphs:
                        block_hash = _hash_block(para)
                        if block_hash in known_notes:
                            snippet = known_notes[block_hash]
                            ref_tag = f"[Reference: note_{block_hash} | Context: \"{snippet}...\"]"
                            modified_text = modified_text.replace(para, ref_tag)
                            dedup_count += 1
                        else:
                            clean_p = " ".join(para.strip().split())
                            known_notes[block_hash] = clean_p[:100]
                    cloned_item = dict(item)
                    cloned_item["text"] = modified_text
                    new_content.append(cloned_item)
                else:
                    new_content.append(item)
            cloned["content"] = new_content

        result_messages.append(cloned)

    return result_messages, dedup_count
