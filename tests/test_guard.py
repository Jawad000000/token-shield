import uuid
from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.cache import SemanticCache
from app.db import Database
from app.guard import redact_messages, redact_text
from app.main import app


def test_guard_unit_redaction_secrets_and_pii() -> None:
    text = (
        "Here is my OpenAI key sk-1234567890abcdef1234567890 and my email is student@college.edu "
        "and phone is 555-123-4567. Also my GitHub token is ghp_1234567890abcdef1234567890abcdef12 "
        "and Vercel key is vck_1234567890abcdef1234567890."
    )
    clean, sec_count, pii_count = redact_text(text)
    assert sec_count == 3
    assert pii_count == 2
    assert "sk-" not in clean
    assert "student@college.edu" not in clean
    assert "ghp_" not in clean
    assert "vck_" not in clean
    assert "[REDACTED_SECRET_" in clean
    assert "[REDACTED_EMAIL_1]" in clean
    assert "[REDACTED_PHONE_1]" in clean


def test_guard_unit_supports_multipart_and_immutability() -> None:
    original = [
        {"role": "system", "content": "You are a helpful tutor."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Contact me at alice@school.edu with key sk-abcdef1234567890abcdef1234567890"},
                {"type": "image_url", "image_url": {"url": "https://example.com/pic.png"}},
            ],
        },
    ]

    redacted, result = redact_messages(original)
    assert result.secrets_redacted == 1
    assert result.pii_redacted == 1
    assert result.applied is True

    # Check original was not mutated
    assert "alice@school.edu" in original[1]["content"][0]["text"]
    assert "sk-" in original[1]["content"][0]["text"]

    # Check redacted copy is sanitized
    user_parts = redacted[1]["content"]
    assert "[REDACTED_EMAIL_1]" in user_parts[0]["text"]
    assert "[REDACTED_SECRET_1]" in user_parts[0]["text"]
    assert user_parts[1]["type"] == "image_url"


def test_guard_integration_triple_safety_and_headers(monkeypatch, tmp_path) -> None:
    test_db = Database(str(tmp_path / "guard_test.sqlite3"))
    test_cache = SemanticCache(test_db, 0.90)
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    fake_secret = "sk-SUPERSECRETKEY12345678901234567890"
    fake_email = "student_leak@mit.edu"
    raw_prompt = f"Help me debug this, my secret is {fake_secret} and reach me at {fake_email}."

    captured_payloads = []

    class FakeProvider:
        name = "safe-upstream"
        model = "safe-model"

    class FakeRouter:
        async def chat_completion(self, payload):
            captured_payloads.append(payload)
            return (
                {
                    "id": "mock-response",
                    "object": "chat.completion",
                    "choices": [{"message": {"role": "assistant", "content": "I have helped you securely."}}],
                },
                FakeProvider(),
                False,
            )

    monkeypatch.setattr(main_module, "providers", FakeRouter())
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": raw_prompt}]},
        headers={"x-tokenshield-session": "guard-session"},
    )
    assert response.status_code == 200
    headers = response.headers

    # 1. Verify mandatory headers are always present
    assert headers["x-tokenshield-guard-mode"] == "enabled"
    assert headers["x-tokenshield-secrets-redacted"] == "1"
    assert headers["x-tokenshield-pii-redacted"] == "1"
    assert "guard_mode" in headers["x-tokenshield-strategies"]
    assert "secret_redaction" in headers["x-tokenshield-strategies"]
    assert "pii_redaction" in headers["x-tokenshield-strategies"]

    req_id = headers["x-tokenshield-request-id"]

    # TRIPLE SAFETY ASSERTION 1: Upstream provider payload must NOT contain raw secret or email
    assert len(captured_payloads) == 1
    upstream_messages = captured_payloads[0]["messages"]
    upstream_user_msg = next(m for m in upstream_messages if m.get("role") == "user")
    upstream_user_text = upstream_user_msg["content"]
    assert fake_secret not in upstream_user_text
    assert fake_email not in upstream_user_text
    assert "[REDACTED_SECRET_1]" in upstream_user_text
    assert "[REDACTED_EMAIL_1]" in upstream_user_text

    # TRIPLE SAFETY ASSERTION 2: SQLite cache_entries must NOT contain raw secret or email
    cached_rows = test_db.list_cache_entries()
    assert len(cached_rows) == 1
    assert fake_secret not in cached_rows[0]["question"]
    assert fake_email not in cached_rows[0]["question"]
    assert "[REDACTED_SECRET_1]" in cached_rows[0]["question"]

    # TRIPLE SAFETY ASSERTION 3: SQLite receipt logs must NOT contain raw secret
    receipt = test_db.get_receipt(req_id)
    assert receipt is not None
    assert receipt["secrets_redacted"] == 1
    assert receipt["pii_redacted"] == 1
    assert receipt["guard_mode"] == "enabled"
    assert "secret_redaction" in receipt["strategies"]
    assert "pii_redaction" in receipt["strategies"]

    # Verify metrics aggregation
    metrics = test_db.metrics()
    assert metrics["secrets_redacted"] == 1
    assert metrics["pii_redacted"] == 1
    assert metrics["total_redactions"] == 2


def test_guard_clean_prompt_headers_and_strategies(monkeypatch, tmp_path) -> None:
    test_db = Database(str(tmp_path / "clean_guard.sqlite3"))
    test_cache = SemanticCache(test_db, 0.90)
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    class FakeRouter:
        async def chat_completion(self, payload):
            class P:
                name = "clean-provider"
                model = "clean-model"
            return (
                {"choices": [{"message": {"role": "assistant", "content": "Clean answer."}}]},
                P(),
                False,
            )

    monkeypatch.setattr(main_module, "providers", FakeRouter())
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Explain binary search."}]},
    )
    assert response.status_code == 200
    headers = response.headers

    # Mandatory headers must still exist with 0 counts
    assert headers["x-tokenshield-guard-mode"] == "enabled"
    assert headers["x-tokenshield-secrets-redacted"] == "0"
    assert headers["x-tokenshield-pii-redacted"] == "0"

    strategies = headers["x-tokenshield-strategies"].split(",")
    assert "guard_mode" in strategies
    assert "secret_redaction" not in strategies
    assert "pii_redaction" not in strategies
