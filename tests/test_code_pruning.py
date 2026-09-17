import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.cache import SemanticCache
from app.code_pruning import detect_file_key, extract_ast_outline, prune_code_snippets
from app.config import ProviderConfig
from app.db import Database
from app.main import app
from app.providers import ProviderResult


SAMPLE_PYTHON_CODE_V1 = """```python
# filename: server.py
import os
import sys

class ItemManager:
    def __init__(self):
        self.items = []
        self.max_capacity = 100

    def add_item(self, item: str) -> None:
        if len(self.items) >= self.max_capacity:
            raise ValueError("Capacity reached")
        self.items.append(item)

    def remove_item(self, item: str) -> bool:
        if item in self.items:
            self.items.remove(item)
            return True
        return False

    def list_items(self) -> list[str]:
        return list(self.items)

    def count(self) -> int:
        return len(self.items)

    def clear(self) -> None:
        self.items.clear()

def run_server():
    print("Starting server on port 8080...")
    manager = ItemManager()
    manager.add_item("initial_seed")
    return manager
```"""

SAMPLE_PYTHON_CODE_V2 = """```python
# filename: server.py
import os
import sys

class ItemManager:
    def __init__(self):
        self.items = []
        self.max_capacity = 100

    def add_item(self, item: str) -> None:
        print(f"Adding item: {item}")
        if len(self.items) >= self.max_capacity:
            raise ValueError("Capacity reached")
        self.items.append(item)

    def remove_item(self, item: str) -> bool:
        if item in self.items:
            self.items.remove(item)
            return True
        return False

    def list_items(self) -> list[str]:
        return list(self.items)

    def count(self) -> int:
        return len(self.items)

    def clear(self) -> None:
        self.items.clear()

def run_server():
    print("Starting server on port 9000...")
    manager = ItemManager()
    manager.add_item("initial_seed")
    return manager
```"""


def test_detect_file_key_and_ast_outline() -> None:
    code = (
        "class OrderService:\n"
        "    def create(self):\n"
        "        pass\n\n"
        "def helper():\n"
        "    return 42\n"
    )
    outline = extract_ast_outline(code)
    assert "Classes: [OrderService]" in outline
    assert "create" in outline and "helper" in outline

    # Non-Python or syntax error doesn't crash
    assert extract_ast_outline("<div>hello</div>") == ""

    # Explicit filename extraction
    assert detect_file_key("python", "# filename: math_util.py\ndef add(a, b): return a + b") == "math_util.py"
    assert detect_file_key("js", "// file: App.jsx\nexport default function App() {}") == "App.jsx"
    assert detect_file_key("python", "def compute(): pass", context_before="Here is my algo.py script:") == "algo.py"


def test_prune_code_snippets_stores_turn1_and_diffs_turn2(tmp_path) -> None:
    test_db = Database(str(tmp_path / "prune_test.sqlite3"))
    session_id = "test-coding-session"

    # Turn 1
    messages_t1 = [{"role": "user", "content": f"Review this code:\n{SAMPLE_PYTHON_CODE_V1}"}]
    optimized_t1, pruned_count_t1 = prune_code_snippets(messages_t1, session_id, test_db)
    assert pruned_count_t1 == 0
    assert SAMPLE_PYTHON_CODE_V1 in optimized_t1[0]["content"]

    # Verify snapshot was stored in SQLite
    snapshot = test_db.get_latest_code_snapshot(session_id, "server.py")
    assert snapshot is not None
    assert "ItemManager" in snapshot

    # Turn 2: sends modified code
    messages_t2 = [{"role": "user", "content": f"I made some changes:\n{SAMPLE_PYTHON_CODE_V2}"}]
    optimized_t2, pruned_count_t2 = prune_code_snippets(messages_t2, session_id, test_db)
    assert pruned_count_t2 == 1

    content_t2 = optimized_t2[0]["content"]
    assert "[Code Update for `server.py` (Diff vs previous turn)]:" in content_t2
    assert "```diff" in content_t2
    assert '+        print(f"Adding item: {item}")' in content_t2
    assert "ItemManager" in content_t2
    assert "run_server" in content_t2
    # Ensure it saved significant characters compared to sending the whole file
    assert len(content_t2) < len(SAMPLE_PYTHON_CODE_V2)


def test_prune_code_snippets_preserves_tiny_snippets(tmp_path) -> None:
    test_db = Database(str(tmp_path / "prune_tiny.sqlite3"))
    session_id = "tiny-session"

    tiny_code = "```python\ndef add(a, b):\n    return a + b\n```"
    messages = [{"role": "user", "content": f"How about this?\n{tiny_code}"}]
    optimized, pruned_count = prune_code_snippets(messages, session_id, test_db)
    assert pruned_count == 0
    assert tiny_code in optimized[0]["content"]


def test_chat_completions_code_pruning_integration(tmp_path, monkeypatch) -> None:
    test_db = Database(str(tmp_path / "chat_prune_integration.sqlite3"))
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(
        main_module,
        "semantic_cache",
        SemanticCache(test_db, hard_threshold=0.95, soft_threshold=0.90),
    )

    fake_provider = ProviderConfig(
        name="test-provider",
        base_url="https://test.example/v1",
        api_key_env="DUMMY_KEY",
        model="test-model",
    )

    received_messages: list[list[dict]] = []

    async def fake_chat(payload: dict):
        received_messages.append(payload["messages"])
        return ProviderResult(
            {"choices": [{"message": {"content": "Code looks good!"}}]},
            fake_provider,
            False,
            attempts=[{"provider": "test-provider", "status": 200}],
        )

    monkeypatch.setattr(main_module.providers, "chat_completion", fake_chat)

    client = TestClient(app)
    session_id = "integration-coding-session"

    # Turn 1: Submit V1 code
    resp1 = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": f"Please review:\n{SAMPLE_PYTHON_CODE_V1}"}]},
        headers={"x-tokenshield-session": session_id},
    )
    assert resp1.status_code == 200
    receipt1 = resp1.json()["tokenshield"]
    assert receipt1["code_pruned"] == 0
    assert "code_pruning" not in receipt1["strategies"]
    assert resp1.headers["x-tokenshield-code-pruned"] == "0"

    # Turn 2: Submit V2 code with small addition
    resp2 = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": f"I updated it:\n{SAMPLE_PYTHON_CODE_V2}"}]},
        headers={"x-tokenshield-session": session_id},
    )
    assert resp2.status_code == 200
    receipt2 = resp2.json()["tokenshield"]
    assert receipt2["code_pruned"] == 1
    assert "code_pruning" in receipt2["strategies"]
    assert resp2.headers["x-tokenshield-code-pruned"] == "1"
    assert "code_pruning" in resp2.headers["x-tokenshield-strategies"]

    # Verify upstream received the pruned diff rather than the raw repeated file
    latest_upstream_msgs = received_messages[-1]
    upstream_user_text = latest_upstream_msgs[-1]["content"]
    assert "[Code Update for `server.py`" in upstream_user_text
    assert "```diff" in upstream_user_text

    # Verify /receipt/{req_id}
    req_id = receipt2["request_id"]
    receipt_resp = client.get(f"/receipt/{req_id}")
    assert receipt_resp.status_code == 200
    assert receipt_resp.json()["code_pruned"] == 1

    # Verify /session/{session_id}/timeline
    timeline_resp = client.get(f"/session/{session_id}/timeline")
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()
    assert len(timeline) == 2
    assert timeline[0]["code_pruned"] == 0
    assert timeline[1]["code_pruned"] == 1
