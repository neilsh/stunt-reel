"""The reap path never lets git delete through a data-root link.

Git's ``worktree remove`` has recursed through Windows junctions on one build and left
their skeletons on another, so [worktree_init.py](../python/scripts/worktree_init.py)
unlinks every reparse point, proves none remain, and only then removes the checkout.
These tests hold that order, the walker that never descends, and the refusal rules.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from stunt_reel import dataroot

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import worktree_init  # noqa: E402

pytestmark = pytest.mark.windows

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


#: Every git call that can create a commit (rebase, merge) needs an identity; CI has no global one.
#: ``core.longpaths`` because the repos sit under the checkout's per-run basetemp: in a worktree
#: under ``.claude/worktrees/<slug>`` with xdist's ``popen-gwN`` level, ``git rebase`` stats an
#: 81-character ``<sha>...<sha>`` range past Windows' 260-character limit ("Filename too long").
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.longpaths",
    "GIT_CONFIG_VALUE_0": "true",
}


def _run_git(cwd: Path, *args: str) -> str:
    git = shutil.which("git")
    assert git is not None, "git is not on PATH"
    result = subprocess.run(  # noqa: S603
        [git, *args],
        cwd=cwd,
        env={**os.environ, **_GIT_ENV},
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


def _head(worktree: Path) -> str:
    """The commit a worktree holds, as reap classifies it."""
    return _run_git(worktree, "rev-parse", "HEAD").strip()


def _ignore_corpus(repo: Path) -> None:
    """Ignore the data-root link as a real checkout's .gitignore does."""
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_bytes(exclude.read_bytes() + b"corpus\n")


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
    _junction(checkout / "captures", target)
    assert worktree_init._unlink_reparse_points(checkout) == []
    assert worktree_init._reparse_points(checkout) == []
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def _refuse_rmdir_on(monkeypatch: pytest.MonkeyPatch, link: Path) -> None:
    """Make Python's directory removal fail on *link* the way a Controlled Folder Access host does."""
    real = Path.rmdir

    def refuse(self: Path) -> None:
        if self == link:
            raise PermissionError(5, "Access is denied", str(self))
        real(self)

    monkeypatch.setattr(Path, "rmdir", refuse)


