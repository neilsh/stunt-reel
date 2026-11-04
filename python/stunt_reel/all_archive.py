"""Generated ``.ALL`` archives: the structural check and the film's one stored archive.

``MAKEONE.EXE`` turns a film's ``.FLM`` into the ``.ALL`` that ``PLAYONE.EXE`` plays
(``research/makeone-exe/driving.md``). A film has one generated archive, in
``captures/<slug>/archives/``, filed beside its captures under the same rule (ADR 0028): a new
archive is written beside the old one and swapped in by :mod:`capture_store`. A film with a
committed manifest has its archive rebuilt from the game files instead (ADR 0032).
"""

from __future__ import annotations

import itertools
import json
import struct
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from stunt_reel import capture_store, dataroot, link, parity_layout
from stunt_reel.hashing import file_sha256

__all__ = [
    "META_FILE",
    "ArchiveError",
    "ArchiveMeta",
    "ArchiveMissing",
    "LinkBuild",
    "check_archive",
    "link_build_in",
    "no_link",
    "publish_archive",
    "resolve_all",
]

#: The file inside an archive directory that says it is complete; it is written last.
META_FILE = capture_store.META_FILE

#: Rebuilds a film's archive: ``(manifest, game tree, output)``; raises :class:`link.LinkError`.
LinkBuild = Callable[[Path, Path, Path], None]


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


def publish_archive(root: Path, data: bytes, meta: ArchiveMeta, *, slug: str, film: str) -> Path:
    """Write *data* as ``<root>/captures/<slug>/archives/<FILM>.ALL`` in the data root *root*.

    It replaces the old archive.

    The files go to a staged sibling, ``meta.json`` last, and the sibling is swapped into place,
    so a reader never sees half an archive. A failed write removes the sibling and leaves the
    old archive where it was.
    """
    target = root / parity_layout.archive_path(slug)
    staged = capture_store.stage(target)
    try:
        (staged / parity_layout.all_name(film)).write_bytes(data)
        (staged / META_FILE).write_text(meta.to_json(), encoding="utf-8")
        return capture_store.publish(staged, target)
    except BaseException:
        capture_store.discard(staged)
        raise


def link_build_in(root: Path, *, build: bool = True) -> LinkBuild:
    """``stuntreel link build``, run in the checkout *root*; the default :data:`LinkBuild`.

    With *build* it first builds the release binary, for a caller that has not. A caller that
    builds it itself, or was told not to (``--no-build``), passes ``build=False``.
    """

    def run(manifest: Path, game: Path, out: Path) -> None:
        if build:
            link.ensure_binary()
        link.build_archive(manifest, game, out, cwd=root)

    return run


def no_link(_manifest: Path, _game: Path, _out: Path) -> None:
    """A :data:`LinkBuild` that builds nothing: a preflight checks a manifest without ``link``."""


def _from_manifest(flm: Path, root: Path, slug: str, link_build: LinkBuild) -> Path | None:
    """The archive rebuilt from the film's manifest, or None when it has no matching one."""
    manifest = root / parity_layout.manifest_path(slug)
    if not manifest.is_file():
        return None
    try:
        record = tomllib.loads(manifest.read_text(encoding="utf-8"))
        fields = record["flm_sha256"], record["game_root"], record["all_sha256"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError) as exc:
        raise ArchiveError(f"manifest {manifest} is unreadable: {exc}") from exc
    match fields:
        case (str(flm_sha256), str(game_root), str(all_sha256)):
            pass
        case _:
            raise ArchiveError(
                f"manifest {manifest} is malformed: flm_sha256, game_root and all_sha256 "
                f"must be strings"
            )
    if flm_sha256 != file_sha256(flm):
        return None
    game = Path(game_root)
    if game.is_absolute() and not game.is_dir():
        raise ArchiveError(
            f"manifest {manifest} names the game tree {game}, outside the checkout, which "
            f"exists only on the machine that wrote it; record it against a tree here with: "
            f"mise run make-all -- --film {flm} --game-root <tree>"
        )
    game = root / game
    if not game.is_dir():
        raise ArchiveError(
            f"manifest {manifest} needs the game tree {game}, which is missing; "
            f"run: mise run init (it links the data root's game files into this checkout)"
        )
    out = root / parity_layout.linked_path(slug, flm.name)
    if out.is_file() and file_sha256(out) == all_sha256:
        # Already built from this manifest; rewriting it would race a reader on Windows.
        return out
    try:
        link_build(manifest, game, out)
    except link.LinkError as exc:
        raise ArchiveError(f"cannot rebuild {flm.name} from manifest {manifest}: {exc}") from exc
    return out


def resolve_all(
    flm: Path, root: Path, slug: str | None = None, *, link_build: LinkBuild | None = None
) -> Path:
    """Return the ``.ALL`` that goes with *flm*, or raise ArchiveMissing.

    A sibling with the film's stem wins (matched case-insensitively, so ``x.All`` beside
    ``x.flm`` counts). Next, the film's committed manifest (``manifests/all/<slug>.toml``,
    ADR 0032) when its ``flm_sha256`` is *flm*'s: the archive is rebuilt from the game tree it
    names into ``target/linked/<slug>/`` by *link_build*, which defaults to building the release
    binary and running ``stuntreel link build``; an earlier build that still matches the
    manifest's ``all_sha256`` is reused. A manifest that matches the film but cannot be read or built is an
    error, never a fall back. Last, the film's stored archive, when it was made from *flm*'s
    bytes; its own bytes must still hash to the recorded ``all_sha256``, and a mismatch is an
    error. *slug* names the film's directory; it defaults to the one
    :func:`parity_layout.film_slug` derives. *root* is the checkout holding the manifests and
    ``target/``; the stored archive is read from the data root (ADR 0033).
    """
    stem = flm.stem.lower()
    for sibling in sorted(flm.parent.iterdir()):
        if sibling.is_file() and sibling.suffix.lower() == ".all" and sibling.stem.lower() == stem:
            return sibling
    slug = slug or parity_layout.slug_for(flm)
    linked = _from_manifest(flm, root, slug, link_build or link_build_in(root))
    if linked is not None:
        return linked
    make = f"run: mise run make-all -- --film {flm}"
    directory = capture_store.current(dataroot.data_root() / parity_layout.archive_path(slug))
    if directory is None:
        raise ArchiveMissing(f"no .ALL for {flm}; {make}")
    try:
        meta = ArchiveMeta.from_json((directory / META_FILE).read_text(encoding="utf-8"))
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise ArchiveError(
            f"stored archive {directory} has an unreadable meta.json: {exc}"
        ) from exc
    if meta.flm_sha256 != file_sha256(flm):
        raise ArchiveMissing(f"the stored archive of {flm} was made from another .FLM; {make}")
    archive = directory / parity_layout.all_name(flm.name)
    if not archive.is_file() or file_sha256(archive) != meta.all_sha256:
        raise ArchiveError(
            f"stored archive {directory} no longer matches its meta.json; "
            f"delete it and rerun make-all"
        )
    return archive
