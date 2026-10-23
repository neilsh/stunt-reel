"""Run one half of the quality gate and print only a line per step, plus failures.

``mise run check`` prints every compiler, linter and test line. While iterating on one
language that output is noise, so this runs the same steps for Rust or Python, prints
``ok``/``FAIL`` with the elapsed time per step, and shows the last lines of a failing
step's output. The full ``mise run check`` stays the gate before a commit (see
``AGENTS.md``).

Usage: ``python python/scripts/quiet_check.py rust|py [--tail N]``
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time

STEPS: dict[str, list[tuple[str, str]]] = {
    "rust": [
        ("fmt", "cargo fmt --check"),
        (
            "clippy",
            "cargo clippy -q --locked --workspace --all-targets --all-features -- -D warnings",
        ),
        ("test", "cargo test -q --locked --workspace --all-features"),
    ],
    "py": [
        ("fmt", "uv run ruff format --check ."),
        ("lint", "uv run ruff check ."),
        ("typecheck", "uv run mypy"),
        ("test", "uv run pytest -q"),
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("half", choices=sorted(STEPS))
    parser.add_argument("--tail", type=int, default=40, help="lines shown of a failing step")
    args = parser.parse_args()

    failed = 0
    for name, command in STEPS[args.half]:
        start = time.monotonic()
        result = subprocess.run(  # noqa: S603 - fixed commands from STEPS
            shlex.split(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        elapsed = time.monotonic() - start
        status = "ok" if result.returncode == 0 else "FAIL"
        print(f"[{args.half}] {name:<9} {status} ({elapsed:.0f}s)")
        if result.returncode != 0:
            failed += 1
            lines = (result.stdout + result.stderr).rstrip().splitlines()
            print("\n".join(lines[-args.tail :]))
    print(f"[{args.half}] {'all passed' if failed == 0 else f'{failed} step(s) failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
