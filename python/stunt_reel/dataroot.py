"""Locate the shared, read-only data root that every checkout borrows.

``corpus/``, the reference captures and ``target_bin/`` are gitignored, so each
checkout would otherwise need its own copy.  They live once per machine, outside
every checkout: ``<parent-of-primary>/<repo-name>.data`` unless ``STUNT_DATA_ROOT``
names another place.  ``mise run init`` links them in, and ``ensure_links`` links
them in again wherever the corpus is read, so a checkout made by any tool works on
first use rather than reading an empty placeholder.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

__all__ = [
    "DATA_ENV",
    "LINK_TARGETS",
    "REPO_ROOT",
    "WRITE_ENV",
    "SharedDataError",
    "SharedWriteError",
    "create_link",
    "data_root",
    "ensure_links",
    "is_link",
    "is_placeholder",
    "is_shared",
    "link_points_at",
    "primary_checkout",
    "remove_link",
    "require_shared_write",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ENV = "STUNT_DATA_ROOT"
WRITE_ENV = "STUNT_DATA_WRITE"
DATA_SUFFIX = ".data"

#: (directory inside the data root, path inside the checkout that borrows it)
LINK_TARGETS: tuple[tuple[str, str], ...] = (
    ("stisldem", "corpus/stisldem"),
    ("si_archive", "corpus/si_archive"),
    ("oracle", "corpus/oracle"),
    ("target_bin", "target_bin"),
    ("reference", "build/parity/reference"),
)

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class SharedWriteError(RuntimeError):
    """Raised when something would write the shared data root without opting in."""


class SharedDataError(RuntimeError):
    """Raised when a checkout cannot be linked to the shared data root."""


def primary_checkout() -> Path | None:
    """The checkout that owns ``.git``, or ``None`` outside a git checkout.

    A linked worktree carries a ``.git`` *file* naming its git directory, and that
    directory sits under ``<primary>/.git/worktrees/<name>``, so walking the parents
    until the ``.git`` directory gives the checkout the data root is named after.
    """
    dot_git = REPO_ROOT / ".git"
    if dot_git.is_dir():
        return REPO_ROOT
    if not dot_git.is_file():
        return None
    _, _, raw = dot_git.read_text(encoding="utf-8").strip().partition(":")
    if not raw.strip():
        return None
    for parent in Path(raw.strip()).resolve().parents:
        if parent.name == ".git":
            return parent.parent
    return None


@lru_cache(maxsize=1)
def data_root() -> Path:
    """The one directory holding the corpus, the reference captures and ``target_bin/``."""
    override = os.environ.get(DATA_ENV)
    if override:
        return Path(override).expanduser().resolve()
    primary = primary_checkout()
    if primary is None:
        return REPO_ROOT
    return primary.with_name(primary.name + DATA_SUFFIX)


def is_shared(path: Path) -> bool:
    """True when *path* resolves inside the shared data root, rather than this checkout."""
    root = data_root()
    if root == REPO_ROOT:
        return False
    try:
        return path.resolve().is_relative_to(root)
    except OSError:
        return False


def require_shared_write(what: str) -> None:
    """Refuse a write into the shared root unless the session opted in."""
    if os.environ.get(WRITE_ENV) == "1":
        return
    raise SharedWriteError(
        f"{what} writes the shared data root ({data_root()}); set {WRITE_ENV}=1 to "
        "allow it, and only one session may capture at a time"
    )


def is_link(path: Path) -> bool:
    """True for symbolic links and Windows junctions, which ``is_symlink`` misses."""
    if path.is_symlink():
        return True
    try:
        # lstat, not stat: stat follows the reparse point and reports the target.
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def is_placeholder(path: Path) -> bool:
    """True when git kept the directory alive with a ``.gitkeep`` and no data."""
    return all(entry.name == ".gitkeep" for entry in path.iterdir())


def link_points_at(path: Path, target: Path) -> bool:
    """True when *path* is a link that resolves to *target*."""
    try:
        return Path(os.path.realpath(path)) == target
    except OSError:
        return False


def remove_link(path: Path) -> None:
    """Remove a symbolic link or junction, never the directory it points at."""
    if path.is_symlink():
        path.unlink()
    else:
        path.rmdir()


def create_link(link: Path, target: Path) -> None:
    """Point *link* at *target*, with a junction on Windows and a symlink elsewhere."""
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
        raise SharedDataError(f"cannot link {link} -> {target}: {detail}")


def ensure_links() -> list[str]:
    """Link the shared data root into this checkout, repairing what is missing.

    Called where the corpus is read rather than where the worktree is made, so a
    checkout from any tool works on first use: a directory holding nothing but a
    ``.gitkeep`` is a worktree whose ``mise run init`` never ran, and it is replaced
    by the link.  Returns the checkout-relative paths it repaired, so a caller can
    say what it did.  Refuses, rather than moving anything, when the checkout holds
    real data: that is ``mise run init -- --migrate``'s decision, not a read's.
    """
    root = data_root()
    if root == REPO_ROOT:
        return []
    if not root.is_dir():
        raise SharedDataError(
            f"no shared data root at {root}; run `mise run init -- --migrate` in the "
            f"primary checkout, or set {DATA_ENV}"
        )
    # Refuse before touching anything: a half-repaired checkout reads as a worktree
    # whose corpus is half present, which is worse than the empty placeholder.
    for _shared, relative in LINK_TARGETS:
        link = REPO_ROOT / relative
        if link.is_dir() and not is_link(link) and not is_placeholder(link):
            raise SharedDataError(
                f"{relative} holds data of its own; run `mise run init -- --migrate` "
                "to move it into the shared root"
            )
    repaired: list[str] = []
    for shared, relative in LINK_TARGETS:
        target = root / shared
        link = REPO_ROOT / relative
        if is_link(link) and link_points_at(link, target):
            if not target.exists():
                raise SharedDataError(f"{relative} links to a missing {target}")
            continue
        if is_link(link):
            remove_link(link)
        elif link.is_dir():
            for entry in link.iterdir():
                entry.unlink()
            link.rmdir()
        elif link.exists():
            link.unlink()
        target.mkdir(parents=True, exist_ok=True)
        create_link(link, target)
        repaired.append(relative)
    return repaired
