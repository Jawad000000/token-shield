import uuid
from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.cache import SemanticCache
from app.config import ProviderConfig
from app.db import Database
from app.main import app, embeddings
from app.providers import ProviderError, ProviderRouter


def test_headers_and_receipt_on_miss_and_hit(monkeypatch, tmp_path) -> None:
    test_db = Database(str(tmp_path / "test_shield.sqlite3"))
    test_cache = SemanticCache(test_db, 0.90)
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    question = "Describe the life cycle of a monarch butterfly."
    answer = "TokenShield records receipts and sets structured headers on every response."
    
    class FakeProvider:
        name = "mock-upstream"
        model = "mock-model"

    class FakeRouter:
        async def chat_completion(self, payload):
            return (
                {
                    "id": "mock-resp",
                    "object": "chat.completion",
                    "choices": [{"message": {"role": "assistant", "content": answer}}],
                },
                FakeProvider(),
                False,
            )

    monkeypatch.setattr(main_module, "providers", FakeRouter())
    client = TestClient(app)

    # 1. First Request: Cache MISS
    miss_resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": question}]},
        headers={"x-tokenshield-session": "test-session"},
    )
    assert miss_resp.status_code == 200
    headers = miss_resp.headers
    assert headers["x-tokenshield-cache"] == "MISS"
    assert headers["x-tokenshield-provider"] == "mock-upstream"
    assert headers["x-tokenshield-failover"] == "false"
    assert "x-tokenshield-raw-input-tokens" in headers
    assert "x-tokenshield-optimized-input-tokens" in headers
    assert headers["x-tokenshield-saved-input-tokens"] == "0"
    assert "provider_proxy" in headers["x-tokenshield-strategies"]
    
    req_id = headers.get("x-tokenshield-request-id")
    assert req_id is not None

    miss_data = miss_resp.json()
    assert "tokenshield" in miss_data
    assert miss_data["tokenshield"]["request_id"] == req_id
    assert miss_data["tokenshield"]["cache"] == "MISS"

    # Verify /receipt/{request_id} endpoint
    receipt_resp = client.get(f"/receipt/{req_id}")
    assert receipt_resp.status_code == 200
    receipt_data = receipt_resp.json()
    assert receipt_data["request_id"] == req_id
    assert receipt_data["provider"] == "mock-upstream"
    assert receipt_data["cache_hit"] is False
    assert receipt_data["session_id"] == "test-session"
    assert "provider_proxy" in receipt_data["strategies"]

    # 2. Second Request: Cache HIT
    hit_resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": question}]},
        headers={"x-tokenshield-session": "test-session"},
    )
    assert hit_resp.status_code == 200
    hit_headers = hit_resp.headers
    assert hit_headers["x-tokenshield-cache"] in ("HIT", "EXACT_HIT")
    assert hit_headers["x-tokenshield-provider"] == "cache"
    assert hit_headers["x-tokenshield-failover"] == "false"
    assert hit_headers["x-tokenshield-upstream-input-tokens"] == "0"
    assert int(hit_headers["x-tokenshield-saved-input-tokens"]) > 0
    assert any(s in hit_headers["x-tokenshield-strategies"] for s in ("semantic_cache", "exact_cache"))

    hit_req_id = hit_headers.get("x-tokenshield-request-id")
    assert hit_req_id is not None
    assert hit_req_id != req_id

    hit_data = hit_resp.json()
    assert "tokenshield" in hit_data
    assert hit_data["tokenshield"]["cache"] in ("HIT", "EXACT_HIT")

    # Verify /receipt/{hit_req_id}
    hit_receipt_resp = client.get(f"/receipt/{hit_req_id}")
    assert hit_receipt_resp.status_code == 200
    assert hit_receipt_resp.json()["cache_hit"] is True


@pytest.mark.anyio
async def test_provider_router_falls_back_on_402_and_403(monkeypatch) -> None:
    monkeypatch.setenv("KEY_1", "secret-one")
    monkeypatch.setenv("KEY_2", "secret-two")
    calls = []

    def make_config(name: str, key_env: str) -> ProviderConfig:
        return ProviderConfig(
            name=name,
            base_url=f"https://{name}.example/v1",
            api_key_env=key_env,
            model="test-model",
        )

    # Test 403 fallback
    async def fake_post_403(config: ProviderConfig, payload: dict):
        calls.append(config.name)
        if config.name == "primary":
            raise ProviderError(config.name, 403, "forbidden/card required")
        return {"choices": [{"message": {"content": "ok from secondary"}}]}

    router_403 = ProviderRouter(
        (make_config("primary", "KEY_1"), make_config("secondary", "KEY_2")),
        post_func=fake_post_403,
    )
    response, used_provider, used_failover = await router_403.chat_completion({"messages": []})
    assert used_provider.name == "secondary"
    assert used_failover is True
    assert calls == ["primary", "secondary"]

    # Test 402 fallback
    calls.clear()
    async def fake_post_402(config: ProviderConfig, payload: dict):
        calls.append(config.name)
        if config.name == "primary":
            raise ProviderError(config.name, 402, "usage limit exceeded")
        return {"choices": [{"message": {"content": "ok from secondary"}}]}

    router_402 = ProviderRouter(
        (make_config("primary", "KEY_1"), make_config("secondary", "KEY_2")),
        post_func=fake_post_402,
    )
    response, used_provider, used_failover = await router_402.chat_completion({"messages": []})
    assert used_provider.name == "secondary"
    assert used_failover is True
    assert calls == ["primary", "secondary"]


def test_receipt_not_found() -> None:
    client = TestClient(app)
    resp = client.get("/receipt/non-existent-req-id")
    assert resp.status_code == 404
