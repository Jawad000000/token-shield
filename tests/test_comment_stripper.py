"""Tests for app.comment_stripper — lossless comment removal from code blocks."""
from __future__ import annotations

import pytest

from app.comment_stripper import (
    strip_comments_from_code,
    strip_comments_in_messages,
    strip_comments_in_text,
)


class TestPythonComments:
    def test_strips_full_line_hash_comments(self):
        code = "# This is a comment\nx = 1\n# Another comment\ny = 2"
        result, modified = strip_comments_from_code(code, "python")
        assert modified
        assert "# This is a comment" not in result
        assert "# Another comment" not in result
        assert "x = 1" in result
        assert "y = 2" in result

    def test_strips_inline_hash_comments(self):
        code = 'x = 1  # set x\ny = "hello"  # set y'
        result, modified = strip_comments_from_code(code, "python")
        assert modified
        assert "x = 1" in result
        assert "# set x" not in result

    def test_preserves_shebang(self):
        code = "#!/usr/bin/env python3\n# a comment\nimport sys"
        result, modified = strip_comments_from_code(code, "python")
        assert "#!/usr/bin/env python3" in result
        assert "# a comment" not in result

    def test_preserves_type_ignore(self):
        code = "x = foo()  # type: ignore\ny = bar()  # noqa"
        result, modified = strip_comments_from_code(code, "python")
        assert "# type: ignore" in result
        assert "# noqa" in result

    def test_preserves_hash_in_strings(self):
        code = 'url = "https://example.com/path#fragment"\ncolor = "#ff0000"'
        result, modified = strip_comments_from_code(code, "python")
        assert "#fragment" in result
        assert "#ff0000" in result

    def test_preserves_docstrings(self):
        code = 'def foo():\n    """This is a docstring."""\n    pass'
        result, modified = strip_comments_from_code(code, "python")
        assert '"""This is a docstring."""' in result


class TestJSComments:
    def test_strips_single_line_slash_comments(self):
        code = "// Initialize app\nconst x = 1;\n// Set config\nconst y = 2;"
        result, modified = strip_comments_from_code(code, "javascript")
        assert modified
        assert "// Initialize app" not in result
        assert "const x = 1;" in result

    def test_strips_inline_slash_comments(self):
        code = "const x = 1; // important value"
        result, modified = strip_comments_from_code(code, "javascript")
        assert "const x = 1;" in result
        assert "// important" not in result

    def test_strips_block_comments(self):
        code = "/* This is\na block comment */\nconst x = 1;"
        result, modified = strip_comments_from_code(code, "javascript")
        assert modified
        assert "block comment" not in result
        assert "const x = 1;" in result

    def test_preserves_jsdoc(self):
        code = "/** @param {string} name */\nfunction greet(name) {}"
        result, modified = strip_comments_from_code(code, "javascript")
        assert "/** @param {string} name */" in result

    def test_preserves_url_in_strings(self):
        code = 'const url = "https://example.com/path";'
        result, modified = strip_comments_from_code(code, "javascript")
        assert "https://example.com/path" in result

    def test_preserves_slash_in_strings(self):
        code = "const regex = '// not a comment';"
        result, modified = strip_comments_from_code(code, "javascript")
        assert "// not a comment" in result


class TestHTMLComments:
    def test_strips_html_comments(self):
        code = "<!-- Navigation -->\n<nav>hello</nav>\n<!-- Footer -->\n<footer>bye</footer>"
        result, modified = strip_comments_from_code(code, "html")
        assert modified
        assert "<!-- Navigation -->" not in result
        assert "<nav>hello</nav>" in result

    def test_preserves_conditional_comments(self):
        code = "<!--[if IE 9]><link href='ie9.css'><![endif]-->"
        result, modified = strip_comments_from_code(code, "html")
        assert "<!--[if IE 9]>" in result


