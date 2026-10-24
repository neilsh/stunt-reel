"""Locate the shared, read-only data root that every checkout borrows.

``corpus/``, the reference captures and ``target_bin/`` are gitignored, so each
checkout would otherwise need its own copy.  They live once per machine, outside
every checkout: ``<parent-of-primary>/<repo-name>.data`` unless ``STUNT_DATA_ROOT``
names another place.  ``mise run init`` links them in.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

__all__ = [
    "DATA_ENV",
    "REPO_ROOT",
    "WRITE_ENV",
    "SharedWriteError",
    "data_root",
    "is_shared",
    "primary_checkout",
    "require_shared_write",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ENV = "STUNT_DATA_ROOT"
WRITE_ENV = "STUNT_DATA_WRITE"
DATA_SUFFIX = ".data"


class SharedWriteError(RuntimeError):
    """Raised when something would write the shared data root without opting in."""


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
