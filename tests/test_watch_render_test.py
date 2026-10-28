"""Pure-function tests for the renderer_test hang watchdog."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from watch_render_test import (  # noqa: E402
    classify_attempt,
    find_test_executable,
    format_attempt,
    last_lines,
    parse_test_result,
    summarize,
    summary_exit_code,
)

OK_SUMMARY = (
    "test result: ok. 9 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 3.5s\n"
)
FAILED_SUMMARY = (
    "test result: FAILED. 8 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; "
    "finished in 3.5s\n"
)


def test_normal_libtest_summary_is_not_a_hang() -> None:
    stdout = f"running 9 tests\ntest a ... ok\n{OK_SUMMARY}"
    assert parse_test_result(stdout) == (9, 0)
    assert classify_attempt(stdout, timed_out=False) == "PASS"


def test_missing_test_result_line_is_a_hang() -> None:
    stdout = "running 9 tests\ntest a ... ok\n"
    assert parse_test_result(stdout) is None
    assert classify_attempt(stdout, timed_out=False) == "HANG"


def test_timeout_is_a_hang_even_with_a_summary() -> None:
    assert classify_attempt(OK_SUMMARY, timed_out=True) == "HANG"


def test_failed_summary_is_a_failure_not_a_hang() -> None:
    assert parse_test_result(FAILED_SUMMARY) == (8, 1)
    assert classify_attempt(FAILED_SUMMARY, timed_out=False) == "FAIL"


def test_summary_accounting_and_exit_code() -> None:
    assert (
        summarize(passed=2, failed=0, hung=1) == "SUMMARY 2 passed, 0 failed, 1 hung (3 attempts)"
    )
    assert summary_exit_code(failed=0, hung=1) == 1
    assert summary_exit_code(failed=1, hung=0) == 1
    assert summary_exit_code(failed=0, hung=0) == 0


def test_attempt_line_and_diagnostic_tail() -> None:
    assert format_attempt(2, 3, "HANG", 60.04) == "HANG 2/3 60.0s"
    text = "\n".join(f"line {i}" for i in range(25))
    assert last_lines(text, 20) == [f"line {i}" for i in range(5, 25)]


def test_find_test_executable_uses_the_compiler_artifact() -> None:
    messages = [
        json.dumps(
            {
                "reason": "compiler-artifact",
                "target": {"name": "another_test", "kind": ["test"]},
                "executable": "/opt/another_test",
            }
        ),
        json.dumps(
            {
                "reason": "compiler-artifact",
                "target": {"name": "renderer_test", "kind": ["test"]},
                "executable": "/opt/renderer_test",
            }
        ),
        "a cargo line that is not JSON",
    ]
    assert find_test_executable("\n".join(messages)) == Path("/opt/renderer_test")


def test_find_test_executable_returns_none_without_an_artifact() -> None:
    assert find_test_executable("") is None
    assert find_test_executable('{"reason":"build-finished","success":true}') is None
