"""Prepare or clean one git worktree.

``mise run init`` links the machine-wide data root into this checkout, so the
relative ``corpus/``, ``build/parity/reference/`` and ``target_bin/`` paths keep working
in every worktree, and links ``.cache`` to the primary checkout's shared tool
cache (ADR 0013).  ``mise run clean`` reports the per-worktree build outputs and
removes them only with ``--yes``; the shared cache is reported, never removed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from stunt_reel.dataroot import (
    DATA_ENV,
    LINK_TARGETS,
    REPO_ROOT,
    SharedDataError,
    cache_root,
    create_link,
    data_root,
    ensure_cache_link,
    is_link,
    is_placeholder,
    link_points_at,
    remove_link,
)

#: Per-worktree build outputs and caches that ``clean`` reports.
CLEAN_PATHS: tuple[str, ...] = ("target", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache")
CLEAN_FILES: tuple[str, ...] = (".coverage",)

REFERENCE_LINK = "build/parity/reference"


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


def _init(migrate: bool) -> int:
    root = data_root()
    source = DATA_ENV if DATA_ENV in os.environ else "derived"
    print(f"worktree   {REPO_ROOT}")
    print(f"data root  {root} ({source})")
    if migrate:
        for shared, relative in LINK_TARGETS:
            _migrate(relative, root / shared)

    problems = 0
    for shared, relative in LINK_TARGETS:
        target = root / shared
        link = REPO_ROOT / relative
        if not target.exists():
            # Reference captures, the oracle and target_bin are populated later, so
            # an empty shared directory is a valid starting point.  Corpus data is not:
            # say so, because every reader below that fails will name this path.
            target.mkdir(parents=True, exist_ok=True)
            print(f"  ! {target} was missing; created it empty")
        if is_link(link) and link_points_at(link, target):
            print(f"  = {relative}")
            continue
        if is_link(link):
            remove_link(link)
        elif link.is_dir():
            if not is_placeholder(link):
                print(f"  ! {relative} is a directory with files; re-run with --migrate")
                problems += 1
                continue
            for entry in link.iterdir():
                entry.unlink()
            link.rmdir()
        elif link.exists():
            link.unlink()
        create_link(link, target)
        print(f"  + {relative} -> {target}")

    try:
        print(f"  {ensure_cache_link()}")
    except SharedDataError as err:
        print(f"  ! .cache: {err}")

    if problems:
        print(f"\n{problems} path(s) unresolved; see corpus/README.md for the archive layout")
        return 1
    return 0


def _clean(confirmed: bool) -> int:
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
    if cache_root().is_dir():
        print(f"  {'shared cache':<14}(shared across worktrees; never removed)")
    if not confirmed:
        print("\ndry run; re-run with --yes to remove them")
        return 0

    reference = REPO_ROOT / REFERENCE_LINK
    restore = is_link(reference)
    if restore:
        remove_link(reference)
    for path in targets:
        if path.exists() and not is_link(path):
            shutil.rmtree(path)
    for path in files:
        path.unlink(missing_ok=True)
    if restore:
        create_link(reference, data_root() / "reference")
    print("\nremoved; the shared data root is untouched")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run ``init`` or ``clean``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="link the shared data root into this checkout")
    init.add_argument(
        "--migrate",
        action="store_true",
        help="move existing in-checkout data into the shared root before linking",
    )
    clean = commands.add_parser("clean", help="report or remove per-worktree build outputs")
    clean.add_argument("--yes", action="store_true", help="actually remove them")
    args = parser.parse_args(argv)
    if args.command == "init":
        return _init(bool(args.migrate))
    return _clean(bool(args.yes))


if __name__ == "__main__":
    sys.exit(main())