class TestMessageIntegration:
    def test_strips_comments_in_fenced_blocks(self):
        text = 'Here is my code:\n```python\n# This is a comment that wastes tokens\nx = 1\n# Another useless comment here\ny = 2\nz = x + y\n```\nPlease review it.'
        result, count = strip_comments_in_text(text)
        assert count == 1
        assert "# This is a comment" not in result
        assert "x = 1" in result
        assert "Please review it." in result

    def test_does_not_modify_prose(self):
        text = "This is just prose with no code blocks at all."
        result, count = strip_comments_in_text(text)
        assert count == 0
        assert result == text

    def test_skips_unknown_languages(self):
        text = "```\nsome plain text block\n# not a comment\n```"
        result, count = strip_comments_in_text(text)
        assert count == 0

    def test_skips_short_code_blocks(self):
        text = "```python\nx = 1\n```"
        result, count = strip_comments_in_text(text)
        assert count == 0

    def test_message_list_processing(self):
        messages = [
            {"role": "user", "content": "```javascript\n// setup the database connection pool\n// this is very important for performance\nconst pool = createPool(config);\nconst client = await pool.connect();\nawait client.query('SELECT 1');\n```"},
        ]
        result, count = strip_comments_in_messages(messages)
        assert count == 1
        assert "// setup the database" not in result[0]["content"]
        assert "createPool(config)" in result[0]["content"]

    def test_never_mutates_input(self):
        original_content = "```python\n# big comment block for testing purposes\nx = 1\ny = 2\nz = x + y\nresult = z * 2\n```"
        messages = [{"role": "user", "content": original_content}]
        strip_comments_in_messages(messages)
        assert messages[0]["content"] == original_content


class TestMultiLanguage:
    def test_typescript(self):
        code = "// TypeScript interface\ninterface User {\n  name: string; // user name\n  age: number;\n}"
        result, modified = strip_comments_from_code(code, "ts")
        assert modified
        assert "// TypeScript interface" not in result
        assert "interface User" in result

    def test_go(self):
        code = "// Package main provides the entry point\npackage main\n\n// main is the entry point\nfunc main() {\n\tfmt.Println(\"hello\")\n}"
        result, modified = strip_comments_from_code(code, "go")
        assert modified
        assert "// Package main" not in result
        assert "package main" in result

    def test_css_block_comments(self):
        code = "/* Reset styles */\nbody { margin: 0; }\n/* Header styles */\n.header { color: red; }"
        result, modified = strip_comments_from_code(code, "css")
        assert modified
        assert "/* Reset styles */" not in result
        assert "body { margin: 0; }" in result

    def test_sql_comments(self):
        code = "-- Select active users\nSELECT id, name -- primary keys\nFROM users -- table\nWHERE active = true;"
        result, modified = strip_comments_from_code(code, "sql")
        assert modified
        assert "-- Select active users" not in result
        assert "-- primary keys" not in result
        assert "SELECT id, name" in result
        assert "FROM users" in result


class TestUnfencedCodeStripping:
    def test_unfenced_python_code(self):
        text = "# Author: dev\ndef add(a, b):\n    # add two numbers\n    return a + b # inline sum\nHow do I test this?"
        result, count = strip_comments_in_text(text)
        assert count > 0
        assert "# Author: dev" not in result
        assert "# add two numbers" not in result
        assert "def add(a, b):" in result
        assert "How do I test this?" in result

    def test_unfenced_sql_code(self):
        text = "-- Daily report\nSELECT id, email -- user email\nFROM users\nWHERE active = 1;\nExplain this query."
        result, count = strip_comments_in_text(text)
        assert count > 0
        assert "-- Daily report" not in result
        assert "-- user email" not in result
        assert "SELECT id, email" in result
        assert "Explain this query." in result

    def test_unfenced_js_code(self):
        text = "function login() {\n  // check auth\n  return true; /* ok */\n}\nAny flaws?"
        result, count = strip_comments_in_text(text)
        assert count > 0
        assert "// check auth" not in result
        assert "/* ok */" not in result
        assert "function login()" in result
        assert "Any flaws?" in result

