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

A row also names the game builds its reference was made with, ``makeone`` and ``playone``, each
``"unpatched"`` or ``"patch3"``, and a ``reason`` whenever either is unpatched (ADR 0029).
:func:`require_builds` is the one check that a run's build pair is the pair its film's row
names; ``play`` and the capture scripts call it before they launch the emulator.
"""

from __future__ import annotations

import hashlib
import json
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
    "BUILD_NAMES",
    "MAKEONE_BUILDS",
    "Builds",
    "Reference",
    "ReferenceCaptureError",
    "archive_makeone_build",
    "capture_digest",
    "open_reference",
    "read_builds",
    "read_reference",
    "reference_films",
    "require_builds",
]

#: The two game builds a row may name; ``patch3`` is the name :mod:`stunt_reel.tac.playone` gives
#: its layout (``game_builds`` calls the same tree ``patched``).
BUILD_NAMES: tuple[str, ...] = ("unpatched", "patch3")

#: SHA-256 of each known ``MAKEONE.EXE`` and the build it belongs to (an archive's
#: ``meta.json`` records it as ``makeone_sha256``).
MAKEONE_BUILDS: dict[str, str] = {
    "2963e0889851287f4d4bfe3fbfb96542e61058ff4511b9783f4d289913e0fc9f": "unpatched",
    "426111d9a42f12acf21cca693b283e1df2306035ad6215bb94ac163aebe67bb6": "patch3",
}


class ReferenceCaptureError(RuntimeError):
    """A film's reference capture cannot be used; the message names the film."""


@dataclass(frozen=True)
class Builds:
    """The game builds a ``references.toml`` row names for its film (ADR 0029)."""

    makeone: str
    playone: str
    reason: str = ""


@dataclass(frozen=True)
class Reference:
    """One ``references.toml`` entry: the film's slug, the hash its capture must have, builds."""

    film: str
    slug: str
    sha256: str
    builds: Builds


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


def _builds(path: Path, name: str, entry: dict[str, object]) -> Builds:
    """The builds row *name* of *path* names; an omitted one is patch3 and an unknown one is an error."""
    found: dict[str, str] = {}
    for field in ("makeone", "playone"):
        value = entry.get(field, "patch3")  # an omitted build is patch3 (ADR 0029)
        if not isinstance(value, str) or value not in BUILD_NAMES:
            raise ReferenceCaptureError(
                f"{path}: the row [{name}] names {field} build {value!r}, "
                f"which is none of {', '.join(BUILD_NAMES)}"
            )
        found[field] = value
    reason = entry.get("reason", "")
    if not isinstance(reason, str):
        raise ReferenceCaptureError(f"{path}: the reason of [{name}] is not a string")
    if "unpatched" in found.values() and not reason.strip():
        raise ReferenceCaptureError(
            f"{path}: the row [{name}] uses an unpatched build, so it needs a reason"
        )
    return Builds(found["makeone"], found["playone"], reason)


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
    return Reference(name, slug, entry["sha256"], _builds(path, name, entry))


def read_builds(root: Path, slug: str) -> tuple[str, Builds] | None:
    """The row of *root*'s ``references.toml`` for the film in directory *slug*, with its builds.

    ``None`` when no row names the film: a film with no row has no pair to check against.
    A row that does name it must name valid builds.
    """
    path, document = _read_document(root)
    for name, entry in document.items():
        if isinstance(entry, dict) and entry.get("film") == slug:
            return name, _builds(path, name, entry)
    return None


def archive_makeone_build(archive: Path) -> str | None:
    """The build of the ``MAKEONE`` that wrote *archive*, from the ``meta.json`` beside it.

    ``None`` for an archive with no such record (a shipped ``.ALL``) or an unknown hash.
    """
    try:
        meta = json.loads((archive.parent / capture_store.META_FILE).read_text("utf-8"))
        return MAKEONE_BUILDS.get(str(meta.get("makeone_sha256", "")))
    except OSError, ValueError, AttributeError:
        return None


def require_builds(
    root: Path, slug: str, *, playone: str | None = None, makeone: str | None = None
) -> None:
    """Refuse a run whose builds differ from the ones the film's row names.

    *playone* and *makeone* are build names, or ``None`` for an executable the run does not use
    or whose build is unknown. A film with no row passes: the row is what names a pair.
    """
    found = read_builds(root, slug)
    if found is None:
        return
    name, named = found
    for field, used in (("playone", playone), ("makeone", makeone)):
        wanted = getattr(named, field)
        if used is not None and used != wanted:
            raise ReferenceCaptureError(
                f"{slug} would run on the {used} {field.upper()}, but the row [{name}] of "
                f"{parity_layout.REFERENCES_FILE.as_posix()} names {wanted}; "
                "use that build, or change the row in a reviewed commit"
            )


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
        except ValueError as err:  # the one ValueError snapshot raises: no complete capture
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
