"""Tests for stack trace folding in log_folding.py."""
import pytest
from app.log_folding import fold_stack_traces, fold_log_text


class TestFoldStackTraces:
    """Tests for the fold_stack_traces function."""

    def test_python_traceback_folding(self):
        """Long Python traceback should fold middle frames."""
        tb = '''Traceback (most recent call last):
  File "/usr/lib/python3.11/site.py", line 45, in main
    run_module()
  File "/usr/lib/python3.11/runpy.py", line 22, in run
    import_module()
  File "/usr/lib/python3.11/importlib/__init__.py", line 10, in load
    loader.exec_module(mod)
  File "/usr/lib/python3.11/importlib/abc.py", line 55, in exec
    spec.loader.exec_module(module)
  File "/home/user/project/manage.py", line 22, in main
    execute_from_command_line(sys.argv)
  File "/home/user/project/app/views.py", line 127, in process
    result = db.query(sql)
  File "/home/user/project/app/db.py", line 42, in query
    cursor.execute(sql)
TypeError: 'NoneType' object is not subscriptable'''

        result, folded = fold_stack_traces(tb)
        assert folded > 0
        assert "more frames" in result
        # Error line must be preserved
        assert "TypeError: 'NoneType' object is not subscriptable" in result
        # Traceback header must be preserved
        assert "Traceback (most recent call last):" in result

    def test_short_traceback_not_folded(self):
        """Short Python traceback (< MIN_FRAMES_TO_FOLD) should not be folded."""
        tb = '''Traceback (most recent call last):
  File "app.py", line 10, in main
    foo()
  File "app.py", line 5, in foo
    raise ValueError("bad")
ValueError: bad'''

        result, folded = fold_stack_traces(tb)
        assert folded == 0
        assert result == tb

    def test_java_stack_trace_folding(self):
        """Long Java stack trace should fold middle frames."""
        frames = [
            "java.lang.NullPointerException: Cannot invoke method on null",
        ]
        for i in range(15):
            frames.append(f"    at com.example.service.Layer{i}.process(Layer{i}.java:{100 + i})")
        tb = "\n".join(frames)

        result, folded = fold_stack_traces(tb)
        assert folded > 0
        assert "more frames" in result
        # Error line is before the frames, not part of them, so it's kept
        assert "NullPointerException" in result

    def test_node_stack_trace_folding(self):
        """Long Node.js stack trace should fold middle frames."""
        frames = [
            "Error: Connection refused",
        ]
        for i in range(10):
            frames.append(f"    at Object.<anonymous> (/app/node_modules/lib/module{i}.js:{10 + i}:{i})")
        tb = "\n".join(frames)

        result, folded = fold_stack_traces(tb)
        assert folded > 0
        assert "more frames" in result

    def test_no_stack_trace(self):
        """Normal text without stack traces should pass through unchanged."""
        text = "This is a normal log message.\nAnother line.\nNo stack trace here."
        result, folded = fold_stack_traces(text)
        assert folded == 0
        assert result == text


class TestFoldLogTextWithStackTraces:
    """Integration: fold_log_text should fold stack traces via pre-pass."""

    def test_log_with_embedded_traceback(self):
        """Log output containing a Python traceback should fold the trace."""
        log = "2024-01-15 10:00:01 INFO Starting application\n"
        log += "2024-01-15 10:00:02 INFO Loading config\n"
        log += "Traceback (most recent call last):\n"
        for i in range(10):
            log += f'  File "/app/layer{i}.py", line {10 + i}, in func{i}\n'
            log += f"    call_layer{i + 1}()\n"
        log += "RuntimeError: database connection failed\n"
        log += "2024-01-15 10:00:03 INFO Retrying..."

        result, folded = fold_log_text(log)
        assert folded > 0
        assert "more frames" in result
        assert "RuntimeError: database connection failed" in result
