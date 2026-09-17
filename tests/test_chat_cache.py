import uuid

from fastapi.testclient import TestClient

import app.main as main_module
from app.cache import SemanticCache
from app.db import Database
from app.main import app, embeddings, semantic_cache


TOKENSHIELD_HEADERS = [
    "x-tokenshield-request-id",
    "x-tokenshield-cache",
    "x-tokenshield-provider",
    "x-tokenshield-failover",
    "x-tokenshield-raw-input-tokens",
    "x-tokenshield-optimized-input-tokens",
    "x-tokenshield-upstream-input-tokens",
    "x-tokenshield-saved-input-tokens",
    "x-tokenshield-strategies",
]


def assert_tokenshield_headers(response) -> None:
    for header in TOKENSHIELD_HEADERS:
        assert header in response.headers


def test_chat_endpoint_can_return_cache_hit() -> None:
    question = "What is TokenShield cache route test unique phrase?"
    answer = "TokenShield can return cached answers without calling an upstream provider."
    vector = embeddings.embed_text(question)
    semantic_cache.store(
        question=question,
        answer=answer,
        vector=vector,
        provider="test",
        model="test-model",
    )

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": question}]},
    )

    assert response.status_code == 200
    assert_tokenshield_headers(response)
    assert response.headers["x-tokenshield-cache"] == "EXACT_HIT"
    assert response.headers["x-tokenshield-provider"] == "cache"
    assert response.headers["x-tokenshield-upstream-input-tokens"] == "0"
    assert "exact_cache" in response.headers["x-tokenshield-strategies"]
    assert response.json()["choices"][0]["message"]["content"] == answer
    assert response.json()["tokenshield"]["cache"] == "EXACT_HIT"


def test_chat_endpoint_miss_then_hit_skips_second_upstream_call(monkeypatch, tmp_path) -> None:
    question = f"What is the TokenShield miss then hit integration phrase {uuid.uuid4().hex}?"
    answer = "The first call is stored, and the second call is served from cache."
    calls = []
    test_db = Database(str(tmp_path / "tokenshield-test.sqlite3"))
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", SemanticCache(test_db, hard_threshold=0.95, soft_threshold=0.90))

    class FakeProvider:
        name = "fake"
        model = "fake-model"

    class FakeRouter:
        async def chat_completion(self, payload):
            calls.append(payload)
            return (
                {
                    "id": "fake-response",
                    "object": "chat.completion",
                    "model": "fake-model",
                    "choices": [{"message": {"role": "assistant", "content": answer}}],
                },
                FakeProvider(),
                False,
            )

    monkeypatch.setattr(main_module, "providers", FakeRouter())

    client = TestClient(app)
    payload = {"messages": [{"role": "user", "content": question}]}

    first = client.post("/v1/chat/completions", json=payload)
    second = client.post("/v1/chat/completions", json=payload)

    assert first.status_code == 200
    assert_tokenshield_headers(first)
    assert first.headers["x-tokenshield-cache"] == "MISS"
    assert first.headers["x-tokenshield-provider"] == "fake"
    assert "provider_proxy" in first.headers["x-tokenshield-strategies"]
    assert first.json()["tokenshield"]["cache"] == "MISS"
    assert first.json()["tokenshield"]["provider"] == "fake"
    assert second.status_code == 200
    assert_tokenshield_headers(second)
    assert second.headers["x-tokenshield-cache"] == "EXACT_HIT"
    assert second.headers["x-tokenshield-upstream-input-tokens"] == "0"
    assert second.headers["x-tokenshield-saved-input-tokens"] == second.headers["x-tokenshield-raw-input-tokens"]
    assert second.json()["choices"][0]["message"]["content"] == answer
    assert "exact_cache" in second.json()["tokenshield"]["strategies"]
    assert "guard_mode" in second.json()["tokenshield"]["strategies"]
    assert len(calls) == 1


def test_chat_endpoint_semantic_soft_hit_and_hit(monkeypatch, tmp_path) -> None:
    test_db = Database(str(tmp_path / "tokenshield-tiers.sqlite3"))
    test_cache = SemanticCache(test_db, hard_threshold=0.95, soft_threshold=0.90)
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    dim = 384
    # Store a base vector [1, 0, 0, ...]
    base_vec = [0.0] * dim
    base_vec[0] = 1.0

    test_cache.store(
        question="What is TokenShield?",
        answer="TokenShield is an AI gateway proxy.",
        vector=base_vec,
        provider="test-provider",
        model="test-model",
    )

    client = TestClient(app)

    # 1. Mock embedder to return high similarity vector (e.g. 0.98 similarity)
    # Cosine similarity between [1, 0, ...] and [0.98, sqrt(1-0.98^2), 0, ...] is 0.98 >= 0.95 (HIT)
    import math
    high_sim_vec = [0.0] * dim
    high_sim_vec[0] = 0.98
    high_sim_vec[1] = math.sqrt(1.0 - 0.98**2)

    class MockHighEmbedder:
        dimension = dim
        def embed_text(self, text: str):
            return high_sim_vec

    monkeypatch.setattr(main_module, "embeddings", MockHighEmbedder())

    # Send a different question text so exact cache misses, but semantic hits
    resp_hit = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Can you define TokenShield?"}]},
    )
    assert resp_hit.status_code == 200
    assert resp_hit.headers["x-tokenshield-cache"] == "HIT"
    assert "semantic_cache" in resp_hit.headers["x-tokenshield-strategies"]
    assert resp_hit.json()["choices"][0]["message"]["content"] == "TokenShield is an AI gateway proxy."

    # 2. Mock embedder to return soft similarity vector (0.92 similarity -> between 0.90 and 0.95)
    soft_sim_vec = [0.0] * dim
    soft_sim_vec[0] = 0.92
    soft_sim_vec[1] = math.sqrt(1.0 - 0.92**2)

    class MockSoftEmbedder:
        dimension = dim
        def embed_text(self, text: str):
            return soft_sim_vec

    monkeypatch.setattr(main_module, "embeddings", MockSoftEmbedder())

    resp_soft = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Tell me about this tool?"}]},
    )
    assert resp_soft.status_code == 200
    assert resp_soft.headers["x-tokenshield-cache"] == "SOFT_HIT"
    assert "semantic_cache_soft" in resp_soft.headers["x-tokenshield-strategies"]
    assert resp_soft.json()["choices"][0]["message"]["content"] == "TokenShield is an AI gateway proxy."
