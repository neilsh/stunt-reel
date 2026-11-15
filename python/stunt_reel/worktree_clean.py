"""``clean``: report a worktree's build outputs, and remove or rotate them only on request.

The shared cache is reported, never removed. ``--parity`` narrows the command to the parity render
trees, the one build output big enough to rotate (``parity_layout.RENDER_ROOTS``).
"""

from __future__ import annotations

import os
import shutil
import stat
import time
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import parity_layout
from stunt_reel.dataroot import (
    REPO_ROOT,
    VENV_DIRNAME,
    cache_root,
    env_target,
    is_link,
    remove_link,
)

if TYPE_CHECKING:
    from collections.abc import Callable


#: Per-worktree build outputs and caches that ``clean`` reports.
CLEAN_PATHS: tuple[str, ...] = ("target", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache")
CLEAN_FILES: tuple[str, ...] = (".coverage",)


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
