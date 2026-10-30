"""Which capture parity scores a film against, and the proof it is the one named.

A capture is written once into ``captures/<film>/<capture id>/`` and never changed
(ADR 0022).  Which of them is a film's *reference* is not a property of the data root: the
committed ``research/parity/references.toml`` names it by id and content hash, so promoting
a capture is a reviewed commit and two branches can score against different ones.  This
module reads that file and hands the capture directory back, or says in one sentence why it
cannot: the file names no capture, the capture is absent on this machine, or its content is
not what the file recorded.  Nothing here prints, chooses an exit code, or writes.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from stunt_reel import parity_layout

__all__ = [
    "Reference",
    "ReferenceCaptureError",
    "capture_digest",
    "read_reference",
    "reference_dir",
]


class ReferenceCaptureError(RuntimeError):
    """A film's reference capture cannot be used; the message names the id."""


@dataclass(frozen=True)
class Reference:
    """One ``references.toml`` entry: the capture id and the hash its content must have."""

    film: str
    capture_id: str
    sha256: str


# Cached by path: safe because a capture is never changed once written (ADR 0022).
@lru_cache(maxsize=32)
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


def read_reference(root: Path, film: str) -> Reference:
    """The entry for *film* in *root*'s ``references.toml``."""
    name = film.lower()
    path = root / parity_layout.REFERENCES_FILE
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise ReferenceCaptureError(
            f"{path} does not exist; it names each film's reference"
        ) from err
    except tomllib.TOMLDecodeError as err:
        raise ReferenceCaptureError(f"{path} is not valid TOML: {err}") from err
    entry = document.get(name)
    if (
        not isinstance(entry, dict)
        or not isinstance(entry.get("capture"), str)
        or not isinstance(entry.get("sha256"), str)
    ):
        raise ReferenceCaptureError(
            f"{path} names no reference capture for {name} (capture, sha256)"
        )
    return Reference(name, entry["capture"], entry["sha256"])


def reference_dir(root: Path, film: str) -> Path:
    """The verified directory of *film*'s reference capture under *root*."""
    pointer = read_reference(root, film)
    directory = root / parity_layout.capture_path(film, pointer.capture_id)
    if not (directory / "meta.json").is_file():
        raise ReferenceCaptureError(
            f"reference capture {pointer.capture_id} of {pointer.film} is absent on this "
            f"machine ({directory}); run `mise run capture-ref` and promote it in "
            f"{parity_layout.REFERENCES_FILE.as_posix()}, or restore it"
        )
    found = capture_digest(directory)
    if found != pointer.sha256:
        raise ReferenceCaptureError(
            f"reference capture {pointer.capture_id} of {pointer.film} has hash {found[:12]}, "
            f"but {parity_layout.REFERENCES_FILE.as_posix()} records {pointer.sha256[:12]}"
        )
    return directory
