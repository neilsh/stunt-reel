"""The reap path never lets git delete through a data-root link.

Git's ``worktree remove`` has recursed through Windows junctions on one build and left
their skeletons on another, so [worktree_init.py](../python/scripts/worktree_init.py)
unlinks every reparse point, proves none remain, and only then removes the checkout.
These tests hold that order, the walker that never descends, and the refusal rules.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import worktree_init  # noqa: E402

PORCELAIN = """\
worktree D:/git/example
HEAD 1111111111111111111111111111111111111111
branch refs/heads/main

worktree D:/git/example/.agents/worktrees/wt-a
HEAD 2222222222222222222222222222222222222222
branch refs/heads/wt-a

worktree C:/Users/me/orca/workspaces/example/fluke
HEAD 3333333333333333333333333333333333333333
branch refs/heads/neilsh/fluke

worktree D:/git/example/.agents/worktrees/detached
HEAD 4444444444444444444444444444444444444444
detached
"""


def _run_git(cwd: Path, *args: str) -> str:
    git = shutil.which("git")
    assert git is not None, "git is not on PATH"
    result = subprocess.run(  # noqa: S603
        [git, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    _run_git(repo, "add", "a.txt")
    _run_git(
        repo,
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "user.name=t",
        "commit",
        "-qm",
        "init",
    )
    return repo


def _junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("directory junctions are a Windows feature")
    shell = os.environ.get("COMSPEC", "cmd.exe")
    subprocess.run(  # noqa: S603
        [shell, "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=True,
    )


def test_parse_worktrees_reads_primary_branch_and_detached() -> None:
    entries = worktree_init._parse_worktrees(PORCELAIN)
    assert [entry.branch for entry in entries] == ["main", "wt-a", "neilsh/fluke", None]
    assert entries[0].path == Path("D:/git/example")
    assert entries[2].path == Path("C:/Users/me/orca/workspaces/example/fluke")


def test_walker_finds_a_junction_without_descending(tmp_path: Path) -> None:
    target = tmp_path / "data"
    (target / "nested").mkdir(parents=True)
    (target / "nested" / "keep.txt").write_text("keep", encoding="utf-8")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _junction(checkout / "corpus", target)
    assert [path.name for path in worktree_init._reparse_points(checkout)] == ["corpus"]


def test_unlinking_keeps_the_target_and_clears_every_link(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _junction(checkout / "corpus", target)
    _junction(checkout / "target_bin", target)
    assert worktree_init._unlink_reparse_points(checkout) == []
    assert worktree_init._reparse_points(checkout) == []
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_blocked_names_the_flag_that_lifts_it() -> None:
    candidate = worktree_init._Candidate(
        worktree=worktree_init._Worktree(path=Path("D:/git/example/wt"), head="0", branch="b"),
        merged=True,
        dirty=[" M a.txt"],
        untracked=["?? scratch.txt"],
        links=[],
        size=0,
    )
    assert len(worktree_init._blocked(candidate, stash_dirty=False, discard_untracked=False)) == 2
    assert worktree_init._blocked(candidate, stash_dirty=True, discard_untracked=False) == [
        "untracked files; pass --discard-untracked to drop them"
    ]
    assert worktree_init._blocked(candidate, stash_dirty=True, discard_untracked=True) == []


def test_reap_one_unlinks_then_removes_and_keeps_the_target(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("directory junctions are a Windows feature")
    repo = _init_repo(tmp_path)
    worktree = tmp_path / "wt"
    _run_git(repo, "worktree", "add", "-q", str(worktree), "-b", "wt-test")
    target = tmp_path / "data"
    (target / "nested").mkdir(parents=True)
    (target / "nested" / "keep.txt").write_text("keep", encoding="utf-8")
    _junction(worktree / "corpus", target)
    candidate = worktree_init._Candidate(
        worktree=worktree_init._Worktree(path=worktree, head="", branch="wt-test"),
        merged=True,
        dirty=[],
        untracked=[],
        links=worktree_init._reparse_points(worktree),
        size=0,
    )
    assert candidate.links
    assert (
        worktree_init._reap_one(repo, candidate, stash_dirty=False, discard_untracked=False) is None
    )
    assert not worktree.exists()
    assert (target / "nested" / "keep.txt").read_text(encoding="utf-8") == "keep"
    branches = _run_git(repo, "branch", "--format=%(refname:short)")
    assert "wt-test" not in branches.split()


def test_candidates_keep_unmerged_and_outside_pool(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    _run_git(repo, "worktree", "add", "-q", str(pool / "merged"), "-b", "merged")
    _run_git(repo, "worktree", "add", "-q", str(pool / "unmerged"), "-b", "unmerged")
    (pool / "unmerged" / "b.txt").write_text("b", encoding="utf-8")
    _run_git(pool / "unmerged", "add", "b.txt")
    _run_git(
        pool / "unmerged",
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "user.name=t",
        "commit",
        "-qm",
        "work",
    )
    outside = tmp_path / "outside"
    _run_git(repo, "worktree", "add", "-q", str(outside), "-b", "outside")

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False
    )

    assert [candidate.worktree.branch for candidate in candidates] == ["merged"]
    joined = "\n".join(skipped)
    assert "unmerged: 1 patch(es) not in main" in joined
    assert "outside: outside this checkout's worktree pool" in joined
