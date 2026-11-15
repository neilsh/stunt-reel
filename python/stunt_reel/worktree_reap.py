"""``reap``: remove merged worktrees without letting git delete through a data-root link.

Git's ``worktree remove`` has recursed through Windows junctions on some builds, so reap
unlinks every reparse point, proves none remain, and only then removes the checkout
(ADR 0018). A merged pull request whose head is the branch tip is found with ``gh``, and a
confirmed reap refuses while any source it runs differs from ``origin/main``'s (issue #218).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel.dataroot import (
    REPO_ROOT,
    SharedDataError,
    discard_env,
    is_link,
    orphan_envs,
    remove_link,
    sweep_orphan_envs,
)
from stunt_reel.worktree_clean import _size
from stunt_reel.worktree_git import _git, _Worktree, _worktrees

if TYPE_CHECKING:
    from collections.abc import Callable

#: Directories inside the primary checkout where linked worktrees live (AGENTS.md, Worktrees).
POOL_DIRS: tuple[str, ...] = (".agents/worktrees", ".claude/worktrees")


@dataclass
class _Candidate:
    """A worktree ``reap`` may remove, with the state that decides whether it may."""

    worktree: _Worktree
    merged: bool
    dirty: list[str]
    untracked: list[str]
    links: list[Path]
    size: int
    #: The merged pull request that squash-landed this branch, when that is why it may go.
    pr: int | None = None


def _is_ancestor(repo: Path, branch: str) -> bool:
    """True when ``main`` already contains every commit of *branch*."""
    return _git(repo, "merge-base", "--is-ancestor", branch, "main").returncode == 0


#: Reflog subjects that record work done on a branch: a commit (also amend, merge, initial), a
#: cherry-pick, revert or am, or a merge or pull that made a merge commit. A rebase is not listed: onto
#: ``main`` it writes ``rebase (finish)`` even with nothing of the branch's own to replay, and
#: commits that were rebased already left a ``commit:``, ``am:`` or ``cherry-pick:`` entry.
#: "Merge made" is git's English message; another locale fails to match and errs toward keeping.
_WORK_SUBJECT = re.compile(r"(commit|cherry-pick|revert|am)(:| \()|(merge|pull)\b[^:]*: Merge made")


def _never_committed(repo: Path, branch: str) -> bool:
    """True when no entry in *branch*'s reflog records work made on it.

    A branch cut from ``main`` is an ancestor of ``main`` from birth, and one that then syncs with
    base (fast-forward merge, ``reset --hard``) stays one, so ancestry cannot tell it from a merged
    branch. Creation, ``reset:`` and ``Fast-forward`` entries are not work. A missing, empty or
    unreadable reflog also counts as fresh, which means a very old merged branch whose reflog
    expired is kept until removed by hand: keeping a worktree is the safe mistake.
    """
    result = _git(repo, "reflog", "show", "--format=%gs", f"refs/heads/{branch}")
    if result.returncode != 0:
        return True
    return not any(_WORK_SUBJECT.match(line) for line in result.stdout.splitlines())


def _unmerged_patch_count(repo: Path, branch: str) -> int:
    """Patches on *branch* that ``main`` does not already hold."""
    result = _git(repo, "cherry", "main", branch)
    return sum(1 for line in result.stdout.splitlines() if line.startswith("+"))


#: Merged pull requests asked of GitHub in one call; older ones fall back to the git checks.
MERGED_PR_LIMIT = 200
#: Seconds to wait for ``gh`` before treating it as offline.
GH_TIMEOUT = 30


def _gh(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one ``gh`` command in *repo*; tests replace this, so the gate stays offline."""
    gh = shutil.which("gh")
    if gh is None:
        raise FileNotFoundError("gh is not on PATH")
    return subprocess.run(  # noqa: S603
        [gh, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=GH_TIMEOUT,
    )


class _MergedPrs:
    """The merged pull requests of the repository, fetched once and only when needed.

    Every PR lands on ``main`` as one squash commit, so neither ancestry nor ``git
    cherry`` recognises a branch with several commits.  GitHub does: a branch whose
    local tip is the head commit of a merged PR was merged, and a tip that moved on
    after the merge is not.  When ``gh`` is missing, signed out or offline,
    :attr:`unavailable` says why and :meth:`find` matches nothing, which leaves the
    git checks as the only ones.
    """

    def __init__(self, repo: Path, gh: Callable[..., subprocess.CompletedProcess[str]] = _gh):
        self._repo = repo
        self._gh = gh
        self._loaded = False
        self._heads: dict[str, list[tuple[int, str]]] = {}
        self.unavailable: str | None = None

    def _load(self) -> None:
        self._loaded = True
        try:
            result = self._gh(
                self._repo,
                "pr",
                "list",
                "--state",
                "merged",
                "--base",
                "main",
                "--json",
                "number,headRefName,headRefOid",
                "--limit",
                str(MERGED_PR_LIMIT),
            )
        except (OSError, subprocess.SubprocessError) as err:
            self.unavailable = str(err) or type(err).__name__
            return
        if result.returncode != 0:
            lines = result.stderr.strip().splitlines()
            self.unavailable = lines[0] if lines else f"gh exited {result.returncode}"
            return
        try:
            for item in json.loads(result.stdout):
                self._heads.setdefault(item["headRefName"], []).append(
                    (int(item["number"]), str(item["headRefOid"]))
                )
        except (ValueError, KeyError, TypeError) as err:
            self._heads.clear()
            self.unavailable = f"unreadable gh output ({err})"

    def find(self, branch: str, tip: str) -> int | None:
        """The merged PR number whose head is *branch* at *tip*, or None."""
        if not self._loaded:
            self._load()
        for number, head in self._heads.get(branch, []):
            if head == tip:
                return number
        return None

    def moved_on(self, branch: str) -> int | None:
        """The newest merged PR from *branch* when its tip is no longer that PR's head."""
        numbers = [number for number, _ in self._heads.get(branch, [])]
        return max(numbers) if numbers else None


def _changed(path: Path, *, untracked: bool) -> list[str]:
    """Modified tracked files, or untracked ones, of one checkout."""
    flag = "--untracked-files=normal" if untracked else "--untracked-files=no"
    result = _git(path, "status", "--porcelain=v1", flag)
    if result.returncode != 0:
        return [f"cannot read status: {result.stderr.strip()}"]
    lines = result.stdout.splitlines()
    if untracked:
        return [line for line in lines if line.startswith("??")]
    return [line for line in lines if not line.startswith("??")]


def _reparse_points(root: Path) -> list[Path]:
    """Every link under *root*, never descending into one."""
    found: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if is_link(path):
                        found.append(path)
                    elif entry.is_dir(follow_symlinks=False):
                        stack.append(path)
        except OSError:
            continue
    return found


def _unlink_reparse_points(root: Path) -> list[str]:
    """Unlink every link under *root*; return the ones that refused."""
    failures: list[str] = []
    for path in _reparse_points(root):
        try:
            remove_link(path)
        except OSError as err:
            failures.append(f"{path}: {err}")
    return failures


def _candidates(
    repo: Path,
    entries: list[_Worktree],
    *,
    include_cherry: bool,
    merged_prs: _MergedPrs | None = None,
) -> tuple[list[_Candidate], list[str]]:
    """Classify worktrees under *repo*; return what may go and what will not."""
    primary = entries[0].path
    candidates: list[_Candidate] = []
    skipped: list[str] = []
    for worktree in entries[1:]:
        label = worktree.branch or "(detached)"
        if primary not in worktree.path.parents:
            skipped.append(f"{label}: outside this checkout's worktree pool")
            continue
        if worktree.path == repo or worktree.path in repo.parents:
            skipped.append(f"{label}: contains this checkout")
            continue
        if worktree.branch is None:
            skipped.append(f"{label}: detached HEAD")
            continue
        merged = _is_ancestor(repo, worktree.branch)
        pr: int | None = None
        if (
            merged
            and _never_committed(repo, worktree.branch)
            and (merged_prs is None or merged_prs.find(worktree.branch, worktree.head) is None)
        ):
            skipped.append(f"{label}: no commits in its reflog")
            continue
        if not merged:
            if merged_prs is not None:
                pr = merged_prs.find(worktree.branch, worktree.head)
            if pr is None:
                patches = _unmerged_patch_count(repo, worktree.branch)
                reason = f"{patches} patch(es) not in main"
                # A branch that moved on after its PR merged keeps its worktree, --cherry or not.
                later = merged_prs.moved_on(worktree.branch) if merged_prs else None
                if later is not None:
                    skipped.append(
                        f"{label}: {reason}; tip differs from the head of merged #{later}"
                    )
                    continue
                if not (include_cherry and patches == 0):
                    skipped.append(f"{label}: {reason}")
                    continue
        candidates.append(
            _Candidate(
                worktree=worktree,
                merged=merged,
                dirty=_changed(worktree.path, untracked=False),
                untracked=_changed(worktree.path, untracked=True),
                links=_reparse_points(worktree.path),
                size=_size(worktree.path),
                pr=pr,
            )
        )
    return candidates, skipped


def _describe(candidate: _Candidate) -> str:
    """One report line for a candidate."""
    worktree = candidate.worktree
    state = "merged" if candidate.merged else "squash" if candidate.pr else "cherry"
    flags: list[str] = []
    if candidate.pr:
        flags.append(f"merged as #{candidate.pr}")
    if candidate.dirty:
        flags.append(f"{len(candidate.dirty)} modified")
    if candidate.untracked:
        flags.append(f"{len(candidate.untracked)} untracked")
    if candidate.links:
        flags.append(f"{len(candidate.links)} link(s)")
    detail = ", ".join(flags) if flags else "clean"
    branch = worktree.branch or "(detached)"
    return (
        f"  {state:<6} {branch:<42}{candidate.size / 1_048_576:9.1f} MiB"
        f"  {worktree.head[:10]}  {detail}"
    )


def _blocked(candidate: _Candidate, *, stash_dirty: bool, discard_untracked: bool) -> list[str]:
    """What stops *candidate* from being removed without losing work."""
    reasons: list[str] = []
    if candidate.dirty and not stash_dirty:
        reasons.append("modified files; pass --stash-dirty to stash them")
    if candidate.untracked and not discard_untracked:
        reasons.append("untracked files; pass --discard-untracked to drop them")
    return reasons


def _reap_one(
    repo: Path,
    candidate: _Candidate,
    *,
    stash_dirty: bool,
    discard_untracked: bool,
) -> str | None:
    """Remove one candidate; return a failure message, or None on success."""
    worktree = candidate.worktree
    branch = worktree.branch
    path = worktree.path
    # The worktree must still hold the branch and tip it was classified with: one switched to
    # another branch is not this candidate, and a commit made since is in neither main nor
    # the merged PR.
    current = next((entry for entry in _worktrees(repo) if entry.path == path), None)
    if current is None or current.branch != branch:
        return f"{branch}: worktree changed since it was classified; left alone"
    if current.head != worktree.head:
        return (
            f"{branch}: tip moved since it was classified "
            f"({worktree.head[:10]} -> {current.head[:10]}); left alone"
        )
    # Cleanliness is read now, not taken from classification: a forced remove must not drop
    # an edit made after reap listed the worktree.
    dirty = _changed(path, untracked=False)
    untracked = _changed(path, untracked=True)
    if dirty and not stash_dirty:
        return f"{branch}: modified files"
    if untracked and not discard_untracked:
        return f"{branch}: untracked files"
    if dirty:
        stash = _git(path, "stash", "push", "--message", f"reap {branch}: uncommitted work")
        if stash.returncode != 0:
            return f"{branch}: git stash failed: {stash.stderr.strip()}"
        if _changed(path, untracked=False):
            return f"{branch}: still modified after stashing"
    failures = _unlink_reparse_points(path)
    if failures:
        return f"{branch}: cannot unlink: {'; '.join(failures)}"
    remaining = _reparse_points(path)
    if remaining:
        return f"{branch}: links remain: {', '.join(str(item) for item in remaining)}"
    if _changed(path, untracked=False):
        return f"{branch}: modified files appeared before removal; left alone"
    remove_args = ["worktree", "remove"]
    if untracked:
        remove_args.append("--force")
    remove = _git(repo, *remove_args, str(path))
    if remove.returncode != 0:
        return f"{branch}: git worktree remove failed: {remove.stderr.strip()}"
    if branch is not None:
        if candidate.merged:
            delete = _git(repo, "branch", "-d", branch)
        else:
            # Compare-and-delete: refused if the branch moved off the classified tip.
            delete = _git(repo, "update-ref", "-d", f"refs/heads/{branch}", worktree.head)
        if delete.returncode != 0:
            return f"{branch}: git branch delete failed: {delete.stderr.strip()}"
    # The environment lives in the shared cache, outside the checkout git just removed.
    discard_env(path)
    return None


def _prune_leftovers(entries: list[_Worktree], *, confirmed: bool) -> tuple[int, int]:
    """Remove pool directories git no longer registers; return count and bytes."""
    primary = entries[0].path
    registered = {entry.path for entry in entries}
    removed = 0
    freed = 0
    for relative in POOL_DIRS:
        pool = primary / relative
        if not pool.is_dir() or is_link(pool):
            continue
        for child in sorted(pool.iterdir()):
            if not child.is_dir() or is_link(child) or child in registered:
                continue
            size = _size(child)
            print(f"  leftover {relative}/{child.name:<38}{size / 1_048_576:9.1f} MiB")
            if not confirmed:
                continue
            failures = _unlink_reparse_points(child)
            if failures or _reparse_points(child):
                print(f"  ! {child.name}: links remain; left alone")
                continue
            if any(child.iterdir()):
                print(f"  ! {child.name}: holds files git does not know; left alone")
                continue
            try:
                child.rmdir()
            except OSError as err:
                print(f"  ! {child.name}: {err}")
                continue
            discard_env(child)
            removed += 1
            freed += size
    return removed, freed


def _prune_envs(*, confirmed: bool) -> int:
    """Remove cached environments whose checkout is gone; return how many."""
    stale = orphan_envs()
    for target in stale:
        print(f"  env      {target.name}")
    if not confirmed or not stale:
        return 0
    return len(sweep_orphan_envs())


def _prune_branches(
    repo: Path, entries: list[_Worktree], *, include_cherry: bool, confirmed: bool
) -> tuple[int, int]:
    """Delete branches no worktree holds; return removed and kept counts."""
    held = {entry.branch for entry in entries if entry.branch}
    result = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    removed = 0
    kept = 0
    for branch in sorted(result.stdout.splitlines()):
        if not branch or branch == "main" or branch in held:
            continue
        merged = _is_ancestor(repo, branch)
        patches = _unmerged_patch_count(repo, branch)
        if not merged and not (include_cherry and patches == 0):
            kept += 1
            continue
        print(f"  branch   {branch:<48}{'merged' if merged else 'patch-equivalent'}")
        if not confirmed:
            continue
        delete = _git(repo, "branch", "-d" if merged else "-D", branch)
        if delete.returncode == 0:
            removed += 1
        else:
            print(f"  ! {branch}: {delete.stderr.strip()}")
    return removed, kept


GIB = 1 << 30
DEFAULT_MIN_FREE_GB = 20.0


def _free_bytes(path: Path) -> int:
    """Free bytes on the drive holding *path*."""
    return shutil.disk_usage(path).free


def _space_is_short(free: int, min_free_gb: float) -> bool:
    """Whether *free* bytes is under the reaping bar of *min_free_gb* GiB."""
    return free < min_free_gb * GIB


#: Every source reap's rules live in: the entrypoint plus the modules it runs (issue #218).
SCRIPT_PATHS: tuple[str, ...] = (
    "python/scripts/worktree_init.py",
    "python/stunt_reel/worktree_clean.py",
    "python/stunt_reel/worktree_ensure.py",
    "python/stunt_reel/worktree_git.py",
    "python/stunt_reel/worktree_provision.py",
    "python/stunt_reel/worktree_reap.py",
)
FETCH_TIMEOUT = 30


def _script_is_stale(repo: Path) -> tuple[bool, list[str]]:
    """Whether any source reap runs differs from ``origin/main``'s, and what to print.

    The primary checkout runs its own copy, so a checkout left on an old branch reaps with
    rules main has since fixed (issue #218). Each of :data:`SCRIPT_PATHS` must match main in
    both the committed copy and the working-tree file reap actually runs. A failed fetch
    compares with the last fetched ``origin/main``; a side that cannot be read is reported and
    does not count as stale.
    """
    lines: list[str] = []
    fetch_error = _fetch_main(repo)
    if fetch_error is not None:
        lines.append(
            f"  ! cannot fetch origin main ({fetch_error}); comparing with the last fetched copy"
        )
    for relative in SCRIPT_PATHS:
        blobs: list[str] = []
        for rev in ("HEAD", "origin/main"):
            result = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}:{relative}")
            if result.returncode != 0:
                lines.append(f"  ! {rev}:{relative} is unreadable; cannot tell if reap is current")
                return False, lines
            blobs.append(result.stdout.strip())
        ours, main = blobs
        if ours == main:
            # HEAD matches, but reap runs the working-tree file, edits included.
            hashed = _git(repo, "hash-object", "--", relative)
            if hashed.returncode != 0:
                lines.append(f"  ! {relative} is unreadable; cannot tell if reap is current")
                return False, lines
            local = hashed.stdout.strip()
            if local == main:
                continue
            lines.append(f"  ! stale reap: the working-tree {relative} is {local}")
            lines.append(f"    but origin/main:{relative} is {main};")
            lines.append(
                "    the working-tree copy has uncommitted changes; merge or discard them,"
                " or review them and pass --allow-stale-script to reap with them"
            )
            return True, lines
        lines.append(f"  ! stale reap: HEAD:{relative} is {ours}")
        lines.append(f"    but origin/main:{relative} is {main};")
        if _git(repo, "merge-base", "--is-ancestor", "origin/main", "HEAD").returncode == 0:
            # Ahead of main, not behind it: updating would not change the copy reap runs.
            lines.append(
                "    HEAD carries a reap change main lacks; merge it first,"
                " or review it and pass --allow-stale-script to reap with it"
            )
        else:
            lines.append(
                "    update the primary checkout to origin/main and run reap from it again"
            )
        return True, lines
    return False, lines


