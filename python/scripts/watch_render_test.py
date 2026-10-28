#!/usr/bin/env python3
"""Run the stunt-render renderer_test binary under a bounded hang watchdog.

The GPU integration tests can deadlock inside the graphics driver/loader on some machines: the
process stays alive forever, libtest never prints its final ``test result:`` line, and a plain
``cargo test`` waits indefinitely (see ``target/renderer_test-hang/report.md``). This runner builds
the test binary once, runs it ``--runs`` times with a wall-clock bound, kills the whole process tree
when the bound expires, and reports ``HANG`` with the last stdout lines and the child-process count.

Usage::

    uv run python python/scripts/watch_render_test.py --runs 3
    uv run python python/scripts/watch_render_test.py --timeout-s 120 --require-gpu
    uv run python python/scripts/watch_render_test.py --bin target/debug/deps/renderer_test.exe

Exit status: ``0`` when every attempt completed with a passing libtest summary, ``1`` when any
attempt hung or its tests failed, ``2`` for usage or build errors.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_PACKAGE = "stunt-render"
TEST_TARGET = "renderer_test"
DEFAULT_RUNS = 1
DEFAULT_TIMEOUT_S = 60.0
DIAGNOSTIC_LINE_LIMIT = 20
_RESULT_RE = re.compile(
    r"^test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed;",
    re.MULTILINE,
)

AttemptOutcome = Literal["PASS", "FAIL", "HANG"]


class WatchError(Exception):
    """The watchdog could not build or invoke the test binary."""


@dataclass(frozen=True)
class Attempt:
    """One bounded run of the test binary."""

    outcome: AttemptOutcome
    elapsed_s: float
    stdout: str
    children: int = 0


def tool(name: str) -> str:
    """Resolve a command from PATH, failing loudly when it is absent."""
    path = shutil.which(name)
    if path is None:
        raise WatchError(f"{name} was not found on PATH")
    return path


def parse_test_result(stdout: str) -> tuple[int, int] | None:
    """Return ``(passed, failed)`` from libtest's final summary, or None when absent."""
    match = _RESULT_RE.search(stdout)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def classify_attempt(stdout: str, *, timed_out: bool) -> AttemptOutcome:
    """Classify one attempt as PASS, FAIL or HANG without touching Cargo or processes.

    A run is a hang when the wall-clock bound expired or when libtest never printed its final
    ``test result:`` line (a crash or an abort looks the same as a stall to the watchdog).
    """
    if timed_out:
        return "HANG"
    counts = parse_test_result(stdout)
    if counts is None:
        return "HANG"
    passed, failed = counts
    return "PASS" if failed == 0 and passed > 0 else "FAIL"


def format_attempt(index: int, total: int, outcome: AttemptOutcome, elapsed_s: float) -> str:
    """One stable line per attempt, e.g. ``PASS 1/3 3.5s``."""
    return f"{outcome} {index}/{total} {elapsed_s:.1f}s"


def last_lines(text: str, limit: int = DIAGNOSTIC_LINE_LIMIT) -> list[str]:
    """The last ``limit`` lines of ``text``, without a trailing blank line."""
    return text.splitlines()[-limit:]


def summarize(*, passed: int, failed: int, hung: int) -> str:
    """The final one-line accounting."""
    total = passed + failed + hung
    attempts = "attempt" if total == 1 else "attempts"
    return f"SUMMARY {passed} passed, {failed} failed, {hung} hung ({total} {attempts})"


def summary_exit_code(*, failed: int, hung: int) -> int:
    """The process exit status for a completed batch."""
    return 1 if failed or hung else 0


def find_test_executable(cargo_json: str) -> Path | None:
    """Find the ``renderer_test`` artifact executable in Cargo's JSON message stream."""
    for line in cargo_json.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            message = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict) or message.get("reason") != "compiler-artifact":
            continue
        target = message.get("target")
        if not isinstance(target, dict):
            continue
        if target.get("name") != TEST_TARGET or "test" not in target.get("kind", []):
            continue
        executable = message.get("executable")
        if isinstance(executable, str) and executable:
            return Path(executable)
    return None


