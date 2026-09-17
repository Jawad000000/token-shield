from __future__ import annotations

import copy
import re
import urllib.parse
from typing import Any

# Known marketing and tracking parameters that bloat URLs without semantic value
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "ref_src",
    "ref_url",
    "yclid",
    "mc_cid",
    "mc_eid",
    "si",
    "igshid",
}

# Regex to find HTTP/HTTPS URLs
URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)

# Repeated horizontal rules / dividers (10+ dashes, equals, underscores, asterisks)
DELIMITER_RUN_PATTERN = re.compile(r"(?m)^[\t ]*([=\-_*~#])\1{7,}[\t ]*$")

# Fenced code block regex to isolate code from markdown normalization
FENCED_BLOCK_PATTERN = re.compile(r"(```[^\n`]*\n[\s\S]*?```)")


def clean_url(url: str) -> str:
    """
    Strips analytics and tracking query parameters from a URL while
    preserving all functional paths, hashes, and non-tracking query parameters.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
        if not parsed.query:
            return url

        query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        cleaned_params = [
            (k, v) for (k, v) in query_params if k.lower() not in TRACKING_PARAMS
        ]

        new_query = urllib.parse.urlencode(cleaned_params)
        cleaned = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
        )
        return cleaned
    except Exception:
        return url


def clean_urls_in_text(text: str) -> tuple[str, int]:
    """Finds and cleans URLs in non-code text."""
    urls_cleaned = 0

    def replace_url(match: re.Match) -> str:
        nonlocal urls_cleaned
        original = match.group(0)
        cleaned = clean_url(original)
        if cleaned != original:
            urls_cleaned += 1
            return cleaned
        return original

    new_text = URL_PATTERN.sub(replace_url, text)
    return new_text, urls_cleaned


def compact_markdown_table_lines(lines: list[str]) -> list[str]:
    """
    Compacts markdown table cells by stripping excessive padding spaces.
    E.g. '|  Header 1          |   Header 2       |' -> '| Header 1 | Header 2 |'
    """
    compacted: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            in_table = True
            cells = stripped.split("|")[1:-1]
            compacted_cells = []
            for cell in cells:
                c = cell.strip()
                # If delimiter row like '---' or ':---:'
                if re.match(r"^:?-+:?$", c):
                    compacted_cells.append(c)
                else:
                    compacted_cells.append(c)
            compacted.append("| " + " | ".join(compacted_cells) + " |")
        else:
            in_table = False
            compacted.append(line)

    return compacted


def normalize_markdown_segment(text: str) -> tuple[str, int]:
    """
    Normalizes markdown text outside of code blocks:
    1. Strips tracking URL parameters
    2. Compacts repetitive delimiter lines to '---'
    3. Collapses excessive spaces in markdown tables
    4. Collapses 3+ consecutive newlines to 2
    5. Strips trailing whitespace per line
    """
    mods = 0

    # 1. Clean tracking URLs
    text, url_mods = clean_urls_in_text(text)
    mods += url_mods

    # 2. Compact delimiter lines
    def replace_delimiter(m: re.Match) -> str:
        nonlocal mods
        mods += 1
        return "---"

    text, delim_mods = DELIMITER_RUN_PATTERN.subn(replace_delimiter, text)

    # 3. Compact markdown tables
    lines = text.split("\n")
    # Strip trailing whitespace on each line
    lines = [line.rstrip() for line in lines]
    compacted_lines = compact_markdown_table_lines(lines)
    text = "\n".join(compacted_lines)

    # 4. Collapse 3+ newlines to 2 newlines (\n\n)
    collapsed_text, nl_mods = re.subn(r"\n{3,}", "\n\n", text)
    mods += nl_mods

    return collapsed_text, mods


def normalize_text(text: str) -> tuple[str, int]:
    """
    Splits text into code blocks and prose segments so code inside fences
    is never altered, while prose, tables, and URLs are optimized losslessly.
    """
    if not text:
        return text, 0

    parts = FENCED_BLOCK_PATTERN.split(text)
    new_parts: list[str] = []
    total_mods = 0

    for part in parts:
        if part.startswith("```"):
            # Inside a code block: keep intact
            new_parts.append(part)
        else:
            # Outside code block: apply lossless normalization
            norm_part, mods = normalize_markdown_segment(part)
            new_parts.append(norm_part)
            total_mods += mods

    return "".join(new_parts), total_mods


def normalize_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """
    Applies lossless structural and URL normalization across all messages.
    Returns (optimized_messages, modifications_count).
    Never mutates input objects.
    """
    optimized: list[dict[str, Any]] = []
    total_mods = 0

    for msg in messages:
        cloned = dict(msg)
        content = cloned.get("content")
        if isinstance(content, str) and len(content) > 20:
            norm_content, mods = normalize_text(content)
            if mods > 0:
                cloned["content"] = norm_content
                total_mods += mods
        optimized.append(cloned)

    return optimized, total_mods
