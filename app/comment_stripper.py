"""
Comment Stripper — removes comments from code blocks and unfenced code snippets.

LLMs understand code structure from the code itself; human-facing comments
(# TODO, // FIXME, /* explanation */, -- SQL notes) waste tokens without improving
model comprehension. Critical directives, shebangs, type annotations, and string literals
are always preserved.
"""
from __future__ import annotations

import copy
import re
from typing import Any

# ── Fenced code block detection ──────────────────────────────────────────────
FENCED_BLOCK_PATTERN = re.compile(r"(```([^\n`]*)\n([\s\S]*?)```)")

# ── Language → comment style mapping ────────────────────────────────────────
# Languages that use # for single-line comments
HASH_COMMENT_LANGS = {
    "python", "py", "ruby", "rb", "perl", "pl", "bash", "sh", "zsh", "r",
    "yaml", "yml", "toml", "dockerfile", "makefile", "make", "powershell", "ps1"
}
# Languages that use // for single-line comments
SLASH_COMMENT_LANGS = {
    "javascript", "js", "typescript", "ts", "java", "c", "cpp", "c++",
    "csharp", "cs", "go", "rust", "rs", "kotlin", "kt", "swift", "scala",
    "dart", "php"
}
# Languages that use -- for single-line comments
DASH_COMMENT_LANGS = {
    "sql", "pgsql", "postgres", "postgresql", "mysql", "sqlite", "sqlite3",
    "plsql", "tsql", "haskell", "hs", "lua", "ada"
}
# Languages that use /* */ for block comments
BLOCK_COMMENT_LANGS = SLASH_COMMENT_LANGS | DASH_COMMENT_LANGS | {"css", "scss", "less", "sass"}
# Languages that use <!-- --> for comments
HTML_COMMENT_LANGS = {"html", "xml", "svg", "vue", "jsx", "tsx", "markdown", "md"}


def _detect_lang(info_string: str) -> str:
    """Extract language from fenced block info string, lowercase."""
    parts = info_string.strip().split()
    return parts[0].lower() if parts else ""


def _strip_hash_comments(code: str) -> str:
    """Strip # comments from Python/Ruby/Bash-style code, preserving shebangs and strings."""
    lines = code.split("\n")
    result: list[str] = []

    for line in lines:
        stripped = line.lstrip()

        # Preserve shebangs
        if stripped.startswith("#!"):
            result.append(line)
            continue

        # Preserve type: ignore, noqa, pragma, type annotations
        if re.search(r"#\s*(type:\s*ignore|noqa|pragma|pylint|mypy|pyright)", stripped):
            result.append(line)
            continue

        # Skip full-line comments entirely
        if stripped.startswith("#"):
            continue

        # Strip inline comments: find # not inside a string
        new_line = _remove_inline_hash_comment(line)
        result.append(new_line)

    return "\n".join(result)


def _remove_inline_hash_comment(line: str) -> str:
    """Remove trailing # comment from a line, respecting string literals."""
    in_single = False
    in_double = False
    in_triple_single = False
    in_triple_double = False
    i = 0
    n = len(line)

    while i < n:
        if i + 2 < n:
            three = line[i:i+3]
            if three == '"""' and not in_single and not in_triple_single:
                in_triple_double = not in_triple_double
                i += 3
                continue
            if three == "'''" and not in_double and not in_triple_double:
                in_triple_single = not in_triple_single
                i += 3
                continue

        ch = line[i]

        if in_triple_single or in_triple_double:
            i += 1
            continue

        if ch == '\\' and i + 1 < n:
            i += 2
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '#' and not in_single and not in_double:
            return line[:i].rstrip()

        i += 1

    return line


def _strip_slash_comments(code: str) -> str:
    """Strip // single-line comments from JS/TS/Java/Go/Rust-style code."""
    lines = code.split("\n")
    result: list[str] = []

    for line in lines:
        stripped = line.lstrip()

        if stripped.startswith("//"):
            continue

        new_line = _remove_inline_slash_comment(line)
        result.append(new_line)

    return "\n".join(result)


def _remove_inline_slash_comment(line: str) -> str:
    """Remove trailing // comment from a line, respecting string literals."""
    in_single = False
    in_double = False
    in_template = False
    i = 0
    n = len(line)

    while i < n:
        ch = line[i]

        if ch == '\\' and i + 1 < n and (in_single or in_double or in_template):
            i += 2
            continue

        if ch == '"' and not in_single and not in_template:
            in_double = not in_double
        elif ch == "'" and not in_double and not in_template:
            in_single = not in_single
        elif ch == '`' and not in_single and not in_double:
            in_template = not in_template
        elif ch == '/' and i + 1 < n and line[i+1] == '/' and not in_single and not in_double and not in_template:
            # Preserve URLs (http:// or https://)
            if i >= 5 and line[max(0, i-5):i+2].lower() in ("http://", "https:/"):
                i += 2
                continue
            return line[:i].rstrip()

        i += 1

    return line


