"""Prepare or clean one git worktree.

``mise run init`` links the machine-wide data root into this checkout, so the
relative ``corpus/`` and capture paths keep working in every
worktree, and links ``.cache`` to the primary checkout's shared tool
cache (ADR 0013).  It parks this checkout's ``.venv`` inside that cache too
(ADR 0019) and then runs ``uv sync``, so the environment is hardlinked out of the
cache instead of copied into the checkout, which is 3 s per worktree.  ``mise run
clean`` reports the per-worktree build outputs and
removes them only with ``--yes``; the shared cache is reported, never removed.
``clean -- --parity --keep N`` narrows the same command to the parity render trees,
which accumulate one directory per render and are the one build output big enough to
need selective rotation.  ``reap`` removes merged worktrees: it unlinks every link
into the data root, proves none remain, and only then lets git delete the checkout,
because git's worktree removal has recursed through Windows junctions on some builds.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from stunt_reel import parity_layout
from stunt_reel.dataroot import (
    DATA_ENV,
    LINK_TARGETS,
    REPO_ROOT,
    VENV_DIRNAME,
    LinkOutcome,
    SharedDataError,
    cache_root,
    convert_layout,
    create_link,
    data_root,
    discard_env,
    ensure_cache_link,
    ensure_links,
    ensure_venv_link,
    env_target,
    is_link,
    is_placeholder,
    orphan_envs,
    remove_link,
    shared_target,
    sweep_orphan_envs,
)

#: Per-worktree build outputs and caches that ``clean`` reports.
CLEAN_PATHS: tuple[str, ...] = ("target", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache")
CLEAN_FILES: tuple[str, ...] = (".coverage",)

#: Directories inside the primary checkout where linked worktrees live (SOP 6).
POOL_DIRS: tuple[str, ...] = (".agents/worktrees", ".claude/worktrees")


def _size(path: Path) -> int:
    """Bytes under *path*, without descending into links to the data root."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [name for name in dirnames if not is_link(Path(dirpath) / name)]
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


def _migrate(relative: str, target: Path) -> None:
    """Move an existing in-checkout directory into the data root, once."""
    link = REPO_ROOT / relative
    if is_link(link) or not link.is_dir() or is_placeholder(link):
        return
    if target.exists():
        print(f"  ! {relative}: both the checkout and {target} hold data; left alone")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(link), str(target))
    print(f"  > {relative} -> {target}")


def _uv_venv(environment: Path) -> int:
    """Seed a linked environment, which uv will not create through a link itself.

    ``uv sync`` refuses a project environment that exists but holds no interpreter,
    and the junction cannot point at a directory that does not exist yet, so the
    first init of a worktree asks ``uv venv`` for the interpreter before syncing.
    """
    if (environment / "pyvenv.cfg").is_file():
        return 0
    uv = shutil.which("uv")
    if uv is None:
        print("  ! uv is not on PATH; run this through mise")
        return 1
    result = subprocess.run(  # noqa: S603
        [uv, "venv", "--allow-existing", str(environment)],
        check=False,
    )
    return int(result.returncode)


def _uv_sync(environment: Path | None) -> int:
    """Run ``uv sync`` for this checkout, installing into *environment* when it is linked.

    The links must exist first: uv resolves its cache through ``.cache``, and an
    environment created before the link would be a copy on the checkout's own volume
    (ADR 0019).
    """
    uv = shutil.which("uv")
    if uv is None:
        print("  ! uv is not on PATH; run this through mise")
        return 1
    child = dict(os.environ)
    if environment is not None:
        child["UV_PROJECT_ENVIRONMENT"] = str(environment)
    print("  uv sync --locked --all-groups")
    result = subprocess.run(  # noqa: S603
        [uv, "sync", "--locked", "--all-groups"],
        env=child,
        check=False,
    )
    if result.returncode != 0:
        print(f"  ! uv sync failed (exit {result.returncode})")
    return int(result.returncode)


def _render_link(outcome: LinkOutcome) -> list[str]:
    """The lines ``init`` prints for one link outcome, indentation included."""
    if outcome.status == "refused":
        return [f"  ! {outcome.reason or outcome.relative}"]
    if outcome.status == "created-empty":
        return [
            f"  ! {outcome.target} was missing; created it empty",
            f"  + {outcome.relative} -> {outcome.target}",
        ]
    if outcome.status == "repaired":
        return [f"  + {outcome.relative} -> {outcome.target}"]
    return [f"  = {outcome.relative}"]


