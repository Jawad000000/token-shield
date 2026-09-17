import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.budgeter import estimate_output_tokens_saved, get_budget_output_cap
from app.cache import SemanticCache
from app.config import ProviderConfig
from app.db import Database
from app.main import app
from app.providers import ProviderResult
from app.recommendations import build_recommendations


def test_budget_output_caps_and_savings() -> None:
    # Test output caps
    assert get_budget_output_cap("normal") == 700
    assert get_budget_output_cap("saving") == 300
    assert get_budget_output_cap("critical") == 120
    assert get_budget_output_cap("unknown_mode") == 300

    # Test output savings estimates against normal baseline of 700
    assert estimate_output_tokens_saved("normal", 200) == 0
    assert estimate_output_tokens_saved("saving", 150) == 550
    assert estimate_output_tokens_saved("saving", 800) == 0
    assert estimate_output_tokens_saved("critical", 80) == 620


def test_build_recommendations_triggers() -> None:
    # 1. Cache hit celebration
    hit_receipt = {"cache": "EXACT_HIT", "output_tokens": 100, "budget_mode": "saving"}
    recs = build_recommendations(hit_receipt)
    assert any(r["type"] == "cache" and "exact cache" in r["message"] for r in recs)

    # 2. Output budget recommendation on normal mode or > 250 output tokens
    high_output_receipt = {"cache": "MISS", "output_tokens": 400, "budget_mode": "normal"}
    recs = build_recommendations(high_output_receipt)
    assert any(r["type"] == "output_budget" for r in recs)

    # 3. Flashcards recommendation when student is struggling
    study_receipt = {
        "cache": "MISS",
        "output_tokens": 100,
        "budget_mode": "saving",
        "study": {"topic": "Dynamic Programming", "struggling": True, "repeat_count": 3},
    }
    recs = build_recommendations(study_receipt)
    assert any(r["type"] == "study" and "Dynamic Programming" in r["message"] for r in recs)

    # 4. Note deduplication advice
    notes_receipt = {"cache": "MISS", "output_tokens": 100, "budget_mode": "saving", "notes_deduplicated": 2}
    recs = build_recommendations(notes_receipt)
    assert any(r["type"] == "notes" and "2 repetitive note blocks" in r["message"] for r in recs)

    # 5. Code pruning advice
    code_receipt = {"cache": "MISS", "output_tokens": 100, "budget_mode": "saving", "code_pruned": 1}
    recs = build_recommendations(code_receipt)
    assert any(r["type"] == "code" and "AST diff" in r["message"] for r in recs)

    # 6. Provider failover shield
    failover_receipt = {"cache": "MISS", "output_tokens": 100, "budget_mode": "saving", "failover": True, "provider": "groq"}
    recs = build_recommendations(failover_receipt)
    assert any(r["type"] == "failover" and "groq" in r["message"] for r in recs)

    # 7. Prompt shortening advice
    prompt_receipt = {
        "cache": "MISS",
        "output_tokens": 100,
        "budget_mode": "saving",
        "raw_input_tokens": 900,
        "saved_input_tokens": 50,
    }
    recs = build_recommendations(prompt_receipt)
    assert any(r["type"] == "prompt" for r in recs)


def test_live_metrics_forecast(tmp_path) -> None:
    test_db = Database(str(tmp_path / "forecast_test.sqlite3"))
    metrics = test_db.metrics()
    assert "forecast" in metrics
    forecast = metrics["forecast"]
    assert forecast["daily_token_quota"] == 50000
    assert forecast["remaining_quota"] == 50000
    assert forecast["estimated_questions_left"] > 0
    assert forecast["budget_mode_recommendation"] == "saving"
    assert "runway_hours" in forecast
    assert "runway_message" in forecast
    assert "quota lasts" in forecast["runway_message"]


def test_chat_completions_integration_savings_coach(tmp_path, monkeypatch) -> None:
    test_db = Database(str(tmp_path / "test_coach.sqlite3"))
    test_cache = SemanticCache(test_db, hard_threshold=0.88, soft_threshold=0.75)

    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    fake_provider = ProviderConfig(
        name="primary-provider",
        base_url="https://test.example/v1",
        api_key_env="DUMMY_KEY",
        model="test-model",
    )

    captured_payloads: list[dict] = []

    async def fake_chat(payload: dict):
        captured_payloads.append(payload)
        return ProviderResult(
            {"choices": [{"message": {"content": "Binary search divides the search space in half each iteration."}}]},
            fake_provider,
            False,
            attempts=[{"provider": "primary-provider", "status": 200}],
        )

    monkeypatch.setattr(main_module.providers, "chat_completion", fake_chat)

    client = TestClient(app)

    # Turn 1: Cache MISS with critical budget mode
    resp1 = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "How does binary search work in computer science?"}]},
        headers={
            "x-tokenshield-session": "coach-session",
            "x-tokenshield-budget-mode": "critical",
        },
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    receipt1 = data1["tokenshield"]

    # Verify hard max_tokens cap was passed upstream
    assert captured_payloads[-1]["max_tokens"] == 120

    # Verify receipt fields
    assert receipt1["max_output_tokens"] == 120
    assert receipt1["estimated_output_tokens_saved"] > 0
    assert isinstance(receipt1["recommendations"], list)
    assert len(receipt1["recommendations"]) >= 1

    # Verify headers
    assert resp1.headers["x-tokenshield-max-output-tokens"] == "120"
    assert int(resp1.headers["x-tokenshield-saved-output-tokens"]) > 0
    assert int(resp1.headers["x-tokenshield-recommendations-count"]) >= 1

    # Verify /receipt/{request_id}
    req_id = receipt1["request_id"]
    receipt_resp = client.get(f"/receipt/{req_id}")
    assert receipt_resp.status_code == 200
    retrieved_receipt = receipt_resp.json()
    assert retrieved_receipt["max_output_tokens"] == 120
    assert retrieved_receipt["estimated_output_tokens_saved"] > 0
    assert len(retrieved_receipt["recommendations"]) >= 1

    # Turn 2: Exact Cache HIT on identical query
    resp2 = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "How does binary search work in computer science?"}]},
        headers={
            "x-tokenshield-session": "coach-session",
            "x-tokenshield-budget-mode": "critical",
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    receipt2 = data2["tokenshield"]
    assert receipt2["cache"] == "EXACT_HIT"
    assert any(r["type"] == "cache" for r in receipt2["recommendations"])
    assert int(resp2.headers["x-tokenshield-recommendations-count"]) >= 1

    # Check /metrics/live reflects forecast
    metrics_resp = client.get("/metrics/live")
    assert metrics_resp.status_code == 200
    live_data = metrics_resp.json()
    assert "forecast" in live_data
    assert live_data["forecast"]["used_tokens"] > 0
