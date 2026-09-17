import pytest

from app.config import ProviderConfig
from app.providers import ProviderError, ProviderRouter


def provider(name: str, key_env: str, model: str) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        base_url=f"https://{name}.example/v1",
        api_key_env=key_env,
        model=model,
    )


@pytest.mark.anyio
async def test_provider_router_uses_first_configured_provider(monkeypatch) -> None:
    monkeypatch.setenv("KEY_1", "secret-one")
    calls = []

    async def fake_post(config: ProviderConfig, payload: dict):
        calls.append((config.name, payload["model"]))
        return {"choices": [{"message": {"content": "ok"}}]}

    router = ProviderRouter(
        (provider("primary", "KEY_1", "model-a"), provider("fallback", "KEY_2", "model-b")),
        post_func=fake_post,
    )

    result = await router.chat_completion({"messages": []})
    response, used_provider, used_failover = result

    assert response["choices"][0]["message"]["content"] == "ok"
    assert used_provider.name == "primary"
    assert used_failover is False
    assert calls == [("primary", "model-a")]
    assert result.attempts == [{"provider": "primary", "status": 200}]


@pytest.mark.anyio
async def test_provider_router_falls_back_on_rate_limit(monkeypatch) -> None:
    monkeypatch.setenv("KEY_1", "secret-one")
    monkeypatch.setenv("KEY_2", "secret-two")
    calls = []

    async def fake_post(config: ProviderConfig, payload: dict):
        calls.append((config.name, payload["model"]))
        if config.name == "primary":
            raise ProviderError(config.name, 429, "rate limited")
        return {"choices": [{"message": {"content": "fallback ok"}}]}

    router = ProviderRouter(
        (provider("primary", "KEY_1", "model-a"), provider("fallback", "KEY_2", "model-b")),
        post_func=fake_post,
    )

    result = await router.chat_completion({"messages": []})
    response, used_provider, used_failover = result

    assert response["choices"][0]["message"]["content"] == "fallback ok"
    assert used_provider.name == "fallback"
    assert used_failover is True
    assert calls == [("primary", "model-a"), ("fallback", "model-b")]
    assert result.attempts == [
        {"provider": "primary", "status": 429},
        {"provider": "fallback", "status": 200},
    ]


@pytest.mark.anyio
async def test_provider_router_tracks_multi_step_failover(monkeypatch) -> None:
    monkeypatch.setenv("K1", "k1")
    monkeypatch.setenv("K2", "k2")
    monkeypatch.setenv("K3", "k3")

    async def fake_post(config: ProviderConfig, payload: dict):
        if config.name == "p1":
            raise ProviderError(config.name, 403, "forbidden / quota exceeded")
        if config.name == "p2":
            raise ProviderError(config.name, 429, "rate limit exceeded")
        return {"choices": [{"message": {"content": "p3 response"}}]}

    router = ProviderRouter(
        (
            provider("p1", "K1", "m1"),
            provider("p2", "K2", "m2"),
            provider("p3", "K3", "m3"),
        ),
        post_func=fake_post,
    )

    result = await router.chat_completion({"messages": []})
    assert result.used_failover is True
    assert result.provider.name == "p3"
    assert result.attempts == [
        {"provider": "p1", "status": 403},
        {"provider": "p2", "status": 429},
        {"provider": "p3", "status": 200},
    ]


@pytest.mark.anyio
async def test_provider_router_does_not_fallback_on_bad_request(monkeypatch) -> None:
    monkeypatch.setenv("KEY_1", "secret-one")
    monkeypatch.setenv("KEY_2", "secret-two")
    calls = []

    async def fake_post(config: ProviderConfig, payload: dict):
        calls.append(config.name)
        raise ProviderError(config.name, 400, "bad request")

    router = ProviderRouter(
        (provider("primary", "KEY_1", "model-a"), provider("fallback", "KEY_2", "model-b")),
        post_func=fake_post,
    )

    with pytest.raises(ProviderError) as error:
        await router.chat_completion({"messages": []})

    assert error.value.status_code == 400
    assert calls == ["primary"]


def test_providers_status_endpoint_returns_safe_provider_list() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/providers/status")
    assert resp.status_code == 200
    data = resp.json()

    assert isinstance(data, list)
    assert len(data) > 0
    for item in data:
        # Must only expose safe metadata
        assert set(item.keys()) == {"name", "configured", "model"}
        assert isinstance(item["name"], str)
        assert isinstance(item["configured"], bool)
        assert isinstance(item["model"], str)
        # Verify no secrets leak
        assert "api_key" not in item
        assert "base_url" not in item


def test_waterfall_attempts_logged_in_receipt_and_timeline(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    import app.main as main_module
    from app.cache import SemanticCache
    from app.db import Database
    from app.main import app
    from app.providers import ProviderResult

    test_db = Database(str(tmp_path / "waterfall_test.sqlite3"))
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(
        main_module,
        "semantic_cache",
        SemanticCache(test_db, hard_threshold=0.92, soft_threshold=0.82),
    )

    failover_attempts = [
        {"provider": "primary-vercel", "status": 403},
        {"provider": "secondary-google", "status": 200},
    ]

    target_provider = provider("secondary-google", "KEY_2", "gemini-2.5")
    mock_result = ProviderResult(
        {"choices": [{"message": {"content": "switched to secondary"}}]},
        target_provider,
        True,
        attempts=failover_attempts,
    )

    async def fake_completion(payload: dict):
        return mock_result

    monkeypatch.setattr(main_module.providers, "chat_completion", fake_completion)

    client = TestClient(app)
    session_id = "test-waterfall-session"
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Explain quicksort in detail"}]},
        headers={"x-tokenshield-session": session_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    receipt = body["tokenshield"]

    assert receipt["failover"] is True
    assert receipt["provider"] == "secondary-google"
    assert receipt["provider_attempts"] == failover_attempts

    req_id = receipt["request_id"]

    # Verify /receipt/{req_id}
    receipt_resp = client.get(f"/receipt/{req_id}")
    assert receipt_resp.status_code == 200
    receipt_data = receipt_resp.json()
    assert receipt_data["provider_attempts"] == failover_attempts
    assert receipt_data["failover_used"] is True

    # Verify /session/{session_id}/timeline
    timeline_resp = client.get(f"/session/{session_id}/timeline")
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()
    assert len(timeline) == 1
    assert timeline[0]["provider_attempts"] == failover_attempts
    assert timeline[0]["provider"] == "secondary-google"

