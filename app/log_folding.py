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
    r"^\s*(tests?\/.*(passed|skipped)|ok\s+[\w\.\/\-]+|success\b)",  # test suite passes
    re.IGNORECASE,
)

# ── Stack trace patterns ─────────────────────────────────────────────────────

# Python: "  File "path.py", line N, in func"
PYTHON_FRAME_PATTERN = re.compile(r'^\s*File\s+".*",\s+line\s+\d+', re.IGNORECASE)
# Python traceback header
PYTHON_TB_HEADER = re.compile(r"^\s*Traceback\s*\(most\s+recent\s+call\s+(last|first)\)\s*:", re.IGNORECASE)

# Java/Kotlin: "  at com.example.Class.method(File.java:123)"
JAVA_FRAME_PATTERN = re.compile(r"^\s*at\s+[\w\.$<>]+\.[\w$<>]+\([\w\.$]+:\d+\)", re.IGNORECASE)

# Node/JS: "    at Object.<anonymous> (/path/to/file.js:12:34)"
NODE_FRAME_PATTERN = re.compile(r"^\s*at\s+.*\(.*:\d+:\d+\)", re.IGNORECASE)

# .NET/C#: "   at Namespace.Class.Method() in File.cs:line 123"
DOTNET_FRAME_PATTERN = re.compile(r"^\s*at\s+[\w\.]+\(.*\)\s+in\s+.*:line\s+\d+", re.IGNORECASE)

# Generic exception line (e.g. "TypeError: ...", "java.lang.NullPointerException: ...")
EXCEPTION_LINE_PATTERN = re.compile(
    r"^\s*(\w+Error|\w+Exception|\w+Fault)\s*:", re.IGNORECASE
)

# Combined: any line that looks like a stack frame
STACK_FRAME_PATTERN = re.compile(
    r"^\s*File\s+\".*\",\s+line\s+\d+"       # Python
    r"|^\s*at\s+[\w\.$<>]+.*[\(:]"            # Java/Node/C#
    r"|^\s*---\s*End of inner exception.*"     # .NET inner exception
    r"|^\s*\.\.\.\s*\d+\s+more\s*$",          # Java "... 12 more"
    re.IGNORECASE,
)

# How many frames to keep at the top and bottom of a folded stack trace
KEEP_FRAMES_TOP = 2
KEEP_FRAMES_BOTTOM = 2
MIN_FRAMES_TO_FOLD = 6  # Only fold if there are at least this many frames


def fold_stack_traces(text: str) -> tuple[str, int]:
    """
    Detects stack traces in text and folds middle frames, keeping the error line
    plus the top and bottom frames for context.

    Returns (folded_text, total_frames_folded).
    """
    lines = text.split("\n")
    result_lines: list[str] = []
    total_folded = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        # Detect Python traceback header
        if PYTHON_TB_HEADER.match(line):
            trace_block = [line]
            i += 1
            # Collect all subsequent frame lines and their context lines
            frame_lines: list[str] = []
            error_line: str | None = None

            while i < len(lines):
                l = lines[i]
                if PYTHON_FRAME_PATTERN.match(l):
                    frame_lines.append(l)
                    i += 1
                    # Python frames are followed by a code context line
                    if i < len(lines) and lines[i].strip() and not PYTHON_FRAME_PATTERN.match(lines[i]) and not PYTHON_TB_HEADER.match(lines[i]):
                        frame_lines.append(lines[i])
                        i += 1
                elif l.strip() and not PYTHON_TB_HEADER.match(l):
                    # This is likely the exception line at the bottom
                    error_line = l
                    i += 1
                    break
                else:
                    break

            if len(frame_lines) >= MIN_FRAMES_TO_FOLD:
                # Keep top N and bottom N frame lines
                keep_top = frame_lines[:KEEP_FRAMES_TOP * 2]  # *2 because each frame has code line
                keep_bottom = frame_lines[-(KEEP_FRAMES_BOTTOM * 2):]
                middle_count = len(frame_lines) - len(keep_top) - len(keep_bottom)
                if middle_count > 0:
                    folded_frames = middle_count // 2 or middle_count
                    total_folded += middle_count
                    result_lines.append(trace_block[0])  # Traceback header
                    result_lines.extend(keep_top)
                    result_lines.append(f"    [... {folded_frames} more frames ...]")
                    result_lines.extend(keep_bottom)
                    if error_line:
                        result_lines.append(error_line)
                    continue
                # Not enough middle to fold — keep all
                result_lines.extend(trace_block)
                result_lines.extend(frame_lines)
                if error_line:
                    result_lines.append(error_line)
            else:
                # Too few frames to fold — keep all
                result_lines.extend(trace_block)
                result_lines.extend(frame_lines)
                if error_line:
                    result_lines.append(error_line)
            continue

        # Detect Java/Node/.NET stack trace (starts with "at ..." line)
        if STACK_FRAME_PATTERN.match(line) and not PYTHON_FRAME_PATTERN.match(line):
            frame_lines = [line]
            i += 1
            while i < len(lines) and STACK_FRAME_PATTERN.match(lines[i]):
                frame_lines.append(lines[i])
                i += 1

            if len(frame_lines) >= MIN_FRAMES_TO_FOLD:
                keep_top = frame_lines[:KEEP_FRAMES_TOP]
                keep_bottom = frame_lines[-KEEP_FRAMES_BOTTOM:]
                middle_count = len(frame_lines) - KEEP_FRAMES_TOP - KEEP_FRAMES_BOTTOM
                if middle_count > 0:
                    total_folded += middle_count
                    result_lines.extend(keep_top)
                    result_lines.append(f"    [... {middle_count} more frames ...]")
                    result_lines.extend(keep_bottom)
                else:
                    result_lines.extend(frame_lines)
            else:
                result_lines.extend(frame_lines)
            continue

        result_lines.append(line)
        i += 1

    if total_folded > 0:
        return "\n".join(result_lines), total_folded
    return text, 0