def test_remove_link_falls_back_to_the_shell_rmdir_when_python_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "data"
    (target / "nested").mkdir(parents=True)
    (target / "nested" / "keep.txt").write_text("keep", encoding="utf-8")
    link = tmp_path / "corpus"
    _junction(link, target)
    _refuse_rmdir_on(monkeypatch, link)
    calls: list[str] = []
    real_run = subprocess.run

    def spy(command: str, *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return real_run(command, *args, **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(subprocess, "run", spy)

    dataroot.remove_link(link)

    assert not os.path.lexists(link)
    assert (target / "nested" / "keep.txt").read_text(encoding="utf-8") == "keep"
    (command,) = calls
    # The path rides in the environment, never on cmd's command line.
    assert command.endswith(f'/d /v:on /c rmdir "!{dataroot._RMDIR_PATH_VAR}!"')
    assert str(link) not in command
    assert "/s" not in command.lower()


@pytest.mark.parametrize(
    "name", ["x&rmdir data&x", "x%PATH%x", "a;b", "p (1)", "c^d", "e!f!g", "Jos\u00e9"]
)
def test_shell_rmdir_takes_any_valid_name_as_plain_text(tmp_path: Path, name: str) -> None:
    """cmd metacharacters and non-ASCII in a junction name neither run nor block removal."""
    target = tmp_path / "data"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    plain = tmp_path / "plain"
    _junction(plain, target)
    # mklink would parse the name itself, so make the junction plain and rename it.
    link = tmp_path / name
    plain.rename(link)

    dataroot._shell_rmdir(link)

    assert not os.path.lexists(link)
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["data"]


def test_remove_link_reports_both_errors_when_the_fallback_fails_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "data"
    target.mkdir()
    link = tmp_path / "corpus"
    _junction(link, target)
    _refuse_rmdir_on(monkeypatch, link)

    def refuse_shell(_path: Path) -> None:
        raise OSError("rmdir exited 5: Access is denied.")

    monkeypatch.setattr(dataroot, "_shell_rmdir", refuse_shell)

    with pytest.raises(OSError, match=r"WinError 5|Access is denied") as raised:
        dataroot.remove_link(link)

    assert "rmdir exited 5" in str(raised.value)
    assert "rmdir refused" in str(raised.value)
    assert dataroot.is_link(link)


def test_reap_one_leaves_the_worktree_alone_when_a_link_cannot_be_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path)
    worktree = tmp_path / "wt"
    _run_git(repo, "worktree", "add", "-q", str(worktree), "-b", "wt-test")
    target = tmp_path / "data"
    target.mkdir()
    link = worktree / "corpus"
    _junction(link, target)
    _refuse_rmdir_on(monkeypatch, link)

    def refuse_shell(_path: Path) -> None:
        raise OSError("rmdir exited 5: Access is denied.")

    monkeypatch.setattr(dataroot, "_shell_rmdir", refuse_shell)
    candidate = worktree_init._Candidate(
        worktree=worktree_init._Worktree(path=worktree, head=_head(worktree), branch="wt-test"),
        merged=True,
        dirty=[],
        untracked=[],
        links=[link],
        size=0,
    )

    error = worktree_init._reap_one(repo, candidate, stash_dirty=False, discard_untracked=False)

    assert error is not None
    assert "cannot unlink" in error
    assert "rmdir refused" in error
    assert "rmdir exited 5" in error
    assert worktree.is_dir()
    assert worktree_init._reparse_points(worktree) == [link]
    assert "wt-test" in _run_git(repo, "branch", "--format=%(refname:short)").split()


def test_reap_one_finishes_through_the_fallback_and_keeps_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path)
    worktree = tmp_path / "wt"
    _run_git(repo, "worktree", "add", "-q", str(worktree), "-b", "wt-test")
    target = tmp_path / "data"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    link = worktree / "corpus"
    _junction(link, target)
    _ignore_corpus(repo)
    _refuse_rmdir_on(monkeypatch, link)
    candidate = worktree_init._Candidate(
        worktree=worktree_init._Worktree(path=worktree, head=_head(worktree), branch="wt-test"),
        merged=True,
        dirty=[],
        untracked=[],
        links=[link],
        size=0,
    )

    assert (
        worktree_init._reap_one(repo, candidate, stash_dirty=False, discard_untracked=False) is None
    )
    assert not worktree.exists()
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
    _ignore_corpus(repo)
    candidate = worktree_init._Candidate(
        worktree=worktree_init._Worktree(path=worktree, head=_head(worktree), branch="wt-test"),
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


def test_reap_one_discards_the_worktrees_cached_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The environment lives in the shared cache, outside the checkout git removes, so
    # reap has to delete it or every reaped worktree leaves one behind.
    if os.name != "nt":
        pytest.skip("directory junctions are a Windows feature")
    repo = _init_repo(tmp_path)
    worktree = tmp_path / "wt"
    _run_git(repo, "worktree", "add", "-q", str(worktree), "-b", "wt-test")
    monkeypatch.setattr(dataroot, "REPO_ROOT", repo)
    target = dataroot.env_target(worktree)
    target.mkdir(parents=True)
    dataroot.env_marker(target).write_text(str(worktree), encoding="utf-8")
    dataroot.create_link(worktree / ".venv", target)
    candidate = worktree_init._Candidate(
        worktree=worktree_init._Worktree(path=worktree, head=_head(worktree), branch="wt-test"),
        merged=True,
        dirty=[],
        untracked=[],
        links=worktree_init._reparse_points(worktree),
        size=0,
    )
    assert (
        worktree_init._reap_one(repo, candidate, stash_dirty=False, discard_untracked=False) is None
    )
    assert not target.exists()
    assert not dataroot.env_marker(target).exists()


def test_candidates_keep_unmerged_and_outside_pool(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    _run_git(repo, "worktree", "add", "-q", str(pool / "merged"), "-b", "merged")
    _merge_into_main(repo, pool / "merged", "m.txt")
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


def test_a_fresh_worktree_is_skipped_and_a_fast_forwarded_branch_is_reaped(
    tmp_path: Path,
) -> None:
    """A branch with no commits of its own is an ancestor of main from birth (issue #196)."""
    repo = _init_repo(tmp_path)
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    _run_git(repo, "worktree", "add", "-q", str(pool / "new"), "-b", "new", "main")
    _run_git(repo, "worktree", "add", "-q", str(pool / "done"), "-b", "done", "main")
    _merge_into_main(repo, pool / "done", "d.txt")

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False
    )

    assert [candidate.worktree.branch for candidate in candidates] == ["done"]
    assert skipped == ["new: no commits in its reflog"]


def test_a_fresh_worktree_that_synced_with_base_is_still_skipped(tmp_path: Path) -> None:
    """A fast-forward onto main is a reflog entry but not a commit of the branch's own."""
    repo = _init_repo(tmp_path)
    _commit(repo, "second.txt")
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    _run_git(repo, "worktree", "add", "-q", str(pool / "new"), "-b", "new", "main~1")
    _run_git(pool / "new", "merge", "-q", "--ff-only", "main")
    assert len(_run_git(repo, "reflog", "show", "refs/heads/new").splitlines()) >= 2

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False
    )

    assert candidates == []
    assert skipped == ["new: no commits in its reflog"]


