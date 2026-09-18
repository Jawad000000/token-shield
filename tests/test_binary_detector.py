"""Tests for binary data detection and replacement."""
import pytest
from app.binary_detector import (
    detect_and_replace_binary,
    detect_binary_in_messages,
    _human_size,
    _guess_hash_type,
)


class TestHumanSize:
    def test_bytes(self):
        assert _human_size(500) == "500B"

    def test_kilobytes(self):
        assert _human_size(2048) == "2.0KB"

    def test_megabytes(self):
        assert _human_size(1048576) == "1.0MB"


class TestGuessHashType:
    def test_sha256(self):
        assert _guess_hash_type(64) == "sha256"

    def test_sha512(self):
        assert _guess_hash_type(128) == "sha512"

    def test_md5(self):
        assert _guess_hash_type(32) == "md5"

    def test_unknown(self):
        result = _guess_hash_type(48)
        assert "bit hash" in result


class TestDetectAndReplaceBinary:
    """Tests for the core detection function."""

    def test_data_uri_replaced(self):
        """data:image/png;base64,... should be replaced with description."""
        b64_data = "A" * 200  # Simulated base64
        text = f"Here's an image: data:image/png;base64,{b64_data} and some text after."
        result, count = detect_and_replace_binary(text)
        assert count == 1
        assert "Embedded base64 data:" in result
        assert "image/png" in result
        assert b64_data not in result

    def test_standalone_base64_replaced(self):
        """Long standalone base64 string should be replaced."""
        b64_data = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/" * 4
        text = f"The token is:\n{b64_data}\nPlease decode it."
        result, count = detect_and_replace_binary(text)
        assert count >= 1
        assert "Base64 data:" in result
        assert b64_data not in result

    def test_sha256_hash_replaced(self):
        """64-char hex string should be recognized as sha256."""
        sha256 = "a1b2c3d4e5f6" * 5 + "a1b2"  # 64 hex chars with mixed digits+letters
        text = f"The file hash is {sha256} and it should be detected as a sha256 hash value in this sufficiently long text."
        result, count = detect_and_replace_binary(text)
        assert count == 1
        assert "sha256 digest" in result
        assert sha256 not in result

    def test_sha512_hash_replaced(self):
        """128-char hex string should be recognized as sha512."""
        sha512 = "f" * 128
        text = f"Checksum: {sha512}"
        result, count = detect_and_replace_binary(text)
        assert count == 1
        assert "sha512 digest" in result

    def test_short_text_unchanged(self):
        """Short text should not be processed."""
        text = "Hello world"
        result, count = detect_and_replace_binary(text)
        assert count == 0
        assert result == text

    def test_code_blocks_preserved(self):
        """Base64 inside fenced code blocks should NOT be replaced."""
        b64_data = "A" * 200
        text = f"```\ndata:image/png;base64,{b64_data}\n```"
        result, count = detect_and_replace_binary(text)
        assert count == 0
        assert b64_data in result

    def test_normal_text_unchanged(self):
        """Normal text without binary data should pass through unchanged."""
        text = "This is a normal prompt about Python programming. " * 5
        result, count = detect_and_replace_binary(text)
        assert count == 0

    def test_hex_dump_replaced(self):
        """Multiple lines of hex values should be detected."""
        # Generate hex values that look like a real hex dump (0x prefixed)
        lines = []
        for i in range(5):
            hex_vals = " ".join(f"0x{(i * 16 + j):02X}" for j in range(16))
            lines.append(hex_vals)
        text = "Memory dump of the process core file contents below:\n" + "\n".join(lines) + "\nEnd of dump."
        result, count = detect_and_replace_binary(text)
        # Should detect either as hex dump or individual long hex strings
        assert count >= 1


class TestDetectBinaryInMessages:
    """End-to-end test through the message pipeline."""

    def test_message_with_base64(self):
        b64_data = "A" * 300
        messages = [
            {"role": "user", "content": f"Here's the image data: data:image/jpeg;base64,{b64_data} - can you analyze it?"}
        ]
        result, count = detect_binary_in_messages(messages)
        assert count > 0
        assert "Embedded base64 data:" in result[0]["content"]
        assert b64_data not in result[0]["content"]

    def test_message_without_binary(self):
        messages = [
            {"role": "user", "content": "Explain how quicksort works in Python with an example."}
        ]
        result, count = detect_binary_in_messages(messages)
        assert count == 0

    def test_original_messages_not_mutated(self):
        b64_data = "B" * 300
        original_content = f"Token: data:application/octet-stream;base64,{b64_data}"
        messages = [{"role": "user", "content": original_content}]
        result, count = detect_binary_in_messages(messages)
        assert count > 0
        # Original should be unchanged
        assert messages[0]["content"] == original_content
