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
import time
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "META_FILE",
    "check_outside",
    "check_replaceable",
    "current",
    "discard",
    "publish",
    "stage",
]

#: The file a writer writes last; its presence is what makes a capture complete.
META_FILE = "meta.json"
#: How long a publisher waits for another one's swap of the same capture before giving up.
_SWAP_WAIT_SECONDS = 30.0
#: A swap lock older than this is left by a process that died mid-swap, which takes milliseconds.
_STALE_LOCK_SECONDS = 300.0


def current(directory: Path) -> Path | None:
    """*directory* when it holds a complete capture, else ``None``."""
    return directory if (directory / META_FILE).is_file() else None


def check_replaceable(directory: Path) -> None:
    """A ``ValueError`` unless *directory* is absent or holds a complete capture.

    Anything else there (the numbered runs of the old layout, or files nobody can account for)
    is not ours to replace: a swap would delete it.
    """
    if directory.exists() and current(directory) is None:
        raise ValueError(
            f"{directory} holds no complete capture, so it is not replaced; if it holds numbered "
            "runs, run mise run migrate-captures first"
        )


def check_outside(path: Path, store: Path) -> None:
    """A ``ValueError`` when *path* lies inside the capture store *store*.

    Only a default capture fills the store (ADR 0028), so an explicit output directory, which
    any parameters may write, must be somewhere else.
    """
    if path.resolve().is_relative_to(store.resolve()):
        raise ValueError(
            f"{path} is inside the capture store {store}; --out must name a directory outside it"
        )


def stage(directory: Path) -> Path:
    """Create and return an empty sibling of *directory* for a new capture to be written into."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    staged = directory.with_name(f"{directory.name}.partial-{uuid.uuid4().hex[:8]}")
    staged.mkdir()
    return staged


def publish(staged: Path, directory: Path) -> Path:
    """Swap the complete capture *staged* into *directory*, replacing any capture there.

    A ``ValueError`` when *staged* has no ``meta.json`` (an incomplete capture never replaces a
    complete one) or when *directory* fails :func:`check_replaceable`. If the second rename
    fails, the old capture is put back. Two publishers of one capture swap one at a time, under
    a lock beside it; captures themselves still run side by side. Removing the old capture is
    best effort: once the new one is in place the publish has succeeded, and a locked file only
    leaves a ``.old-*`` sibling that no reader looks at.
    """
    if current(staged) is None:
        raise ValueError(f"{staged} has no {META_FILE}; an incomplete capture is never published")
    with _swap_lock(directory):
        check_replaceable(directory)
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


@contextmanager
def _swap_lock(directory: Path) -> Iterator[None]:
    """Hold ``<directory>.lock`` for one swap; ``mkdir`` is the atomic claim."""
    lock = directory.with_name(f"{directory.name}.lock")
    deadline = time.monotonic() + _SWAP_WAIT_SECONDS
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                stale = time.time() - lock.stat().st_mtime > _STALE_LOCK_SECONDS
            except FileNotFoundError:
                continue
            if stale:
                lock.rmdir()
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"{lock} is held by another publish of this capture") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.rmdir()


def discard(staged: Path) -> None:
    """Remove a staged capture that will not be published."""
    shutil.rmtree(staged, ignore_errors=True)
