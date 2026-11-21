"""A suite run under ``git rebase --exec`` or a hook leaves the caller's repository alone.

Issue #868 adds the worktree case, and not through an inherited variable: a fixture repo's
``git worktree add`` registered with the checkout that holds the tests, at
``.../repo/.agents/worktrees/new`` under the pytest basetemp, so git reached the checkout by
discovery.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from git_helpers import git_dir, run_git

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git")

#: A test whose fixture runs ``git init`` and ``git config user.name`` in its scratch directory.
_SCRATCH_REPO_TEST = "tests/test_check_commit_msg.py::test_the_hook_reads_the_staged_paths"

#: The tests that run ``git worktree add`` in a fixture repository of their own.
_WORKTREE_TESTS = (
    "tests/test_git_hooks.py::test_blame_still_runs_in_a_worktree_older_than_the_ignore_file",
    "tests/test_worktree_reap.py::test_a_fresh_worktree_is_skipped_and_a_fast_forwarded_branch_is_reaped",
    "tests/test_worktree_reap.py::test_a_fresh_worktree_that_synced_with_base_is_still_skipped",
    "tests/test_worktree_reap.py::test_a_fresh_worktree_rebased_onto_main_is_still_skipped",
)


def _init_repo(path: Path) -> Path:
    """A scratch repository at *path* with one commit on ``main``."""
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main", check=True)
    (path / "a.txt").write_text("a", encoding="utf-8")
    run_git(path, "add", "a.txt", check=True)
    run_git(path, "commit", "-q", "-m", "init", check=True)
    return path


def _worktrees(repo: Path) -> list[Path]:
    """The worktrees ``git worktree list`` names for *repo*."""
    listed = run_git(repo, "worktree", "list", "--porcelain", check=True).stdout
    return [
        Path(line.removeprefix("worktree "))
        for line in listed.splitlines()
        if line.startswith("worktree ")
    ]


def _is_under(path: Path, parent: Path) -> bool:
    """Whether *path* is inside *parent*, as the platform's path comparison decides."""
    return path == parent or parent in path.parents


@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_a_test_run_with_git_dir_set_leaves_that_repository_unchanged(tmp_path: Path) -> None:
    assert GIT is not None
    caller = tmp_path / "caller"
    subprocess.run([GIT, "init", "-q", str(caller)], check=True)  # noqa: S603 - fixed git arguments
    before = (caller / ".git" / "config").read_text()
    # `git rebase --exec` exports GIT_DIR to the command it runs; the suite inherits it.
    env = {**os.environ, "GIT_DIR": str(caller / ".git"), "PYTEST_ADDOPTS": ""}
    inner = subprocess.run(  # noqa: S603 - this interpreter, fixed pytest arguments
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(tmp_path / "inner"),
            _SCRATCH_REPO_TEST,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (caller / ".git" / "config").read_text() == before
    assert "1 passed" in inner.stdout, inner.stdout + inner.stderr


@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_a_linked_worktree_is_pinned_to_its_own_git_dir(tmp_path: Path) -> None:
    """A fixture worktree's ``.git`` is a file; its commands still name the directory it lives in."""
    repo = _init_repo(tmp_path / "repo")
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-q", str(worktree), "-b", "wt", check=True)

    assert git_dir(worktree) == (repo / ".git" / "worktrees" / "wt").resolve()
    assert run_git(worktree, "rev-parse", "--abbrev-ref", "HEAD", check=True).stdout.strip() == "wt"


@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_a_fixture_repo_without_its_git_dir_cannot_register_with_the_caller(
    tmp_path: Path,
) -> None:
    """Discovery from a fixture's directory must not reach the checkout that holds the tests (#868).

    The leaked registration was a fixture repo's ``.agents/worktrees/new`` under the pytest
    basetemp, which sits inside the checkout: git found the enclosing repository from there.
    """
    caller = _init_repo(tmp_path / "caller")
    fixture = caller / "repo"
    fixture.mkdir()

    added = run_git(fixture, "worktree", "add", "-q", "-b", "new", str(fixture / "wt"), "main")

    assert added.returncode != 0, added.stdout + added.stderr
    assert "not a git repository" in added.stderr
    assert len(_worktrees(caller)) == 1, _worktrees(caller)


@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_the_worktree_tests_add_no_worktree_under_their_basetemp(tmp_path: Path) -> None:
    """The suite's worktree tests must not register a fixture worktree with the outer repository."""
    basetemp = tmp_path / "inner"
    inner = subprocess.run(  # noqa: S603 - this interpreter, fixed pytest arguments
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "--basetemp",
            str(basetemp),
            *_WORKTREE_TESTS,
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTEST_ADDOPTS": ""},
        capture_output=True,
        text=True,
        check=False,
    )

    assert inner.returncode == 0, inner.stdout + inner.stderr
    assert [path for path in _worktrees(REPO_ROOT) if _is_under(path, basetemp)] == []
