"""The commit-msg hook: a Conventional Commit subject, and a gate line in any body (SOP 3)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "python" / "scripts" / "check_commit_msg.py"
TRAILER = "Co-Authored-By: Someone <someone@example.com>"


@pytest.fixture(scope="module")
def hook() -> Any:
    spec = importlib.util.spec_from_file_location("check_commit_msg", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "subject",
    [
        "feat(core): add a parser",
        "fix: refuse a bad manifest",
        "docs(research)!: renumber the items",
        "chore(deps): bump toml",
    ],
)
def test_a_conventional_subject_with_no_body_passes(hook: Any, subject: str) -> None:
    assert hook.problems(subject + "\n") == []


@pytest.mark.parametrize(
    "subject", ["Add a parser", "feat add a parser", "feature: add a parser", "fix(): empty scope"]
)
def test_any_other_subject_is_named(hook: Any, subject: str) -> None:
    [problem] = hook.problems(subject + "\n")
    assert "Conventional Commit" in problem
    assert subject in problem


def test_a_body_with_the_gate_line_passes(hook: Any) -> None:
    message = f"fix: a thing\n\nWhy it changed.\n\nmise run check passes.\n\n{TRAILER}\n"
    assert hook.problems(message) == []


def test_a_gate_line_naming_what_did_not_run_passes(hook: Any) -> None:
    message = "docs: a note\n\nWhy.\n\nmise run check-py passes; check-rust not run.\n"
    assert hook.problems(message) == []


def test_a_gate_line_that_does_not_run_the_gate_passes(hook: Any) -> None:
    message = (
        "fix: a mode bit\n\nWhy.\n\nmise run check not run: a mode-only change, checked by CI.\n"
    )
    assert hook.problems(message) == []


@pytest.mark.parametrize(
    "line",
    [
        "mise run check failed.",
        "Run mise run check before merging.",
        "mise run check failed; CI passes.",
        "mise run check failed, the fix is not run yet.",
    ],
)
def test_a_gate_line_must_report_an_outcome(hook: Any, line: str) -> None:
    [problem] = hook.problems(f"fix: a thing\n\nWhy it changed.\n\n{line}\n")
    assert "gate line" in problem


def test_a_body_without_a_gate_line_is_named(hook: Any) -> None:
    [problem] = hook.problems(f"fix: a thing\n\nWhy it changed.\n\n{TRAILER}\n")
    assert "mise run check" in problem


def test_trailers_alone_are_not_a_body(hook: Any) -> None:
    assert hook.problems(f"chore: rename a file\n\n{TRAILER}\n") == []


def test_git_comments_and_the_scissors_are_ignored(hook: Any) -> None:
    message = (
        "fix: a thing\n# Please enter the commit message\n"
        "# ------------------------ >8 ------------------------\n"
        "diff --git a/x b/x\nWhy it changed.\n"
    )
    assert hook.problems(message) == []


@pytest.mark.parametrize(
    "subject",
    [
        "Merge branch 'main' into feat/x",
        'Revert "feat: add a parser"',
        "fixup! feat: add a parser",
        "squash! feat: add a parser",
        "amend! feat: add a parser",
    ],
)
def test_git_generated_subjects_are_left_alone(hook: Any, subject: str) -> None:
    assert hook.problems(subject + "\n\nno gate line here\n") == []


def test_the_script_checks_a_message_file(tmp_path: Path) -> None:
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.write_text("fix: a thing\n", encoding="utf-8")
    bad.write_text("a thing\n", encoding="utf-8")
    run = [sys.executable, str(SCRIPT)]
    assert subprocess.run([*run, str(good)], check=False).returncode == 0  # noqa: S603
    failed = subprocess.run(  # noqa: S603
        [*run, str(bad)], capture_output=True, text=True, check=False
    )
    assert failed.returncode == 1
    assert "Conventional Commit" in failed.stderr


def test_the_script_checks_a_commit_range(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        done = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    git("commit", "-q", "--allow-empty", "-m", "chore: start")
    base = git("rev-parse", "HEAD")
    git("commit", "-q", "--allow-empty", "-m", "feat: fine")
    git("commit", "-q", "--allow-empty", "-m", "not conventional")
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--range", f"{base}..HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1
    assert "not conventional" in done.stderr
    assert "feat: fine" not in done.stderr
