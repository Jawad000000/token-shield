import uuid
from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.budgeter import get_budget_directive, resolve_budget_mode
from app.cache import SemanticCache
from app.db import Database
from app.main import app, embeddings
from app.memory import clear_session_memory, deduplicate_session_notes
from app.shrinker import shrink_conversation
from app.tokens import estimate_message_tokens


def test_budgeter_directives_and_auto_escalation() -> None:
    saving_text, mode1 = get_budget_directive("saving")
    assert mode1 == "saving"
    assert "SAVING" in saving_text

    crit_text, mode2 = get_budget_directive("critical")
    assert mode2 == "critical"
    assert "CRITICAL" in crit_text

    # Auto escalation on high token count
    _, auto_crit = get_budget_directive("normal", raw_tokens=4500)
    assert auto_crit == "critical"


def test_shrinker_preserves_latest_question_and_compresses_history() -> None:
    history = [
        {"role": "system", "content": "You are an algorithms tutor."},
        {"role": "user", "content": "What is binary search?"},
        {
            "role": "assistant",
            "content": (
                "Binary search is an efficient algorithm for finding an item from a sorted list of items. "
                "It works by repeatedly dividing in half the portion of the list that could contain the item, "
                "until you've narrowed down the possible locations to just one. Time complexity is O(log n)."
                "Here is an extensive Python implementation with docstrings and full examples..."
            ),
        },
        {"role": "user", "content": "What is the worst case time complexity?"},
        {
            "role": "assistant",
            "content": "The worst case time complexity is O(log n) when the target element is at the end or not present.",
        },
        {"role": "user", "content": "Can you give me an example of an iterative implementation?"},
        {
            "role": "assistant",
            "content": "def binary_search(arr, target):\n    low, high = 0, len(arr) - 1\n    while low <= high:\n        mid = (low + high) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            low = mid + 1\n        else:\n            high = mid - 1\n    return -1",
        },
        {"role": "user", "content": "What happens if the array is not sorted beforehand?"},
    ]

    raw_tokens = estimate_message_tokens(history)
    shrunk, result = shrink_conversation(history, requested_budget_mode="saving", raw_tokens=raw_tokens)

    assert result.applied is True
    # Only the older turns are summarized; the most recent turns are kept verbatim.
    assert result.turns_shrunk == 4
    assert result.turns_kept_verbatim == 2
    assert len(shrunk) == 4  # [compact_system, recent_user, recent_assistant, latest_user]

    # Latest user question must be 100% intact
    assert shrunk[-1]["role"] == "user"
    assert shrunk[-1]["content"] == "What happens if the array is not sorted beforehand?"

    # The most recent exchange must survive byte-for-byte, not as a truncated summary.
    assert shrunk[1]["content"] == "Can you give me an example of an iterative implementation?"
    assert "def binary_search(arr, target):" in shrunk[2]["content"]

    # Stable content (system instructions + budget directive) precedes the growing
    # summary block so provider prompt-prefix caching can match across turns.
    system_block = shrunk[0]["content"]
    assert system_block.index("[System Instructions]") < system_block.index("[Answer Budget")
    assert system_block.index("[Answer Budget") < system_block.index("[Earlier Conversation Summary]")

    # Tokens must still be reduced. The margin is deliberately smaller than a
    # summarize-everything strategy: keeping the last exchange verbatim trades some
    # input compression for answer quality, and output tokens cost more than input.
    shrunk_tokens = estimate_message_tokens(shrunk)
    assert shrunk_tokens < raw_tokens
    assert (raw_tokens - shrunk_tokens) >= 15


def test_memory_note_deduplication() -> None:
    session = f"session_{uuid.uuid4().hex}"
    clear_session_memory(session)

    long_lecture_note = (
        "LECTURE 4: Dynamic Programming is mainly an optimization over plain recursion. "
        "Wherever we see a recursive solution that has repeated calls for the same inputs, "
        "we can optimize it using Dynamic Programming. The idea is to simply store the results of "
        "subproblems so that we do not have to re-compute them later when needed."
    )
    assert len(long_lecture_note) >= 180

    prompt_1 = [{"role": "user", "content": f"Here are my notes:\n\n{long_lecture_note}\n\nWhat is DP?"}]
    deduped_1, count_1 = deduplicate_session_notes(prompt_1, session)
    assert count_1 == 0
    assert long_lecture_note in deduped_1[0]["content"]

    # Second question with the exact same pasted lecture notes
    prompt_2 = [{"role": "user", "content": f"Here are my notes:\n\n{long_lecture_note}\n\nGive 2 examples."}]
    deduped_2, count_2 = deduplicate_session_notes(prompt_2, session)
    assert count_2 == 1
    assert "[Reference: note_" in deduped_2[0]["content"]
    assert long_lecture_note not in deduped_2[0]["content"]