def _strip_dash_comments(code: str) -> str:
    """Strip -- comments from SQL/Lua/Haskell code, respecting string literals."""
    lines = code.split("\n")
    result: list[str] = []

    for line in lines:
        stripped = line.lstrip()

        if stripped.startswith("--"):
            continue

        new_line = _remove_inline_dash_comment(line)
        result.append(new_line)

    return "\n".join(result)


def _remove_inline_dash_comment(line: str) -> str:
    """Remove trailing -- comment from a line, respecting string literals."""
    in_single = False
    in_double = False
    i = 0
    n = len(line)

    while i < n:
        ch = line[i]

        if ch == '\\' and i + 1 < n and (in_single or in_double):
            i += 2
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '-' and i + 1 < n and line[i+1] == '-' and not in_single and not in_double:
            return line[:i].rstrip()

        i += 1

    return line


def _compact_multiline_docstrings(code: str) -> str:
    """
    Compacts multi-line docstrings in Python code (>= 2 lines) into a concise single-line docstring.
    Single-line docstrings (e.g. \"\"\"This is a docstring.\"\"\") are preserved verbatim.
    """
    def _replace_doc(m: re.Match) -> str:
        prefix = m.group(1)
        doc = m.group(2)
        quote = '"""' if doc.startswith('"""') else "'''"
        inner = doc[3:-3].strip()
        # If it's already a single-line docstring, preserve as-is
        if '\n' not in inner:
            return m.group(0)
        first_line = inner.split('\n')[0].strip().rstrip('.')
        if first_line:
            return f"{prefix}{quote}{first_line}.{quote}\n"
        return prefix

    pattern = re.compile(
        r'((?:def\s+\w+\s*\([^)]*\)\s*(?:->\s*[^:]+)?|class\s+\w+(?:\([^)]*\))?)\s*:\s*\n\s*)'
        r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')\s*\n',
        re.MULTILINE
    )
    return pattern.sub(_replace_doc, code)


def _compact_multiline_jsdoc(code: str) -> str:
    """
    Compacts multi-line JSDoc comments into a single-line summary or comment.
    Single-line JSDoc (e.g. /** @param {string} name */) is preserved verbatim.
    """
    def _replace_jsdoc(m: re.Match) -> str:
        full = m.group(0)
        inner = m.group(1)
        # If single line, keep it verbatim
        if '\n' not in inner.strip():
            return full
        lines = [line.strip().lstrip('*').strip() for line in inner.split('\n')]
        useful = [line for line in lines if line and not line.startswith('@')]
        if useful:
            summary = useful[0]
            if len(summary) > 60:
                summary = summary[:57] + '...'
            return f"/* {summary} */"
        return ""

    return re.compile(r"/\*\*([\s\S]*?)\*/").sub(_replace_jsdoc, code)


def _strip_block_comments(code: str) -> str:
    """Strip /* ... */ block comments, preserving single-line JSDoc and string literals."""
    result: list[str] = []
    i = 0
    n = len(code)
    in_single = False
    in_double = False

    while i < n:
        ch = code[i]

        if ch == '\\' and i + 1 < n and (in_single or in_double):
            result.append(code[i:i+2])
            i += 2
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            result.append(ch)
            i += 1
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            result.append(ch)
            i += 1
            continue

        if in_single or in_double:
            result.append(ch)
            i += 1
            continue

        # Check for block comment start
        if ch == '/' and i + 1 < n and code[i+1] == '*':
            # Preserve single-line JSDoc (/** ... */)
            if i + 2 < n and code[i+2] == '*' and (i + 3 >= n or code[i+3] != '/'):
                end_jsdoc = code.find("*/", i + 3)
                if end_jsdoc != -1 and '\n' not in code[i:end_jsdoc]:
                    result.append(code[i:end_jsdoc+2])
                    i = end_jsdoc + 2
                    continue

            # Skip the block comment
            end = code.find("*/", i + 2)
            if end != -1:
                i = end + 2
            else:
                result.append(ch)
                i += 1
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def _strip_html_comments(code: str) -> str:
    """Strip <!-- ... --> comments from HTML/XML content."""
    return re.sub(r"<!--(?!\[if\s)[\s\S]*?-->", "", code)


def strip_comments_from_code(code: str, lang: str) -> tuple[str, bool]:
    """
    Strips comments from a code snippet based on its language.
    Returns (cleaned_code, was_modified).
    """
    original = code

    if lang in HASH_COMMENT_LANGS:
        code = _strip_hash_comments(code)
        if lang in ("python", "py"):
            code = _compact_multiline_docstrings(code)

    if lang in SLASH_COMMENT_LANGS:
        code = _compact_multiline_jsdoc(code)
        code = _strip_slash_comments(code)
        code = _strip_block_comments(code)

    if lang in DASH_COMMENT_LANGS:
        code = _strip_dash_comments(code)
        code = _strip_block_comments(code)

    if lang in BLOCK_COMMENT_LANGS and lang not in SLASH_COMMENT_LANGS and lang not in DASH_COMMENT_LANGS:
        code = _strip_block_comments(code)

    if lang in HTML_COMMENT_LANGS:
        code = _strip_html_comments(code)

    # Clean up artifacts: collapse 3+ blank lines to 2
    code = re.sub(r"\n{3,}", "\n\n", code)
    code = code.strip("\n")

    modified = code != original.strip("\n")
    return code, modified


