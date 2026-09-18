"""Tests for JSON array schema deduplication."""
import json
import pytest
from app.json_compressor import (
    collapse_homogeneous_array,
    compress_json_snippet,
    compress_json_in_messages,
)


class TestCollapseHomogeneousArray:
    """Tests for the new schema-based array collapsing."""

    def test_flat_homogeneous_array(self):
        """Array of flat dicts with identical keys should collapse."""
        data = [
            {"id": i, "name": f"user_{i}", "email": f"user{i}@test.com"}
            for i in range(10)
        ]
        result = collapse_homogeneous_array(data)
        assert result is not None
        assert "Array of 10 objects" in result
        assert "schema:" in result
        assert "email" in result
        assert "id" in result
        assert "name" in result
        assert "Sample[0]:" in result
        assert "Sample[1]:" in result
        assert "8 more items" in result

    def test_nested_homogeneous_array(self):
        """Array of dicts with nested values should still collapse on keys."""
        data = [
            {"id": i, "config": {"nested": True}, "tags": ["a", "b"]}
            for i in range(7)
        ]
        result = collapse_homogeneous_array(data)
        assert result is not None
        assert "Array of 7 objects" in result
        assert "config" in result
        assert "5 more items" in result

    def test_heterogeneous_array_not_collapsed(self):
        """Array with different key schemas should NOT collapse."""
        data = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "email": "bob@test.com"},
        ]
        result = collapse_homogeneous_array(data)
        assert result is None

    def test_too_few_items(self):
        """Arrays with fewer than 5 items should NOT collapse."""
        data = [{"id": i, "name": f"u{i}"} for i in range(4)]
        result = collapse_homogeneous_array(data)
        assert result is None

    def test_array_of_non_dicts(self):
        """Array of non-dict items should NOT collapse."""
        data = [1, 2, 3, 4, 5, 6, 7]
        result = collapse_homogeneous_array(data)
        assert result is None

    def test_empty_array(self):
        result = collapse_homogeneous_array([])
        assert result is None

    def test_array_of_empty_dicts(self):
        data = [{}, {}, {}, {}, {}, {}]
        result = collapse_homogeneous_array(data)
        assert result is None


class TestCompressJsonSnippetWithSchema:
    """Integration test: compress_json_snippet should try schema dedup first."""

    def test_large_homogeneous_json_array(self):
        """Large array of homogeneous objects should be collapsed."""
        data = [
            {"userId": i, "username": f"user_{i}", "active": True, "score": i * 10}
            for i in range(20)
        ]
        raw = json.dumps(data, indent=2)
        result = compress_json_snippet(raw)
        assert result is not None
        assert "Array of 20 objects" in result
        assert len(result) < len(raw) * 0.5  # Should be significantly smaller

    def test_small_array_falls_through_to_minify(self):
        """Small arrays should fall through to minification, not schema dedup."""
        data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        raw = json.dumps(data, indent=2)
        result = compress_json_snippet(raw)
        # Should minify but not collapse (< 5 items)
        if result is not None:
            assert "Array of" not in result


class TestCompressJsonInMessagesWithSchema:
    """End-to-end test through the message pipeline."""

    def test_message_with_large_json_array(self):
        data = [
            {"id": i, "status": "active", "role": "user"}
            for i in range(15)
        ]
        messages = [
            {"role": "user", "content": f"Here's the data:\n```json\n{json.dumps(data, indent=2)}\n```\nAnalyze it."}
        ]
        result, count = compress_json_in_messages(messages)
        assert count > 0
        assert "Array of 15 objects" in result[0]["content"]
