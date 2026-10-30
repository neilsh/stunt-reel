"""Generated ``.ALL`` archives: the structural check and the add-only store.

``MAKEONE.EXE`` turns a film's ``.FLM`` into the ``.ALL`` that ``PLAYONE.EXE`` plays
(``research/makeone-exe/driving.md``). A generated archive is written once under
``captures/<slug>/archives/<run>/`` and never changed (ADR 0022), so this module only ever
adds a directory; it never rewrites one.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import struct
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from stunt_reel import parity_layout, runs

__all__ = [
    "META_FILE",
    "ArchiveError",
    "ArchiveMeta",
    "ArchiveMissing",
    "check_archive",
    "publish_archive",
    "resolve_all",
]

#: The file inside an id directory that says the directory is complete; it is written last.
META_FILE = "meta.json"


class ArchiveError(RuntimeError):
    """A generated archive that cannot be used."""


class ArchiveMissing(ArchiveError):  # noqa: N818 - the agreed interface name
    """No archive exists for the film; ``make-all`` generates one."""


@dataclass(frozen=True)
class ArchiveMeta:
    """What ``meta.json`` records about one generated archive."""

    film: str
    flm_bytes: int
    flm_sha256: str
    all_bytes: int
    all_sha256: str
    makeone_sha256: str = ""
    game_files: tuple[tuple[str, int], ...] = ()
    wall_seconds: float = 0.0
    created: str = ""

    def to_json(self) -> str:
        """The ``meta.json`` text."""
        return json.dumps(asdict(self), indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> ArchiveMeta:
        """Parse ``meta.json``; unknown keys are ignored and absent optional keys take defaults."""
        raw = json.loads(text)
        known = {field.name for field in fields(cls)}
        values = {key: value for key, value in raw.items() if key in known}
        values["game_files"] = tuple(
            (str(name), int(size)) for name, size in values.get("game_files", ())
        )
        return cls(**values)


def check_archive(data: bytes) -> int:
    """Return the chunk count of *data*, or raise ArchiveError when it is not an intact archive.

    The layout is ``research/formats/all.ksy``: a ``u16`` count ``n``, ``n`` ids, then
    ``n + 1`` ``u32`` offsets. The first offset equals the header size ``6n + 6``, offsets
    never decrease, and the last is the file size.
    """
    if len(data) < 2:
        raise ArchiveError("archive is shorter than its chunk count")
    count: int = struct.unpack_from("<H", data)[0]
    if count == 0:
        raise ArchiveError("archive declares no chunks")
    header = 6 * count + 6
    if len(data) < header:
        raise ArchiveError(f"archive is {len(data)} bytes, shorter than its {header}-byte header")
    offsets = struct.unpack_from(f"<{count + 1}I", data, 2 + 2 * count)
    if offsets[0] != header:
        raise ArchiveError(f"first offset is {offsets[0]}, expected the header size {header}")
    if any(later < earlier for earlier, later in itertools.pairwise(offsets)):
        raise ArchiveError("chunk offsets decrease")
    if offsets[-1] != len(data):
        raise ArchiveError(f"final offset is {offsets[-1]}, expected the file size {len(data)}")
    return count


def publish_archive(root: Path, slug: str, film: str, data: bytes, meta: ArchiveMeta) -> Path:
    """Write *data* as the next ``<root>/captures/<slug>/archives/<run>/<FILM>.ALL``; return the directory.

    The run number is claimed first as ``<run>.lock``, which also keeps another publisher from
    choosing it. The files go to a ``<run>.partial`` sibling, ``meta.json`` last, and the
    sibling is renamed into place, so a reader never sees half an archive. The claim is
    released in every case; a run that dies leaves ``.lock`` and ``.partial`` behind, which
    readers skip and which hold their number until someone deletes them.
    """
    stem = Path(film).stem
    parent = root / parity_layout.archives_root(slug)
    run = runs.claim_run(parent, ".lock")
    lock = parent / f"{run}.lock"
    try:
        target = parent / run
        partial = parent / f"{run}.partial"
        partial.mkdir()
        (partial / f"{stem.upper()}.ALL").write_bytes(data)
        (partial / META_FILE).write_text(meta.to_json(), encoding="utf-8")
        partial.rename(target)
    finally:
        lock.rmdir()
    return target


def resolve_all(flm: Path, root: Path, slug: str | None = None) -> Path:
    """Return the ``.ALL`` that goes with *flm*, or raise ArchiveMissing.

    A sibling with the film's stem wins (matched case-insensitively, so ``x.All`` beside
    ``x.flm`` counts). Otherwise the stored archive with the greatest id whose film hash
    equals *flm*'s; its bytes must still hash to the recorded ``all_sha256``, and a
    mismatch is an error naming the run, never a fall back to an older archive. *slug* names
    the film's directory; it defaults to the one :func:`parity_layout.film_slug` derives.
    """
    stem = flm.stem.lower()
    for sibling in sorted(flm.parent.iterdir()):
        if sibling.is_file() and sibling.suffix.lower() == ".all" and sibling.stem.lower() == stem:
            return sibling
    digest = hashlib.sha256(flm.read_bytes()).hexdigest()
    parent = root / parity_layout.archives_root(slug or parity_layout.film_slug(flm.resolve()))
    for number in reversed(runs.run_numbers(parent)):
        directory = parent / parity_layout.run_id(number)
        meta_file = directory / META_FILE
        if not meta_file.is_file():
            continue
        try:
            meta = ArchiveMeta.from_json(meta_file.read_text(encoding="utf-8"))
        except (ValueError, TypeError, AttributeError, OSError) as exc:
            raise ArchiveError(
                f"stored archive {directory.name} has an unreadable meta.json: {exc}"
            ) from exc
        if meta.flm_sha256 != digest:
            continue
        archive = directory / f"{flm.stem.upper()}.ALL"
        if (
            not archive.is_file()
            or hashlib.sha256(archive.read_bytes()).hexdigest() != meta.all_sha256
        ):
            raise ArchiveError(
                f"stored archive {directory.name} no longer matches its meta.json; "
                f"delete {directory} and rerun make-all"
            )
        return archive
    raise ArchiveMissing(f"no .ALL for {flm}; run: mise run make-all -- --film {flm}")
