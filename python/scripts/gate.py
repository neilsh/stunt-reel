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

The ``docs`` half runs only the documentation tests (``test-py-docs``, ``pytest -m docs``): a
change that touches no Python still runs them, since a Rust or Markdown change can break a cited
path. ``classify`` sorts a changed path into a category, and ``scope_for`` turns the categories into
the halves a run needs, or the full gate with a reason. See the scoped-gate plan,
``docs/process/plans/scoped-gate-2026-11-06.md``.

``STEP_ENV`` holds the environment a step runs with only inside the gate. The Python test step
sets ``STUNT_REQUIRE_KSC=1``, so a missing Kaitai compiler fails the gate instead of skipping the
schema contract test, and ``STUNT_REQUIRE_PREK=1`` does the same for the commit hooks' prek test.
It also runs pytest across every core (``-n auto``), the gate's longest lane; a scoped
``mise run test-py -- <file>`` stays in one process, where starting workers would cost more than
it saves.

``gate.py all`` reads the branch's changed paths from git and runs only the halves they need;
``--full``, a set ``CI``, an unclassified path, no changes, or paths git cannot give run the full
gate. A passing run prints the commit body's closing gate line.

Usage: ``python python/scripts/gate.py {all|rust|py|docs} [--full] [--base REF] [--tail N]``
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

LOG_PATH = Path("target") / "check.log"

# The step list is every leaf task, in display order; a task that only aggregates others
# (check, fmt-check, lint, test) must never appear here or the gate recurses. A step added here
# needs a STEP_LANES entry, and _lane_plan refuses to run without one.
STEPS: dict[str, list[str]] = {
    "rust": ["fmt-check-rust", "lint-rust", "test-rust", "doc", "check-rust-matrix"],
    "py": ["fmt-check-py", "lint-py", "typecheck", "test-py"],
    "docs": ["test-py-docs"],
}

# Each step belongs to one lane. Steps in the same lane run in order, one at a time; lanes run
# concurrently. The lane is the unit of an exclusively held resource, so a cargo step shares its
# lane with every other step that builds into the same target directory: cargo holds an exclusive
# lock there, and two lanes on one directory would only serialise on it. lint-rust and doc share
# target/check and so one lane; check-rust-matrix alone builds target/matrix and owns its lane.
STEP_LANES: dict[str, str] = {
    "fmt-check-rust": "rust-fmt",
    "lint-rust": "rust-lint",
    "test-rust": "rust-build",
    "doc": "rust-lint",
    "check-rust-matrix": "rust-matrix",
    "fmt-check-py": "py-fmt",
    "lint-py": "py-lint",
    "typecheck": "py-typecheck",
    "test-py": "py-test",
    "test-py-docs": "py-docs",
}

# The scoped task that runs each half of STEPS (mise.toml: check-rust, check-py). A failing step
# names the task for its own half, so membership comes from STEPS and cannot drift from the plan.
SCOPED_TASKS: dict[str, str] = {"rust": "check-rust", "py": "check-py", "docs": "check-docs"}

# Steps whose failure `mise run fix` repairs mechanically: ruff's fixable lint findings, ruff
# format and rustfmt. The task itself is defined in mise.toml beside the steps it mirrors.
FIX_TASK = "fix"
FIXABLE_STEPS = frozenset({"fmt-check-rust", "fmt-check-py", "lint-py"})

_PYTEST_ENV = {
    "STUNT_REQUIRE_KSC": "1",
    "STUNT_REQUIRE_PREK": "1",
    "PYTEST_ADDOPTS": "-n auto",
}
STEP_ENV: dict[str, dict[str, str]] = {"test-py": _PYTEST_ENV, "test-py-docs": dict(_PYTEST_ENV)}

Category = Literal["rust", "python", "docs", "other"]

# The full gate's halves; every other run is a subset of these plus ``docs``.
_FULL = ("rust", "py")
_RUST_FILES = frozenset({"Cargo.toml", "Cargo.lock", "deny.toml"})
_PYTHON_FILES = frozenset({"pyproject.toml", "uv.lock"})
# Documents a Rust test reads from outside crates/ (report_doc.rs checks the parity report's
# field tables). tests/test_gate_plan.py finds every such read, so this set cannot fall behind.
_RUST_READS = frozenset({"research/parity/method.md"})


