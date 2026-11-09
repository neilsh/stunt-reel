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

A row may also record the film's recapture noise, ``noise_sigma``, and in
``[<film>.expected.<class>]`` the scores the film is expected to reach on each renderer class,
with the ``crates/`` tree and pins they were measured on; :func:`read_reference` checks both.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
import tomllib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from stunt_reel import capture_store, parity_layout
from stunt_reel.dataroot import REPO_ROOT, corpus_root

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

__all__ = [
    "BUILD_NAMES",
    "MAKEONE_BUILDS",
    "RENDERER_CLASSES",
    "UNKNOWN_BUILD",
    "Builds",
    "Expected",
    "Reference",
    "ReferenceCaptureError",
    "archive_makeone_build",
    "capture_digest",
    "open_reference",
    "read_builds",
    "read_pin",
    "read_reference",
    "reference_films",
    "require_builds",
]

#: The two game builds a row may name; ``patch3`` is the name :mod:`stunt_reel.tac.playone` gives
#: its layout and the name of the ``builds/`` tree.
BUILD_NAMES: tuple[str, ...] = ("unpatched", "patch3")

#: SHA-256 of each known ``MAKEONE.EXE`` and the build it belongs to (an archive's
#: ``meta.json`` records it as ``makeone_sha256``).
MAKEONE_BUILDS: dict[str, str] = {
    "2963e0889851287f4d4bfe3fbfb96542e61058ff4511b9783f4d289913e0fc9f": "unpatched",
    "426111d9a42f12acf21cca693b283e1df2306035ad6215bb94ac163aebe67bb6": "patch3",
}


#: A pinned archive hash: SHA-256 as ``file_sha256`` writes it.
_SHA256 = re.compile(r"[0-9a-f]{64}")

#: The renderer classes a row keys its expected scores by: ``gpu`` for a hardware adapter,
#: ``lavapipe`` for a CPU one.
RENDERER_CLASSES: tuple[str, ...] = ("gpu", "lavapipe")

#: A measured commit as an expected score names it: 7 to 40 lowercase hex digits.
_COMMIT = re.compile(r"[0-9a-f]{7,40}")

#: A measured ``crates/`` tree: a whole git object name, SHA-1 or SHA-256, in lowercase hex.
_TREE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

#: The fields of one ``[<film>.expected.<class>]`` table.
_EXPECTED_FIELDS = ("ssim", "iou", "crates", "sha256", "all_sha256", "commit", "adapter")

