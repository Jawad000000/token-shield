from __future__ import annotations

import ast
import difflib
import re
from typing import Any


CODE_BLOCK_PATTERN = re.compile(r"```([^\n`]*)\n([\s\S]*?)```")
FILENAME_COMMENT_PATTERN = re.compile(
    r"(?:#|//|<!--|\*)\s*(?:filename|file):\s*([a-zA-Z0-9_.-]+)",
    re.IGNORECASE,
)
FIRST_LINE_FILE_PATTERN = re.compile(
    r"^(?:#|//)\s*([a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+)\s*$",
    re.MULTILINE,
)
CONTEXT_FILENAME_PATTERN = re.compile(
    r"\b([a-zA-Z0-9_.-]+\.[a-zA-Z0-9]{1,8})\b"
)
SIGNATURE_PATTERN = re.compile(
    r"(?:class|interface|struct|function|func|def)\s+([a-zA-Z0-9_]+)",
    re.IGNORECASE,
)


def extract_ast_outline(code: str) -> str:
    """
    Extracts classes and functions for Python code in deterministic sorted order.
    Gracefully returns empty string on non-Python or syntax errors.
    """
    try:
        tree = ast.parse(code)
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        functions = [
            node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        parts: list[str] = []
        if classes:
            parts.append(f"Classes: [{', '.join(sorted(set(classes)))}]")
        if functions:
            parts.append(f"Functions: [{', '.join(sorted(set(functions)))}]")
        return " | ".join(parts)
    except Exception:
        return ""


def detect_file_key(lang_info: str, code: str, context_before: str = "") -> str:
    """
    Determines a stable identifier for the code block based on info string,
    explicit filename comments, surrounding context, or top-level signatures.
    """
    # 1. Look for filename inside code block info string (e.g. ```javascript AuthService.js)
    info_parts = lang_info.strip().split()
    clean_lang = info_parts[0].lower() if info_parts else "code"
    for part in info_parts[1:]:
        if "." in part and not part.endswith("."):
            return part.strip()

    # 2. Look for explicit comment like `# filename: app.py` or `// file: App.tsx`
    comment_match = FILENAME_COMMENT_PATTERN.search(code)
    if comment_match:
        return comment_match.group(1).strip()

    # 3. Look for first line like `# app.py`
    first_line_match = FIRST_LINE_FILE_PATTERN.search(code[:200])
    if first_line_match:
        return first_line_match.group(1).strip()

    # 4. Look for filename mentioned in the prompt context right before the code block
    if context_before:
        context_files = CONTEXT_FILENAME_PATTERN.findall(context_before[-150:])
        valid_files = [f for f in context_files if "." in f and not f.endswith(".")]
        if valid_files:
            return valid_files[-1].strip()

    # 5. Infer from top-level Python functions/classes
    try:
        tree = ast.parse(code)
        defs = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if defs:
            return f"{clean_lang}_{defs[0]}"
    except Exception:
        pass

    # 6. Multi-language signature extraction (JS/TS/Go/Java/Rust)
    sig_match = SIGNATURE_PATTERN.search(code)
    if sig_match:
        return f"{clean_lang}_{sig_match.group(1)}"

    # 7. Fallback based on language or generic identifier
    return f"{clean_lang}_snippet"


def prune_code_snippets(
    messages: list[dict[str, Any]],
    session_id: str,
    db: Any,
) -> tuple[list[dict[str, Any]], int]:
    """
    Scans messages for repeated code blocks against previous session snapshots.
    If a previous snapshot exists and a unified diff or reference is smaller
    than resending the full file, replaces the block with the diff and updates the snapshot.
    """
    if not messages:
        return messages, 0

    total_pruned = 0
    updated_messages: list[dict[str, Any]] = []

    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, str) or "```" not in content:
            updated_messages.append(dict(msg))
            continue

        new_content = content
        matches = list(CODE_BLOCK_PATTERN.finditer(content))

        for match in matches:
            full_match_text = match.group(0)
            lang_info = match.group(1) or ""
            code_text = match.group(2)

            # Skip tiny snippets (< 5 lines or < 80 chars) where diff overhead wouldn't save tokens
            lines = code_text.strip().splitlines()
            if len(lines) < 5 or len(code_text.strip()) < 80:
                continue

            start_idx = match.start()
            context_before = content[max(0, start_idx - 150):start_idx]
            file_key = detect_file_key(lang_info, code_text, context_before)

            # Check for existing snapshot in database
            prev_snapshot = db.get_latest_code_snapshot(session_id, file_key)

            if prev_snapshot is not None:
                # Measure similarity between previous and current code
                matcher = difflib.SequenceMatcher(None, prev_snapshot, code_text)
                ratio = matcher.ratio()

                # Case A: Identical code repeated verbatim
                if ratio >= 0.99:
                    replacement = f"[Code Reference: `{file_key}` is unchanged from previous turn]"
                    new_content = new_content.replace(full_match_text, replacement, 1)
                    total_pruned += 1
                    continue

                # Case B: Significant overlap (>= 40% identical)
                if ratio >= 0.4:
                    diff_lines = list(
                        difflib.unified_diff(
                            prev_snapshot.splitlines(keepends=True),
                            code_text.splitlines(keepends=True),
                            fromfile="",
                            tofile="",
                            n=1,
                        )
                    )
                    if len(diff_lines) >= 2 and diff_lines[0].startswith("---") and diff_lines[1].startswith("+++"):
                        diff_lines = diff_lines[2:]
                    diff_text = "".join(diff_lines).strip()

                    ast_outline = extract_ast_outline(code_text)
                    ast_header = f"AST Outline: {ast_outline}\n" if ast_outline else ""

                    replacement = (
                        f"[Code Update for `{file_key}` (Diff vs previous turn)]:\n"
                        f"{ast_header}"
                        f"```diff\n{diff_text}\n```"
                    )

                    if len(replacement) < len(full_match_text):
                        new_content = new_content.replace(full_match_text, replacement, 1)
                        total_pruned += 1
                        db.save_code_snapshot(session_id, file_key, code_text)
                        continue

            # Store snapshot for future turns
            db.save_code_snapshot(session_id, file_key, code_text)

        cloned_msg = dict(msg)
        cloned_msg["content"] = new_content
        updated_messages.append(cloned_msg)

    return updated_messages, total_pruned