#: The committed hooks directory ``init`` points ``core.hooksPath`` at, relative to the worktree.
HOOKS_DIR = ".githooks"


def ensure_hooks_path(repo: Path) -> list[str]:
    """Point *repo*'s ``core.hooksPath`` at the committed hooks; the lines ``init`` prints.

    The setting is in the shared repository config, so one ``init`` covers every worktree,
    and the relative value resolves against whichever worktree runs the hook. A different
    value someone chose is left alone and reported. Setting it turns off the untracked hooks in
    the git directory, so any that the committed ones do not chain to are named.
    """
    current = _git(repo, "config", "--get", "core.hooksPath").stdout.strip()
    if current and current != HOOKS_DIR:
        return [f"  ! core.hooksPath is {current!r}; left alone, so {HOOKS_DIR}/ does not run"]
    lines = [f"  = core.hooksPath {HOOKS_DIR}"]
    if not current:
        result = _git(repo, "config", "core.hooksPath", HOOKS_DIR)
        if result.returncode != 0:
            return [f"  ! could not set core.hooksPath: {result.stderr.strip()}"]
        lines = [f"  + core.hooksPath -> {HOOKS_DIR}"]
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    local = Path(common) / "hooks"
    if not common or not local.is_dir():
        return lines
    hooks = repo / HOOKS_DIR
    committed = {path.name for path in hooks.iterdir()} if hooks.is_dir() else set()
    for hook in sorted(local.iterdir()):
        if hook.suffix != ".sample" and hook.is_file() and hook.name not in committed:
            lines.append(f"  ! {hook} no longer runs: core.hooksPath replaces the hooks there")
    return lines


def _init(migrate: bool) -> int:
    root = data_root()
    source = DATA_ENV if DATA_ENV in os.environ else "derived"
    print(f"worktree   {REPO_ROOT}")
    print(f"data root  {root} ({source})")
    try:
        for line in ensure_hooks_path(REPO_ROOT):
            print(line)
    except SharedDataError as err:
        print(f"  ! hooks: {err}")
    if migrate:
        if root != REPO_ROOT and root.is_dir():
            try:
                for line in convert_layout(root):
                    print(f"  > {line}")
            except SharedDataError as err:
                print(f"  ! {err}")
                return 1
        for shared, relative in LINK_TARGETS:
            _migrate(relative, root / shared)
    if root != REPO_ROOT:
        # A fresh machine has no data root yet, and provisioning it is init's job:
        # that is why ensure_links, the read path, refuses one that is missing.
        root.mkdir(parents=True, exist_ok=True)
    try:
        outcomes = ensure_links()
    except SharedDataError as err:
        print(f"  ! {err}")
        print(
            "    the target is outside this session's writable workspace; "
            "provision the worktree from a session with wider file access "
            "(see docs/harness-setup.md)",
        )
        return 1

    # The links come before the sync, so uv hardlinks its packages out of the shared
    # cache instead of copying them, and so the environment is not born in the checkout.
    venv: str | None = None
    try:
        print(f"  {ensure_cache_link()}")
        venv = ensure_venv_link()
    except (SharedDataError, OSError) as err:
        print(f"  ! .cache: {err}")
    if venv is not None:
        print(f"  {venv}")
    stale = sweep_orphan_envs()
    if stale:
        print(f"  - {len(stale)} environment(s) whose checkout is gone")
    environment = env_target(REPO_ROOT) if venv is not None else None
    if environment is not None and _uv_venv(environment):
        return 1
    code = _uv_sync(environment)
    if code:
        return code

    problems = 0
    for outcome in outcomes:
        if outcome.status == "refused":
            problems += 1
        for line in _render_link(outcome):
            print(line)

    if problems:
        print(f"\n{problems} path(s) unresolved; see corpus/README.md for the archive layout")
        return 1
    return 0


def _tree_footprint(path: Path) -> tuple[int, int]:
    """Bytes and file count under *path*, following no links."""
    total = 0
    files = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                        files += 1
        except OSError:
            continue
    return total, files