def build_test_binary() -> Path:
    """Build ``renderer_test`` once and return the executable Cargo reports."""
    command = [
        tool("cargo"),
        "test",
        "-p",
        TEST_PACKAGE,
        "--test",
        TEST_TARGET,
        "--no-run",
        "--message-format=json",
    ]
    completed = subprocess.run(  # noqa: S603 - fixed argv, cargo resolved from PATH
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        tail = "\n".join(last_lines(completed.stderr))
        raise WatchError(f"cargo build failed (exit {completed.returncode}):\n{tail}")
    executable = find_test_executable(completed.stdout)
    if executable is None:
        raise WatchError("cargo did not report an executable for renderer_test")
    return executable


def count_descendants(pid: int) -> int:
    """Count live descendant processes of ``pid`` (best effort, never fails the run)."""
    if os.name == "nt":
        return _windows_descendant_count(pid)
    return _posix_descendant_count(pid)


def _count_tree(children: dict[int, list[int]], root: int) -> int:
    count = 0
    seen = {root}
    pending = [root]
    while pending:
        for child in children.get(pending.pop(), []):
            if child in seen:
                continue
            seen.add(child)
            count += 1
            pending.append(child)
    return count


def _windows_descendant_count(pid: int) -> int:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        return 0
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, shell resolved from PATH
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return 0
    if completed.returncode != 0 or not completed.stdout.strip():
        return 0
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return 0
    entries = payload if isinstance(payload, list) else [payload]
    children: dict[int, list[int]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        parent = entry.get("ParentProcessId")
        child = entry.get("ProcessId")
        if isinstance(parent, int) and isinstance(child, int):
            children.setdefault(parent, []).append(child)
    return _count_tree(children, pid)


def _posix_descendant_count(pid: int) -> int:
    ps = shutil.which("ps")
    if ps is None:
        return 0
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, ps resolved from PATH
            [ps, "-eo", "pid=,ppid="],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return 0
    if completed.returncode != 0:
        return 0
    children: dict[int, list[int]] = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            child_pid, parent_pid = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        children.setdefault(parent_pid, []).append(child_pid)
    return _count_tree(children, pid)


def kill_process_tree(process: subprocess.Popen[str]) -> None:
    """Kill ``process`` and every descendant, without leaving orphans."""
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill is not None:
            subprocess.run(  # noqa: S603 - fixed argv, taskkill resolved from PATH
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
    else:
        killpg = getattr(os, "killpg", None)
        getpgid = getattr(os, "getpgid", None)
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        if killpg is not None and getpgid is not None:
            with contextlib.suppress(ProcessLookupError):
                killpg(getpgid(process.pid), sigkill)
    with contextlib.suppress(ProcessLookupError, OSError):
        process.kill()


def _collect_after_kill(process: subprocess.Popen[str]) -> str:
    """Reap the killed process and return everything it wrote before dying."""
    try:
        stdout, _ = process.communicate(timeout=10.0)
        return stdout
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            process.kill()
    try:
        stdout, _ = process.communicate(timeout=10.0)
    except subprocess.TimeoutExpired:
        return ""
    return stdout


def run_attempt(
    binary: Path,
    *,
    timeout_s: float,
    require_gpu: bool,
    test_threads: int | None,
) -> Attempt:
    """Run the binary once under a wall-clock bound and classify the outcome."""
    arguments = [str(binary)]
    if test_threads is not None:
        arguments += ["--test-threads", str(test_threads)]
    environment = dict(os.environ)
    if require_gpu:
        environment["STUNT_REQUIRE_GPU"] = "1"
    process = subprocess.Popen(  # noqa: S603 - fixed argv, binary path from cargo or --bin
        arguments,
        cwd=REPO_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=os.name != "nt",
    )
    started = time.monotonic()
    timed_out = False
    children = 0
    try:
        stdout, _ = process.communicate(timeout=timeout_s)
        elapsed_s = time.monotonic() - started
    except subprocess.TimeoutExpired:
        timed_out = True
        elapsed_s = time.monotonic() - started
        children = count_descendants(process.pid)
        kill_process_tree(process)
        stdout = _collect_after_kill(process)
    return Attempt(
        outcome=classify_attempt(stdout, timed_out=timed_out),
        elapsed_s=elapsed_s,
        stdout=stdout,
        children=children,
    )


def print_hang_diagnostics(attempt: Attempt) -> None:
    """Print the elapsed time, last stdout lines and child-process count for a hang."""
    print(f"  elapsed: {attempt.elapsed_s:.1f}s")
    print(f"  child processes still alive: {attempt.children}")
    print(f"  last {DIAGNOSTIC_LINE_LIMIT} stdout lines:")
    lines = last_lines(attempt.stdout)
    if not lines:
        print("    (no output captured)")
    for line in lines:
        print(f"    {line}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"number of attempts (default {DEFAULT_RUNS})",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"wall-clock bound per attempt in seconds (default {DEFAULT_TIMEOUT_S:g})",
    )
    parser.add_argument(
        "--require-gpu",
        action="store_true",
        help="set STUNT_REQUIRE_GPU=1 for every attempt (missing adapter fails instead of skips)",
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=None,
        help="run this renderer_test binary instead of building it",
    )
    parser.add_argument(
        "--test-threads",
        type=int,
        default=None,
        help="pass --test-threads N to each attempt",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress per-attempt PASS lines (hang diagnostics and the summary are always printed)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Build once, run the bounded attempts, and return the batch exit status."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be positive")
    if args.test_threads is not None and args.test_threads < 1:
        parser.error("--test-threads must be at least 1")

    try:
        if args.bin is not None:
            binary = Path(args.bin).resolve()
            if not binary.is_file():
                raise WatchError(f"test binary not found: {binary}")
            if not args.quiet:
                print(f"BIN {binary}")
        else:
            binary = build_test_binary()
            if not args.quiet:
                print(f"BUILD {binary}")
    except WatchError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2

    passed = failed = hung = 0
    for index in range(1, args.runs + 1):
        attempt = run_attempt(
            binary,
            timeout_s=args.timeout_s,
            require_gpu=args.require_gpu,
            test_threads=args.test_threads,
        )
        if attempt.outcome == "PASS":
            passed += 1
        elif attempt.outcome == "FAIL":
            failed += 1
        else:
            hung += 1
        line = format_attempt(index, args.runs, attempt.outcome, attempt.elapsed_s)
        if attempt.outcome == "HANG":
            print(line)
            print_hang_diagnostics(attempt)
        elif not args.quiet:
            print(line)
    print(summarize(passed=passed, failed=failed, hung=hung))
    return summary_exit_code(failed=failed, hung=hung)


if __name__ == "__main__":
    raise SystemExit(main())