def classify(path: str) -> Category:
    """Sort one changed path (git's: ``/``-separated, from the root) into a gate category.

    The first rule that matches wins. Fixtures feed both languages' tests, so they are ``other``
    and run the full gate; a Markdown file under ``crates/`` is Rust, because rustdoc reads it, and so is a document a Rust
    test reads (``_RUST_READS``).
    """
    if path.startswith("tests/fixtures/"):
        return "other"
    if path.startswith("crates/") or path in _RUST_FILES or path in _RUST_READS:
        return "rust"
    if path.endswith(".py") or path in _PYTHON_FILES:
        return "python"
    if path.endswith((".md", ".ksy")):
        return "docs"
    return "other"


@dataclass(frozen=True)
class Scope:
    """The halves one ``gate.py all`` run executes, and why it is the full gate when it is."""

    halves: tuple[str, ...]
    full: bool
    reason: str = ""
    paths: dict[Category, list[str]] = field(default_factory=dict)


def scope_for(
    paths: list[str] | None,
    *,
    full_flag: bool,
    ci: bool,
    error: str = "",
    base: str = "main",
) -> Scope:
    """Choose the halves for *paths*, or the full gate with the first reason that applies.

    *paths* is ``None`` when they could not be read, and *error* says why. A Rust change runs the
    docs half too; a Python change does not need it, since ``test-py`` runs every test.
    """
    grouped: dict[Category, list[str]] = {}
    for path in paths or []:
        grouped.setdefault(classify(path), []).append(path)
    unclassified = grouped.get("other", [])
    if full_flag:
        reason = "--full"
    elif ci:
        reason = "CI is set"
    elif paths is None:
        reason = f"changed paths unknown: {error}"
    elif unclassified:
        reason = f"unclassified path: {unclassified[0]}"
    elif not paths:
        reason = f"no changes against {base}"
    else:
        reason = ""
    if reason:
        return Scope(_FULL, full=True, reason=reason, paths=grouped)
    halves = [
        half for half, category in (("rust", "rust"), ("py", "python")) if category in grouped
    ]
    if "py" not in halves:
        halves.append("docs")
    return Scope(tuple(halves), full=False, paths=grouped)


def ci_requested(env: Mapping[str, str]) -> bool:
    """Whether ``CI`` asks for the full gate: set, and neither ``false`` nor ``0``."""
    return env.get("CI", "").strip().lower() not in {"", "false", "0"}


_GIT_LOCATION = frozenset({"GIT_DIR", "GIT_WORK_TREE"})


class ChangedPathsError(Exception):
    """git could not say which paths the branch changed; the message is git's."""


def _git_paths(repo: Path, *args: str) -> list[str]:
    """Run one git command that prints NUL-separated paths, and return them."""
    git = shutil.which("git")
    if git is None:
        raise ChangedPathsError("git is not on PATH")
    # *repo* decides the repository: GIT_DIR or GIT_WORK_TREE left set by a hook or a shell could
    # name another checkout and scope this run by that checkout's changes.
    env = {key: value for key, value in os.environ.items() if key not in _GIT_LOCATION}
    proc = subprocess.run(  # noqa: S603 - fixed git arguments, git resolved from PATH
        [git, *args], cwd=repo, env=env, capture_output=True, check=False
    )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ChangedPathsError(message or f"git {args[0]} exited {proc.returncode}")
    return [path for path in proc.stdout.decode("utf-8").split("\0") if path]