def test_a_fresh_worktree_rebased_onto_main_is_still_skipped(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _commit(repo, "second.txt")
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    _run_git(repo, "worktree", "add", "-q", str(pool / "new"), "-b", "new", "main~1")
    _run_git(pool / "new", "rebase", "-q", "main")

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False
    )

    assert candidates == []
    assert skipped == ["new: no commits in its reflog"]


def test_a_branch_with_its_own_commit_rebased_and_fast_forwarded_is_reaped(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    _run_git(repo, "worktree", "add", "-q", str(pool / "work"), "-b", "work", "main")
    _commit(pool / "work", "w.txt")
    _commit(repo, "second.txt")
    _run_git(pool / "work", "rebase", "-q", "main")
    _run_git(repo, "merge", "-q", "--ff-only", "work")

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False
    )

    assert skipped == []
    assert [candidate.worktree.branch for candidate in candidates] == ["work"]


@pytest.mark.parametrize(
    ("subject", "is_work"),
    [
        ("commit: x", True),
        ("commit (merge): x", True),
        ("merge main: Merge made by the 'ort' strategy.", True),
        ("pull origin main: Merge made by the 'ort' strategy.", True),
        ("pull: Fast-forward", False),
        ("merge main: Fast-forward", False),
        ("rebase (finish): refs/heads/b onto abc", False),
        ("reset: moving to origin/main", False),
        ("branch: Created from main", False),
    ],
)
def test_work_subject_classification(subject: str, is_work: bool) -> None:
    assert bool(worktree_init._WORK_SUBJECT.match(subject)) is is_work


def test_a_branch_without_a_reflog_is_skipped(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    _run_git(repo, "worktree", "add", "-q", str(pool / "old"), "-b", "old", "main")
    _merge_into_main(repo, pool / "old", "o.txt")
    (repo / ".git" / "logs" / "refs" / "heads" / "old").unlink()

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False
    )

    assert candidates == []
    assert skipped == ["old: no commits in its reflog"]


def test_a_fresh_branch_named_by_a_merged_pr_is_still_reaped(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    _run_git(repo, "worktree", "add", "-q", str(pool / "new"), "-b", "new", "main")
    tip = _head(pool / "new")
    prs: list[dict[str, object]] = [{"number": 5, "headRefName": "new", "headRefOid": tip}]
    merged_prs = worktree_init._MergedPrs(repo, _gh_stub(prs))  # type: ignore[arg-type]

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False, merged_prs=merged_prs
    )

    assert skipped == []
    assert [candidate.worktree.branch for candidate in candidates] == ["new"]


def test_clean_parity_keeps_the_baselines_and_removes_a_scratch_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rotation asks the layout which names are baselines before deleting a tree."""
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    ours = tmp_path / "build" / "parity" / "ours"
    sweep = tmp_path / "build" / "scratch" / "sweep"
    for tree in (ours / "ctry_current", ours / "ctry_base", ours / "ctry_old", sweep / "v001"):
        tree.mkdir(parents=True)
        (tree / "tick_00000.idx").write_bytes(b"frame")

    assert worktree_init._prune_render_trees(confirmed=True, keep=0) == 0

    assert (ours / "ctry_current").is_dir()
    assert (ours / "ctry_base").is_dir()
    assert not (ours / "ctry_old").exists()
    assert not (sweep / "v001").exists()


def _commit(cwd: Path, name: str) -> str:
    (cwd / name).write_text(name, encoding="utf-8")
    _run_git(cwd, "add", name)
    _run_git(
        cwd,
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "user.name=t",
        "commit",
        "-qm",
        name,
    )
    return _run_git(cwd, "rev-parse", "HEAD").strip()


def _merge_into_main(repo: Path, worktree: Path, name: str) -> None:
    """Commit once on a worktree's branch, then fast-forward ``main`` onto it."""
    _commit(worktree, name)
    branch = _run_git(worktree, "branch", "--show-current").strip()
    _run_git(repo, "merge", "-q", "--ff-only", branch)


