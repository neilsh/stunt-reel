"""Which capture parity scores a film against, and the proof it is the one named.

A film has one frame capture, ``captures/<slug>/frames/``, and a new capture replaces it
(ADR 0028).  Whether that capture is the film's *reference* is not a property of the data
root: the committed ``research/parity/references.toml`` pins it by content hash (ADR 0029), so
a replaced reference is a loud mismatch in every worktree until a reviewed commit repins it.
This module reads that file and holds a snapshot of the capture for the caller, or says in one
sentence why it cannot: the file names no reference, the capture is absent on this machine, or
its content is not what the file recorded.  The hash is checked on the snapshot, which a later
swap cannot change, so a caller that reads for minutes reads the capture it validated
(ADR 0031).  Nothing here prints or chooses an exit code; the snapshot is the only write.
"""

from __future__ import annotations

import hashlib
import tomllib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stunt_reel import capture_store, parity_layout
from stunt_reel.dataroot import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "Reference",
    "ReferenceCaptureError",
    "capture_digest",
    "open_reference",
    "read_reference",
    "reference_films",
]


class ReferenceCaptureError(RuntimeError):
    """A film's reference capture cannot be used; the message names the film."""


@dataclass(frozen=True)
class Reference:
    """One ``references.toml`` entry: the film's slug and the hash its capture must have."""

    film: str
    slug: str
    sha256: str


# Not cached: a capture is replaced in place (ADR 0028), so a digest keyed by path goes stale.
def capture_digest(directory: Path) -> str:
    """SHA-256 over every file under *directory*: each relative path and that file's hash.

    The order is sorted and the separators are fixed, so the digest depends on the content
    and the names and on nothing the machine adds.
    """
    outer = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        inner = hashlib.sha256(path.read_bytes()).hexdigest()
        outer.update(f"{path.relative_to(directory).as_posix()}\0{inner}\n".encode())
    return outer.hexdigest()


def _read_document(root: Path) -> tuple[Path, dict[str, object]]:
    """The ``references.toml`` that serves *root*, and its parsed table."""
    # The pointer is a committed repository file; *root* only says where the captures are,
    # so a data root without one reads this checkout's.
    path = root / parity_layout.REFERENCES_FILE
    if not path.is_file():
        path = REPO_ROOT / parity_layout.REFERENCES_FILE
    try:
        return path, tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise ReferenceCaptureError(
            f"{path} does not exist; it names each film's reference"
        ) from err
    except tomllib.TOMLDecodeError as err:
        raise ReferenceCaptureError(f"{path} is not valid TOML: {err}") from err


def reference_films(root: Path) -> tuple[str, ...]:
    """The films the parity loop covers: *root*'s rows that pin a reference with ``sha256``."""
    _, document = _read_document(root)
    return tuple(
        name
        for name, entry in document.items()
        if isinstance(entry, dict)
        and isinstance(entry.get("film"), str)
        and isinstance(entry.get("sha256"), str)
    )


def read_reference(root: Path, film: str) -> Reference:
    """The entry for *film* in *root*'s ``references.toml``."""
    name = film.lower()
    path, document = _read_document(root)
    entry = document.get(name)
    if (
        not isinstance(entry, dict)
        or not isinstance(entry.get("film"), str)
        or not isinstance(entry.get("sha256"), str)
    ):
        raise ReferenceCaptureError(f"{path} names no reference capture for {name} (film, sha256)")
    try:
        slug = parity_layout.require_slug(entry["film"])
    except ValueError as err:
        raise ReferenceCaptureError(
            f"{path}: the film entry of {name} is not a slug: {err}"
        ) from err
    return Reference(name, slug, entry["sha256"])


@contextmanager
def open_reference(root: Path, film: str) -> Iterator[Path]:
    """Hold a verified snapshot of *film*'s reference capture under *root* for the block.

    Read the capture through the yielded directory, never through the store's path: a
    ``mise run capture-ref`` may swap a new capture there while the block runs.
    """
    pointer = read_reference(root, film)
    directory = root / parity_layout.frames_path(pointer.slug)
    with ExitStack() as stack:
        try:
            held = stack.enter_context(capture_store.snapshot(directory))
        except ValueError as err:
            raise ReferenceCaptureError(
                f"the reference capture of {pointer.film} is absent on this machine "
                f"({directory}); run `mise run capture-ref` and promote it in "
                f"{parity_layout.REFERENCES_FILE.as_posix()}, or restore it"
            ) from err
        found = capture_digest(held)
        if found != pointer.sha256:
            raise ReferenceCaptureError(
                f"the capture of {pointer.film} has hash {found[:12]}, but "
                f"{parity_layout.REFERENCES_FILE.as_posix()} records {pointer.sha256[:12]}; "
                "it was replaced, so repin it in a reviewed commit or restore it"
            )
        yield held