def test_route_miss_saves_tokens_via_shrinker(monkeypatch, tmp_path) -> None:
    test_db = Database(str(tmp_path / "shrinker_test.sqlite3"))
    test_cache = SemanticCache(test_db, 0.90)
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    captured_payloads = []

    class FakeProvider:
        name = "shrinker-provider"
        model = "shrinker-model"

    class FakeRouter:
        async def chat_completion(self, payload):
            captured_payloads.append(payload)
            return (
                {
                    "id": "mock-response",
                    "object": "chat.completion",
                    "choices": [{"message": {"role": "assistant", "content": "Short concise answer."}}],
                },
                FakeProvider(),
                False,
            )

    monkeypatch.setattr(main_module, "providers", FakeRouter())
    client = TestClient(app)

    unique_query = f"Unique question about binary search trees {uuid.uuid4().hex}"
    long_chat = [
        {"role": "user", "content": "What is a binary tree?"},
        {"role": "assistant", "content": "A binary tree is a hierarchical data structure in which each node has at most two children, typically referred to as the left child and the right child. Binary trees are widely used in search algorithms, syntax parsing, priority queues via binary heaps, and prefix coding trees in data compression algorithms. Each node stores a value and two pointers."},
        {"role": "user", "content": "What is an AVL tree?"},
        {"role": "assistant", "content": "An AVL tree is a self-balancing binary search tree named after its inventors Adelson-Velsky and Landis. In an AVL tree, the heights of the two child subtrees of any node differ by at most one. If at any time after insertion or deletion they differ by more than one, rebalancing via single or double tree rotations is automatically performed to restore the invariant, ensuring O(log n) lookup time."},
        {"role": "user", "content": unique_query},
    ]

    response = client.post(
        "/v1/chat/completions",
        json={"messages": long_chat},
        headers={
            "x-tokenshield-session": "shrinker-demo",
            "x-tokenshield-budget-mode": "saving",
        },
    )
    assert response.status_code == 200
    headers = response.headers

    assert headers["x-tokenshield-cache"] == "MISS"
    raw_tokens = int(headers["x-tokenshield-raw-input-tokens"])
    opt_tokens = int(headers["x-tokenshield-optimized-input-tokens"])
    saved_tokens = int(headers["x-tokenshield-saved-input-tokens"])

    # Proof that cache MISS saved tokens!
    assert saved_tokens > 0
    assert opt_tokens < raw_tokens
    assert saved_tokens == (raw_tokens - opt_tokens)

    strategies = headers["x-tokenshield-strategies"]
    assert "conversation_shrinker" in strategies
    assert "budget_saving" in strategies
    assert int(headers["x-tokenshield-turns-shrunk"]) == 2

    # Verify upstream payload was shrunk but kept the recent exchange intact
    assert len(captured_payloads) == 1
    upstream_msgs = captured_payloads[0]["messages"]
    assert len(upstream_msgs) == 4  # [compact_summary, recent_user, recent_assistant, latest_user]
    assert upstream_msgs[-1]["content"] == unique_query
    assert upstream_msgs[1]["content"] == "What is an AVL tree?"
    assert "Adelson-Velsky and Landis" in upstream_msgs[2]["content"]

    # Verify receipt
    req_id = headers["x-tokenshield-request-id"]
    receipt = test_db.get_receipt(req_id)
    assert receipt is not None
    assert receipt["turns_shrunk"] == 2
    assert receipt["budget_mode"] == "saving"
    # Receipt and metrics DB must report the identical savings figure.
    assert receipt["saved_tokens"] == saved_tokens


def test_optimization_reversion_when_tokens_would_inflate(monkeypatch, tmp_path) -> None:
    test_db = Database(str(tmp_path / "revert_test.sqlite3"))
    test_cache = SemanticCache(test_db, 0.90)
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    class FakeProvider:
        name = "test-provider"
        model = "test-model"

    class FakeRouter:
        async def chat_completion(self, payload):
            return (
                {
                    "id": "mock-response",
                    "object": "chat.completion",
                    "choices": [{"message": {"role": "assistant", "content": "Tiny answer."}}],
                },
                FakeProvider(),
                False,
            )

    monkeypatch.setattr(main_module, "providers", FakeRouter())
    client = TestClient(app)

    # Very short prompt where injecting the 40-token directive would inflate input tokens
    short_chat = [
        {"role": "user", "content": "Hi."},
        {"role": "assistant", "content": "Hello."},
        {"role": "user", "content": "Quick question."},
    ]

    response = client.post(
        "/v1/chat/completions",
        json={"messages": short_chat},
        headers={"x-tokenshield-budget-mode": "saving"},
    )
    assert response.status_code == 200
    headers = response.headers

    # Verification of safeguard
    raw_tokens = int(headers["x-tokenshield-raw-input-tokens"])
    opt_tokens = int(headers["x-tokenshield-optimized-input-tokens"])
    saved_tokens = int(headers["x-tokenshield-saved-input-tokens"])
    strategies = headers["x-tokenshield-strategies"]

    assert opt_tokens <= raw_tokens
    assert saved_tokens == 0
    assert "optimization_reverted_no_savings" in strategies
    assert int(headers["x-tokenshield-turns-shrunk"]) == 0


def test_contextual_cache_prevents_generic_followup_collision(monkeypatch, tmp_path) -> None:
    from app.cache import build_cache_query

    chat_algo = [
        {"role": "user", "content": "Explain Quicksort algorithm."},
        {"role": "assistant", "content": "Quicksort divides and conquers using a pivot element."},
        {"role": "user", "content": "Why?"},
    ]

    chat_bio = [
        {"role": "user", "content": "Explain cellular respiration in biology."},
        {"role": "assistant", "content": "Cellular respiration converts glucose into ATP energy."},
        {"role": "user", "content": "Why?"},
    ]

    query_algo = build_cache_query(chat_algo)
    query_bio = build_cache_query(chat_bio)

    # Both have the same latest question ("Why?"), but contextual fingerprints differ
    assert "Quicksort" in query_algo
    assert "cellular respiration" in query_bio
    assert query_algo != query_bio

    test_db = Database(str(tmp_path / "collision_test.sqlite3"))
    cache = SemanticCache(test_db, 0.90)

    # Store algo response
    vec_algo = embeddings.embed_text(query_algo)
    cache.store(
        question=query_algo,
        answer="Because pivot partitioning guarantees smaller subproblems.",
        vector=vec_algo,
        provider="test",
        model="test-model",
    )

    # Biology question "Why?" should NOT match Quicksort's "Why?"
    vec_bio = embeddings.embed_text(query_bio)
    hit = cache.lookup(vec_bio)
    assert hit is None