def _gh_stub(
    prs: list[dict[str, object]] | None = None,
    *,
    returncode: int = 0,
    stderr: str = "",
    error: Exception | None = None,
    calls: list[tuple[str, ...]] | None = None,
) -> object:
    """A ``gh`` replacement: the tests never reach the network."""

    def run(_repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if calls is not None:
            calls.append(args)
        if error is not None:
            raise error
        return subprocess.CompletedProcess(
            args=["gh", *args],
            returncode=returncode,
            stdout=json.dumps(prs or []),
            stderr=stderr,
        )

    return run


def _squash_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    """A repo whose pool holds ``feat``: two commits that main never merged."""
    repo = _init_repo(tmp_path)
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    worktree = pool / "feat"
    _run_git(repo, "worktree", "add", "-q", str(worktree), "-b", "feat")
    _commit(worktree, "one.txt")
    tip = _commit(worktree, "two.txt")
    # main gets the same change as one squash commit, which ancestry and cherry cannot see.
    (repo / "squashed.txt").write_text("one two", encoding="utf-8")
    _commit(repo, "squashed.txt")
    return repo, worktree, tip


def test_squash_merged_branch_is_a_candidate_with_its_pr_number(tmp_path: Path) -> None:
    repo, worktree, tip = _squash_repo(tmp_path)
    prs: list[dict[str, object]] = [
        {"number": 89, "headRefName": "feat", "headRefOid": tip},
        {"number": 7, "headRefName": "other", "headRefOid": "0" * 40},
    ]
    merged_prs = worktree_init._MergedPrs(repo, _gh_stub(prs))  # type: ignore[arg-type]

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False, merged_prs=merged_prs
    )

    assert skipped == []
    assert [candidate.worktree.branch for candidate in candidates] == ["feat"]
    assert candidates[0].pr == 89
    assert not candidates[0].merged
    assert "merged as #89" in worktree_init._describe(candidates[0])
    assert worktree_init._describe(candidates[0]).lstrip().startswith("squash")
    assert worktree.is_dir()


def test_squash_merged_branch_is_removed_and_its_branch_force_deleted(tmp_path: Path) -> None:
    repo, worktree, tip = _squash_repo(tmp_path)
    merged_prs = worktree_init._MergedPrs(
        repo,
        _gh_stub([{"number": 89, "headRefName": "feat", "headRefOid": tip}]),  # type: ignore[arg-type]
    )
    candidates, _ = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False, merged_prs=merged_prs
    )

    error = worktree_init._reap_one(repo, candidates[0], stash_dirty=False, discard_untracked=False)

    assert error is None
    assert not worktree.exists()
    assert "feat" not in _run_git(repo, "branch", "--format=%(refname:short)").split()


def test_a_commit_after_classification_keeps_the_worktree_and_branch(tmp_path: Path) -> None:
    repo, worktree, tip = _squash_repo(tmp_path)
    merged_prs = worktree_init._MergedPrs(
        repo,
        _gh_stub([{"number": 89, "headRefName": "feat", "headRefOid": tip}]),  # type: ignore[arg-type]
    )
    candidates, _ = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False, merged_prs=merged_prs
    )
    later = _commit(worktree, "three.txt")

    error = worktree_init._reap_one(repo, candidates[0], stash_dirty=False, discard_untracked=False)

    assert error is not None
    assert "tip moved" in error
    assert worktree.is_dir()
    assert _run_git(repo, "rev-parse", "refs/heads/feat").strip() == later


def test_an_edit_after_classification_blocks_a_forced_removal(tmp_path: Path) -> None:
    repo, worktree, tip = _squash_repo(tmp_path)
    (worktree / "scratch.txt").write_text("untracked", encoding="utf-8")
    merged_prs = worktree_init._MergedPrs(
        repo,
        _gh_stub([{"number": 89, "headRefName": "feat", "headRefOid": tip}]),  # type: ignore[arg-type]
    )
    candidates, _ = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False, merged_prs=merged_prs
    )
    assert candidates[0].untracked
    assert not candidates[0].dirty
    (worktree / "two.txt").write_text("edited after reap listed it", encoding="utf-8")

    error = worktree_init._reap_one(repo, candidates[0], stash_dirty=False, discard_untracked=True)

    assert error is not None
    assert "modified files" in error
    assert (worktree / "two.txt").read_text(encoding="utf-8") == "edited after reap listed it"


def test_a_worktree_switched_to_another_branch_is_left_alone(tmp_path: Path) -> None:
    repo, worktree, tip = _squash_repo(tmp_path)
    merged_prs = worktree_init._MergedPrs(
        repo,
        _gh_stub([{"number": 89, "headRefName": "feat", "headRefOid": tip}]),  # type: ignore[arg-type]
    )
    candidates, _ = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False, merged_prs=merged_prs
    )
    _run_git(worktree, "switch", "-q", "-c", "other")

    error = worktree_init._reap_one(repo, candidates[0], stash_dirty=False, discard_untracked=False)

    assert error is not None
    assert "worktree changed" in error
    assert worktree.is_dir()
    assert _run_git(repo, "rev-parse", "refs/heads/feat").strip() == tip


