"""A film's one capture of each kind: find the complete one, and replace it by swap (ADR 0028).

A film has at most one frame capture, one video capture and one archive, each a directory that
:mod:`parity_layout` names (``captures/<slug>/frames``, ``video``, ``archives``). A capture is
complete once its ``meta.json`` exists, because every writer writes it last; :func:`current`
returns the directory then and ``None`` otherwise, so no reader ever scores half a capture.

A writer never writes into the capture it replaces. :func:`stage` makes a fresh sibling,
the writer fills it, and :func:`publish` swaps it into place; :func:`discard` drops a sibling
whose write failed. Two writers of one film each get their own sibling, and the last swap wins.
Nothing here decides what a capture holds or how one is made.
"""

from __future__ import annotations

import shutil
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["META_FILE", "current", "discard", "publish", "stage"]

#: The file a writer writes last; its presence is what makes a capture complete.
META_FILE = "meta.json"


def current(directory: Path) -> Path | None:
    """*directory* when it holds a complete capture, else ``None``."""
    return directory if (directory / META_FILE).is_file() else None


def stage(directory: Path) -> Path:
    """Create and return an empty sibling of *directory* for a new capture to be written into."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    staged = directory.with_name(f"{directory.name}.partial-{uuid.uuid4().hex[:8]}")
    staged.mkdir()
    return staged


def publish(staged: Path, directory: Path) -> Path:
    """Swap the complete capture *staged* into *directory*, replacing any capture there.

    A ``ValueError`` when *staged* has no ``meta.json``: an incomplete capture never replaces a
    complete one. If the second rename fails, the old capture is put back. Removing the old
    capture is best effort: once the new one is in place the publish has succeeded, and a
    locked file only leaves a ``.old-*`` sibling that no reader looks at.
    """
    if current(staged) is None:
        raise ValueError(f"{staged} has no {META_FILE}; an incomplete capture is never published")
    old = None
    if directory.exists():
        old = directory.with_name(f"{directory.name}.old-{uuid.uuid4().hex[:8]}")
        directory.rename(old)
    try:
        staged.rename(directory)
    except BaseException:
        if old is not None:
            old.rename(directory)
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)
    return directory


def discard(staged: Path) -> None:
    """Remove a staged capture that will not be published."""
    shutil.rmtree(staged, ignore_errors=True)
