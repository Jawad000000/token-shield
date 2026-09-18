"""
Binary Data Detector — detects and replaces base64 data, data URIs, hex dumps,
and long hash strings that LLMs cannot interpret.

These are pure waste: models cannot decode base64, read hex dumps, or use raw
hash digests. Replacing them with a short description saves thousands of tokens
per hit with zero information loss for the model.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any

# ── Fenced code block detection ──────────────────────────────────────────────
FENCED_BLOCK_PATTERN = re.compile(r"(```[^\n`]*\n[\s\S]*?```)")

# ── Data URI: data:mime/type;base64,... ──────────────────────────────────────
DATA_URI_PATTERN = re.compile(
    r"data:([a-zA-Z0-9]+/[a-zA-Z0-9\-\+\.]+);base64,"
    r"([A-Za-z0-9+/=]{100,})",
    re.IGNORECASE,
)

# ── Standalone base64: long strings of base64 characters (≥128 chars) ────────
# Must be on its own line or surrounded by whitespace/quotes
STANDALONE_BASE64_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+/])"
    r"([A-Za-z0-9+/]{128,}={0,2})"
    r"(?![A-Za-z0-9+/=])",
)

# ── Hex dump: lines like "0x4A 0x61 0x77 0x61 0x64" or "4A 61 77 61 64" ─────
HEX_DUMP_LINE_PATTERN = re.compile(
    r"^[ \t]*(?:0x)?[0-9a-fA-F]{2}(?:[ \t]+(?:0x)?[0-9a-fA-F]{2}){7,}",
    re.MULTILINE,
)

# ── Long hex strings (SHA-256/512 hashes, etc.) — 64+ hex chars ──────────────
LONG_HEX_PATTERN = re.compile(
    r"(?<![a-fA-F0-9])"
    r"([a-fA-F0-9]{64,})"
    r"(?![a-fA-F0-9])",
)


def _human_size(num_bytes: int) -> str:
    """Convert bytes to human-readable size string."""
    if num_bytes < 1024:
        return f"{num_bytes}B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    else:
        return f"{num_bytes / (1024 * 1024):.1f}MB"


def _guess_hash_type(length: int) -> str:
    """Guess hash algorithm from hex string length."""
    hash_lengths = {
        32: "md5",
        40: "sha1",
        56: "sha224",
        64: "sha256",
        96: "sha384",
        128: "sha512",
    }
    return hash_lengths.get(length, f"{length * 4}-bit hash")


def detect_and_replace_binary(text: str) -> tuple[str, int]:
    """
    Scans text for binary data patterns and replaces them with short descriptions.
    Only operates on prose segments (outside fenced code blocks).

    Returns (cleaned_text, replacements_count).
    """
    if not text or len(text) < 100:
        return text, 0

    parts = FENCED_BLOCK_PATTERN.split(text)
    new_parts: list[str] = []
    total_replacements = 0

    for part in parts:
        if part.startswith("```"):
            # Code block: keep intact
            new_parts.append(part)
            continue

        replacements = 0

        # 1. Data URIs (data:image/png;base64,...)
        def replace_data_uri(match: re.Match) -> str:
            nonlocal replacements
            mime_type = match.group(1)
            base64_data = match.group(2)
            # Estimate original size: base64 encodes 3 bytes into 4 chars
            estimated_bytes = math.ceil(len(base64_data) * 3 / 4)
            replacements += 1
            return f"[Embedded base64 data: ~{_human_size(estimated_bytes)} {mime_type}]"

        part = DATA_URI_PATTERN.sub(replace_data_uri, part)

        # 2. Long hex strings (hashes, digests) — BEFORE base64 to avoid false matches
        def replace_long_hex(match: re.Match) -> str:
            nonlocal replacements
            hex_str = match.group(1)
            hash_type = _guess_hash_type(len(hex_str))
            replacements += 1
            return f"[{hash_type} digest]"

        part = LONG_HEX_PATTERN.sub(replace_long_hex, part)

        # 3. Standalone base64 strings (must contain base64-specific chars like +, /)
        def replace_standalone_base64(match: re.Match) -> str:
            nonlocal replacements
            b64_str = match.group(1)
            # Only match if it contains at least one base64-specific char (+, /)
            # or has mixed case with digits (to distinguish from pure hex)
            has_b64_chars = "+" in b64_str or "/" in b64_str
            has_upper = any(c.isupper() for c in b64_str)
            has_lower = any(c.islower() for c in b64_str)
            has_mixed = has_upper and has_lower
            if not (has_b64_chars or has_mixed):
                return match.group(0)  # Leave it alone, likely hex
            estimated_bytes = math.ceil(len(b64_str) * 3 / 4)
            replacements += 1
            return f"[Base64 data: ~{_human_size(estimated_bytes)}]"

        part = STANDALONE_BASE64_PATTERN.sub(replace_standalone_base64, part)

        # 4. Hex dumps (multiple hex values per line, min 2 lines)
        hex_dump_lines = HEX_DUMP_LINE_PATTERN.findall(part)
        if len(hex_dump_lines) >= 2:
            # Count total hex bytes across all dump lines
            total_hex_bytes = 0
            for hex_line in hex_dump_lines:
                hex_values = re.findall(r"(?:0x)?([0-9a-fA-F]{2})", hex_line)
                total_hex_bytes += len(hex_values)

            def replace_hex_dump(match: re.Match) -> str:
                return ""  # Remove individual lines, we'll add summary

            new_part = HEX_DUMP_LINE_PATTERN.sub(replace_hex_dump, part)
            # Collapse multiple blank lines left by removal
            new_part = re.sub(r"\n{3,}", "\n\n", new_part)
            # Insert summary where first dump was
            summary = f"[Hex dump: {total_hex_bytes} bytes]"
            if new_part.strip():
                part = new_part.strip() + "\n" + summary
            else:
                part = summary
            replacements += 1

        total_replacements += replacements
        new_parts.append(part)

    return "".join(new_parts), total_replacements


def detect_binary_in_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """
    Applies binary data detection and replacement across all messages.
    Returns (optimized_messages, total_replacements).
    Never mutates input objects.
    """
    optimized: list[dict[str, Any]] = []
    total_replaced = 0

    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and len(content) > 100:
            cleaned_text, count = detect_and_replace_binary(content)
            if count > 0:
                total_replaced += count
                cloned = dict(msg)
                cloned["content"] = cleaned_text
                optimized.append(cloned)
                continue
        optimized.append(msg)

    return optimized, total_replaced
