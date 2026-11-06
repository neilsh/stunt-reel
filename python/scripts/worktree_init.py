"""Prepare or clean one git worktree.

A worktree needs no provisioning (ADR 0036): code reads the data root directly, mise
names the shared caches by absolute path, and ``ensure``, a dependency of every task
that builds Rust, seeds an empty ``target/`` and sets ``core.hooksPath`` under a lock.
``mise run init`` does the same eagerly with a full report, runs ``uv sync``, and names
any link an older ``init`` left, which ``reap`` unlinks.  ``mise run
clean`` reports the per-worktree build outputs and
removes them only with ``--yes``; the shared cache is reported, never removed.
``clean -- --parity --keep N`` narrows the same command to the parity render trees,
which accumulate one directory per render and are the one build output big enough to
need selective rotation.  ``reap`` removes merged worktrees, including branches whose pull
request was squash-merged (found with ``gh``): it unlinks every link
into the data root, proves none remain, and only then lets git delete the checkout,
because git's worktree removal has recursed through Windows junctions on some builds.
The seed clones another checkout's built ``target/`` into an empty one on a ReFS volume, so
the first build compiles only the workspace crates (ADR 0030).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

from stunt_reel import parity_layout
from stunt_reel.dataroot import (
    CACHE_DIRNAME,
    DATA_ENV,
    LINK_TARGETS,
    REPO_ROOT,
    VENV_DIRNAME,
    SharedDataError,
    cache_root,
    convert_layout,
    corpus_root,
    data_root,
    discard_env,
    env_target,
    is_link,
    is_placeholder,
    orphan_envs,
    primary_checkout,
    remove_link,
    require_corpus,
    sweep_orphan_envs,
)
from stunt_reel.target_seed import SeedOutcome, exclusive, needs_seed, seed

if TYPE_CHECKING:
    from collections.abc import Callable

#: Per-worktree build outputs and caches that ``clean`` reports.
CLEAN_PATHS: tuple[str, ...] = ("target", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache")
CLEAN_FILES: tuple[str, ...] = (".coverage",)

#: Directories inside the primary checkout where linked worktrees live (AGENTS.md, Worktrees).
POOL_DIRS: tuple[str, ...] = (".agents/worktrees", ".claude/worktrees")


@dataclass(frozen=True)
class Line:
    """One line of ``init``'s report, printed as ``  <mark> <text>``.

    *mark* is ``+`` (changed), ``-`` (skipped), ``=`` (already so) or ``!`` (a problem).
    *news* marks a line ``ensure`` prints even when quiet: a change this run made, or one it
    failed to make. A standing warning, such as a hooks path someone else chose, is not news.
    """

    mark: Literal["+", "-", "=", "!"]
    text: str
    news: bool = False

    @override
    def __str__(self) -> str:
        return f"  {self.mark} {self.text}"


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


def _uv_sync() -> int:
    """Run ``uv sync`` for this checkout into its own ``.venv`` (ADR 0036)."""
    uv = shutil.which("uv")
    if uv is None:
        print("  ! uv is not on PATH; run this through mise")
        return 1
    print("  uv sync --locked --all-groups")
    result = subprocess.run(  # noqa: S603
        [uv, "sync", "--locked", "--all-groups"],
        check=False,
    )
    if result.returncode != 0:
        print(f"  ! uv sync failed (exit {result.returncode})")
    return int(result.returncode)


#: The committed hooks directory ``init`` points ``core.hooksPath`` at, relative to the worktree.
HOOKS_DIR = ".githooks"


def ensure_hooks_path(repo: Path) -> list[Line]:
    """Point *repo*'s ``core.hooksPath`` at the committed hooks; the lines ``init`` prints.

    The setting is in the shared repository config, so one ``init`` covers every worktree,
    and the relative value resolves against whichever worktree runs the hook. A different
    value someone chose is left alone and reported. Setting it turns off the untracked hooks in
    the git directory, so any that the committed ones do not chain to are named.
    """
    current = _git(repo, "config", "--get", "core.hooksPath").stdout.strip()
    if current and current != HOOKS_DIR:
        return [
            Line("!", f"core.hooksPath is {current!r}; left alone, so {HOOKS_DIR}/ does not run")
        ]
    lines = [Line("=", f"core.hooksPath {HOOKS_DIR}")]
    if not current:
        result = _git(repo, "config", "core.hooksPath", HOOKS_DIR)
        if result.returncode != 0:
            return [Line("!", f"could not set core.hooksPath: {result.stderr.strip()}", news=True)]
        lines = [Line("+", f"core.hooksPath -> {HOOKS_DIR}", news=True)]
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    local = Path(common) / "hooks"
    if not common or not local.is_dir():
        return lines
    hooks = repo / HOOKS_DIR
    committed = {path.name for path in hooks.iterdir()} if hooks.is_dir() else set()
    for hook in sorted(local.iterdir()):
        if hook.suffix != ".sample" and hook.is_file() and hook.name not in committed:
            lines.append(
                Line("!", f"{hook} no longer runs: core.hooksPath replaces the hooks there")
            )
    return lines


#: The checkout paths the old layout linked (ADR 0008, ADR 0013, ADR 0019); init reports them.
_LEGACY_LINKS: tuple[str, ...] = (
    *(relative for _, relative in LINK_TARGETS),
    CACHE_DIRNAME,
    VENV_DIRNAME,
)


def _init(migrate: bool) -> int:
    """``ensure`` with its full report, then ``uv sync``; links nothing (ADR 0036).

    ``--migrate`` still moves an in-checkout corpus into the data root, which code reads
    directly now. Links an older ``init`` made are reported and left for ``reap``, and real
    data at one of their paths is named, because nothing reads it there any more. A machine
    with no game files fails here, not at its first capture.
    """
    root = data_root()
    source = DATA_ENV if DATA_ENV in os.environ else "derived"
    print(f"worktree   {REPO_ROOT}")
    print(f"data root  {root} ({source})")
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
    _ensure(report=True)
    code = _uv_sync()
    if code:
        return code
    for relative in _LEGACY_LINKS:
        if is_link(REPO_ROOT / relative):
            print(f"  ~ {relative} is a link from the old layout; reap unlinks it")
    for relative in _stranded_data():
        print(
            f"  ! {relative} holds data the data root does not read; run mise run init -- --migrate"
        )
    try:
        require_corpus()
    except SharedDataError as err:
        print(f"  ! {err}")
        return 1
    return 0


def _stranded_data() -> list[str]:
    """The old link paths that hold real data in this checkout, which no code reads now."""
    corpus = corpus_root()
    stranded: list[str] = []
    for _, relative in LINK_TARGETS:
        path = REPO_ROOT / relative
        if is_link(path) or not path.is_dir() or is_placeholder(path):
            continue
        # The primary checkout's own corpus is read when the data root has none.
        if path.resolve().is_relative_to(corpus.resolve()):
            continue
        stranded.append(relative)
    return stranded


def _rustc_vv() -> str | None:
    """``rustc -vV``, or ``None`` when rustc is not on PATH or fails."""
    rustc = shutil.which("rustc")
    if rustc is None:
        return None
    result = subprocess.run(  # noqa: S603 - fixed argv, rustc resolved from PATH
        [rustc, "-vV"], capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def _cargo_home() -> Path:
    """The CARGO_HOME cargo tasks use: mise passes it in; run directly, the shared cache."""
    named = os.environ.get("STUNT_CARGO_HOME")
    return Path(named) if named else cache_root() / "cargo"


def _cargo_home_warning(cargo_home: Path) -> Line | None:
    """A line for a CARGO_HOME that names another cache than the primary checkout's.

    mise falls back to the checkout's own ``.cache/cargo`` where git cannot name the primary
    checkout. Cargo fingerprints that path, so every dependency builds again here and no
    donor qualifies (ADR 0030).
    """
    shared = cache_root() / "cargo"
    if os.path.normcase(os.path.normpath(cargo_home)) == os.path.normcase(os.path.normpath(shared)):
        return None
    return Line(
        "!", f"CARGO_HOME {cargo_home} is not {shared}: every dependency rebuilds here", news=True
    )


def _seed_target() -> list[Line]:
    """Seed this checkout's empty target/ from another checkout; a line saying what happened,
    and a second when the cargo home differs from the shared one."""
    cargo_home = _cargo_home()
    try:
        rustc_vv = _rustc_vv()
        if rustc_vv is None:
            outcome = SeedOutcome("skipped", "rustc not on PATH")
        else:
            outcome = seed(
                REPO_ROOT,
                checkouts=[worktree.path for worktree in _worktrees(REPO_ROOT)],
                rustc_vv=rustc_vv,
                cargo_home=cargo_home,
            )
    except Exception as error:
        outcome = SeedOutcome("failed", f"{type(error).__name__}: {error}")
    if outcome.status == "seeded":
        line = Line("+", f"target/ seeded {outcome.detail}", news=True)
    elif outcome.status == "skipped":
        line = Line("-", f"target/ not seeded: {outcome.detail}")
    else:
        line = Line("!", f"seed: {outcome.detail}", news=True)
    warning = _cargo_home_warning(cargo_home)
    return [line] if warning is None else [line, warning]


#: The lock file under target/ that orders concurrent ``ensure`` and ``seed`` runs; no seed
#: copies it.
ENSURE_LOCK = ".ensure.lock"

#: The file under target/ saying ``ensure`` has checked ``core.hooksPath`` for this target/, so a
#: later run costs a few stats and no git; ``cargo clean`` or ``clean`` removes it with target/.
HOOKS_CHECKED = ".hooks-checked"

#: The tag that tells backup and indexing tools a directory is a cache (bford.info/cachedir).
#: Cargo writes it only into a target/ it creates, and ``ensure`` creates target/ first, so
#: ``ensure`` writes it into any target/ that lacks it.
CACHEDIR_TAG = (
    "Signature: 8a477f597d28d172789f06886806bc55\n"
    "# This file is a cache directory tag created by stunt-reel's ensure task.\n"
    "# For information about cache directory tags see https://bford.info/cachedir/\n"
)


def _ensure(*, report: bool = False) -> int:
    """Seed an empty target/ and set ``core.hooksPath``; quiet when neither needed doing.

    Every task that builds Rust depends on this (ADR 0036), so it is the step a new worktree
    used to need ``init`` for; *report* prints every line, as ``init`` does. A failed seed, a
    git that will not run or a lock held past its timeout is a slower first build or an unset
    hooks path, not a reason to stop the task, so it returns 0 whatever happened.
    """
    target = REPO_ROOT / "target"
    try:
        # The gate's cargo lanes run this at once, so another may make target/ or the tag first.
        target.mkdir(parents=True, exist_ok=True)
        _tag_cache(target)
        # The first holder seeds; the others wait, then find target/ built.
        with exclusive(target / ENSURE_LOCK):
            lines = _hooks(target, report=report)
            if needs_seed(target):
                seeded = _seed_target()
                lines += seeded if report else [line for line in seeded if line.news]
            elif report:
                lines.append(Line("=", "target/ already built"))
    except OSError as err:
        # TimeoutError is an OSError: a stuck holder, as much as a lock this volume refuses.
        lines = [
            Line("!", f"ensure: {err}; target/ not seeded, core.hooksPath not checked", news=True)
        ]
    for line in lines:
        print(line)
    return 0


def _tag_cache(target: Path) -> None:
    """Write ``CACHEDIR.TAG`` into *target* unless it has one; a concurrent writer may win."""
    tag = target / "CACHEDIR.TAG"
    if tag.exists():
        return
    try:
        with tag.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(CACHEDIR_TAG)
    except FileExistsError:
        pass


def _hooks(target: Path, *, report: bool) -> list[Line]:
    """``ensure_hooks_path``'s lines worth printing; none outside a git checkout.

    The shared setting rarely changes, so a quiet run checks it once per *target*: the stamp
    :data:`HOOKS_CHECKED` there skips git until target/ goes. A failed check leaves no stamp.
    """
    stamp = target / HOOKS_CHECKED
    if (not report and stamp.exists()) or primary_checkout() is None:
        return []
    try:
        hooks = ensure_hooks_path(REPO_ROOT)
    except (SharedDataError, OSError) as err:
        return [Line("!", f"hooks: {err}", news=True)]
    if not any(line.news and line.mark == "!" for line in hooks):
        stamp.touch()
    # Only a hooks path this call set, or failed to set, is news; the rest is init's report.
    return hooks if report or any(line.news for line in hooks) else []


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
            if (
                not child.is_dir()
                or is_link(child)
                or parity_layout.is_protected_render(child.name)
            ):
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
        _remove_tree(child)
    print(f"\nremoved {len(doomed)} tree(s)")
    return 0


def _remove_tree(path: Path) -> None:
    """Delete ``path`` whole, read-only files included: git marks its objects read-only,
    so a test's scratch repository under ``.pytest_cache`` stops ``rmtree`` on Windows.
    Any other failure is raised: a link at ``path``, since ``chmod`` follows it and would
    change the target, and any POSIX failure, where a refused unlink means the parent
    directory is not writable and the file's own mode is not the cause."""

    def _clear_read_only(
        function: Callable[[str], object], name: str, error: BaseException
    ) -> None:
        if (
            os.name != "nt"
            or not isinstance(error, PermissionError)
            or function not in (os.unlink, os.rmdir)
            or is_link(Path(name))
        ):
            raise error
        Path(name).chmod(stat.S_IWRITE)
        function(name)

    shutil.rmtree(path, onexc=_clear_read_only)


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

    # An old worktree's capture link sits inside build/; unlink it first, so removing build/
    # never reaches the data root through it. Nothing reads through it any more (ADR 0036).
    reference = REPO_ROOT / parity_layout.LEGACY_CAPTURE_LINK
    if is_link(reference):
        remove_link(reference)
    for path in targets:
        if path.exists() and not is_link(path):
            _remove_tree(path)
    for path in files:
        path.unlink(missing_ok=True)
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
    #: The merged pull request that squash-landed this branch, when that is why it may go.
    pr: int | None = None


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


