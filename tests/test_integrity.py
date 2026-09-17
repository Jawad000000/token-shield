"""
Tests for receipt integrity and the soft-hit verifier.

These cover the guarantees TokenShield makes to the user about its own numbers:
savings are computed on one tokenizer, the receipt and the metrics DB never
disagree, truncated answers are not counted as savings, and borderline cache
matches are checked before being served as answers.
"""

import math
import uuid

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.budgeter import estimate_output_tokens_saved
from app.cache import SemanticCache
from app.config import ProviderConfig
from app.db import Database
from app.main import app
from app.verifier import SoftHitVerifier


class FakeProvider:
    name = "integrity-provider"
    model = "integrity-model"


def make_router(answer: str, *, usage: dict | None = None, finish_reason: str = "stop", sink: list | None = None):
    class FakeRouter:
        async def chat_completion(self, payload):
            if sink is not None:
                sink.append(payload)
            response = {
                "id": "mock-response",
                "object": "chat.completion",
                "choices": [
                    {"message": {"role": "assistant", "content": answer}, "finish_reason": finish_reason}
                ],
            }
            if usage is not None:
                response["usage"] = usage
            return (response, FakeProvider(), False)

    return FakeRouter()


def install_db(monkeypatch, tmp_path, name: str) -> Database:
    test_db = Database(str(tmp_path / name))
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(
        main_module, "semantic_cache", SemanticCache(test_db, hard_threshold=0.95, soft_threshold=0.90)
    )
    return test_db


def test_receipt_and_metrics_db_report_identical_savings(monkeypatch, tmp_path) -> None:
    """
    Regression: the receipt once computed savings as (our estimate - provider count)
    while the DB logged (our estimate - our estimate). The two panels disagreed on
    screen. Both must now use the same tokenizer on both sides of the subtraction.
    """
    test_db = install_db(monkeypatch, tmp_path, "integrity.sqlite3")
    monkeypatch.setattr(
        main_module,
        "providers",
        # Provider reports a wildly different prompt count (different tokenizer).
        make_router("Concise answer.", usage={"prompt_tokens": 9999, "completion_tokens": 7}),
    )
    client = TestClient(app)

    long_chat = [
        {"role": "user", "content": "What is a red-black tree?"},
        {
            "role": "assistant",
            "content": (
                "A red-black tree is a self-balancing binary search tree where each node stores an "
                "extra colour bit. The colouring rules guarantee that the longest path from root to "
                "leaf is no more than twice the shortest, which keeps operations at O(log n) time."
            ),
        },
        {"role": "user", "content": "And what about AVL trees and splay trees?"},
        {
            "role": "assistant",
            "content": (
                "An AVL tree keeps the heights of any node's two subtrees within one of each other, "
                "rebalancing with rotations after every insert or delete. A splay tree instead moves "
                "recently accessed nodes toward the root, giving amortised O(log n) behaviour that "
                "favours workloads with strong temporal locality rather than uniform access."
            ),
        },
        {"role": "user", "content": "And what about B-trees?"},
        {
            "role": "assistant",
            "content": (
                "A B-tree is a self-balancing search tree in which nodes may hold many keys and have "
                "many children, which makes it well suited to block-oriented storage such as disks "
                "and database indexes where minimising node reads matters most."
            ),
        },
        {"role": "user", "content": f"Compare their write amplification {uuid.uuid4().hex}"},
    ]

    response = client.post(
        "/v1/chat/completions",
        json={"messages": long_chat},
        headers={"x-tokenshield-session": "integrity", "x-tokenshield-budget-mode": "saving"},
    )
    assert response.status_code == 200
    receipt = response.json()["tokenshield"]

    raw = receipt["raw_input_tokens"]
    optimized = receipt["optimized_input_tokens"]

    # Savings stay inside one tokenizer.
    assert receipt["saved_input_tokens"] == raw - optimized
    assert receipt["saved_input_tokens"] > 0

    # The provider's own count is reported alongside, never subtracted from ours.
    assert receipt["upstream_input_tokens"] == 9999
    assert receipt["upstream_token_source"] == "provider"

    # Receipt and metrics DB must agree.
    stored = test_db.get_receipt(receipt["request_id"])
    assert stored["saved_tokens"] == receipt["saved_input_tokens"]
    assert int(response.headers["x-tokenshield-saved-input-tokens"]) == receipt["saved_input_tokens"]


