from __future__ import annotations

import copy
import re
from typing import Any

# Patterns indicating critical error/traceback lines that must NEVER be folded
CRITICAL_LINE_PATTERN = re.compile(
    r"\b(error|fatal|failed|failure|critical|exception|traceback|syntaxerror|typeerror|valueerror|assertionerror)\b"
    r"|^\s*at\s+[\w\.\/<>]+\s*\(.*:\d+\)"  # JS/Node stack trace
    r"|^\s*File\s+\".*\",\s+line\s+\d+"     # Python stack trace
    r"|^\s*-->\s+.*:\d+:\d+",               # Rust compiler error pointer
    re.IGNORECASE,
)

# Patterns identifying repetitive terminal noise lines eligible for folding
NOISE_LINE_PATTERN = re.compile(
    r"^(\[?\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[^\]]*\]?\s*)?"  # optional timestamp
    r"\b(info|debug|verbose|trace)\b|"                              # log levels
    r"^\s*(\[={2,}>?\]|\.{3,}|[-=]{5,}|\d+%\s*\[|\d+/\d+\s*\[)|"   # progress bars
    r"\b(downloading|fetching|installing|compiling|cached|extracting|resolving)\b|"
    r"^\s*(tests?\/.*(passed|skipped)|ok\s+[\w\.\/-]+|success\b)",  # test suite passes
    re.IGNORECASE,
)


def is_critical_line(line: str) -> bool:
    return bool(CRITICAL_LINE_PATTERN.search(line))


def is_noise_line(line: str) -> bool:
    if is_critical_line(line):
        return False
    return bool(NOISE_LINE_PATTERN.search(line))


def fold_log_text(text: str, min_consecutive_noise: int = 3) -> tuple[str, int]:
    """
    Scans multiline text for repetitive terminal/compiler log lines.
    Preserves all errors, warnings, stack traces, and question context verbatim.
    Folds blocks of >= min_consecutive_noise repetitive lines into a concise summary.
    """
    lines = text.split("\n")
    if len(lines) < min_consecutive_noise:
        return text, 0

    folded_lines: list[str] = []
    noise_buffer: list[str] = []
    total_lines_folded = 0

    def flush_noise_buffer() -> None:
        nonlocal total_lines_folded
        if not noise_buffer:
            return
        if len(noise_buffer) < min_consecutive_noise:
            folded_lines.extend(noise_buffer)
        else:
            first_line = noise_buffer[0].strip()
            last_line = noise_buffer[-1].strip()
            # Truncate first/last preview to 60 chars for neatness
            if len(first_line) > 60:
                first_line = first_line[:57] + "..."
            if len(last_line) > 60:
                last_line = last_line[:57] + "..."

            count = len(noise_buffer)
            total_lines_folded += count
            folded_marker = f"[Folded {count} terminal/log lines: '{first_line}' ... '{last_line}']"
            folded_lines.append(folded_marker)
        noise_buffer.clear()

    for line in lines:
        if is_noise_line(line):
            noise_buffer.append(line)
        else:
            flush_noise_buffer()
            folded_lines.append(line)

    flush_noise_buffer()

    if total_lines_folded > 0:
        return "\n".join(folded_lines), total_lines_folded
    return text, 0


def fold_logs_in_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """
    Applies log folding across all messages in a conversation.
    Returns (optimized_messages, total_folded_lines).
    Never mutates original messages.
    """
    optimized: list[dict[str, Any]] = []
    total_folded = 0

    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and len(content) > 100:
            folded_text, count = fold_log_text(content)
            if count > 0:
                total_folded += count
                msg_copy = copy.deepcopy(msg)
                msg_copy["content"] = folded_text
                optimized.append(msg_copy)
                continue
        optimized.append(msg)

    return optimized, total_folded
