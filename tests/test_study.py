import uuid
from fastapi.testclient import TestClient

import app.main as main_module
from app.cache import SemanticCache
from app.db import Database
from app.main import app
from app.study import assess_struggle, extract_topic, generate_study_package


def test_topic_extraction_and_clustering() -> None:
    # 1. Base topic extraction
    t1 = extract_topic("What is binary search?")
    assert t1 == "binary search"

    # 2. Topic clustering with existing session topics
    existing = ["binary search"]
    t2 = extract_topic("Can you explain binary search time complexity?", existing_topics=existing)
    assert t2 == "binary search"

    t3 = extract_topic("Why is binary search log n?", existing_topics=existing)
    assert t3 == "binary search"

    # 3. Different topic
    t4 = extract_topic("How does cellular respiration work?", existing_topics=existing)
    assert t4 == "cellular respiration"

    # 4. Fallback on empty
    assert extract_topic("") == "general"


def test_assess_struggle_rules() -> None:
    topic = "binary search"

    # 1 question -> not struggling
    events_1 = [{"topic": topic, "cache_hit": False}]
    struggling, count = assess_struggle(events_1, topic)
    assert struggling is False
    assert count == 2

    # 2 questions (before 3rd is added) -> with current request, count reaches 3 -> struggling
    events_2 = [
        {"topic": topic, "cache_hit": False},
        {"topic": topic, "cache_hit": False},
    ]
    struggling, count = assess_struggle(events_2, topic)
    assert struggling is True
    assert count == 3

    # 2 cache hits in topic -> struggling even if total is fewer
    events_cache = [
        {"topic": topic, "cache_hit": True},
        {"topic": topic, "cache_hit": True},
    ]
    struggling, count = assess_struggle(events_cache, topic)
    assert struggling is True


def test_generate_study_package_structure() -> None:
    session_id = f"test-sess-{uuid.uuid4().hex[:8]}"
    events = [
        {
            "topic": "binary search",
            "question": "What is binary search?",
            "answer": "Binary search is an efficient algorithm for finding an item in a sorted list.",
            "cache_hit": False,
        },
        {
            "topic": "binary search",
            "question": "Why is binary search O(log n)?",
            "answer": "It divides the search interval in half each iteration.",
            "cache_hit": False,
        },
        {
            "topic": "binary search",
            "question": "What happens if array is not sorted in binary search?",
            "answer": "Binary search will produce incorrect results because it relies on ordering.",
            "cache_hit": False,
        },
        {
            "topic": "quicksort",
            "question": "How does quicksort pick a pivot?",
            "answer": "Common strategies include choosing first, last, or random elements as pivot.",
            "cache_hit": False,
        },
    ]
    stats = {
        "requests": 4,
        "cache_hits": 0,
        "saved_tokens": 120,
        "raw_input_tokens": 300,
        "upstream_input_tokens": 180,
        "secrets_redacted": 1,
        "pii_redacted": 0,
    }

    pkg = generate_study_package(session_id, events, stats)
    assert pkg["session_id"] == session_id
    assert "binary search" in pkg["struggling_topics"]
    assert "quicksort" not in pkg["struggling_topics"]
    assert "binary search" in pkg["topics_covered"]
    assert "quicksort" in pkg["topics_covered"]
    assert len(pkg["flashcards"]) >= 4
    assert len(pkg["mini_quiz"]) >= 1
    assert "5-Minute Revision Sheet" in pkg["revision_sheet"]
    assert "Binary Search" in pkg["revision_sheet"]
    assert pkg["total_saved_tokens"] == 120
    assert pkg["secrets_protected"] == 1


def test_chat_completions_study_headers_and_struggle_detection(monkeypatch, tmp_path) -> None:
    test_db = Database(str(tmp_path / "study_test.sqlite3"))
    test_cache = SemanticCache(test_db, hard_threshold=0.95, soft_threshold=0.90)
    monkeypatch.setattr(main_module, "db", test_db)
    monkeypatch.setattr(main_module, "semantic_cache", test_cache)

    session_id = f"study-session-{uuid.uuid4().hex[:8]}"

    class FakeProvider:
        name = "fake-study"
        model = "fake-model"

    class FakeRouter:
        async def chat_completion(self, payload):
            return (
                {
                    "id": "fake-resp",
                    "object": "chat.completion",
                    "choices": [{"message": {"role": "assistant", "content": "Binary search divides the interval in half."}}],
                },
                FakeProvider(),
                False,
            )

    monkeypatch.setattr(main_module, "providers", FakeRouter())
    client = TestClient(app)

    # Question 1: "What is binary search?"
    r1 = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "What is binary search?"}]},
        headers={"x-tokenshield-session": session_id},
    )
    assert r1.status_code == 200
    assert r1.headers.get("x-tokenshield-topic") == "binary search"
    assert "x-tokenshield-struggling-topic" not in r1.headers
    assert r1.json()["tokenshield"]["study"]["topic"] == "binary search"
    assert r1.json()["tokenshield"]["study"]["struggling"] is False

    # Question 2: "What is binary search time complexity?"
    r2 = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "What is binary search time complexity?"}]},
        headers={"x-tokenshield-session": session_id},
    )
    assert r2.status_code == 200
    assert r2.headers.get("x-tokenshield-topic") == "binary search"
    assert "x-tokenshield-struggling-topic" not in r2.headers
    assert r2.json()["tokenshield"]["study"]["struggling"] is False

    # Question 3: "Why is binary search log n?" (3rd question in topic -> triggers struggling!)
    r3 = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Why is binary search log n?"}]},
        headers={"x-tokenshield-session": session_id},
    )
    assert r3.status_code == 200
    assert r3.headers.get("x-tokenshield-topic") == "binary search"
    assert r3.headers.get("x-tokenshield-struggling-topic") == "binary search"
    assert r3.json()["tokenshield"]["study"]["struggling"] is True
    assert r3.json()["tokenshield"]["study"]["repeat_count"] == 3

    # Now call POST /session/{session_id}/finish
    finish_resp = client.post(f"/session/{session_id}/finish")
    assert finish_resp.status_code == 200
    finish_data = finish_resp.json()
    assert finish_data["session_id"] == session_id
    assert "binary search" in finish_data["struggling_topics"]
    assert len(finish_data["flashcards"]) >= 3
    assert len(finish_data["mini_quiz"]) >= 1
    assert "5-Minute Revision Sheet" in finish_data["revision_sheet"]
    assert "Binary Search" in finish_data["revision_sheet"]


def test_finish_session_not_found(tmp_path, monkeypatch) -> None:
    test_db = Database(str(tmp_path / "empty.sqlite3"))
    monkeypatch.setattr(main_module, "db", test_db)
    client = TestClient(app)
    resp = client.post("/session/non-existent-session-12345/finish")
    assert resp.status_code == 404