#: The hash fields of an expected table: the form each takes and how an error words it.
_HASH_FIELDS: Mapping[str, tuple[re.Pattern[str], str]] = {
    "crates": (_TREE, "a git tree hash (git rev-parse <commit>:crates)"),
    "sha256": (_SHA256, "a SHA-256 (64 lowercase hex digits)"),
    "all_sha256": (_SHA256, "a SHA-256 (64 lowercase hex digits)"),
    "commit": (_COMMIT, "a commit (7 to 40 lowercase hex digits)"),
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
class Expected:
    """The scores a film is expected to reach on one renderer class, and where they were measured.

    ``ssim`` and ``iou`` are a report's ``mean_ssim_scored`` and ``mean_iou_scored``; ``crates``
    is the git tree hash of the ``crates/`` measured, ``sha256`` and ``all_sha256`` the row's pins
    then, and ``adapter`` the name of the adapter it rendered on. ``commit``, when recorded, says
    where the measurement was made and is never compared: it may be a branch commit that a
    squash merge kept off ``main``.
    """

    ssim: float
    iou: float
    crates: str
    sha256: str
    adapter: str
    all_sha256: str | None = None
    commit: str | None = None


@dataclass(frozen=True)
class Reference:
    """One ``references.toml`` entry: the film's slug, the hash its capture must have, builds.

    ``all_sha256`` pins the archive the film plays, when the row names one (ADR 0037): parity
    renders and captures with the archive of exactly those bytes. ``expected`` holds the row's
    expected scores by renderer class, read-only and empty without any; ``noise_sigma`` is the
    recapture noise of the whole-frame SSIM, when the row names it.
    """

    film: str
    slug: str
    sha256: str
    builds: Builds
    all_sha256: str | None = None
    # A mapping proxy is not hashable, so the hash leaves it out; equality still compares it.
    expected: Mapping[str, Expected] = dataclasses.field(
        default_factory=lambda: MappingProxyType({}), hash=False
    )
    noise_sigma: float | None = None


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
    return Reference(
        name,
        slug,
        entry["sha256"],
        _builds(path, name, entry),
        _pin(path, name, entry),
        expected=_expected(path, name, entry),
        noise_sigma=_noise_sigma(path, name, entry),
    )


def _pin(path: Path, name: str, entry: dict[str, object]) -> str | None:
    """The archive pin row *name* of *path* names: 64 lowercase hex digits, or ``None``."""
    value = entry.get("all_sha256")
    if value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReferenceCaptureError(
            f"{path}: the row [{name}] names all_sha256 {value!r}, which is not a SHA-256 "
            "(64 lowercase hex digits)"
        )
    return value


def _invalid(path: Path, name: str, key: str, value: object, wanted: str) -> ReferenceCaptureError:
    """The error for row *name* of *path* whose *key* is *value* (``None``: absent), not *wanted*."""
    if value is None:
        return ReferenceCaptureError(f"{path}: the row [{name}] has no {key}; it must be {wanted}")
    return ReferenceCaptureError(
        f"{path}: the row [{name}] names {key} {value!r}, which is not {wanted}"
    )


def _number(value: object) -> float | None:
    """*value* as a float when it is a TOML number (an integer counts, a boolean does not)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _noise_sigma(path: Path, name: str, entry: dict[str, object]) -> float | None:
    """The recapture noise row *name* of *path* names: a finite positive number, or ``None``."""
    value = entry.get("noise_sigma")
    if value is None:
        return None
    number = _number(value)
    if number is None or not 0 < number < math.inf:
        raise _invalid(path, name, "noise_sigma", value, "a finite positive number")
    return number


def _expected(path: Path, name: str, entry: dict[str, object]) -> Mapping[str, Expected]:
    """The expected scores row *name* of *path* names, by renderer class; empty without any."""
    tables = entry.get("expected", {})
    if not isinstance(tables, dict):
        raise _invalid(path, name, "expected", tables, "a table of renderer classes")
    found: dict[str, Expected] = {}
    for renderer, table in tables.items():
        key = f"expected.{renderer}"
        if renderer not in RENDERER_CLASSES:
            raise ReferenceCaptureError(
                f"{path}: the row [{name}] names {key}, but the renderer classes are "
                f"{', '.join(RENDERER_CLASSES)}"
            )
        if not isinstance(table, dict):
            raise _invalid(path, name, key, table, f"a table of {', '.join(_EXPECTED_FIELDS)}")
        found[renderer] = _expected_entry(path, name, key, table)
    return MappingProxyType(found)


def _expected_entry(path: Path, name: str, key: str, table: dict[str, object]) -> Expected:
    """The ``[<film>.expected.<class>]`` table *key* of row *name* of *path*, checked."""
    unknown = sorted(table.keys() - set(_EXPECTED_FIELDS))
    if unknown:
        raise ReferenceCaptureError(
            f"{path}: the row [{name}] names {key}.{unknown[0]}, but an expected score has only "
            f"{', '.join(_EXPECTED_FIELDS)}"
        )
    scores: dict[str, float] = {}
    for score, low in (("ssim", -1.0), ("iou", 0.0)):  # SSIM runs from -1, IoU from 0
        value = table.get(score)
        number = _number(value)
        if number is None or not low <= number <= 1:
            raise _invalid(path, name, f"{key}.{score}", value, f"a number from {low:g} to 1")
        scores[score] = number
    adapter = table.get("adapter")
    if not isinstance(adapter, str) or not adapter.strip():
        raise _invalid(path, name, f"{key}.adapter", adapter, "an adapter name")

    def hashed(field: str) -> str | None:
        value = table.get(field)
        pattern, wanted = _HASH_FIELDS[field]
        if value is None:
            return None
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise _invalid(path, name, f"{key}.{field}", value, wanted)
        return value

    crates, sha256 = hashed("crates"), hashed("sha256")
    if crates is None or sha256 is None:
        field = "crates" if crates is None else "sha256"
        raise _invalid(path, name, f"{key}.{field}", None, _HASH_FIELDS[field][1])
    return Expected(
        scores["ssim"],
        scores["iou"],
        crates,
        sha256,
        adapter,
        all_sha256=hashed("all_sha256"),
        commit=hashed("commit"),
    )


def read_pin(root: Path, slug: str) -> str | None:
    """The archive pin of the row for the film in directory *slug*, or ``None`` without one."""
    path, document = _read_document(root)
    for name, entry in document.items():
        if isinstance(entry, dict) and entry.get("film") == slug:
            return _pin(path, name, entry)
    return None


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


#: Stands for a ``MAKEONE`` build that cannot be determined; :func:`require_builds` refuses it
#: whenever the film's row names a ``makeone`` build.
UNKNOWN_BUILD = "unknown"

#: Game trees whose shipped ``.ALL`` files the unpatched ``MAKEONE`` wrote: the demo and the
#: retail game, which ship the unpatched executables (``patch3.md`` section 1).
_UNPATCHED_TREES = ("stisldem", "stuntisl")


def _recorded_makeone(path: Path, key_file: str) -> str | None:
    """The build for the ``makeone_sha256`` in *path* (JSON or TOML by *key_file*), else None."""
    try:
        text = path.read_text("utf-8")
        record = json.loads(text) if key_file == "json" else tomllib.loads(text)
        return MAKEONE_BUILDS.get(str(record.get("makeone_sha256", "")))
    except OSError, ValueError, AttributeError:
        return None


def _manifest_archive(manifest: Path) -> str | None:
    """The ``all_sha256`` a film's manifest records, else ``None``."""
    try:
        value = tomllib.loads(manifest.read_text("utf-8")).get("all_sha256")
    except OSError, ValueError:
        return None
    return value if isinstance(value, str) else None


def _sha256_or_none(path: Path) -> str | None:
    """The SHA-256 of *path*'s bytes, or ``None`` when it cannot be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def archive_makeone_build(root: Path, slug: str, archive: Path) -> str:
    """The build of the ``MAKEONE`` that wrote *archive* for film *slug*, else ``UNKNOWN_BUILD``.

    Known archives: a stored one (the ``meta.json`` beside it records ``makeone_sha256``); one
    rebuilt under ``target/linked/<slug>``, or any copy hashing to the manifest's ``all_sha256``
    (a pinned sibling, ADR 0037), both recorded by ``manifests/all/<slug>.toml``; and a shipped
    ``.ALL`` in the demo's or retail game's corpus tree, written by the unpatched ``MAKEONE``.
    Any other archive, such as a community film's, is ``UNKNOWN_BUILD``.
    """
    found = _recorded_makeone(archive.parent / capture_store.META_FILE, "json")
    manifest = root / parity_layout.manifest_path(slug)
    if found is None and archive.parent == (root / parity_layout.linked_path(slug, "x")).parent:
        found = _recorded_makeone(manifest, "toml")
    if found is None:
        pinned = _manifest_archive(manifest)
        if pinned is not None and pinned == _sha256_or_none(archive):
            found = _recorded_makeone(manifest, "toml")
    if found is None:
        shipped = corpus_root()
        if any(archive.is_relative_to(shipped / tree) for tree in _UNPATCHED_TREES):
            found = "unpatched"
    return found or UNKNOWN_BUILD


def require_builds(
    root: Path, slug: str, *, playone: str | None = None, makeone: str | None = None
) -> None:
    """Raise :class:`ReferenceCaptureError` when a run's builds differ from the film's row.

    *playone* and *makeone* are build names, or ``None`` for an executable the run does not use;
    ``UNKNOWN_BUILD`` for *makeone* is refused when the row names one. Only the row for the
    directory *slug* is checked: a film with no row, or run under another ``--name`` slug,
    passes unchecked until #140's fallback chooses its builds.
    """
    found = read_builds(root, slug)
    if found is None:
        return
    name, named = found
    if makeone == UNKNOWN_BUILD:
        raise ReferenceCaptureError(
            f"the MAKEONE build of the {slug} archive cannot be determined, but the row [{name}] "
            f"of {parity_layout.REFERENCES_FILE.as_posix()} names {named.makeone}; "
            "make the archive with make-all, or restore its manifest"
        )
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