def _prune_render_trees(confirmed: bool, keep: int) -> int:
    """Report the render trees under the layout's roots, keeping the *keep* newest per root."""
    roots = [REPO_ROOT / root for root in parity_layout.RENDER_ROOTS]
    ranked: list[tuple[Path, int, int]] = []
    for root in roots:
        if not root.is_dir() or is_link(root):
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or parity_layout.is_protected_render(child.name):
                continue
            size, files = _tree_footprint(child)
            ranked.append((child, size, files))
    if not ranked:
        names = ", ".join(root.as_posix() for root in parity_layout.RENDER_ROOTS)
        print(f"no render trees under {names}")
        return 0
    ranked.sort(key=lambda item: item[0].stat().st_mtime, reverse=True)
    seen: dict[Path, int] = {}
    doomed: list[tuple[Path, int]] = []
    for child, size, files in ranked:
        index = seen.get(child.parent, 0)
        seen[child.parent] = index + 1
        age_days = int((time.time() - child.stat().st_mtime) / 86_400)
        mark = "keep" if index < keep else "prune"
        print(
            f"  {mark:<5} {child.relative_to(REPO_ROOT).as_posix():<34}"
            f"{size / 1_048_576:9.1f} MiB {files:>6} files {age_days:>3}d old"
        )
        if mark == "prune":
            doomed.append((child, size))
    freed = sum(size for _, size in doomed)
    print(f"  {'prune':<5} {freed / 1_048_576:9.1f} MiB in {len(doomed)} tree(s)")
    if not doomed:
        return 0
    if not confirmed:
        print("\ndry run; re-run with --yes to remove them")
        return 0
    for child, _ in doomed:
        shutil.rmtree(child, ignore_errors=True)
    print(f"\nremoved {len(doomed)} tree(s)")
    return 0


def _clean(confirmed: bool, parity: bool = False, keep: int = 1) -> int:
    if parity:
        return _prune_render_trees(confirmed, keep)
    targets = [REPO_ROOT / name for name in CLEAN_PATHS]
    files = [REPO_ROOT / name for name in CLEAN_FILES]
    total = 0
    for path in targets:
        if not path.exists() or is_link(path):
            continue
        size = _size(path)
        total += size
        print(f"  {path.relative_to(REPO_ROOT).as_posix():<14}{size / 1_048_576:9.1f} MiB")
    for path in files:
        if path.is_file():
            total += path.stat().st_size
            print(f"  {path.name:<14}{path.stat().st_size / 1_048_576:9.1f} MiB")
    print(f"  {'total':<14}{total / 1_048_576:9.1f} MiB")
    environment = env_target(REPO_ROOT)
    if is_link(REPO_ROOT / VENV_DIRNAME) and environment.is_dir():
        print(
            f"  {'worktree env':<14}{_size(environment) / 1_048_576:9.1f} MiB"
            " (in the shared cache; reap removes it)"
        )
    if cache_root().is_dir():
        print(f"  {'shared cache':<14}(shared across worktrees; never removed)")
    if not confirmed:
        print("\ndry run; re-run with --yes to remove them")
        return 0

    reference = REPO_ROOT / parity_layout.capture_root()
    restore = is_link(reference)
    if restore:
        remove_link(reference)
    for path in targets:
        if path.exists() and not is_link(path):
            shutil.rmtree(path)
    for path in files:
        path.unlink(missing_ok=True)
    if restore:
        create_link(reference, shared_target(parity_layout.capture_root().as_posix()))
    print("\nremoved; the shared data root is untouched")
    return 0


@dataclass(frozen=True)
class _Worktree:
    """One entry of ``git worktree list --porcelain``."""

    path: Path
    head: str
    branch: str | None


