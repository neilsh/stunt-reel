"""The commit-msg hook: a Conventional Commit subject and the fresh review (AGENTS.md, Committing)."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from collections.abc import Callable
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


def test_any_body_passes(hook: Any) -> None:
    message = f"fix: a thing\n\nWhy it changed.\n\n{TRAILER}\n"
    assert hook.problems(message) == []


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
    assert hook.problems(subject + "\n\nany body\n") == []


def test_the_script_checks_a_message_file(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.write_text("fix: a thing\n", encoding="utf-8")
    bad.write_text("a thing\n", encoding="utf-8")
    run = [sys.executable, str(SCRIPT)]
    assert subprocess.run([*run, str(good)], cwd=tmp_path, check=False).returncode == 0  # noqa: S603
    failed = subprocess.run(  # noqa: S603
        [*run, str(bad)], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert failed.returncode == 1
    assert "Conventional Commit" in failed.stderr


@pytest.mark.parametrize("title", ["feat(core): add a parser", 'Revert "feat: x"'])
def test_a_conventional_or_git_title_passes(hook: Any, title: str) -> None:
    assert hook.main(["--subject", title]) == 0


def test_a_bad_title_is_named(hook: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert hook.main(["--subject", "Update stuff"]) == 1
    assert "pull request title" in capsys.readouterr().err


def test_a_title_with_shell_text_is_only_read(hook: Any, tmp_path: Path) -> None:
    # Review Focus 1: the title is data, never run.
    marker = tmp_path / "ran"
    assert hook.main(["--subject", f"feat: $(touch {marker}) `touch {marker}`"]) == 0
    assert not marker.exists()


Git = Callable[..., str]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Git:
    """A scratch repository as the working directory, holding one commit; returns its git."""

    def git(*args: str) -> str:
        done = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    git("commit", "-q", "--allow-empty", "-m", "chore: start")
    monkeypatch.chdir(tmp_path)
    return git


def _path(*parts: str) -> str:
    """A repository-relative path from *parts*, so the doc checks do not read it as a citation."""
    return "/".join(parts)


REVIEW = "Fresh-review: a subagent read the diff and the notes it cites"


@pytest.mark.parametrize(
    ("path", "at_commit"),
    [
        (_path("work", "2026-11", "440_target-frame-adoption", "spec.md"), True),
        (_path("work", "2026-11", "440_target-frame-adoption", "plan.md"), True),
        (_path("work", "2026-11", "440_target-frame-adoption", "journal.md"), False),
        (_path("work", "README.md"), False),
        (_path("research", "parity", "metric-bench.md"), False),
        ("NOTICE.md", False),
        (_path("docs", "howto", "score-a-render-change.md"), False),
        (_path("docs", "SPEC.md"), False),
        (_path("docs", "adr", "0001-x.md"), False),
        ("python/scripts/check_commit_msg.py", False),
    ],
)
def test_which_paths_need_a_fresh_review(hook: Any, path: str, at_commit: bool) -> None:
    assert hook.reviewed_at_commit(path) is at_commit


def test_a_staged_spec_needs_the_trailer(hook: Any) -> None:
    spec = _path("work", "2026-11", "440_x", "spec.md")
    [problem] = hook.review_problems("docs(work): a spec\n", [spec, "README.md"])
    assert spec in problem
    assert "Fresh-review:" in problem
    assert hook.review_problems(f"docs(work): a spec\n\n{REVIEW}\n", [spec]) == []
    assert hook.review_problems("docs(work): a spec\n\nFresh-review:\n", [spec]) != []


def test_the_hook_reads_the_staged_paths(repo: Git, tmp_path: Path) -> None:
    spec = tmp_path / "work" / "2026-11" / "440_x" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Spec\n", encoding="utf-8")
    repo("add", "work")
    unreviewed, reviewed = tmp_path / "unreviewed", tmp_path / "reviewed"
    unreviewed.write_text("docs(work): a spec\n", encoding="utf-8")
    reviewed.write_text(f"docs(work): a spec\n\n{REVIEW}\n", encoding="utf-8")
    run = [sys.executable, str(SCRIPT)]
    failed = subprocess.run(  # noqa: S603
        [*run, str(unreviewed)], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert failed.returncode == 1
    assert "Fresh-review:" in failed.stderr
    assert subprocess.run([*run, str(reviewed)], cwd=tmp_path, check=False).returncode == 0  # noqa: S603


@pytest.mark.parametrize(
    "subject", ["Merge branch 'spec'", 'Revert "docs(work): a spec"', "fixup! docs(work): a spec"]
)
def test_git_subjects_need_no_review(hook: Any, subject: str) -> None:
    spec = _path("work", "2026-11", "440_x", "spec.md")
    assert hook.review_problems(subject + "\n", [spec]) == []


def test_the_hook_fails_closed_outside_a_repository(tmp_path: Path) -> None:
    message = tmp_path / "message"
    message.write_text("fix: a thing\n", encoding="utf-8")
    failed = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), str(message)],
        cwd=tmp_path,
        env={**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path.parent)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 2
    assert "cannot read the staged paths" in failed.stderr


def test_a_non_ascii_path_is_read_unquoted(repo: Git, tmp_path: Path, hook: Any) -> None:
    note = tmp_path / "research" / "café.md"
    note.parent.mkdir()
    note.write_text("x\n", encoding="utf-8")
    repo("add", "research")
    assert hook._staged_paths() == [_path("research", "café.md")]


def test_a_title_starting_with_a_dash_is_read_as_text(hook: Any) -> None:
    assert hook.main(["--subject=-x"]) == 1


def test_the_title_workflow_rechecks_edits_and_never_interpolates_the_title() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "pr-title.yml").read_text(encoding="utf-8")
    assert re.search(r"types: \[opened, edited, synchronize, reopened\]", workflow)
    assert "TITLE: ${{ github.event.pull_request.title }}" in workflow  # via env only
    # Every `run:` is one line here, so a line scan sees it whole; keep it so.
    run_lines = [line for line in workflow.splitlines() if "run:" in line]
    assert all("${{" not in line and not line.rstrip().endswith(("|", ">")) for line in run_lines)
    assert 'commit-msg-check -- --subject="$TITLE"' in workflow
    assert 'MISE_AUTO_INSTALL: "false"' in workflow
    assert "name: PR title" in workflow
