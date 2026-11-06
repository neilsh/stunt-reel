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
import threading
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
    "write_archive",
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
    #: False when MAKEONE wrote the archive but never returned to DOS and was killed.
    returned_to_dos: bool = True

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


def write_archive(directory: Path, data: bytes, meta: ArchiveMeta, *, film: str) -> None:
    """Write *data* as ``<FILM>.ALL`` into *directory*, ``meta.json`` last (the capture is complete then)."""
    (directory / parity_layout.all_name(film)).write_bytes(data)
    (directory / META_FILE).write_text(meta.to_json(), encoding="utf-8")


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
        write_archive(staged, data, meta, film=film)
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


#: One lock per linked archive, so the threads of one parity run build each archive once while
#: different archives build at the same time.
_LINK_LOCKS: dict[Path, threading.Lock] = {}
_LINK_LOCKS_GUARD = threading.Lock()


def _link_lock(out: Path) -> threading.Lock:
    """The lock that serializes the check-and-build of the linked archive *out*."""
    with _LINK_LOCKS_GUARD:
        return _LINK_LOCKS.setdefault(out.resolve(), threading.Lock())


def _from_manifest(
    flm: Path, root: Path, slug: str, link_build: LinkBuild, *, want: str | None = None
) -> Path | None:
    """The archive rebuilt from the film's manifest, or None when it has no matching one.

    With *want*, a manifest whose ``all_sha256`` is not *want* does not match, and is not built.
    """
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
    if flm_sha256 != file_sha256(flm) or (want is not None and all_sha256 != want):
        return None
    game = Path(game_root)
    if game.is_absolute() and not game.is_dir():
        raise ArchiveError(
            f"manifest {manifest} names the game tree {game}, outside the checkout, which "
            f"exists only on the machine that wrote it; record it against a tree here with: "
            f"mise run make-all -- --film {flm} --game-root <tree>"
        )
    # A corpus/... tree is the data root's (ADR 0036); any other relative tree is the checkout's.
    game = dataroot.resolve_data_path(game)
    if not game.is_absolute():
        game = root / game
    if not game.is_dir():
        raise ArchiveError(
            f"manifest {manifest} needs the game tree {game}, which is missing; "
            f"check the data root ({dataroot.DATA_ENV}, or <primary checkout>.data), or the primary "
            "checkout's corpus/ when the data root has none"
        )
    out = root / parity_layout.linked_path(slug, flm.name)
    # Parallel renders resolve the same film at once; one builds, the rest find its archive.
    with _link_lock(out):
        if out.is_file() and file_sha256(out) == all_sha256:
            # Already built from this manifest; rewriting it would race a reader on Windows.
            return out
        try:
            link_build(manifest, game, out)
        except link.LinkError as exc:
            raise ArchiveError(
                f"cannot rebuild {flm.name} from manifest {manifest}: {exc}"
            ) from exc
    return out


def resolve_all(
    flm: Path,
    root: Path,
    slug: str | None = None,
    *,
    link_build: LinkBuild | None = None,
    pinned: str | None = None,
    data: Path | None = None,
) -> Path:
    """Return the ``.ALL`` that goes with *flm*, or raise ArchiveMissing.

    With *pinned*, the SHA-256 a ``references.toml`` row pins (ADR 0037), the archive is the
    first of these whose bytes hash to it: the sibling, the manifest rebuild, the stored archive,
    then a sibling of any copy of the film in the corpus of *data*, the data root the caller
    reads (the configured one by default). If none does, :class:`ArchiveError` names the
    pin. The order below, and its errors, hold for each candidate the pin can name.

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
    ``target/``; the stored archive is read from the data root (ADR 0036).
    """
    sibling = _sibling(flm)
    if sibling is not None and (pinned is None or file_sha256(sibling) == pinned):
        return sibling
    slug = slug or parity_layout.slug_for(flm)
    linked = _from_manifest(flm, root, slug, link_build or link_build_in(root), want=pinned)
    if linked is not None:
        return linked
    make = f"run: mise run make-all -- --film {flm}"
    stored = _stored(slug)
    if pinned is not None:
        if (
            stored is not None
            and stored[1].all_sha256 == pinned
            and stored[1].flm_sha256 == file_sha256(flm)
        ):
            return _checked(flm, *stored)
        copy = _corpus_copy(flm, pinned, data or dataroot.data_root())
        if copy is not None:
            return copy
        raise ArchiveError(
            f"no archive of {flm.name} hashes to the pinned all_sha256 {pinned}; {make} "
            "and repin, or restore the archive the row names"
        )
    if stored is None:
        raise ArchiveMissing(f"no .ALL for {flm}; {make}")
    if stored[1].flm_sha256 != file_sha256(flm):
        raise ArchiveMissing(f"the stored archive of {flm} was made from another .FLM; {make}")
    return _checked(flm, *stored)


def _sibling(flm: Path) -> Path | None:
    """The ``.ALL`` beside *flm* with its stem, matched case-insensitively, else ``None``."""
    stem = flm.stem.lower()
    for sibling in sorted(flm.parent.iterdir()):
        if sibling.is_file() and sibling.suffix.lower() == ".all" and sibling.stem.lower() == stem:
            return sibling
    return None


def _stored(slug: str) -> tuple[Path, ArchiveMeta] | None:
    """The film directory's stored archive and its meta, or ``None`` when it has none.

    The meta may record another film's ``flm_sha256``; the caller decides what that means.
    """
    directory = capture_store.current(dataroot.data_root() / parity_layout.archive_path(slug))
    if directory is None:
        return None
    try:
        meta = ArchiveMeta.from_json((directory / META_FILE).read_text(encoding="utf-8"))
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise ArchiveError(
            f"stored archive {directory} has an unreadable meta.json: {exc}"
        ) from exc
    return directory, meta


def _checked(flm: Path, directory: Path, meta: ArchiveMeta) -> Path:
    """The stored archive, whose bytes must still hash to its meta's ``all_sha256``."""
    archive = directory / parity_layout.all_name(flm.name)
    if not archive.is_file() or file_sha256(archive) != meta.all_sha256:
        raise ArchiveError(
            f"stored archive {directory} no longer matches its meta.json; "
            f"delete it and rerun make-all"
        )
    return archive


def _corpus_copy(flm: Path, pinned: str, data: Path) -> Path | None:
    """A ``.ALL`` beside a copy of *flm* (same name, same bytes) in *data*'s corpus, hashing to *pinned*."""
    film_sha = file_sha256(flm)
    corpus = dataroot.corpus_of(data)
    for archive in sorted(corpus.rglob(f"{flm.stem}.all", case_sensitive=False)):
        film = _film_beside(archive, flm.stem)
        if film is not None and file_sha256(film) == film_sha and file_sha256(archive) == pinned:
            return archive
    return None


def _film_beside(archive: Path, stem: str) -> Path | None:
    """The ``.FLM`` named *stem* beside *archive*, matched case-insensitively, else ``None``."""
    for path in archive.parent.iterdir():
        if path.is_file() and path.suffix.lower() == ".flm" and path.stem.lower() == stem.lower():
            return path
    return None