def changed_paths(repo: Path, base: str = "main") -> list[str]:
    """Every path the branch changed since it left *base*: committed, staged, unstaged, untracked.

    ``--no-renames`` lists both sides of a rename, so a file moved across categories counts in
    both. ``-z`` keeps a non-ASCII name as itself instead of git's quoted octal.
    """
    merge_base = _git_paths(repo, "merge-base", "HEAD", base)
    if not merge_base:
        raise ChangedPathsError(f"no merge base between HEAD and {base}")
    changed = _git_paths(repo, "diff", "--name-only", "--no-renames", "-z", merge_base[0].strip())
    untracked = _git_paths(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted({*changed, *untracked})


def _not_run(halves: Sequence[str]) -> list[str]:
    """The scoped tasks of the halves a run skipped; ``docs`` is covered whenever ``py`` ran."""
    return [
        SCOPED_TASKS[half]
        for half in ("rust", "py", "docs")
        if half not in halves and not (half == "docs" and "py" in halves)
    ]


def _scope_lines(scope: Scope) -> list[str]:
    """What the run decided and from which paths, printed before the steps and logged."""
    if scope.full:
        lines = [f"[gate] scope: full ({scope.reason})"]
    else:
        halves, skipped = ", ".join(scope.halves), ", ".join(_not_run(scope.halves))
        lines = [f"[gate] scope: {halves}; not run: {skipped}"]
    for category, paths in scope.paths.items():
        more = f" (+{len(paths) - 3} more)" if len(paths) > 3 else ""
        lines.append(f"[gate]   {category}: {', '.join(paths[:3])}{more}")
    return lines


def gate_line(halves: Sequence[str]) -> str:
    """The commit body's closing line for a passing run of *halves* (AGENTS.md, Committing).

    The first half names its task in full and the rest by name; a half that did not run is
    named as not run, except ``docs`` after ``py``, whose ``test-py`` already ran those tests.
    """
    if set(_FULL) <= set(halves):
        return "mise run check passes."
    ran = [f"{SCOPED_TASKS[half]} passes" for half in halves]
    skipped = [f"{task} not run" for task in _not_run(halves)]
    return f"mise run {'; '.join([*ran, *skipped])}."


def _plan(half: str) -> list[str]:
    """Return the ordered steps for one half of the gate."""
    return [*STEPS["rust"], *STEPS["py"]] if half == "all" else STEPS[half]


def _reruns(failed: Sequence[str], half: str) -> list[str]:
    """Return the scoped tasks that re-run only the failed lanes' half of the gate.

    A task is named for each half with a failing step, except the half this run already is
    (``check-rust`` never suggests itself). A step in neither half names nothing.
    """
    return [
        f"mise run {scoped}"
        for scope, scoped in SCOPED_TASKS.items()
        if scope != half and any(task in STEPS[scope] for task in failed)
    ]


def _verdict(failed: Sequence[str], plan: Sequence[str], half: str, total: float) -> str:
    """Return the gate's closing line: PASS, or FAIL naming the failing steps and what to run."""
    passed = len(plan) - len(failed)
    if not failed:
        return f"[gate] PASS {passed}/{len(plan)} steps in {total:.0f}s; log: {LOG_PATH}"
    line = f"[gate] FAIL ({', '.join(failed)}) {passed}/{len(plan)} steps in {total:.0f}s"
    line += f"; log: {LOG_PATH}"
    if any(task in FIXABLE_STEPS for task in failed):
        line += f"; fix: mise run {FIX_TASK}"
    reruns = _reruns(failed, half)
    return f"{line}; re-run: {', '.join(reruns)}" if reruns else line


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
    env = {**os.environ, "MISE_QUIET": "1", **STEP_ENV.get(task, {})}
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
    parser.add_argument(
        "half", choices=("all", "rust", "py", "docs"), help="which half of the gate"
    )
    parser.add_argument("--tail", type=int, default=40, help="lines shown of a failing step")
    parser.add_argument("--full", action="store_true", help="run every half whatever changed")
    parser.add_argument(
        "--base", default="main", help="the branch changes are counted from (default: main)"
    )
    args = parser.parse_args(argv)

    half = str(args.half)
    scope_lines: list[str] = []
    if half == "all":
        full_flag, ci = bool(args.full), ci_requested(os.environ)
        paths: list[str] | None = None
        error = ""
        if not (full_flag or ci):
            try:
                paths = changed_paths(Path.cwd(), str(args.base))
            except ChangedPathsError as err:
                error = str(err)
        scope = scope_for(paths, full_flag=full_flag, ci=ci, error=error, base=str(args.base))
        halves = scope.halves
        plan = [step for scoped in halves for step in STEPS[scoped]]
        scope_lines = _scope_lines(scope)
    else:
        halves = (half,)
        plan = _plan(half)
    for line in scope_lines:
        print(line, flush=True)
    lanes = _lane_plan(plan)
    mise = _mise()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    results: dict[str, tuple[int, str, float]] = {}
    lock = threading.Lock()
    started = time.monotonic()

    with LOG_PATH.open("w", encoding="utf-8", errors="replace") as log:
        log.write(f"# gate {args.half} started {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
        for line in scope_lines:
            log.write(f"# {line.removeprefix('[gate] ')}\n")
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
            note = f" (fix: mise run {FIX_TASK})" if task in FIXABLE_STEPS else ""
            print(f"\n---- {task} output tail{note} ----", flush=True)
            print("\n".join(results[task][1].rstrip().splitlines()[-args.tail :]), flush=True)

        verdict = _verdict(failed, plan, half, total)
        print(verdict, flush=True)
        log.write(f"\n# {verdict.removeprefix('[gate] ')}\n")
        if not failed:
            print(f"[gate] gate line: {gate_line(halves)}", flush=True)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
