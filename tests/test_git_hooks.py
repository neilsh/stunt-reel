"""The committed pre-commit hook: what it runs, how init installs it, what it catches.

A rebase continue once committed ``<<<<<<<`` markers, and a docs commit claimed the gate
passed with broken links. ``.githooks/pre-commit`` dispatches ``mise run pre-commit``
(prek over ``prek.toml``, ADR 0026), and ``mise run init`` points ``core.hooksPath`` at
``.githooks``. These tests hold the hook to one dispatch line and init to the setting;
``test_prek_config.py`` holds ``prek.toml`` to the tasks it names.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import worktree_init  # noqa: E402

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")

#: Variables that point git at another repository. Git sets them while it runs a hook, so a
#: suite started from one would otherwise configure and commit in the outer repository.
_GIT_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


@pytest.fixture(autouse=True)
def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _GIT_LOCATION_ENV:
        monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert GIT is not None
    return subprocess.run(  # noqa: S603 - fixed test arguments
        [GIT, *args], cwd=repo, capture_output=True, text=True, check=False
    )


def _repo(path: Path) -> Path:
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "test")
    _git(path, "config", "user.email", "test@example.invalid")
    # A user's commit.gpgSign would otherwise make every fixture commit fail without a key.
    _git(path, "config", "commit.gpgSign", "false")
    return path


def _mise_tasks() -> set[str]:
    with (REPO_ROOT / "mise.toml").open("rb") as handle:
        return set(tomllib.load(handle)["tasks"])


def _commands(hook: Path) -> list[str]:
    """The hook's lines that are neither comments nor blank."""
    lines = hook.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def test_the_pre_commit_hook_only_dispatches_the_mise_task() -> None:
    commands = _commands(REPO_ROOT / ".githooks" / "pre-commit")
    assert commands[-1] == "exec mise run pre-commit"
    assert not [line for line in commands if "ruff" in line or "pytest" in line], (
        "the hook restates a check; put it in prek.toml (ADR 0026: no second copy)"
    )
    assert "pre-commit" in _mise_tasks()


@needs_git
def test_the_hooks_are_executable_in_the_index() -> None:
    listed = _git(REPO_ROOT, "ls-files", "-s", ".githooks").stdout.splitlines()
    modes = {line.split("\t")[1]: line.split()[0] for line in listed}
    assert modes.get(".githooks/pre-commit") == "100755"
    assert modes.get(".githooks/pre-push") == "100755"


@needs_git
def test_init_sets_the_hooks_path_once(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / ".githooks").mkdir()
    assert worktree_init.ensure_hooks_path(repo) == ["  + core.hooksPath -> .githooks"]
    assert _git(repo, "config", "--get", "core.hooksPath").stdout.strip() == ".githooks"
    assert worktree_init.ensure_hooks_path(repo) == ["  = core.hooksPath .githooks"]


@needs_git
def test_init_leaves_a_hooks_path_someone_chose(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "config", "core.hooksPath", ".husky")
    lines = worktree_init.ensure_hooks_path(repo)
    assert len(lines) == 1
    assert lines[0].startswith("  ! core.hooksPath is '.husky'")
    assert _git(repo, "config", "--get", "core.hooksPath").stdout.strip() == ".husky"


@needs_git
def test_init_names_local_hooks_the_setting_turns_off(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / ".githooks").mkdir()
    (repo / ".githooks" / "pre-push").write_text("#!/bin/sh\n", encoding="utf-8")
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-push").write_text("#!/bin/sh\n", encoding="utf-8")
    (hooks / "commit-msg").write_text("#!/bin/sh\n", encoding="utf-8")
    (hooks / "commit-msg.sample").write_text("#!/bin/sh\n", encoding="utf-8")
    lines = worktree_init.ensure_hooks_path(repo)
    named = [line for line in lines if "no longer runs" in line]
    assert len(named) == 1
    assert "commit-msg" in named[0]
