"""A film's one capture of each kind: find the complete one, and replace it by swap (ADR 0028).

A film has at most one frame capture, one video capture and one archive, each a directory that
:mod:`parity_layout` names (``captures/<slug>/frames``, ``video``, ``archives``). A capture is
complete once its ``meta.json`` exists, because every writer writes it last; :func:`current`
returns the directory then and ``None`` otherwise, so no reader ever scores half a capture.

A writer never writes into the capture it replaces. :func:`stage` makes a fresh sibling,
the writer fills it, and :func:`publish` swaps it into place; :func:`discard` drops a sibling
whose write failed. Two writers of one film each get their own sibling, and the last swap wins.
A reader that reads one capture for minutes holds a :func:`snapshot` instead (ADR 0031): hard
links to its files that a later swap cannot change. Nothing here decides what a capture holds or
how one is made.
"""

from __future__ import annotations

import os
import shutil
import sys
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
    "snapshot",
    "stage",
]

#: The file a writer writes last; its presence is what makes a capture complete.
META_FILE = "meta.json"
#: How long a publisher waits for the swap lock before giving up. A swap holds it for
#: milliseconds, but a snapshot on a volume without hard links holds it while it copies the
#: capture; five minutes covers the largest capture (216 MB) at under 1 MB/s.
_SWAP_WAIT_SECONDS = 300.0
#: A snapshot older than this was left by a reader that died; no scoring run holds one a day.
_STALE_SNAPSHOT_SECONDS = 86400.0


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
    a lock beside it; captures themselves still run side by side. Removing the old capture
    happens after the lock is released and is best effort: once the new one is in place the
    publish has succeeded, and a locked file only leaves a ``.old-*`` sibling no reader looks at.
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
    """Hold an OS lock on the file ``<directory>.lock`` for one swap.

    The operating system releases the lock when its holder exits, so a publisher that dies
    mid-swap leaves no stale lock to reclaim, and no pathname is ever removed to take one over.
    The file itself stays beside the capture.
    """
    lock = directory.with_name(f"{directory.name}.lock")
    deadline = time.monotonic() + _SWAP_WAIT_SECONDS
    with lock.open("a+b") as handle:
        while not _try_lock(handle.fileno()):
            if time.monotonic() > deadline:
                raise TimeoutError(f"{lock} is held by another publish of this capture")
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(handle.fileno())


if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        """Take the lock on *fd*'s first byte without waiting; ``False`` when another holds it."""
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        """Take the lock on *fd* without waiting; ``False`` when another holds it."""
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def snapshot(directory: Path) -> Iterator[Path]:
    """Hold a copy of the complete capture in *directory* that no later swap changes.

    The copy is a sibling of hard links, so it costs no space and stays on the store's volume;
    a file system without hard links gets a real copy. The links are made under the swap lock,
    so no :func:`publish` lands while they are made, and a writer never changes a published
    file, only swaps the whole directory, so the linked files stay the capture as it was. The
    lock is held for the linking only, not while the caller reads. A ``ValueError`` when
    *directory* holds no complete capture. The copy is removed when the block ends; one a
    killed reader left behind is removed by a later snapshot of the same capture.
    """
    if not directory.parent.is_dir():
        raise ValueError(f"{directory} holds no complete capture")
    held = directory.with_name(f"{directory.name}.read-{uuid.uuid4().hex[:8]}")
    with _swap_lock(directory):
        _remove_leftovers(directory)
        if current(directory) is None:
            raise ValueError(f"{directory} holds no complete capture")
        try:
            _link_tree(directory, held)
        except BaseException:
            shutil.rmtree(held, ignore_errors=True)
            raise
    try:
        yield held
    finally:
        shutil.rmtree(held, ignore_errors=True)


def _link_tree(source: Path, target: Path) -> None:
    """Make *target* a tree of hard links to every file under *source*."""
    target.mkdir()
    for path in sorted(source.rglob("*")):
        destination = target / path.relative_to(source)
        if path.is_dir():
            destination.mkdir()
            continue
        try:
            os.link(path, destination)
        except OSError:
            shutil.copy2(path, destination)


def _remove_leftovers(directory: Path) -> None:
    """Remove the old captures and day-old snapshots of *directory* that nothing removed.

    Called under the swap lock, where every ``.old-*`` is garbage: :func:`publish` only puts
    one back while it holds the lock, and it is left when a reader's open file kept its
    removal from succeeding. A ``.read-*`` older than a day is a killed reader's. A
    ``.partial-*`` belongs to a writer that may still be running, so it is left to that writer.
    """
    for old in directory.parent.glob(f"{directory.name}.old-*"):
        shutil.rmtree(old, ignore_errors=True)
    for held in directory.parent.glob(f"{directory.name}.read-*"):
        try:
            stale = time.time() - held.stat().st_mtime > _STALE_SNAPSHOT_SECONDS
        except FileNotFoundError:
            continue
        if stale:
            shutil.rmtree(held, ignore_errors=True)


def discard(staged: Path) -> None:
    """Remove a staged capture that will not be published."""
    shutil.rmtree(staged, ignore_errors=True)
