"""Tests for app.phrase_compactor — verbose phrase compaction."""
from __future__ import annotations

import pytest

from app.phrase_compactor import (
    compact_phrases_in_messages,
    compact_phrases_in_segment,
    compact_phrases_in_text,
)


class TestPhraseSubstitutions:
    """Verify each verbose phrase is replaced with its shorter equivalent."""

    @pytest.mark.parametrize(
        "verbose, expected",
        [
            ("in order to", "to"),
            ("as well as", "and"),
            ("due to the fact that", "because"),
            ("for the purpose of", "to"),
            ("in the event that", "if"),
            ("on the other hand", "however"),
            ("a large number of", "many"),
            ("first and foremost", "first"),
            ("each and every", "every"),
            ("whether or not", "whether"),
            ("the fact that", "that"),
            ("is able to", "can"),
            ("prior to", "before"),
            ("subsequent to", "after"),
            ("in close proximity to", "near"),
            ("in the majority of cases", "usually"),
            ("on a regular basis", "regularly"),
            ("take into account", "consider"),
        ],
    )
    def test_phrase_substitution(self, verbose: str, expected: str):
        text = f"You should {verbose} do this correctly."
        result, count = compact_phrases_in_segment(text)
        assert count >= 1
        assert expected in result.lower()
        assert verbose not in result.lower()

    def test_case_insensitive(self):
        text = "In Order To achieve this goal, you must try."
        result, count = compact_phrases_in_segment(text)
        assert count >= 1
        assert "in order to" not in result.lower()

    def test_multiple_phrases_in_one_text(self):
        text = "In order to do X as well as Y, due to the fact that Z is true."
        result, count = compact_phrases_in_segment(text)
        assert count >= 3
        assert "in order to" not in result.lower()
        assert "as well as" not in result.lower()
        assert "due to the fact that" not in result.lower()

    def test_no_double_spaces_after_substitution(self):
        text = "We need to do this in order to ensure quality."
        result, count = compact_phrases_in_segment(text)
        assert "  " not in result


class TestCodeBlockPreservation:
    def test_does_not_modify_code_blocks(self):
        text = 'Here is code:\n```python\nprint("in order to test")\n```\nIn order to verify.'
        result, count = compact_phrases_in_text(text)
        # Should compact the prose "In order to" but NOT the string inside code
        assert 'print("in order to test")' in result
        assert count >= 1

    def test_preserves_multiline_code_blocks(self):
        text = '```javascript\n// In order to initialize\nconst x = 1;\n```'
        result, count = compact_phrases_in_text(text)
        assert "// In order to initialize" in result
        assert count == 0


class TestMessageIntegration:
    def test_compacts_phrases_in_messages(self):
        messages = [
            {"role": "user", "content": "In order to deploy the application as well as the database."},
        ]
        result, count = compact_phrases_in_messages(messages)
        assert count >= 2
        assert "in order to" not in result[0]["content"].lower()
        assert "as well as" not in result[0]["content"].lower()

    def test_skips_short_messages(self):
        messages = [
            {"role": "user", "content": "Hello world"},
        ]
        result, count = compact_phrases_in_messages(messages)
        assert count == 0
        assert result[0]["content"] == "Hello world"

    def test_never_mutates_input(self):
        original = "In order to test this, we need to verify each and every step."
        messages = [{"role": "user", "content": original}]
        compact_phrases_in_messages(messages)
        assert messages[0]["content"] == original

    def test_preserves_non_string_content(self):
        messages = [{"role": "system", "content": None}]
        result, count = compact_phrases_in_messages(messages)
        assert count == 0
        assert result[0]["content"] is None


class TestEdgeCases:
    def test_empty_text(self):
        result, count = compact_phrases_in_text("")
        assert result == ""
        assert count == 0

    def test_no_verbose_phrases(self):
        text = "This is a simple sentence with no verbose phrases at all."
        result, count = compact_phrases_in_segment(text)
        assert count == 0
        assert result == text

    def test_word_boundary_safety(self):
        """Ensure we don't match partial words."""
        text = "The priorito setting is configured."
        result, count = compact_phrases_in_segment(text)
        # "prior to" should NOT match inside "priorito"
        assert "priorito" in result
