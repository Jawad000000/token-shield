"""Tests for sentence-level deduplication and response summarizer."""
from app.sentence_dedup import dedup_sentences_in_text, dedup_sentences_in_messages
from app.response_summarizer import summarize_response, summarize_assistant_responses


# ── Sentence Dedup Tests ────────────────────────────────────────────────────


def test_dedup_repeated_sentence():
    text = (
        "A derivative measures the rate of change of a function. "
        "A derivative measures the rate of change of a function. "
        "A derivative measures the rate of change of a function."
    )
    result, count = dedup_sentences_in_text(text)
    assert count == 2
    assert "x3" in result
    # The sentence should only appear once
    assert result.count("A derivative measures") == 1


def test_dedup_no_duplicates():
    text = "The sky is blue and the grass is green. Plants convert sunlight to energy."
    result, count = dedup_sentences_in_text(text)
    assert count == 0
    assert result == text


def test_dedup_short_sentences_ignored():
    text = "OK. OK. OK. Yes. Yes."
    result, count = dedup_sentences_in_text(text)
    assert count == 0  # All too short (< 20 chars)


def test_dedup_preserves_code_blocks():
    text = (
        "This line is repeated here.\n"
        "This line is repeated here.\n"
        "```python\n"
        "def foo():\n"
        "    pass\n"
        "def foo():\n"
        "    pass\n"
        "```\n"
        "Another repeated sentence that is long enough to qualify for dedup.\n"
        "Another repeated sentence that is long enough to qualify for dedup."
    )
    result, count = dedup_sentences_in_text(text)
    # Code block duplicates should NOT be removed
    assert result.count("def foo():") == 2
    # Prose duplicates SHOULD be removed
    assert count >= 1


def test_dedup_messages_only_user():
    messages = [
        {"role": "system", "content": "You are helpful. You are helpful."},
        {"role": "user", "content": "Explain this concept please. Explain this concept please."},
        {"role": "assistant", "content": "Here is my answer. Here is my answer."},
    ]
    result, count = dedup_sentences_in_messages(messages)
    assert count >= 1
    # System and assistant should be untouched
    assert result[0]["content"] == messages[0]["content"]
    assert result[2]["content"] == messages[2]["content"]
    # User message should be deduped
    assert result[1]["content"] != messages[1]["content"]


# ── Response Summarizer Tests ───────────────────────────────────────────────


def test_summarize_short_response_unchanged():
    text = "F = ma. This is Newton's second law."
    result = summarize_response(text)
    assert result == text  # Too short to summarize


def test_summarize_long_response_compressed():
    # A long assistant response
    text = (
        "Photosynthesis is the process by which plants convert light energy "
        "into chemical energy stored in glucose. It occurs in two main stages: "
        "the light-dependent reactions and the Calvin cycle. "
        "The light-dependent reactions take place in the thylakoid membranes "
        "of the chloroplast. These reactions capture light energy and convert "
        "it into ATP and NADPH. Water molecules are split in this process, "
        "releasing oxygen as a byproduct. "
        "The Calvin cycle, also known as the light-independent reactions, "
        "occurs in the stroma. It uses the ATP and NADPH produced by the "
        "light-dependent reactions to fix carbon dioxide into glucose. "
        "This process is essential for life on Earth as it provides both "
        "food and oxygen for most organisms."
    )
    result = summarize_response(text)
    assert len(result) < len(text)
    assert "[AI prior response" in result


def test_summarize_preserves_formulas():
    text = (
        "Newton's second law states that F = ma, where F is force, "
        "m is mass, and a is acceleration. This fundamental law "
        "describes how the velocity of an object changes when it "
        "is subjected to an external force. The law implies that "
        "the acceleration is directly proportional to the net force "
        "and inversely proportional to the mass. Let me explain "
        "this concept in more detail with several examples that "
        "demonstrate practical applications of this principle."
    )
    result = summarize_response(text)
    # Formula sentence should be preserved due to high score
    assert "F = ma" in result


def test_summarize_messages_keeps_recent():
    long_response = (
        "Relational database management systems use SQL for querying. "
        "They enforce ACID properties which guarantee transactions are processed reliably. "
        "Tables consist of rows and columns with primary keys identifying unique records. "
        "Foreign keys establish relationships between different tables in the schema."
    )
    messages = [
        {"role": "user", "content": "What is RDBMS?"},
        {"role": "assistant", "content": long_response},  # Long enough to summarize
        {"role": "user", "content": "And what about NoSQL?"},
        {"role": "assistant", "content": "NoSQL is non-relational and scales horizontally."},  # Most recent — keep verbatim
    ]
    result, count = summarize_assistant_responses(messages)
    assert count == 1  # Only the first assistant message should be summarized
    # Most recent assistant message is kept verbatim
    assert result[3]["content"] == messages[3]["content"]
    # Older assistant message is summarized
    assert result[1]["content"] != messages[1]["content"]


def test_summarize_messages_single_assistant_unchanged():
    messages = [
        {"role": "user", "content": "What is X?"},
        {"role": "assistant", "content": "X is a concept with many details that goes on and on." * 10},
    ]
    result, count = summarize_assistant_responses(messages)
    assert count == 0  # Only 1 assistant message — nothing to summarize


def test_summarize_messages_never_mutates_input():
    original_content = (
        "Database normalization is the process of structuring a relational database. "
        "It reduces data redundancy and improves data integrity through normal forms like 1NF, 2NF, 3NF. "
        "Edgar F. Codd proposed the relational model in 1970 and introduced 1NF."
    )
    messages = [
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": original_content},
        {"role": "user", "content": "Q2"},
        {"role": "assistant", "content": "Short final answer"},
    ]
    result, count = summarize_assistant_responses(messages)
    # Original message should not be modified
    assert messages[1]["content"] == original_content
