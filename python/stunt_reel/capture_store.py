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
import time
import uuid
from contextlib import contextmanager, suppress
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
#: How long a publisher waits for another one's swap of the same capture before giving up.
_SWAP_WAIT_SECONDS = 30.0
#: A swap lock older than this is left by a process that died mid-swap, which takes milliseconds.
_STALE_LOCK_SECONDS = 300.0
#: How many times :func:`snapshot` links a capture that a swap keeps replacing before giving up.
_SNAPSHOT_TRIES = 3
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


@contextmanager
def snapshot(directory: Path) -> Iterator[Path]:
    """Hold a copy of the complete capture in *directory* that no later swap changes.

    The copy is a sibling of hard links, so it costs no space and stays on the store's volume;
    a file system without hard links gets a real copy. A writer never changes a published
    file, only swaps the whole directory (:func:`publish`), so the linked files are the capture
    as it was when linked. If a swap lands while the links are made, the directory is no longer
    the same one and the links are made again. A ``ValueError`` when *directory* holds no
    complete capture. The copy is removed when the block ends; one a killed reader left behind
    is removed by a later snapshot of the same capture.
    """
    _remove_stale_snapshots(directory)
    for _ in range(_SNAPSHOT_TRIES):
        before = _identity(directory)
        if before is None or current(directory) is None:
            raise ValueError(f"{directory} holds no complete capture")
        held = directory.with_name(f"{directory.name}.read-{uuid.uuid4().hex[:8]}")
        with suppress(FileNotFoundError):
            _link_tree(directory, held)
        if _identity(directory) == before and current(held) is not None:
            break
        shutil.rmtree(held, ignore_errors=True)
    else:
        raise ValueError(f"{directory} was replaced {_SNAPSHOT_TRIES} times while it was linked")
    try:
        yield held
    finally:
        shutil.rmtree(held, ignore_errors=True)


def _identity(directory: Path) -> tuple[int, int] | None:
    """The file system's identity of *directory*, which a rename keeps and a swap changes."""
    try:
        info = directory.stat()
    except FileNotFoundError:
        return None
    return info.st_dev, info.st_ino


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
        except FileNotFoundError:
            raise  # a swap moved the file away: the caller links again
        except OSError:
            shutil.copy2(path, destination)


def _remove_stale_snapshots(directory: Path) -> None:
    """Remove the snapshots of *directory* that readers which died left behind."""
    if not directory.parent.is_dir():
        return
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
