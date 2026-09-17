import uuid
from fastapi.testclient import TestClient

import app.main as main_module
from app.cache import SemanticCache
from app.db import Database
from app.main import app


def test_expanded_live_metrics(tmp_path, monkeypatch) -> None:
    test_db = Database(str(tmp_path / "metrics_test.sqlite3"))
    monkeypatch.setattr(main_module, "db", test_db)

    # Log several sample requests with different budget modes and strategies
    test_db.log_request(
        request_id="req-1",
        session_id="s1",
        provider="test-p",
        model="test-m",
        cache_hit=False,
        raw_input_tokens=100,
        optimized_input_tokens=80,
        upstream_input_tokens=80,
        output_tokens=30,
        saved_tokens=20,
        strategies=["guard_mode", "conversation_shrinker"],
        failover_used=False,
        budget_mode="saving",
        cache="MISS",
    )
    test_db.log_request(
        request_id="req-2",
        session_id="s1",
        provider="cache",
        model="test-m",
        cache_hit=True,
        raw_input_tokens=100,
        optimized_input_tokens=100,
        upstream_input_tokens=0,
        output_tokens=30,
        saved_tokens=100,
        strategies=["guard_mode", "exact_cache"],
        failover_used=False,
        budget_mode="normal",
        cache="EXACT_HIT",
    )

    client = TestClient(app)
    resp = client.get("/metrics/live")
    assert resp.status_code == 200
    data = resp.json()

    assert data["requests"] == 2
    assert data["cache_hits"] == 1
    assert data["cache_hit_rate"] == 0.5
    assert data["saved_tokens"] == 120

    # Phase 6.1: budget_modes breakdown
    assert "budget_modes" in data
    assert data["budget_modes"].get("saving") == 1
    assert data["budget_modes"].get("normal") == 1

    # Phase 6.1: top_strategies ranking
    assert "top_strategies" in data
    assert data["top_strategies"].get("guard_mode") == 2
    assert data["top_strategies"].get("conversation_shrinker") == 1
    assert data["top_strategies"].get("exact_cache") == 1


def test_session_timeline(tmp_path, monkeypatch) -> None:
    test_db = Database(str(tmp_path / "timeline_test.sqlite3"))
    test_cache = SemanticCache(test_db, hard_threshold=0.95, soft_threshold=0.90)
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    session_id = f"timeline-session-{uuid.uuid4().hex[:8]}"

    class FakeProvider:
        name = "fake-timeline"
        model = "fake-model"

    class FakeRouter:
        async def chat_completion(self, payload):
            return (
                {
                    "id": "fake-resp",
                    "object": "chat.completion",
                    "choices": [{"message": {"role": "assistant", "content": "Sample timeline response."}}],
                },
                FakeProvider(),
                False,
            )

    monkeypatch.setattr(main_module, "providers", FakeRouter())
    client = TestClient(app)

    # First request: MISS
    first = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Explain binary search"}]},
        headers={"x-tokenshield-session": session_id},
    )
    assert first.status_code == 200

    # Second request: EXACT_HIT
    second = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "explain binary search"}]},
        headers={"x-tokenshield-session": session_id},
    )
    assert second.status_code == 200

    # Query timeline
    timeline_resp = client.get(f"/session/{session_id}/timeline")
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()

    assert len(timeline) == 2
    # Event 1: MISS
    assert timeline[0]["cache"] == "MISS"
    assert timeline[0]["provider"] == "fake-timeline"
    assert "guard_mode" in timeline[0]["strategies"]
    assert "created_at" in timeline[0]

    # Event 2: EXACT_HIT
    assert timeline[1]["cache"] == "EXACT_HIT"
    assert timeline[1]["provider"] == "cache"
    assert "exact_cache" in timeline[1]["strategies"]
    assert timeline[1]["saved_input_tokens"] > 0


def test_cors_preflight_headers() -> None:
    client = TestClient(app)
    # Test preflight OPTIONS request
    response = client.options(
        "/v1/chat/completions",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-tokenshield-session",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"

    # Test Vite port 5173
    vite_resp = client.options(
        "/metrics/live",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert vite_resp.status_code == 200
    assert vite_resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
