from __future__ import annotations

from typing import Any

_encoder: object = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding("o200k_base")
        except Exception:
            _encoder = "fallback"
    return _encoder


def estimate_text_tokens(text: str) -> int:
    encoder = _get_encoder()
    if encoder == "fallback":
        return max(1, len(text) // 4)
    return len(encoder.encode(text))


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        else:
            total += estimate_text_tokens(str(content))
        total += 4
    return total
