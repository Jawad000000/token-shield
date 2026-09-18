from __future__ import annotations

import copy
import json
import re
from typing import Any

JSON_BLOCK_REGEX = re.compile(r"```(?:json)?\s*([\[\{][\s\S]*?[\]\}])\s*```", re.MULTILINE)


def tabularize_json_list(data: list[Any]) -> str | None:
    """
    Attempts to tabularize a uniform array of dictionaries.
    Returns compact table format or None if not applicable.
    """
    if len(data) < 3:
        return None

    first_item = data[0]
    if not isinstance(first_item, dict) or not first_item:
        return None

    keys = list(first_item.keys())
    # Ensure all items are dicts with the same keys and simple scalar values
    for item in data:
        if not isinstance(item, dict) or list(item.keys()) != keys:
            return None
        for v in item.values():
            if isinstance(v, (dict, list)):
                return None  # nested complex structure, avoid flattening table

    header = " | ".join(str(k) for k in keys)
    rows: list[str] = []
    for item in data:
        row_str = " | ".join(str(item[k]).replace("\n", " ") for k in keys)
        rows.append(row_str)

    table = f"[JSON Table ({len(data)} items): {header}]\n" + "\n".join(rows)
    return table


def _extract_key_schema(obj: Any) -> set[str] | None:
    """Extract the set of top-level keys from a dict. Returns None for non-dicts."""
    if isinstance(obj, dict) and obj:
        return set(obj.keys())
    return None


def collapse_homogeneous_array(data: list[Any], min_items: int = 5) -> str | None:
    """
    Collapses a JSON array where all items are objects with the same key schema
    into a compact representation: schema + first 2 samples + count.

    Works for nested structures (not limited to flat scalar values).
    Only activates for arrays with >= min_items homogeneous objects.
    """
    if len(data) < min_items:
        return None

    first_schema = _extract_key_schema(data[0])
    if first_schema is None:
        return None

    for item in data[1:]:
        item_schema = _extract_key_schema(item)
        if item_schema != first_schema:
            return None

    # All items share the same schema — collapse
    sorted_keys = sorted(first_schema)
    schema_str = ", ".join(sorted_keys)

    # Show first 2 samples minified
    samples = []
    for item in data[:2]:
        samples.append(json.dumps(item, separators=(",", ":"), ensure_ascii=False))

    total = len(data)
    result = (
        f"[Array of {total} objects, schema: {{{schema_str}}}]\n"
        f"Sample[0]: {samples[0]}\n"
        f"Sample[1]: {samples[1]}\n"
        f"[...{total - 2} more items with same structure]"
    )
    return result


def compress_json_snippet(snippet: str) -> str | None:
    """
    Parses a JSON string.
    If valid and compressable, returns minified or tabularized JSON.
    Otherwise returns None.
    """
    cleaned = snippet.strip()
    if not ((cleaned.startswith("{") and cleaned.endswith("}")) or (cleaned.startswith("[") and cleaned.endswith("]"))):
        return None

    try:
        data = json.loads(cleaned)
    except Exception:
        return None

    # Check if array deduplication applies for uniform lists
    if isinstance(data, list):
        # Try schema-based collapse first (works for nested structures)
        collapsed = collapse_homogeneous_array(data)
        if collapsed and len(collapsed) < len(cleaned) * 0.85:
            return collapsed

        # Fallback: try flat tabularization
        table = tabularize_json_list(data)
        if table and len(table) < len(cleaned) * 0.85:
            return table

    # Lossless minification (strips indentations and line breaks)
    minified = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if len(minified) < len(cleaned) * 0.85:
        return minified

    return None


def compress_json_text(text: str) -> tuple[str, int]:
    """
    Finds JSON blocks in text (in markdown code fences or standalone)
    and compresses them losslessly.
    Returns (compressed_text, blocks_compressed_count).
    """
    compressed_count = 0

    def replace_fence(match: re.Match) -> str:
        nonlocal compressed_count
        raw_json = match.group(1)
        compressed = compress_json_snippet(raw_json)
        if compressed:
            compressed_count += 1
            if compressed.startswith("[JSON Table"):
                return compressed
            return f"```json\n{compressed}\n```"
        return match.group(0)

    # 1. Match code fenced JSON
    new_text = JSON_BLOCK_REGEX.sub(replace_fence, text)

    # 2. If no code fences were compressed, check if the entire content is a standalone JSON payload
    if compressed_count == 0:
        compressed_standalone = compress_json_snippet(new_text)
        if compressed_standalone:
            return compressed_standalone, 1

    return new_text, compressed_count


def compress_json_in_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """
    Scans messages and applies lossless JSON compression.
    Returns (optimized_messages, total_compressed_blocks).
    Never mutates original message objects.
    """
    optimized: list[dict[str, Any]] = []
    total_compressed = 0

    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and len(content) > 80:
            compressed_text, count = compress_json_text(content)
            if count > 0:
                total_compressed += count
                msg_copy = copy.deepcopy(msg)
                msg_copy["content"] = compressed_text
                optimized.append(msg_copy)
                continue
        optimized.append(msg)

    return optimized, total_compressed