def test_branch_that_moved_on_after_the_merge_is_skipped_with_a_reason(tmp_path: Path) -> None:
    repo, worktree, tip = _squash_repo(tmp_path)
    _commit(worktree, "after-merge.txt")
    merged_prs = worktree_init._MergedPrs(
        repo,
        _gh_stub([{"number": 89, "headRefName": "feat", "headRefOid": tip}]),  # type: ignore[arg-type]
    )

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False, merged_prs=merged_prs
    )

    assert candidates == []
    assert len(skipped) == 1
    assert skipped[0].startswith("feat: ")
    assert "tip differs from the head of merged #89" in skipped[0]


def test_cherry_does_not_take_a_branch_that_moved_on_after_its_merge(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    worktree = pool / "feat"
    _run_git(repo, "worktree", "add", "-q", str(worktree), "-b", "feat")
    merged_head = _commit(worktree, "one.txt")
    _commit(worktree, "two.txt")
    # main holds both patches, so --cherry alone would call the branch merged. Its own
    # messages keep its commits from matching the branch's byte for byte within one second.
    for name in ("one.txt", "two.txt"):
        (repo / name).write_text(name, encoding="utf-8")
        _run_git(repo, "add", name)
        _run_git(
            repo,
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            f"main: {name}",
        )
    merged_prs = worktree_init._MergedPrs(
        repo,
        _gh_stub([{"number": 89, "headRefName": "feat", "headRefOid": merged_head}]),  # type: ignore[arg-type]
    )

    candidates, skipped = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=True, merged_prs=merged_prs
    )

    assert candidates == []
    assert "tip differs from the head of merged #89" in skipped[0]