def test_truncated_answer_is_flagged_and_not_counted_as_savings(monkeypatch, tmp_path) -> None:
    install_db(monkeypatch, tmp_path, "truncation.sqlite3")
    monkeypatch.setattr(
        main_module,
        "providers",
        make_router("This answer was cut off mid-sen", finish_reason="length"),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": f"Explain paging {uuid.uuid4().hex}"}]},
        headers={"x-tokenshield-budget-mode": "critical"},
    )
    assert response.status_code == 200
    receipt = response.json()["tokenshield"]

    assert receipt["truncated"] is True
    assert receipt["finish_reason"] == "length"
    assert receipt["estimated_output_tokens_saved"] == 0
    assert "output_truncated" in receipt["strategies"]
    assert response.headers["x-tokenshield-truncated"] == "true"


def test_max_output_tokens_reports_whether_it_was_applied(monkeypatch, tmp_path) -> None:
    install_db(monkeypatch, tmp_path, "cap.sqlite3")
    sink: list = []
    monkeypatch.setattr(main_module, "providers", make_router("Short.", sink=sink))
    client = TestClient(app)

    # Normal mode: no cap is sent upstream, so the receipt must not claim one was.
    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": f"Define mutex {uuid.uuid4().hex}"}]},
        headers={"x-tokenshield-budget-mode": "normal"},
    )
    assert "max_tokens" not in sink[0] or sink[0]["max_tokens"] is None

    # Critical mode: a real cap is sent and reported as applied.
    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": f"Define semaphore {uuid.uuid4().hex}"}]},
        headers={"x-tokenshield-budget-mode": "critical"},
    )
    receipt = response.json()["tokenshield"]
    assert receipt["max_output_tokens_applied"] is True
    assert sink[1]["max_tokens"] == receipt["max_output_tokens"] == 120


def test_output_savings_basis_is_labelled(monkeypatch, tmp_path) -> None:
    install_db(monkeypatch, tmp_path, "basis.sqlite3")
    monkeypatch.setattr(main_module, "providers", make_router("Short."))
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": f"Define a trap {uuid.uuid4().hex}"}]},
        headers={"x-tokenshield-budget-mode": "saving"},
    )
    receipt = response.json()["tokenshield"]
    # With no measured history the basis must say so rather than implying a measurement.
    assert receipt["output_savings_basis"] == "default_baseline"
    assert receipt["output_baseline_tokens"] == 700


def test_output_baseline_uses_measured_average_once_samples_exist(tmp_path) -> None:
    test_db = Database(str(tmp_path / "baseline.sqlite3"))
    assert test_db.output_baseline()["basis"] == "default_baseline"

    for index in range(6):
        test_db.log_request(
            request_id=f"req-{index}",
            session_id="baseline",
            provider="p",
            model="m",
            cache_hit=False,
            raw_input_tokens=100,
            optimized_input_tokens=100,
            upstream_input_tokens=100,
            output_tokens=200,
            saved_tokens=0,
            strategies=[],
            failover_used=False,
            budget_mode="normal",
        )

    baseline = test_db.output_baseline()
    assert baseline["basis"] == "measured_avg"
    assert baseline["baseline"] == 200
    # Savings are now measured against observed behaviour, not a hardcoded 700.
    assert estimate_output_tokens_saved("saving", 150, baseline=baseline["baseline"]) == 50


@pytest.mark.anyio
async def test_verifier_accepts_and_rejects(monkeypatch) -> None:
    monkeypatch.setenv("VERIFIER_KEY", "secret")
    config = ProviderConfig(
        name="cheap", base_url="https://cheap.example/v1", api_key_env="VERIFIER_KEY", model="tiny-model"
    )

    def router_returning(word: str):
        class R:
            async def chat_completion(self, payload):
                assert payload["max_tokens"] <= 8  # verification must stay cheap
                return (
                    {
                        "choices": [{"message": {"content": word}}],
                        "usage": {"total_tokens": 42},
                    },
                    config,
                    False,
                )

        return R()

    accept = await SoftHitVerifier((config,), router=router_returning("YES")).verify("q", "a")
    assert accept.verdict == "accept"
    assert accept.rejected is False
    assert accept.tokens_used == 42

    reject = await SoftHitVerifier((config,), router=router_returning("NO")).verify("q", "a")
    assert reject.verdict == "reject"
    assert reject.rejected is True

    # Unparseable verdicts fail open so a working cache is never blocked by a bad reply.
    unknown = await SoftHitVerifier((config,), router=router_returning("maybe?")).verify("q", "a")
    assert unknown.verdict == "unavailable"
    assert unknown.rejected is False