def is_critical_line(line: str) -> bool:
    return bool(CRITICAL_LINE_PATTERN.search(line))


def is_noise_line(line: str) -> bool:
    if is_critical_line(line):
        return False
    return bool(NOISE_LINE_PATTERN.search(line))


def fold_log_text(text: str, min_consecutive_noise: int = 3) -> tuple[str, int]:
    """
    Scans multiline text for repetitive terminal/compiler log lines and repeated error messages.
    First folds stack traces, then folds noise lines, then folds repeated error bursts.
    Folds blocks of >= min_consecutive_noise repetitive lines into a concise summary.
    """
    # Pre-pass: fold stack traces first
    text, stack_folded = fold_stack_traces(text)

    lines = text.split("\n")
    if len(lines) < min_consecutive_noise and stack_folded == 0:
        return text, 0

    intermediate_lines: list[str] = []
    noise_buffer: list[str] = []
    total_lines_folded = 0

    def flush_noise_buffer() -> None:
        nonlocal total_lines_folded
        if not noise_buffer:
            return
        if len(noise_buffer) < min_consecutive_noise:
            intermediate_lines.extend(noise_buffer)
        else:
            first_line = noise_buffer[0].strip()
            last_line = noise_buffer[-1].strip()
            if len(first_line) > 60:
                first_line = first_line[:57] + "..."
            if len(last_line) > 60:
                last_line = last_line[:57] + "..."

            count = len(noise_buffer)
            total_lines_folded += count
            folded_marker = f"[Folded {count} terminal/log lines: '{first_line}' ... '{last_line}']"
            intermediate_lines.append(folded_marker)
        noise_buffer.clear()

    for line in lines:
        if is_noise_line(line):
            noise_buffer.append(line)
        else:
            flush_noise_buffer()
            intermediate_lines.append(line)

    flush_noise_buffer()

    # Pass 2: Repeated identical/near-identical log lines (e.g. repeated error bursts)
    final_lines: list[str] = []
    repeat_buffer: list[str] = []
    current_sig: str | None = None

    def flush_repeat_buffer() -> None:
        nonlocal total_lines_folded
        if not repeat_buffer:
            return
        if len(repeat_buffer) >= (min_consecutive_noise - 1):
            count = len(repeat_buffer)
            total_lines_folded += count
            preview = repeat_buffer[0].strip()
            if len(preview) > 60:
                preview = preview[:57] + "..."
            final_lines.append(f"[Folded {count} repeated lines: '{preview}']")
        else:
            final_lines.extend(repeat_buffer)
        repeat_buffer.clear()

    for line in intermediate_lines:
        stripped = line.strip()
        if stripped and (re.search(r"\b(ERROR|WARN|INFO|DEBUG|FATAL|Exception|Timeout)\b", stripped, re.I) or re.match(r"^\[?\d{4}-\d{2}-\d{2}", stripped)):
            sig = re.sub(r"^\[?\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\]?\s*", "", stripped)
            sig = re.sub(r"\[REDACTED_[A-Z0-9_]+\]", "[REDACTED]", sig)
            sig = re.sub(r"_\d+\b", "", sig)
            sig = re.sub(r"\b\d+\b", "", sig).strip()
            if sig and sig == current_sig:
                repeat_buffer.append(line)
                continue
            else:
                flush_repeat_buffer()
                current_sig = sig
                final_lines.append(line)
        else:
            flush_repeat_buffer()
            current_sig = None
            final_lines.append(line)

    flush_repeat_buffer()

    total_lines_folded += stack_folded
    if total_lines_folded > 0:
        return "\n".join(final_lines), total_lines_folded
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
