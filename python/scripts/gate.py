"""Run the quality gate as concurrent lanes of steps and print a verdict.

``mise run check`` used to be a ``depends`` chain: each task printed its own output, nothing
gave a verdict, and the quiet halves ran a shorter step list than the full gate. This script
runs the leaf steps, prints one line per step plus a failing step's tail, writes the complete
output to ``target/check.log``, and ends with PASS or FAIL. The commands stay defined in
``mise.toml``: each step is executed as ``mise run <task>``, so there is no second copy of the
gate to drift. See [ADR 0014](../docs/adr/0014-the-gate-is-one-ordered-script.md).

Steps run as *lanes*: the steps in one lane run in order, and lanes run at the same time. A lane
is the unit of an exclusively held resource, so the cargo steps that build into one target
directory share a lane, while a step that only reads files, or builds into a target directory of
its own, gets a lane of its own. See [ADR 0016](../docs/adr/0016-the-gate-runs-independent-lanes.md).

The gate reports every failing step, not just the first: lanes keep running so one run names all
of them. The plan is one step list for the whole gate and for each half.

Steps that can silently skip are listed in ``REQUIRED_ENV``. The Python test step sets
``STUNT_REQUIRE_KSC=1``, so a missing Kaitai compiler fails the gate instead of skipping the
schema contract test.

Usage: ``python python/scripts/gate.py {all|rust|py} [--tail N]``
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Sequence

LOG_PATH = Path("target") / "check.log"

# The step list is every leaf task, in display order; a task that only aggregates others
# (check, fmt-check, lint, test) must never appear here or the gate recurses. A step added here
# needs a STEP_LANES entry, and _lane_plan refuses to run without one.
STEPS: dict[str, list[str]] = {
    "rust": ["fmt-check-rust", "lint-rust", "test-rust", "doc", "check-rust-matrix"],
    "py": ["fmt-check-py", "lint-py", "typecheck", "test-py"],
}

# Each step belongs to one lane. Steps in the same lane run in order, one at a time; lanes run
# concurrently. The lane is the unit of an exclusively held resource, so a cargo step shares its
# lane with every other step that builds into the same target directory: cargo holds an exclusive
# lock there, and two lanes on one directory would only serialise on it. A task that sets its own
# CARGO_TARGET_DIR in mise.toml (lint-rust, check-rust-matrix) therefore owns its lane.
STEP_LANES: dict[str, str] = {
    "fmt-check-rust": "rust-fmt",
    "lint-rust": "rust-lint",
    "test-rust": "rust-build",
    "doc": "rust-build",
    "check-rust-matrix": "rust-matrix",
    "fmt-check-py": "py-fmt",
    "lint-py": "py-lint",
    "typecheck": "py-typecheck",
    "test-py": "py-test",
}

REQUIRED_ENV: dict[str, dict[str, str]] = {"test-py": {"STUNT_REQUIRE_KSC": "1"}}


def _plan(half: str) -> list[str]:
    """Return the ordered steps for one half of the gate."""
    return [*STEPS["rust"], *STEPS["py"]] if half == "all" else STEPS[half]


def _report(task: str, code: int, elapsed: float) -> None:
    print(f"[gate] {task:<18} {'ok' if code == 0 else 'FAIL':<4} ({elapsed:>4.0f}s)", flush=True)


def _lane_plan(plan: Sequence[str]) -> list[tuple[str, list[str]]]:
    """Group the plan into lanes, keeping each lane's steps in plan order."""
    lanes: dict[str, list[str]] = {}
    for task in plan:
        try:
            lane = STEP_LANES[task]
        except KeyError:
            raise SystemExit(f"step {task!r} has no lane in STEP_LANES") from None
        lanes.setdefault(lane, []).append(task)
    return list(lanes.items())


def _mise() -> str:
    """Resolve the mise executable, which is how every step is dispatched."""
    executable = shutil.which("mise")
    if executable is None:
        raise SystemExit("mise is not on PATH; run the gate through 'mise run check'")
    return executable


def _step(mise: str, task: str) -> tuple[int, str, float]:
    """Run one mise task, returning its exit code, combined output and duration."""
    # MISE_QUIET silences the child mise's own tool-resolution chatter, which would
    # otherwise repeat once per step in the log.
    env = {**os.environ, "MISE_QUIET": "1", **REQUIRED_ENV.get(task, {})}
    started = time.monotonic()
    proc = subprocess.run(  # noqa: S603 - fixed task names from STEPS, mise resolved from PATH
        [mise, "run", task],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    return proc.returncode, f"{proc.stdout}{proc.stderr}", time.monotonic() - started


def _run_lane(
    mise: str,
    tasks: Sequence[str],
    log: TextIO,
    lock: threading.Lock,
    results: dict[str, tuple[int, str, float]],
) -> None:
    """Run one lane's steps in order, reporting each as it finishes."""
    for task in tasks:
        try:
            code, output, elapsed = _step(mise, task)
        except Exception as exc:
            # A step that cannot even start must still name the failure in the verdict.
            code, output, elapsed = 1, f"gate could not run the step: {exc!r}", 0.0
        with lock:
            results[task] = (code, output, elapsed)
            log.write(f"\n===== mise run {task} (exit {code}, {elapsed:.1f}s) =====\n")
            log.write(output)
            log.flush()
            _report(task, code, elapsed)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("half", choices=("all", "rust", "py"), help="which half of the gate")
    parser.add_argument("--tail", type=int, default=40, help="lines shown of a failing step")
    args = parser.parse_args(argv)

    plan = _plan(str(args.half))
    lanes = _lane_plan(plan)
    mise = _mise()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    results: dict[str, tuple[int, str, float]] = {}
    lock = threading.Lock()
    started = time.monotonic()

    with LOG_PATH.open("w", encoding="utf-8", errors="replace") as log:
        log.write(f"# gate {args.half} started {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
        for lane, tasks in lanes:
            log.write(f"# lane {lane:<12} {' -> '.join(tasks)}\n")
        log.flush()

        # One worker per lane, but never more lanes than CPUs: a small runner would otherwise
        # over-subscribe several concurrent cargo builds and slow every one of them down.
        workers = max(1, min(len(lanes), os.cpu_count() or 1))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gate") as pool:
            futures = [
                pool.submit(_run_lane, mise, tasks, log, lock, results) for _, tasks in lanes
            ]
            for future in futures:
                future.result()

        for task in plan:
            results.setdefault(task, (1, "gate never ran this step", 0.0))
        total = time.monotonic() - started
        failed = [task for task in plan if results[task][0] != 0]
        for task in failed:
            print(f"\n---- {task} output tail ----", flush=True)
            print("\n".join(results[task][1].rstrip().splitlines()[-args.tail :]), flush=True)

        passed = len(plan) - len(failed)
        verdict = "PASS" if not failed else f"FAIL ({', '.join(failed)})"
        print(
            f"[gate] {verdict} {passed}/{len(plan)} steps in {total:.0f}s; log: {LOG_PATH}",
            flush=True,
        )
        log.write(f"\n# {verdict} {passed}/{len(plan)} steps in {total:.0f}s\n")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
