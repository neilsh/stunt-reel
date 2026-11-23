"""``review-worktree`` lands a review's detached worktree under the primary checkout (issue #981)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from git_helpers import run_git
from stunt_reel import worktree_git, worktree_review
from stunt_reel.git_env import git_location_vars

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import worktree_init  # noqa: E402

pytestmark = pytest.mark.windows


def _git(cwd: Path, *args: str) -> str:
    return run_git(cwd, *args, check=True).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-qm", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, str]:
    """A primary checkout cloned from an origin that holds PR 7's head; a linked worktree in it."""
    for var in git_location_vars():
        monkeypatch.delenv(var, raising=False)
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _commit(origin, "a.txt")
    _git(origin, "checkout", "-q", "-b", "pr-branch")
    pr_head = _commit(origin, "b.txt")
    _git(origin, "update-ref", "refs/pull/7/head", pr_head)
    _git(origin, "checkout", "-q", "main")
    primary = tmp_path / "primary"
    _git(tmp_path, "clone", "-q", str(origin), "primary")
    linked = tmp_path / "workspaces" / "wt"
    _git(primary, "worktree", "add", "-q", "-b", "work", str(linked))
    return primary, linked, pr_head


def test_pr_from_a_linked_worktree_lands_under_the_primary_checkout(
    repos: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    primary, linked, pr_head = repos
    assert worktree_review._review("7", cwd=linked) == 0
    path = Path(capsys.readouterr().out.strip().splitlines()[-1])
    assert path == (primary / ".claude" / "worktrees" / "review-7").resolve()
    assert path.is_absolute()
    assert _git(path, "rev-parse", "HEAD") == pr_head
    assert _git(path, "branch", "--show-current") == ""


def test_unpushed_sha_checks_out_that_commit(
    repos: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    primary, linked, _ = repos
    sha = _commit(linked, "c.txt")
    assert worktree_review._review(sha, cwd=linked) == 0
    path = Path(capsys.readouterr().out.strip().splitlines()[-1])
    assert path == (primary / ".claude" / "worktrees" / f"review-{sha[:7]}").resolve()
    assert _git(path, "rev-parse", "HEAD") == sha


def test_existing_path_gets_a_suffix(
    repos: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    primary, linked, _ = repos
    pool = primary / ".claude" / "worktrees"
    assert worktree_review._review("7", cwd=linked) == 0
    assert worktree_review._review("7", cwd=primary) == 0
    assert worktree_review._review("7", cwd=primary) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [Path(line).name for line in lines] == ["review-7", "review-7b", "review-7c"]
    assert Path(lines[-1]).parent == pool.resolve()


def test_unknown_target_fails_without_a_path(
    repos: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    _, linked, _ = repos
    assert worktree_review._review("deadbeefdead", cwd=linked) == 1
    assert worktree_review._review("999", cwd=linked) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "review-worktree:" in captured.err


def test_cli_runs_in_the_working_directory(
    repos: tuple[Path, Path, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primary, linked, _ = repos
    monkeypatch.chdir(linked)
    assert worktree_init.main(["review", "7"]) == 0
    path = Path(capsys.readouterr().out.strip().splitlines()[-1])
    assert path.parent == (primary / ".claude" / "worktrees").resolve()


def test_pushed_sha_missing_locally_is_fetched_from_origin(
    repos: tuple[Path, Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A commit pushed after the clone, from another clone, is fetched by its full SHA."""
    primary, linked, _ = repos
    origin = tmp_path / "origin"
    _git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    _git(origin, "checkout", "-q", "-b", "later")
    sha = _commit(origin, "later.txt")
    assert run_git(primary, "cat-file", "-e", sha).returncode != 0
    assert worktree_review._review(sha, cwd=linked) == 0
    path = Path(capsys.readouterr().out.strip().splitlines()[-1])
    assert _git(path, "rev-parse", "HEAD") == sha


def test_abbreviated_sha_missing_locally_fails_with_the_hint(
    repos: tuple[Path, Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, linked, _ = repos
    sha = _commit(tmp_path / "origin", "x.txt")
    assert worktree_review._review(sha[:10], cwd=linked) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "full 40-character SHA" in captured.err


def test_pr_head_does_not_depend_on_fetch_head(
    repos: tuple[Path, Path, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Another fetch landing after ours (a second review, a ``git pull``) must not change the commit."""
    _, linked, pr_head = repos
    real = worktree_git._git

    def clobbering(repo: Path, *args: str) -> object:
        done = real(repo, *args)
        if args[:1] == ("fetch",):
            real(repo, "fetch", "--quiet", "origin", "main")
        return done

    monkeypatch.setattr(worktree_review, "_git", clobbering)
    assert worktree_review._review("7", cwd=linked) == 0
    path = Path(capsys.readouterr().out.strip().splitlines()[-1])
    assert _git(path, "rev-parse", "HEAD") == pr_head


def test_a_registered_worktree_whose_folder_is_gone_takes_a_suffix(
    repos: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    _, linked, _ = repos
    assert worktree_review._review("7", cwd=linked) == 0
    first = Path(capsys.readouterr().out.strip())
    shutil.rmtree(first)
    assert worktree_review._review("7", cwd=linked) == 0
    assert Path(capsys.readouterr().out.strip()).name == "review-7b"


def test_a_name_taken_between_the_check_and_the_add_takes_the_next_suffix(
    repos: tuple[Path, Path, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A second run for the same target that wins the race for ``review-7`` leaves us ``review-7b``."""
    primary, linked, _ = repos
    real = worktree_git._git
    taken = primary / ".claude" / "worktrees" / "review-7"

    def racing(repo: Path, *args: str) -> object:
        if args[:2] == ("worktree", "add") and Path(args[-2]) == taken and not taken.exists():
            taken.mkdir(parents=True)
            (taken / "other-run").write_text("x", encoding="utf-8")
        return real(repo, *args)

    monkeypatch.setattr(worktree_review, "_git", racing)
    assert worktree_review._review("7", cwd=linked) == 0
    assert Path(capsys.readouterr().out.strip().splitlines()[-1]).name == "review-7b"
