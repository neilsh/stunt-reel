"""Prepare or clean one git worktree.

``mise run init`` links the machine-wide data root into this checkout, so the
relative ``corpus/``, ``build/parity/reference/`` and ``target_bin/`` paths keep working
in every worktree.  ``mise run clean`` reports the per-worktree build outputs and
removes them only with ``--yes``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from stunt_reel.dataroot import DATA_ENV, REPO_ROOT, data_root

#: (directory inside the data root, path inside the checkout that borrows it)
LINKS: tuple[tuple[str, str], ...] = (
    ("stisldem", "corpus/stisldem"),
    ("si_archive", "corpus/si_archive"),
    ("oracle", "corpus/oracle"),
    ("target_bin", "target_bin"),
    ("reference", "build/parity/reference"),
)

#: Per-worktree build outputs and caches that ``clean`` reports.
CLEAN_PATHS: tuple[str, ...] = ("target", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache")
CLEAN_FILES: tuple[str, ...] = (".coverage",)

REFERENCE_LINK = "build/parity/reference"
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_link(path: Path) -> bool:
    """True for symbolic links and Windows junctions, which ``is_symlink`` misses."""
    if path.is_symlink():
        return True
    try:
        # lstat, not stat: stat follows the reparse point and reports the target.
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _is_placeholder(path: Path) -> bool:
    """True when git kept the directory alive with a ``.gitkeep`` and no data."""
    return all(entry.name == ".gitkeep" for entry in path.iterdir())


def _link_points_at(path: Path, target: Path) -> bool:
    try:
        return Path(os.path.realpath(path)) == target
    except OSError:
        return False


def _remove_link(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    else:
        path.rmdir()


def _create_link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.symlink(target, link, target_is_directory=True)
        return
    # A junction needs neither elevation nor Developer Mode, unlike a symlink.
    command = [
        os.environ.get("COMSPEC", "cmd.exe"),
        "/c",
        "mklink",
        "/J",
        str(link),
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"cannot link {link} -> {target}: {detail}")


def _size(path: Path) -> int:
    """Bytes under *path*, without descending into links to the data root."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [name for name in dirnames if not _is_link(Path(dirpath) / name)]
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


def _migrate(relative: str, target: Path) -> None:
    """Move an existing in-checkout directory into the data root, once."""
    link = REPO_ROOT / relative
    if _is_link(link) or not link.is_dir() or _is_placeholder(link):
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
        for shared, relative in LINKS:
            _migrate(relative, root / shared)

    problems = 0
    for shared, relative in LINKS:
        target = root / shared
        link = REPO_ROOT / relative
        if not target.exists():
            # Reference captures, the oracle and target_bin are populated later, so
            # an empty shared directory is a valid starting point.  Corpus data is not:
            # say so, because every reader below that fails will name this path.
            target.mkdir(parents=True, exist_ok=True)
            print(f"  ! {target} was missing; created it empty")
        if _is_link(link) and _link_points_at(link, target):
            print(f"  = {relative}")
            continue
        if _is_link(link):
            _remove_link(link)
        elif link.is_dir():
            if not _is_placeholder(link):
                print(f"  ! {relative} is a directory with files; re-run with --migrate")
                problems += 1
                continue
            for entry in link.iterdir():
                entry.unlink()
            link.rmdir()
        elif link.exists():
            link.unlink()
        _create_link(link, target)
        print(f"  + {relative} -> {target}")

    if problems:
        print(f"\n{problems} path(s) unresolved; see corpus/README.md for the archive layout")
        return 1
    return 0


def _clean(confirmed: bool) -> int:
    targets = [REPO_ROOT / name for name in CLEAN_PATHS]
    files = [REPO_ROOT / name for name in CLEAN_FILES]
    total = 0
    for path in targets:
        if not path.exists() or _is_link(path):
            continue
        size = _size(path)
        total += size
        print(f"  {path.relative_to(REPO_ROOT).as_posix():<14}{size / 1_048_576:9.1f} MiB")
    for path in files:
        if path.is_file():
            total += path.stat().st_size
            print(f"  {path.name:<14}{path.stat().st_size / 1_048_576:9.1f} MiB")
    print(f"  {'total':<14}{total / 1_048_576:9.1f} MiB")
    if not confirmed:
        print("\ndry run; re-run with --yes to remove them")
        return 0

    reference = REPO_ROOT / REFERENCE_LINK
    restore = _is_link(reference)
    if restore:
        _remove_link(reference)
    for path in targets:
        if path.exists() and not _is_link(path):
            shutil.rmtree(path)
    for path in files:
        path.unlink(missing_ok=True)
    if restore:
        _create_link(reference, data_root() / "reference")
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