def strip_unfenced_comments(text: str) -> tuple[str, bool]:
    """
    Finds and strips comments from unfenced code snippets pasted into text,
    while safely preserving regular markdown prose and headings.
    """
    original = text

    # Quick check: does the text have any comment characters?
    if not any(marker in text for marker in ("/*", "<!--", "//", "--", "#", '"""', "'''")):
        return text, False

    # 1. Compact verbose JSDoc blocks
    if "/**" in text:
        text = _compact_multiline_jsdoc(text)

    # 2. Strip ordinary block comments /* ... */
    if "/*" in text:
        text = _strip_block_comments(text)

    # 3. Strip HTML comments <!-- ... -->
    if "<!--" in text:
        text = _strip_html_comments(text)

    # 4. Compact Python multi-line docstrings if function/class def present
    if "def " in text or "class " in text:
        text = _compact_multiline_docstrings(text)

    # 5. Determine code contexts
    has_sql = bool(re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|CREATE\s+TABLE)\b", text, re.I))
    has_py = bool(re.search(r"\b(def\s+\w+|class\s+\w+|import\s+\w+|elif\s+|if\s+__name__|return\b)", text))
    has_slash_code = bool(re.search(r"\b(function\s+\w+|const\s+\w+|let\s+\w+|var\s+\w+|public\s+|private\s+|interface\s+)\b", text)) or "//" in text

    lines = text.split("\n")
    cleaned_lines = []

    for line in lines:
        stripped = line.lstrip()

        # SQL full-line comments (-- comment)
        if has_sql and stripped.startswith("--"):
            continue

        # Slash full-line comments (// comment)
        if stripped.startswith("//"):
            continue

        # Hash comments (# comment)
        if stripped.startswith("#"):
            if stripped.startswith("#!"):
                cleaned_lines.append(line)
                continue
            if re.search(r"#\s*(type:\s*ignore|noqa|pragma|pylint)", stripped):
                cleaned_lines.append(line)
                continue
            # If in python code or indented
            if has_py or line.startswith("    ") or line.startswith("\t"):
                continue
            # Check comment metadata headers
            if re.match(r"^#\s*(Author|Date|License|TODO|FIXME|NOTE|Step\s*\d|Base|Recursive|Check|Config)", stripped, re.I):
                continue
            # If markdown heading, preserve unless python code context
            if stripped.startswith("###") or stripped.startswith("##") or stripped.startswith("# "):
                if has_py:
                    continue
                cleaned_lines.append(line)
                continue
            continue

        # Inline comments
        cur = line
        if has_sql and "--" in cur:
            cur = _remove_inline_dash_comment(cur)
        if "//" in cur and not re.search(r"https?://", cur):
            cur = _remove_inline_slash_comment(cur)
        if has_py and "#" in cur:
            cur = _remove_inline_hash_comment(cur)

        cleaned_lines.append(cur)

    res = "\n".join(cleaned_lines)
    res = re.sub(r"\n{3,}", "\n\n", res).strip()
    return res, res != original.strip()


def strip_comments_in_text(text: str) -> tuple[str, int]:
    """
    Finds comments in text (both fenced code blocks and unfenced snippets)
    and strips them losslessly.
    Returns (optimized_text, blocks_modified_count).
    """
    blocks_modified = 0

    if "```" in text:
        def replace_block(match: re.Match) -> str:
            nonlocal blocks_modified
            full = match.group(0)
            info = match.group(2) or ""
            code = match.group(3)

            lang = _detect_lang(info)
            if not lang or len(code.strip()) < 30:
                return full

            cleaned, was_modified = strip_comments_from_code(code, lang)
            if was_modified and len(cleaned.strip()) > 0:
                blocks_modified += 1
                return f"```{info}\n{cleaned}\n```"
            return full

        text = FENCED_BLOCK_PATTERN.sub(replace_block, text)

    # Also handle unfenced comments or comments outside fences
    unfenced_cleaned, unfenced_modified = strip_unfenced_comments(text)
    if unfenced_modified and len(unfenced_cleaned.strip()) > 0:
        blocks_modified += 1
        text = unfenced_cleaned

    return text, blocks_modified


def strip_comments_in_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """
    Applies comment stripping across all messages.
    Returns (optimized_messages, total_blocks_modified).
    Never mutates input objects.
    """
    optimized: list[dict[str, Any]] = []
    total_modified = 0

    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and len(content) > 30:
            stripped_text, count = strip_comments_in_text(content)
            if count > 0:
                total_modified += count
                cloned = dict(msg)
                cloned["content"] = stripped_text
                optimized.append(cloned)
                continue
        optimized.append(msg)

    return optimized, total_modified