@pytest.mark.parametrize(
    "stub",
    [
        _gh_stub(error=FileNotFoundError("gh is not on PATH")),
        _gh_stub(returncode=4, stderr="To get started with GitHub CLI, please run: gh auth login"),
        _gh_stub(error=subprocess.TimeoutExpired(cmd="gh", timeout=30)),
    ],
    ids=["missing", "signed-out", "offline"],
)
def test_without_gh_reap_falls_back_to_git_checks_and_says_so(
    tmp_path: Path,
    stub: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, worktree, _tip = _squash_repo(tmp_path)
    monkeypatch.setattr(worktree_init, "REPO_ROOT", repo)
    monkeypatch.setattr(worktree_init, "_gh", stub)

    assert worktree_init._reap(False) == 0

    out = capsys.readouterr().out
    assert "gh unavailable" in out
    assert "squash-merged branches are not recognised" in out
    assert "feat: 2 patch(es) not in main" in out
    assert worktree.is_dir()


def test_dry_run_lists_the_squash_merged_branch_without_removing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, worktree, tip = _squash_repo(tmp_path)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(worktree_init, "REPO_ROOT", repo)
    monkeypatch.setattr(
        worktree_init,
        "_gh",
        _gh_stub([{"number": 89, "headRefName": "feat", "headRefOid": tip}], calls=calls),
    )

    assert worktree_init._reap(False) == 0

    out = capsys.readouterr().out
    assert "squash" in out
    assert "merged as #89" in out
    assert "gh unavailable" not in out
    assert worktree.is_dir()
    assert len(calls) == 1, "one gh call covers every branch"
    assert "--state" in calls[0]
    assert "merged" in calls[0]


def test_gh_is_not_asked_when_every_branch_is_already_in_main(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    pool = repo / ".agents" / "worktrees"
    pool.mkdir(parents=True)
    _run_git(repo, "worktree", "add", "-q", str(pool / "merged"), "-b", "merged")
    _merge_into_main(repo, pool / "merged", "m.txt")
    calls: list[tuple[str, ...]] = []
    merged_prs = worktree_init._MergedPrs(repo, _gh_stub(calls=calls))  # type: ignore[arg-type]

    candidates, _ = worktree_init._candidates(
        repo, worktree_init._worktrees(repo), include_cherry=False, merged_prs=merged_prs
    )

    assert [candidate.worktree.branch for candidate in candidates] == ["merged"]
    assert calls == []


def test_clean_removes_read_only_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A test's scratch repository under ``.pytest_cache`` holds git objects, which git
    marks read-only, and Windows refuses to unlink a read-only file."""
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    objects = tmp_path / ".pytest_cache" / "basetemp" / "repo" / ".git" / "objects" / "05"
    objects.mkdir(parents=True)
    blob = objects / "43213c3e614823f0f6500583215b8c4a87066e"
    blob.write_bytes(b"blob")
    blob.chmod(0o444)

    assert worktree_init._clean(confirmed=True) == 0

    assert not (tmp_path / ".pytest_cache").exists()


def test_remove_tree_refuses_a_link_and_leaves_its_target_alone(tmp_path: Path) -> None:
    """``chmod`` follows a link, so the read-only retry must not run on one."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "frame.idx").write_bytes(b"frame")
    link = tmp_path / "link"
    dataroot.create_link(link, target)
    mode = target.stat().st_mode

    # rmtree words the refusal differently per platform (no message on POSIX).
    with pytest.raises(OSError):  # noqa: PT011
        worktree_init._remove_tree(link)

    assert target.stat().st_mode == mode
    assert (target / "frame.idx").read_bytes() == b"frame"
    dataroot.remove_link(link)


def test_clean_parity_skips_a_linked_render_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A render child that links elsewhere is not this checkout's to prune."""
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "tick_00000.idx").write_bytes(b"frame")
    linked = tmp_path / "build" / "scratch" / "sweep" / "v001"
    dataroot.create_link(linked, elsewhere)

    assert worktree_init._prune_render_trees(confirmed=True, keep=0) == 0

    assert dataroot.is_link(linked)
    assert (elsewhere / "tick_00000.idx").is_file()
    dataroot.remove_link(linked)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_remove_tree_keeps_a_file_mode_when_its_directory_refuses(tmp_path: Path) -> None:
    """On POSIX a refused unlink is the parent directory's mode, so the file keeps its own."""
    locked = tmp_path / "tree" / "locked"
    locked.mkdir(parents=True)
    blob = locked / "blob"
    blob.write_bytes(b"blob")
    blob.chmod(0o444)
    locked.chmod(0o555)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("this process can write a 0555 directory (root or CAP_DAC_OVERRIDE)")
        with pytest.raises(PermissionError):
            worktree_init._remove_tree(tmp_path / "tree")
        assert stat.S_IMODE(blob.stat().st_mode) == 0o444
    finally:
        locked.chmod(0o755)


def test_clean_unlinks_the_legacy_capture_link_and_keeps_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build/ of an old worktree holds a junction into the data root's captures (ADR 0018)."""
    checkout = tmp_path / "checkout"
    meta = tmp_path / "data" / "captures" / "vault-ctry" / "frames" / "meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text("{}", encoding="utf-8")
    legacy = checkout / "build" / "parity" / "captures"
    dataroot.create_link(legacy, tmp_path / "data" / "captures")
    (checkout / "build" / "scratch").mkdir(parents=True)
    (checkout / "build" / "scratch" / "x.png").write_bytes(b"png")
    monkeypatch.setattr(worktree_init, "REPO_ROOT", checkout)

    assert worktree_init._clean(confirmed=True) == 0

    assert meta.is_file()
    assert not dataroot.is_link(legacy)
    assert not (checkout / "build").exists()


def _stub_reap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, free: int | OSError) -> list[Path]:
    """``_reap`` over one squash-merged ``feat`` candidate on a drive with *free* bytes.

    Nothing touches git: these tests decide whether ``_reap`` removes, not how. The returned
    list records each worktree ``_reap_one`` was asked to remove.
    """
    feat = worktree_init._Worktree(tmp_path / ".agents" / "worktrees" / "feat", "1" * 40, "feat")
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(dataroot, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(worktree_init, "_gh", _gh_stub())
    monkeypatch.setattr(
        worktree_init,
        "_worktrees",
        lambda _repo: [worktree_init._Worktree(tmp_path, "0" * 40, "main"), feat],
    )
    candidate = worktree_init._Candidate(
        worktree=feat, merged=True, dirty=[], untracked=[], links=[], size=0, pr=89
    )
    monkeypatch.setattr(worktree_init, "_candidates", lambda *_a, **_k: ([candidate], []))

    def free_bytes(_path: Path) -> int:
        if isinstance(free, OSError):
            raise free
        return free

    monkeypatch.setattr(worktree_init, "_free_bytes", free_bytes)
    removed: list[Path] = []

    def reap_one(_repo: Path, chosen: worktree_init._Candidate, **_kwargs: object) -> None:
        removed.append(chosen.worktree.path)

    monkeypatch.setattr(worktree_init, "_reap_one", reap_one)
    return removed


def _feat(tmp_path: Path) -> Path:
    return tmp_path / ".agents" / "worktrees" / "feat"


def test_space_is_short_only_below_the_bar() -> None:
    gib = worktree_init.GIB
    assert worktree_init._space_is_short(19 * gib, 20.0)
    assert not worktree_init._space_is_short(20 * gib, 20.0)


def test_reap_with_plenty_of_space_removes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    removed = _stub_reap(monkeypatch, tmp_path, 50 * worktree_init.GIB)

    assert worktree_init._reap(True) == 0
    assert removed == []
    assert "nothing removed" in capsys.readouterr().out


def test_reap_below_the_bar_removes_the_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    removed = _stub_reap(monkeypatch, tmp_path, 5 * worktree_init.GIB)

    assert worktree_init._reap(True) == 0
    assert removed == [_feat(tmp_path)]


def test_force_reaps_with_plenty_of_space(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    removed = _stub_reap(monkeypatch, tmp_path, 50 * worktree_init.GIB)

    assert worktree_init._reap(True, force=True) == 0
    assert removed == [_feat(tmp_path)]


def test_min_free_gb_moves_the_bar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    removed = _stub_reap(monkeypatch, tmp_path, 50 * worktree_init.GIB)

    assert worktree_init._reap(True, min_free_gb=100.0) == 0
    assert removed == [_feat(tmp_path)]


def test_unknown_free_space_removes_nothing_without_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    removed = _stub_reap(monkeypatch, tmp_path, OSError("boom"))

    assert worktree_init._reap(True) == 0
    assert removed == []
    out = capsys.readouterr().out
    assert "free space unknown" in out
    assert "plenty of space" not in out


def test_force_reaps_when_free_space_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    removed = _stub_reap(monkeypatch, tmp_path, OSError("boom"))

    assert worktree_init._reap(True, force=True) == 0
    assert removed == [_feat(tmp_path)]


def test_prune_with_plenty_of_space_prunes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    removed = _stub_reap(monkeypatch, tmp_path, 50 * worktree_init.GIB)
    seen: list[bool] = []

    def spy(*_args: object, confirmed: bool, **_kwargs: object) -> tuple[int, int]:
        seen.append(confirmed)
        return 0, 0

    for name in ("_prune_leftovers", "_prune_envs", "_prune_branches"):
        monkeypatch.setattr(worktree_init, name, spy)

    assert worktree_init._reap(True, prune=True) == 0
    assert removed == []
    assert seen
    assert True not in seen


def test_reap_cli_defaults_and_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def spy(_confirmed: bool, **kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(worktree_init, "_reap", spy)

    worktree_init.main(["reap"])
    worktree_init.main(["reap", "--force", "--min-free-gb", "5"])
    worktree_init.main(["reap", "--allow-stale-script"])

    assert (calls[0]["force"], calls[0]["min_free_gb"]) == (False, 20.0)
    assert (calls[1]["force"], calls[1]["min_free_gb"]) == (True, 5.0)
    assert [call["allow_stale_script"] for call in calls] == [False, False, True]


def test_negative_min_free_gb_is_refused() -> None:
    with pytest.raises(SystemExit):
        worktree_init.main(["reap", "--min-free-gb", "-1"])


def _commit_script(repo: Path, text: str) -> str:
    """Commit *text* as the repo's reap script; return its blob."""
    script = repo / worktree_init.SCRIPT_PATH
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(text, encoding="utf-8")
    _run_git(repo, "add", worktree_init.SCRIPT_PATH)
    _run_git(repo, "commit", "-qm", text)
    return _run_git(repo, "rev-parse", f"HEAD:{worktree_init.SCRIPT_PATH}").strip()


def _stale_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, free: int, *, stale: bool = True
) -> tuple[Path, Path, str, str]:
    """``_reap_env`` plus a local ``origin`` whose main holds a newer reap script when *stale*.

    Returns the repo, the squash-merged worktree, and the blobs of HEAD's and main's script.
    """
    repo, worktree = _reap_env(monkeypatch, tmp_path, free)
    ours = _commit_script(repo, "old rules")
    main = _commit_script(repo, "new rules") if stale else ours
    origin = tmp_path / "origin.git"
    _run_git(tmp_path, "clone", "-q", "--bare", str(repo), str(origin))
    _run_git(repo, "remote", "add", "origin", str(origin))
    _run_git(repo, "fetch", "-q", "origin")
    if stale:
        # The primary checkout sits one commit behind the main it fetched (issue #218).
        _run_git(repo, "reset", "-q", "--hard", "HEAD~1")
    return repo, worktree, ours, main


def test_a_stale_script_refuses_a_confirmed_reap_and_names_both_blobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, worktree, ours, main = _stale_env(monkeypatch, tmp_path, 5 * worktree_init.GIB)

    assert worktree_init._reap(True) == 1
    assert worktree.is_dir()
    out = capsys.readouterr().out
    assert ours in out
    assert main in out
    assert "update the primary checkout" in out
    assert "--allow-stale-script" in out


def test_force_does_not_lift_the_stale_script_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, worktree, _, _ = _stale_env(monkeypatch, tmp_path, 50 * worktree_init.GIB)

    assert worktree_init._reap(True, force=True) == 1
    assert worktree.is_dir()


def test_allow_stale_script_reaps_anyway(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, worktree, _, _ = _stale_env(monkeypatch, tmp_path, 5 * worktree_init.GIB)

    assert worktree_init._reap(True, allow_stale_script=True) == 0
    assert not worktree.exists()


def test_a_dry_run_warns_about_a_stale_script_and_still_lists_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, worktree, ours, _ = _stale_env(monkeypatch, tmp_path, 5 * worktree_init.GIB)

    assert worktree_init._reap(False) == 0
    assert worktree.is_dir()
    out = capsys.readouterr().out
    assert f"stale reap: HEAD:{worktree_init.SCRIPT_PATH} is {ours}" in out
    assert "merged as #89" in out
    assert "dry run" in out


def test_a_current_script_reaps_without_a_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, worktree, _, _ = _stale_env(monkeypatch, tmp_path, 5 * worktree_init.GIB, stale=False)

    assert worktree_init._reap(True) == 0
    assert not worktree.exists()
    assert "stale reap" not in capsys.readouterr().out


def test_a_checkout_ahead_of_main_is_told_to_merge_not_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, worktree, _, main = _stale_env(monkeypatch, tmp_path, 5 * worktree_init.GIB, stale=False)
    ours = _commit_script(repo, "unmerged rules")

    assert worktree_init._reap(True) == 1
    assert worktree.is_dir()
    out = capsys.readouterr().out
    assert ours in out
    assert main in out
    assert "merge it first" in out
    assert "update the primary checkout" not in out


def test_offline_reap_compares_with_the_last_fetched_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, worktree, _, main = _stale_env(monkeypatch, tmp_path, 5 * worktree_init.GIB)
    _run_git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    assert worktree_init._reap(True) == 1
    assert worktree.is_dir()
    out = capsys.readouterr().out
    assert "cannot fetch origin main" in out
    assert main in out


def test_a_narrowed_fetch_refspec_still_updates_origin_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, worktree, _, _ = _stale_env(monkeypatch, tmp_path, 5 * worktree_init.GIB, stale=False)
    # A single-branch clone: a bare `git fetch origin main` would move only FETCH_HEAD.
    _run_git(repo, "config", "remote.origin.fetch", "+refs/heads/other:refs/remotes/origin/other")
    pusher = tmp_path / "pusher"
    _run_git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(pusher))
    newer = _commit_script(pusher, "new rules")
    _run_git(pusher, "push", "-q", "origin", "HEAD:main")

    assert worktree_init._reap(True) == 1
    assert worktree.is_dir()
    assert newer in capsys.readouterr().out


def test_an_uncommitted_script_edit_refuses_until_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, worktree, _, main = _stale_env(monkeypatch, tmp_path, 5 * worktree_init.GIB, stale=False)
    # HEAD matches main; reap runs the working-tree file, which has an edit.
    (repo / worktree_init.SCRIPT_PATH).write_text("edited rules", encoding="utf-8")

    assert worktree_init._reap(True) == 1
    assert worktree.is_dir()
    out = capsys.readouterr().out
    assert "uncommitted changes" in out
    assert main in out

    assert worktree_init._reap(True, allow_stale_script=True) == 0
    assert not worktree.exists()


def test_a_bounded_run_does_not_wait_for_a_child_holding_stderr(tmp_path: Path) -> None:
    # A grandchild that keeps the stderr handle, as git's ssh can after git is killed. Read
    # through a pipe, the timeout would wait the grandchild's full 8 s.
    child = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(8)'], stderr=sys.stderr); "
        "time.sleep(8)"
    )
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        worktree_init._run_bounded([sys.executable, "-c", child], tmp_path, 1)
    assert time.monotonic() - start < 5


def test_a_bounded_run_returns_the_exit_code_and_stderr(tmp_path: Path) -> None:
    code = "import sys; sys.stderr.write('fatal: nope\\n'); sys.exit(3)"
    returncode, stderr = worktree_init._run_bounded([sys.executable, "-c", code], tmp_path, 30)
    assert (returncode, stderr.strip()) == (3, "fatal: nope")