def _run_bounded(
    args: list[str], cwd: Path, timeout: float, env: dict[str, str] | None = None
) -> tuple[int, str]:
    """Run *args* for at most *timeout* seconds; return its exit code and stderr.

    No output goes through a pipe. On a timeout ``subprocess.run`` kills the process and
    then reads its pipes to the end, which never comes while a child it started (git's
    ssh, say) still holds them open. A temporary file has no end to wait for. Raises
    ``subprocess.TimeoutExpired`` and ``OSError`` as ``subprocess.run`` does.
    """
    with tempfile.TemporaryFile() as err:
        result = subprocess.run(  # noqa: S603
            args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=err,
            check=False,
            timeout=timeout,
            env=env,
        )
        err.seek(0)
        return result.returncode, err.read().decode("utf-8", errors="replace")


def _fetch_main(repo: Path) -> str | None:
    """Fetch ``origin``'s ``main`` quietly; return why it failed, or ``None``.

    The refspec names the destination, so ``origin/main`` moves even when
    ``remote.origin.fetch`` does not cover ``main`` (a single-branch clone), where a bare
    ``git fetch origin main`` would update only ``FETCH_HEAD``.
    """
    git = shutil.which("git")
    if git is None:
        return "git is not on PATH"
    try:
        returncode, stderr = _run_bounded(
            [git, "fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main"],
            repo,
            FETCH_TIMEOUT,
            # Offline or signed out, git must fail rather than wait at a credential prompt.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return str(err)
    if returncode == 0:
        return None
    lines = stderr.strip().splitlines()
    return lines[0] if lines else f"exit {returncode}"


def _reap(
    confirmed: bool,
    *,
    include_cherry: bool = False,
    prune: bool = False,
    stash_dirty: bool = False,
    discard_untracked: bool = False,
    force: bool = False,
    min_free_gb: float = DEFAULT_MIN_FREE_GB,
    allow_stale_script: bool = False,
) -> int:
    """Remove merged worktrees, unlinking every data-root link first.

    A confirmed reap refuses when any source it runs differs from ``origin/main``'s, unless
    *allow_stale_script* is set; *force* does not lift that.
    It still removes nothing while the drive has *min_free_gb* GiB free or its free
    space cannot be read, unless *force* is set.
    """
    repo = REPO_ROOT
    try:
        entries = _worktrees(repo)
    except SharedDataError as err:
        print(f"  ! {err}")
        return 1
    if len(entries) < 2:
        print("no linked worktrees")
        return 0
    if entries[0].path != repo:
        print("reap must run from the primary checkout")
        return 1
    stale, notes = _script_is_stale(repo)
    for line in notes:
        print(line)
    if stale and confirmed and not allow_stale_script:
        print("\nrefusing to reap with a stale script; --allow-stale-script reaps anyway")
        return 1
    merged_prs = _MergedPrs(repo, _gh)
    candidates, skipped = _candidates(
        repo, entries, include_cherry=include_cherry, merged_prs=merged_prs
    )
    print(f"worktree   {repo}")
    try:
        free = _free_bytes(repo)
    except OSError as err:
        print(f"  ! free space unknown ({err}); nothing removed without --force")
        short = False
        hold_reason = "free space unknown"
    else:
        print(
            f"disk       {free / GIB:.1f} GB free; reaping waits for under"
            f" {min_free_gb:g} GB (--force skips)"
        )
        short = _space_is_short(free, min_free_gb)
        hold_reason = "plenty of space"
    if merged_prs.unavailable is not None:
        print(
            f"  ! gh unavailable ({merged_prs.unavailable}); squash-merged branches are not"
            " recognised, using the ancestry and --cherry checks only"
        )
    print("candidates:")
    for candidate in candidates:
        print(_describe(candidate))
    if not candidates:
        print("  (none)")
    if skipped:
        print("skipped:")
        for line in skipped:
            print(f"  {line}")
    blocked = False
    for candidate in candidates:
        reasons = _blocked(candidate, stash_dirty=stash_dirty, discard_untracked=discard_untracked)
        if reasons:
            label = candidate.worktree.branch or "(detached)"
            print(f"  ! {label}: {'; '.join(reasons)}")
            blocked = True
    if blocked:
        print("\nrefusing to remove anything until every candidate is clean or allowed")
        return 1
    held = confirmed and not (short or force)
    if held:
        confirmed = False
    if not confirmed:
        if prune:
            _prune_leftovers(entries, confirmed=False)
            _prune_envs(confirmed=False)
            _prune_branches(repo, entries, include_cherry=include_cherry, confirmed=False)
        if held:
            print(f"\n{hold_reason}: nothing removed; --force reaps anyway")
        else:
            print("\ndry run; re-run with --yes to reap")
        return 0
    failed = 0
    reclaimed = 0
    for candidate in candidates:
        error = _reap_one(
            repo,
            candidate,
            stash_dirty=stash_dirty,
            discard_untracked=discard_untracked,
        )
        if error is not None:
            print(f"  ! {error}")
            failed += 1
            continue
        reclaimed += candidate.size
        print(f"  removed  {candidate.worktree.branch}")
    print(f"\nreaped {len(candidates) - failed} worktree(s), {reclaimed / 1_048_576:.1f} MiB")
    if prune:
        print("\npruning pool leftovers and branches without a worktree:")
        fresh = _worktrees(repo)
        leftover_dirs, leftover_bytes = _prune_leftovers(fresh, confirmed=True)
        envs = _prune_envs(confirmed=True)
        branches, kept = _prune_branches(repo, fresh, include_cherry=include_cherry, confirmed=True)
        print(
            f"  removed {branches} branch(es), {leftover_dirs} leftover dir(s) and"
            f" {envs} environment(s), {leftover_bytes / 1_048_576:.1f} MiB;"
            f" kept {kept} unmerged branch(es)"
        )
    return 1 if failed else 0
