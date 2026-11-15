"""``ensure`` and ``seed``: seed an empty target/, check the hooks path, and make the scratch folder.

Every task that builds Rust depends on ``ensure`` (ADR 0036), so a failed seed, a git that will not
run or a lock held past its timeout is a slower first build, never a stopped task.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from stunt_reel import parity_layout
from stunt_reel.dataroot import REPO_ROOT, SharedDataError, cache_root, primary_checkout
from stunt_reel.target_seed import SeedOutcome, exclusive, needs_seed, seed
from stunt_reel.uv import check_uv
from stunt_reel.worktree_git import Line, _worktrees, ensure_blame_ignore, ensure_hooks_path


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

#: The file under target/ saying ``ensure`` has checked ``core.hooksPath`` and
#: ``blame.ignoreRevsFile`` for this target/, so a later run costs a few stats and no git;
#: ``cargo clean`` or ``clean`` removes it with target/. Renamed when a check is added, so a
#: target/ stamped before it runs the new one.
HOOKS_CHECKED = ".git-config-checked"

#: The tag that tells backup and indexing tools a directory is a cache (bford.info/cachedir).
#: Cargo writes it only into a target/ it creates, and ``ensure`` creates target/ first, so
#: ``ensure`` writes it into any target/ that lacks it.
CACHEDIR_TAG = (
    "Signature: 8a477f597d28d172789f06886806bc55\n"
    "# This file is a cache directory tag created by stunt-reel's ensure task.\n"
    "# For information about cache directory tags see https://bford.info/cachedir/\n"
)


def _ensure(*, report: bool = False) -> int:
    """Make the scratch folder, seed an empty target/ and set ``core.hooksPath``; quiet when no
    seed or hooks change was needed.

    Every task that builds Rust depends on this (ADR 0036), so it is the step a new worktree
    used to need ``init`` for; *report* prints every line, as ``init`` does. A failed seed, a
    git that will not run or a lock held past its timeout is a slower first build or an unset
    hooks path, not a reason to stop the task, so it returns 0 whatever happened.
    """
    try:
        uv_warning = check_uv(REPO_ROOT / "mise.toml", shadowed=True)
    except OSError, KeyError, ValueError:
        # The gate needs the pin; a checkout without a readable one still ensures quietly.
        uv_warning = None
    if uv_warning is not None:
        print(f"  ! {uv_warning}")
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
    scratch = parity_layout.scratch_root()
    try:
        # Agents write bodies, logs and scripts here; a shell redirect does not make the folder.
        (REPO_ROOT / scratch).mkdir(parents=True, exist_ok=True)
    except OSError as err:
        lines.append(Line("!", f"ensure: {err}; {scratch.as_posix()}/ not made", news=True))
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
    """``ensure_hooks_path`` and ``ensure_blame_ignore``'s lines worth printing; none outside git.

    The shared setting rarely changes, so a quiet run checks it once per *target*: the stamp
    :data:`HOOKS_CHECKED` there skips git until target/ goes. A failed check leaves no stamp.
    """
    stamp = target / HOOKS_CHECKED
    if (not report and stamp.exists()) or primary_checkout() is None:
        return []
    try:
        hooks = ensure_hooks_path(REPO_ROOT) + ensure_blame_ignore(REPO_ROOT)
    except (SharedDataError, OSError) as err:
        return [Line("!", f"hooks: {err}", news=True)]
    if not any(line.news and line.mark == "!" for line in hooks):
        stamp.touch()
    # Only a hooks path this call set, or failed to set, is news; the rest is init's report.
    return hooks if report or any(line.news for line in hooks) else []


def _seed_command() -> int:
    """``mise run seed``: seed target/ under ensure's lock; exit 1 when the seed failed."""
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