#: This script, as a checkout's tree names it; reap compares its copy with main's (issue #218).
SCRIPT_PATH = "python/scripts/worktree_init.py"
FETCH_TIMEOUT = 30


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
        result = subprocess.run(  # noqa: S603
            [git, "fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=FETCH_TIMEOUT,
            # Offline or signed out, git must fail rather than wait at a credential prompt.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return str(err)
    if result.returncode == 0:
        return None
    lines = result.stderr.strip().splitlines()
    return lines[0] if lines else f"exit {result.returncode}"


def _script_is_stale(repo: Path) -> tuple[bool, list[str]]:
    """Whether *repo*'s committed reap script differs from ``origin/main``'s, and what to print.

    The primary checkout runs its own copy, so a checkout left on an old branch reaps with
    rules main has since fixed (issue #218). A failed fetch compares with the last fetched
    ``origin/main``; a side that cannot be read is reported and does not count as stale.
    """
    lines: list[str] = []
    fetch_error = _fetch_main(repo)
    if fetch_error is not None:
        lines.append(
            f"  ! cannot fetch origin main ({fetch_error}); comparing with the last fetched copy"
        )
    blobs: list[str] = []
    for rev in ("HEAD", "origin/main"):
        result = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}:{SCRIPT_PATH}")
        if result.returncode != 0:
            lines.append(f"  ! {rev}:{SCRIPT_PATH} is unreadable; cannot tell if reap is current")
            return False, lines
        blobs.append(result.stdout.strip())
    ours, main = blobs
    if ours == main:
        return False, lines
    lines.append(f"  ! stale reap: HEAD:{SCRIPT_PATH} is {ours}")
    lines.append(f"    but origin/main:{SCRIPT_PATH} is {main};")
    if _git(repo, "merge-base", "--is-ancestor", "origin/main", "HEAD").returncode == 0:
        # Ahead of main, not behind it: updating would not change the copy reap runs.
        lines.append(
            "    HEAD carries a reap change main lacks; merge it first,"
            " or review it and pass --allow-stale-script to reap with it"
        )
    else:
        lines.append("    update the primary checkout to origin/main and run reap from it again")
    return True, lines


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

    A confirmed reap refuses when this checkout's copy of the script differs from
    ``origin/main``'s, unless *allow_stale_script* is set; *force* does not lift that.
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


def main(argv: list[str] | None = None) -> int:
    """Run ``init``, ``clean`` or ``reap``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="seed target/, set core.hooksPath and uv sync now, and report old links"
    )
    init.add_argument(
        "--migrate",
        action="store_true",
        help="convert an old-layout shared root, then move existing in-checkout data into it",
    )
    commands.add_parser("seed", help="clone another checkout's built target/ into an empty one")
    commands.add_parser("ensure", help="seed an empty target/ and set core.hooksPath, quietly")
    clean = commands.add_parser("clean", help="report or remove per-worktree build outputs")
    clean.add_argument("--yes", action="store_true", help="actually remove them")
    clean.add_argument(
        "--parity",
        action="store_true",
        help="only report or rotate the parity render trees under build/",
    )
    clean.add_argument("--keep", type=int, default=1, help="render trees to keep per root")
    reap = commands.add_parser(
        "reap",
        help="remove merged or squash-merged worktrees after unlinking their data-root links",
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
    reap.add_argument("--force", action="store_true", help="reap even when the drive has room")
    reap.add_argument(
        "--allow-stale-script",
        action="store_true",
        help="reap even when this checkout's worktree_init.py differs from origin/main's",
    )
    reap.add_argument(
        "--min-free-gb",
        type=float,
        default=DEFAULT_MIN_FREE_GB,
        help="reap only when the drive has under this many GB free (default %(default)g)",
    )
    args = parser.parse_args(argv)
    if args.command == "init":
        return _init(bool(args.migrate))
    if args.command == "ensure":
        return _ensure()
    if args.command == "seed":
        try:
            # The same lock as ensure: two seeds would share one staging directory.
            with exclusive(REPO_ROOT / "target" / ENSURE_LOCK):
                lines = _seed_target()
        except OSError as err:
            # TimeoutError is an OSError, as is a lock this volume refuses.
            lines = [Line("!", f"seed: {err}", news=True)]
        for line in lines:
            print(line)
        # The first line is the seed's outcome; a second only warns about the cargo home.
        return 1 if lines[0].mark == "!" else 0
    if args.command == "reap":
        if float(args.min_free_gb) < 0:
            parser.error("--min-free-gb must not be negative")
        return _reap(
            bool(args.yes),
            include_cherry=bool(args.cherry),
            prune=bool(args.prune),
            stash_dirty=bool(args.stash_dirty),
            discard_untracked=bool(args.discard_untracked),
            force=bool(args.force),
            min_free_gb=float(args.min_free_gb),
            allow_stale_script=bool(args.allow_stale_script),
        )
    if int(args.keep) < 0:
        parser.error("--keep must not be negative")
    return _clean(bool(args.yes), parity=bool(args.parity), keep=int(args.keep))


if __name__ == "__main__":
    sys.exit(main())
