import json
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.cache import SemanticCache
from app.config import ProviderConfig
from app.db import Database
from app.json_compressor import compress_json_text, tabularize_json_list
from app.log_folding import fold_log_text, is_critical_line, is_noise_line
from app.main import app
from app.providers import ProviderResult


SAMPLE_BUILD_LOG = """
[2026-06-13T10:02:00Z] INFO compiling module core::worker::task_0 (incremental)
[2026-06-13T10:02:01Z] INFO compiling module core::worker::task_1 (incremental)
[2026-06-13T10:02:02Z] INFO compiling module core::worker::task_2 (incremental)
[2026-06-13T10:02:03Z] INFO compiling module core::worker::task_3 (incremental)
[2026-06-13T10:02:04Z] INFO compiling module core::worker::task_4 (incremental)
[2026-06-13T10:02:05Z] INFO compiling module core::worker::task_5 (incremental)
[2026-06-13T10:02:06Z] INFO compiling module core::worker::task_6 (incremental)
[2026-06-13T10:02:07Z] INFO compiling module core::worker::task_7 (incremental)
[2026-06-13T10:02:08Z] INFO compiling module core::worker::task_8 (incremental)
[2026-06-13T10:02:09Z] INFO compiling module core::worker::task_9 (incremental)
[2026-06-13T10:02:31Z] ERROR src/worker/pool.py:214: ValueError: invalid literal for int() with base 10: 'abc'
Traceback (most recent call last):
  File "/workspace/app/main.py", line 42, in process_batch
    worker_pool.dispatch(item)
[2026-06-13T10:02:32Z] INFO compiling module core::net::conn_0 (incremental)
[2026-06-13T10:02:33Z] INFO compiling module core::net::conn_1 (incremental)
[2026-06-13T10:02:34Z] INFO compiling module core::net::conn_2 (incremental)
[2026-06-13T10:02:35Z] INFO compiling module core::net::conn_3 (incremental)
[2026-06-13T10:02:36Z] INFO compiling module core::net::conn_4 (incremental)
"""


SAMPLE_INDENTED_JSON = """```json
[
    {
        "id": 101,
        "name": "Database Systems",
        "instructor": "Dr. Stone",
        "credits": 4,
        "enrolled": 120
    },
    {
        "id": 102,
        "name": "Operating Systems",
        "instructor": "Dr. Tanenbaum",
        "credits": 4,
        "enrolled": 140
    },
    {
        "id": 103,
        "name": "Distributed Algorithms",
        "instructor": "Dr. Lynch",
        "credits": 3,
        "enrolled": 85
    },
    {
        "id": 104,
        "name": "Computer Networks",
        "instructor": "Dr. Kurose",
        "credits": 3,
        "enrolled": 110
    }
]
```"""


def test_log_folding_unit() -> None:
    # 1. Critical line detection
    assert is_critical_line("ERROR src/main.rs:12: mismatched types")
    assert is_critical_line("Traceback (most recent call last):")
    assert is_critical_line("  File \"server.py\", line 99, in run")
    assert not is_critical_line("INFO fetching dependencies...")

    # 2. Noise line detection
    assert is_noise_line("[2026-06-13T10:02:00Z] INFO compiling core...")
    assert is_noise_line("downloading package v1.0.4...")
    assert is_noise_line("tests/test_api.py::test_auth PASSED")

    # 3. Log folding execution
    folded_text, count = fold_log_text(SAMPLE_BUILD_LOG)
    assert count == 15  # 10 lines in block 1 + 5 lines in block 2
    assert "[Folded 10 terminal/log lines:" in folded_text
    assert "[Folded 5 terminal/log lines:" in folded_text

    # CRITICAL: Verify error and traceback lines preserved verbatim
    assert "ERROR src/worker/pool.py:214: ValueError" in folded_text
    assert "Traceback (most recent call last):" in folded_text
    assert "worker_pool.dispatch(item)" in folded_text


def test_json_compressor_unit() -> None:
    # 1. Tabularize uniform array
    data = [
        {"id": 1, "topic": "BFS", "score": 90},
        {"id": 2, "topic": "DFS", "score": 95},
        {"id": 3, "topic": "Dijkstra", "score": 88},
        {"id": 4, "topic": "A*", "score": 92},
    ]
    table = tabularize_json_list(data)
    assert table is not None
    assert "[JSON Table (4 items): id | topic | score]" in table
    assert "1 | BFS | 90" in table
    assert "4 | A* | 92" in table

    # 2. Compress JSON block
    compressed, blocks = compress_json_text(SAMPLE_INDENTED_JSON)
    assert blocks == 1
    # Check that indentations were eliminated and data is preserved
    assert "Database Systems" in compressed
    assert "Dr. Tanenbaum" in compressed
    assert len(compressed) < len(SAMPLE_INDENTED_JSON) * 0.70


def test_integration_log_folding_and_json_completions(tmp_path, monkeypatch) -> None:
    test_db = Database(str(tmp_path / "test_compress.sqlite3"))
    test_cache = SemanticCache(test_db, hard_threshold=0.88, soft_threshold=0.75)

    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    fake_provider = ProviderConfig(
        name="test-llm",
        base_url="https://test.example/v1",
        api_key_env="DUMMY_KEY",
        model="test-model",
    )

    captured_payloads: list[dict] = []

    async def fake_chat(payload: dict):
        captured_payloads.append(payload)
        return ProviderResult(
            {"choices": [{"message": {"content": "The error occurs because string 'abc' cannot be parsed to an int."}}]},
            fake_provider,
            False,
            attempts=[{"provider": "test-llm", "status": 200}],
        )

    monkeypatch.setattr(main_module.providers, "chat_completion", fake_chat)

    client = TestClient(app)

    # 1. Test request with noisy build log
    prompt_with_log = f"Why did my build fail?\n\n{SAMPLE_BUILD_LOG}"
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": prompt_with_log}]},
        headers={"x-tokenshield-session": "log-session"},
    )
    assert resp.status_code == 200
    receipt = resp.json()["tokenshield"]

    assert receipt["logs_folded"] > 0
    assert "log_folding" in receipt["strategies"]
    assert int(resp.headers["x-tokenshield-logs-folded"]) > 0

    # Verify upstream received folded text with verbatim error
    upstream_user_text = captured_payloads[-1]["messages"][-1]["content"]
    assert "[Folded 10 terminal/log lines:" in upstream_user_text
    assert "ERROR src/worker/pool.py:214" in upstream_user_text
    assert "Traceback (most recent call last):" in upstream_user_text

    # Verify recommendations contain log folding tip
    assert any(r["type"] == "logs" for r in receipt["recommendations"])

    # 2. Test request with indented JSON payload
    prompt_with_json = f"Can you analyze this curriculum?\n\n{SAMPLE_INDENTED_JSON}"
    resp2 = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": prompt_with_json}]},
        headers={"x-tokenshield-session": "json-session"},
    )
    assert resp2.status_code == 200
    receipt2 = resp2.json()["tokenshield"]

    assert receipt2["json_compressed"] > 0
    assert "json_compression" in receipt2["strategies"]
    assert int(resp2.headers["x-tokenshield-json-compressed"]) > 0

    # Verify recommendations contain json tip
    assert any(r["type"] == "json" for r in receipt2["recommendations"])

    # 3. Verify /receipt/{request_id}
    req_id = receipt["request_id"]
    receipt_resp = client.get(f"/receipt/{req_id}")
    assert receipt_resp.status_code == 200
    retrieved = receipt_resp.json()
    assert retrieved["logs_folded"] > 0