@pytest.mark.anyio
async def test_verifier_survives_provider_errors(monkeypatch) -> None:
    monkeypatch.setenv("VERIFIER_KEY", "secret")
    config = ProviderConfig(
        name="cheap", base_url="https://cheap.example/v1", api_key_env="VERIFIER_KEY", model="tiny-model"
    )

    class BrokenRouter:
        async def chat_completion(self, payload):
            raise RuntimeError("upstream exploded")

    result = await SoftHitVerifier((config,), router=BrokenRouter()).verify("q", "a")
    assert result.verdict == "unavailable"
    assert result.rejected is False


def test_verifier_disabled_without_configured_provider() -> None:
    assert SoftHitVerifier(()).available is False
    assert SoftHitVerifier((), enabled=False).available is False


def test_rejected_soft_hit_falls_through_to_upstream(monkeypatch, tmp_path) -> None:
    """The headline behaviour: a 0.92-similarity match is NOT served blindly."""
    test_db = install_db(monkeypatch, tmp_path, "softhit.sqlite3")
    test_cache = SemanticCache(test_db, hard_threshold=0.95, soft_threshold=0.90)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    dim = getattr(main_module.embeddings, "dimension", 384)
    stored_vec = [0.0] * dim
    stored_vec[0] = 1.0
    test_cache.store(
        question="How do I sort a list in Python?",
        answer="Use sorted(my_list) or my_list.sort().",
        vector=stored_vec,
        provider="seed",
        model="seed-model",
    )

    soft_vec = [0.0] * dim
    soft_vec[0] = 0.92
    soft_vec[1] = math.sqrt(1.0 - 0.92**2)

    class FakeEmbedder:
        dimension = dim

        def embed_text(self, text: str):
            return soft_vec

    monkeypatch.setattr(main_module, "embeddings", FakeEmbedder())
    monkeypatch.setattr(main_module, "providers", make_router("A fresh, correct answer."))

    class RejectingVerifier:
        available = True

        async def verify(self, question, answer):
            from app.verifier import VerificationResult

            return VerificationResult(verdict="reject", provider="cheap", model="tiny", tokens_used=30)

    monkeypatch.setattr(main_module, "soft_hit_verifier", RejectingVerifier())
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "How do I NOT sort a list in Python?"}]},
    )
    assert response.status_code == 200
    body = response.json()
    receipt = body["tokenshield"]

    # The wrong cached answer was rejected and a real call was made instead.
    assert receipt["cache"] == "MISS"
    assert "soft_hit_rejected" in receipt["strategies"]
    assert body["choices"][0]["message"]["content"] == "A fresh, correct answer."
    assert receipt["soft_hit_verification"]["verdict"] == "reject"
    assert response.headers["x-tokenshield-soft-hit-verdict"] == "reject"


def test_accepted_soft_hit_is_still_served_from_cache(monkeypatch, tmp_path) -> None:
    test_db = install_db(monkeypatch, tmp_path, "softhit_ok.sqlite3")
    test_cache = SemanticCache(test_db, hard_threshold=0.95, soft_threshold=0.90)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    dim = getattr(main_module.embeddings, "dimension", 384)
    stored_vec = [0.0] * dim
    stored_vec[0] = 1.0
    test_cache.store(
        question="How do I sort a list in Python?",
        answer="Use sorted(my_list) or my_list.sort().",
        vector=stored_vec,
        provider="seed",
        model="seed-model",
    )

    soft_vec = [0.0] * dim
    soft_vec[0] = 0.92
    soft_vec[1] = math.sqrt(1.0 - 0.92**2)

    class FakeEmbedder:
        dimension = dim

        def embed_text(self, text: str):
            return soft_vec

    class AcceptingVerifier:
        available = True

        async def verify(self, question, answer):
            from app.verifier import VerificationResult

            return VerificationResult(verdict="accept", provider="cheap", model="tiny", tokens_used=28)

    monkeypatch.setattr(main_module, "embeddings", FakeEmbedder())
    monkeypatch.setattr(main_module, "soft_hit_verifier", AcceptingVerifier())
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "What is the way to order a Python list?"}]},
    )
    assert response.status_code == 200
    receipt = response.json()["tokenshield"]
    assert receipt["cache"] == "SOFT_HIT"
    assert receipt["soft_hit_verification"]["verdict"] == "accept"
    assert receipt["upstream_input_tokens"] == 0
