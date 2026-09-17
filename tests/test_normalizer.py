import pytest
from app.normalizer import (
    clean_url,
    clean_urls_in_text,
    compact_markdown_table_lines,
    normalize_text,
    normalize_messages,
)


def test_clean_url_strips_tracking_preserves_functional():
    dirty = "https://example.com/docs/api?utm_source=google&utm_medium=cpc&id=42&fbclid=XYZ123&page=2#section-3"
    cleaned = clean_url(dirty)
    assert "utm_source" not in cleaned
    assert "fbclid" not in cleaned
    assert "id=42" in cleaned
    assert "page=2" in cleaned
    assert "#section-3" in cleaned
    assert cleaned.startswith("https://example.com/docs/api?")


def test_compact_markdown_table():
    lines = [
        "| Service             | Status    | Latency        |",
        "|---------------------|-----------|----------------|",
        "| Auth Service        | Online    | 24ms           |",
        "| Database Cache      | Standby   | 4ms            |",
    ]
    compacted = compact_markdown_table_lines(lines)
    assert compacted[0] == "| Service | Status | Latency |"
    assert compacted[1] == "| --------------------- | ----------- | ---------------- |"
    assert compacted[2] == "| Auth Service | Online | 24ms |"
    assert compacted[3] == "| Database Cache | Standby | 4ms |"


def test_collapse_delimiter_runs():
    text = "Section A\n==============================\nDetails here.\n------------------------------\nEnd."
    norm, mods = normalize_text(text)
    assert mods >= 2
    assert "==============================" not in norm
    assert "------------------------------" not in norm
    assert norm.count("---") == 2


def test_code_blocks_are_never_mutated():
    text = (
        "Here is a table:\n"
        "| Key          | Val         |\n"
        "|--------------|-------------|\n"
        "| A            | B           |\n\n"
        "And here is raw code that must not change:\n"
        "```python\n"
        "# ------------------------------\n"
        "url = 'https://example.com?utm_source=test'\n"
        "```\n"
    )
    norm, mods = normalize_text(text)
    # The URL and delimiter inside the python block should be intact
    assert "url = 'https://example.com?utm_source=test'" in norm
    assert "# ------------------------------" in norm
    # The table outside should be compacted
    assert "| Key | Val |" in norm


def test_normalize_messages():
    messages = [
        {
            "role": "user",
            "content": (
                "Check out this documentation:\n"
                "https://api.example.com/v1/auth?utm_campaign=spring2026&utm_medium=email\n\n\n\n"
                "----------------------------------------\n"
                "| Header 1         | Header 2         |\n"
                "|------------------|------------------|\n"
                "| Val 1            | Val 2            |\n"
            )
        }
    ]
    optimized, count = normalize_messages(messages)
    assert count > 0
    content = optimized[0]["content"]
    assert "utm_campaign" not in content
    assert "----------------------------------------" not in content
    assert "\n\n\n\n" not in content
    assert "| Header 1 | Header 2 |" in content
