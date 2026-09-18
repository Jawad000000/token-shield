"""Tests for Preamble & Conversational Scaffolding Stripper."""
from app.preamble_stripper import strip_student_preamble, strip_preambles_in_messages


def test_strip_student_greetings_and_preamble():
    raw = (
        "Hi professor! Hope you are doing well. I am currently preparing for my DBMS exam tomorrow "
        "and I am really confused about one concept. Could you please explain what is database normalization?"
    )
    result = strip_student_preamble(raw)
    assert "Hi professor" not in result
    assert "Hope you are doing well" not in result
    assert "DBMS exam tomorrow" not in result
    assert "database normalization" in result
    assert len(result) < len(raw) * 0.6


def test_strip_signoffs():
    raw = "What is the difference between primary key and foreign key? Thanks in advance, please help asap!"
    result = strip_student_preamble(raw)
    assert "Thanks in advance" not in result
    assert "please help asap" not in result
    assert "primary key" in result
    assert "foreign key" in result


def test_strip_conversational_hedges():
    raw = "Basically what I kind of want to know is how ACID properties ensure consistency."
    result = strip_student_preamble(raw)
    assert "Basically" not in result
    assert "kind of" not in result
    assert "ACID properties" in result


def test_preserves_code_blocks():
    raw = (
        "Hello tutor! Please help me with this code:\n"
        "```python\n"
        "# Do not touch this\n"
        "x = 10\n"
        "```\n"
        "Thanks so much!"
    )
    result = strip_student_preamble(raw)
    assert "```python\n# Do not touch this\nx = 10\n```" in result
    assert "Hello tutor" not in result
    assert "Thanks so much" not in result


def test_strip_preambles_in_messages():
    messages = [
        {"role": "system", "content": "You are a DBMS tutor."},
        {
            "role": "user",
            "content": "Hi teacher! I am a beginner in DBMS and I was wondering if you could please explain 1NF?",
        },
    ]
    optimized, count = strip_preambles_in_messages(messages)
    assert count == 1
    assert optimized[0]["content"] == messages[0]["content"]  # System unchanged
    assert "Hi teacher" not in optimized[1]["content"]
    assert "1NF" in optimized[1]["content"]
