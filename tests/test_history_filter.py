"""Tests for Query-Aware History Filter."""
from app.history_filter import filter_query_aware_history


def test_filter_irrelevant_older_turns():
    messages = [
        {"role": "system", "content": "You are a helpful programming tutor."},
        # Turn 1: Off-topic Python setup
        {
            "role": "user",
            "content": "How do I install Python virtualenv and configure pip on Windows 11 with PowerShell?",
        },
        {
            "role": "assistant",
            "content": (
                "To install virtualenv on Windows, run python -m venv myenv in PowerShell. "
                "Then activate it with myenv\\Scripts\\Activate.ps1. If script execution is restricted, "
                "set the ExecutionPolicy to RemoteSigned. You can then install packages using pip install."
            ),
        },
        # Turn 2: Transitioning to DBMS
        {
            "role": "user",
            "content": "What is an index in relational databases?",
        },
        {
            "role": "assistant",
            "content": "An index is a data structure that improves the speed of data retrieval operations.",
        },
        # Turn 3: Current active question about B+ trees
        {
            "role": "user",
            "content": "What is the structure of a B+ tree and how do page splits occur during key insertion in DBMS?",
        },
    ]

    optimized, count = filter_query_aware_history(messages)
    # The older Turn 1 assistant message about Python virtualenv should be compacted
    assert count >= 1
    assert optimized[0]["content"] == messages[0]["content"]  # System untouched
    assert optimized[-1]["content"] == messages[-1]["content"]  # Latest user query untouched
    # Recent Turn 2 assistant message should be kept verbatim
    assert optimized[-2]["content"] == messages[-2]["content"]
    # Older assistant message was compacted to a concise marker
    assert len(optimized[2]["content"]) < len(messages[2]["content"])
    assert "[Assistant prior context:" in optimized[2]["content"]


def test_preserves_relevant_older_turns():
    messages = [
        {"role": "system", "content": "You are a helpful programming tutor."},
        {
            "role": "user",
            "content": "What is a B+ tree index in relational databases?",
        },
        {
            "role": "assistant",
            "content": (
                "A B+ tree index is a balanced tree data structure with leaf nodes pointing to rows. "
                "B+ trees are widely used in relational database engines like MySQL and PostgreSQL."
            ),
        },
        {
            "role": "user",
            "content": "How are leaf nodes linked in a B+ tree index?",
        },
        {
            "role": "assistant",
            "content": "Leaf nodes are linked as a doubly-linked list for fast sequential range scans.",
        },
        {
            "role": "user",
            "content": "How do B+ trees handle splits when leaf pages become full?",
        },
    ]

    optimized, count = filter_query_aware_history(messages)
    # Since all turns discuss B+ trees and indexes, the older turn has high keyword overlap and should NOT be pruned
    assert count == 0
    assert optimized == messages


def test_short_history_untouched():
    messages = [
        {"role": "user", "content": "What is SQL?"},
        {"role": "assistant", "content": "SQL is structured query language."},
        {"role": "user", "content": "What is DDL?"},
    ]
    optimized, count = filter_query_aware_history(messages)
    assert count == 0
    assert optimized == messages
