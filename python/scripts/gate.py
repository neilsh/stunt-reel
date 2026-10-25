"""Run the quality gate as steps and print a verdict instead of a transcript.

``mise run check``` used to be a ``depends`` chain: each task printed its own output, nothing
gave a verdict, and the quiet halves ran a shorter step list than the full gate. This script
runs the leaf steps in order, prints one line per step plus a failing step's tail, writes the
complete output to ``target/check.log``, and ends with PASS or FAIL. The commands stay defined
in ``mise.toml``: each step is executed as ``mise run <task>``, so there is no second copy of
the gate to drift. See [ADR 0014](../docs/adr/0014-the-gate-is-one-ordered-script.md).

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
import time
from collections.abc import Sequence
from pathlib import Path

LOG_PATH = Path("target") / "check.log"

# The step list is the ordered leaf tasks; a task that only aggregates others
# (check, fmt-check, lint, test) must never appear here or the gate recurses.
STEPS: dict[str, list[str]] = {
    "rust": ["fmt-check-rust", "lint-rust", "test-rust", "doc", "check-rust-matrix"],
    "py": ["fmt-check-py", "lint-py", "typecheck", "test-py"],
}

REQUIRED_ENV: dict[str, dict[str, str]] = {"test-py": {"STUNT_REQUIRE_KSC": "1"}}


def _plan(half: str) -> list[str]:
    """Return the ordered steps for one half of the gate."""
    return [*STEPS["rust"], *STEPS["py"]] if half == "all" else STEPS[half]


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("half", choices=("all", "rust", "py"), help="which half of the gate")
    parser.add_argument("--tail", type=int, default=40, help="lines shown of a failing step")
    args = parser.parse_args(argv)

    plan = _plan(str(args.half))
    mise = _mise()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    started = time.monotonic()

    with LOG_PATH.open("w", encoding="utf-8", errors="replace") as log:
        for task in plan:
            code, output, elapsed = _step(mise, task)
            log.write(f"\n===== mise run {task} (exit {code}, {elapsed:.1f}s) =====\n")
            log.write(output)
            print(f"[gate] {task:<18} {'ok' if code == 0 else 'FAIL':<4} ({elapsed:>4.0f}s)")
            if code != 0:
                failed.append(task)
                tail = output.rstrip().splitlines()[-args.tail :]
                print("\n".join(tail))

    passed = len(plan) - len(failed)
    total = time.monotonic() - started
    verdict = "PASS" if not failed else f"FAIL ({', '.join(failed)})"
    print(f"[gate] {verdict} {passed}/{len(plan)} steps in {total:.0f}s; log: {LOG_PATH}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