@dataclass
class _Candidate:
    """A worktree ``reap`` may remove, with the state that decides whether it may."""

    worktree: _Worktree
    merged: bool
    dirty: list[str]
    untracked: list[str]
    links: list[Path]
    size: int


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git command in *repo*; the caller decides what a failure means."""
    git = shutil.which("git")
    if git is None:
        raise SharedDataError("git is not on PATH")
    return subprocess.run(  # noqa: S603
        [git, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_worktrees(text: str) -> list[_Worktree]:
    """Parse ``git worktree list --porcelain``; the primary checkout comes first."""
    found: list[_Worktree] = []
    path: Path | None = None
    head = ""
    branch: str | None = None
    for line in [*text.splitlines(), ""]:
        if not line:
            if path is not None:
                found.append(_Worktree(path=path, head=head, branch=branch))
            path, head, branch = None, "", None
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            path = Path(value)
        elif key == "HEAD":
            head = value
        elif key == "branch":
            branch = value.removeprefix("refs/heads/")
    return found


def _worktrees(repo: Path) -> list[_Worktree]:
    """Every worktree git knows in *repo*, primary first."""
    result = _git(repo, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        raise SharedDataError(f"cannot list worktrees: {result.stderr.strip()}")
    return _parse_worktrees(result.stdout)


def _is_ancestor(repo: Path, branch: str) -> bool:
    """True when ``main`` already contains every commit of *branch*."""
    return _git(repo, "merge-base", "--is-ancestor", branch, "main").returncode == 0


def _unmerged_patch_count(repo: Path, branch: str) -> int:
    """Patches on *branch* that ``main`` does not already hold."""
    result = _git(repo, "cherry", "main", branch)
    return sum(1 for line in result.stdout.splitlines() if line.startswith("+"))


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
    repo: Path, entries: list[_Worktree], *, include_cherry: bool
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
        if not merged:
            patches = _unmerged_patch_count(repo, worktree.branch)
            if not (include_cherry and patches == 0):
                skipped.append(f"{label}: {patches} patch(es) not in main")
                continue
        candidates.append(
            _Candidate(
                worktree=worktree,
                merged=merged,
                dirty=_changed(worktree.path, untracked=False),
                untracked=_changed(worktree.path, untracked=True),
                links=_reparse_points(worktree.path),
                size=_size(worktree.path),
            )
        )
    return candidates, skipped


def _describe(candidate: _Candidate) -> str:
    """One report line for a candidate."""
    worktree = candidate.worktree
    state = "merged" if candidate.merged else "cherry"
    flags: list[str] = []
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
    if candidate.dirty and not stash_dirty:
        return f"{branch}: modified files"
    if candidate.untracked and not discard_untracked:
        return f"{branch}: untracked files"
    if candidate.dirty:
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
    remove_args = ["worktree", "remove"]
    if candidate.untracked:
        remove_args.append("--force")
    remove = _git(repo, *remove_args, str(path))
    if remove.returncode != 0:
        return f"{branch}: git worktree remove failed: {remove.stderr.strip()}"
    if branch is not None:
        delete = _git(repo, "branch", "-d" if candidate.merged else "-D", branch)
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


def _reap(
    confirmed: bool,
    *,
    include_cherry: bool = False,
    prune: bool = False,
    stash_dirty: bool = False,
    discard_untracked: bool = False,
) -> int:
    """Remove merged worktrees, unlinking every data-root link first."""
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
    candidates, skipped = _candidates(repo, entries, include_cherry=include_cherry)
    print(f"worktree   {repo}")
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
    if not confirmed:
        if prune:
            _prune_leftovers(entries, confirmed=False)
            _prune_envs(confirmed=False)
            _prune_branches(repo, entries, include_cherry=include_cherry, confirmed=False)
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


def main(argv: list[str] | None = None) -> int:
    """Run ``init``, ``clean`` or ``reap``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="link the shared data root into this checkout")
    init.add_argument(
        "--migrate",
        action="store_true",
        help="convert an old-layout shared root, then move existing in-checkout data into it before linking",
    )
    clean = commands.add_parser("clean", help="report or remove per-worktree build outputs")
    clean.add_argument("--yes", action="store_true", help="actually remove them")
    clean.add_argument(
        "--parity",
        action="store_true",
        help="only report or rotate the parity render trees under build/",
    )
    clean.add_argument("--keep", type=int, default=1, help="render trees to keep per root")
    reap = commands.add_parser(
        "reap", help="remove merged worktrees after unlinking their data-root links"
    )
    reap.add_argument("--yes", action="store_true", help="actually remove them")
    reap.add_argument(
        "--cherry",
        action="store_true",
        help="also reap worktrees whose patches main already holds without a merge",
    )
    reap.add_argument(
        "--prune",
        action="store_true",
        help="also remove unregistered pool dirs and branches left without a worktree",
    )
    reap.add_argument(
        "--stash-dirty",
        action="store_true",
        help="stash a worktree's modified files instead of refusing",
    )
    reap.add_argument(
        "--discard-untracked",
        action="store_true",
        help="delete a worktree's untracked files instead of refusing",
    )
    args = parser.parse_args(argv)
    if args.command == "init":
        return _init(bool(args.migrate))
    if args.command == "reap":
        return _reap(
            bool(args.yes),
            include_cherry=bool(args.cherry),
            prune=bool(args.prune),
            stash_dirty=bool(args.stash_dirty),
            discard_untracked=bool(args.discard_untracked),
        )
    if int(args.keep) < 0:
        parser.error("--keep must not be negative")
    return _clean(bool(args.yes), parity=bool(args.parity), keep=int(args.keep))


if __name__ == "__main__":
    sys.exit(main())
