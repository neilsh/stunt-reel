"""Generated ``.ALL`` archives: the structural check and the add-only publish."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from archive_helpers import build_all
from stunt_reel import parity_layout
from stunt_reel.all_archive import (
    META_FILE,
    ArchiveError,
    ArchiveMeta,
    ArchiveMissing,
    ArchiveTaken,
    check_archive,
    publish_archive,
    resolve_all,
)

CHUNKS = [b"alpha", b"bb", b"c" * 9]
ID = "2026-10-29-wt-abcd1234"


def _meta(data: bytes) -> ArchiveMeta:
    return ArchiveMeta(
        film="BALLOON.FLM",
        flm_bytes=7,
        flm_sha256="f" * 64,
        all_bytes=len(data),
        all_sha256="a" * 64,
    )


def test_check_accepts_a_built_archive() -> None:
    assert check_archive(build_all(CHUNKS)) == len(CHUNKS)


def _patch_u32(data: bytes, position: int, value: int) -> bytes:
    return data[:position] + struct.pack("<I", value) + data[position + 4 :]


def _bad_archives() -> dict[str, bytes]:
    good = build_all(CHUNKS)
    n = len(CHUNKS)
    first = 2 + 2 * n
    return {
        "empty": b"",
        "zero count": b"\x00\x00",
        "truncated": good[:-1],
        "first offset off by one": _patch_u32(good, first, 6 * n + 7),
        "offsets decrease": _patch_u32(good, first + 8, 6 * n + 1),
        "sentinel is not the file size": _patch_u32(good, first + 4 * n, len(good) + 1),
    }


@pytest.mark.parametrize("name", list(_bad_archives()))
def test_check_rejects(name: str) -> None:
    with pytest.raises(ArchiveError):
        check_archive(_bad_archives()[name])


def test_meta_round_trips_and_defaults_missing_fields() -> None:
    meta = ArchiveMeta(
        film="A.FLM",
        flm_bytes=1,
        flm_sha256="x",
        all_bytes=2,
        all_sha256="y",
        game_files=(("MAKEONE.EXE", 10),),
        wall_seconds=1.5,
    )
    assert ArchiveMeta.from_json(meta.to_json()) == meta
    sparse = ArchiveMeta.from_json(
        '{"film": "A.FLM", "flm_bytes": 1, "flm_sha256": "x", "all_bytes": 2, "all_sha256": "y",'
        ' "future_field": 3}'
    )
    assert sparse.makeone_sha256 == ""
    assert sparse.game_files == ()


def test_publish_writes_meta_last_and_renames(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    target = publish_archive(tmp_path, "BALLOON.FLM", ID, data, _meta(data))
    assert target == tmp_path / parity_layout.all_path("BALLOON", ID)
    assert (target / "BALLOON.ALL").read_bytes() == data
    assert ArchiveMeta.from_json(
        (target / "meta.json").read_text(encoding="utf-8")
    ).all_bytes == len(data)
    assert not list(target.parent.glob("*.partial"))


def test_publish_refuses_an_existing_id(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    target = publish_archive(tmp_path, "BALLOON.FLM", ID, data, _meta(data))
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    with pytest.raises(ArchiveTaken):
        publish_archive(tmp_path, "BALLOON.FLM", ID, build_all([b"other"]), _meta(data))
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before


def test_a_held_publication_claim_refuses_without_touching_anything(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    target = tmp_path / parity_layout.all_path("BALLOON", ID)
    target.mkdir(parents=True)
    (target / "BALLOON.ALL").write_bytes(b"another run's archive")
    target.with_name(target.name + ".lock").mkdir()
    with pytest.raises(ArchiveTaken):
        publish_archive(tmp_path, "BALLOON.FLM", ID, data, _meta(data))
    assert (target / "BALLOON.ALL").read_bytes() == b"another run's archive"


def test_publish_releases_its_claim_on_success_and_on_failure(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    target = tmp_path / parity_layout.all_path("BALLOON", ID)
    lock = target.with_name(target.name + ".lock")
    publish_archive(tmp_path, "BALLOON.FLM", ID, data, _meta(data))
    assert not lock.exists()
    with pytest.raises(ArchiveTaken):
        publish_archive(tmp_path, "BALLOON.FLM", ID, data, _meta(data))
    assert not lock.exists()


def test_publish_clears_a_partial_without_meta(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    target = tmp_path / parity_layout.all_path("BALLOON", ID)
    target.mkdir(parents=True)
    (target / "BALLOON.ALL").write_bytes(b"half")
    partial = target.with_name(target.name + ".partial")
    partial.mkdir()
    (partial / "stale").write_bytes(b"x")
    publish_archive(tmp_path, "BALLOON.FLM", ID, data, _meta(data))
    assert (target / "BALLOON.ALL").read_bytes() == data
    assert (target / "meta.json").is_file()
    assert not partial.exists()


FLM_BYTES = b"FILM-balloon"


def _store(root: Path, capture_id: str, flm: bytes, archive: bytes) -> Path:
    meta = ArchiveMeta(
        film="BALLOON.FLM",
        flm_bytes=len(flm),
        flm_sha256=hashlib.sha256(flm).hexdigest(),
        all_bytes=len(archive),
        all_sha256=hashlib.sha256(archive).hexdigest(),
    )
    return publish_archive(root, "BALLOON.FLM", capture_id, archive, meta)


def _film(tmp_path: Path, name: str = "BALLOON.FLM") -> Path:
    directory = tmp_path / "vault"
    directory.mkdir(exist_ok=True)
    film = directory / name
    film.write_bytes(FLM_BYTES)
    return film


def test_a_sibling_wins_over_a_stored_archive(tmp_path: Path) -> None:
    film = _film(tmp_path)
    sibling = film.with_suffix(".ALL")
    sibling.write_bytes(build_all([b"sibling"]))
    _store(tmp_path, ID, FLM_BYTES, build_all([b"stored"]))
    assert resolve_all(film, tmp_path) == sibling


def test_a_sibling_is_found_whatever_its_case(tmp_path: Path) -> None:
    film = _film(tmp_path, "balloon.flm")
    sibling = film.parent / "balloon.All"
    sibling.write_bytes(build_all([b"s"]))
    assert resolve_all(film, tmp_path) == sibling


def test_a_sibling_must_match_the_stem_and_suffix_exactly(tmp_path: Path) -> None:
    film = _film(tmp_path)
    for decoy in ("BALLOON2.ALL", "BALLOON.ALL.BAK", "OTHER.ALL", "BALLOON.TKE"):
        (film.parent / decoy).write_bytes(build_all([b"decoy"]))
    exact = film.parent / "Balloon.all"
    exact.write_bytes(build_all([b"exact"]))
    assert resolve_all(film, tmp_path) == exact


def test_the_newest_stored_archive_for_the_film_hash_is_used(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _store(tmp_path, "2026-10-28-wt-aaaaaaaa", FLM_BYTES, build_all([b"old"]))
    newest = _store(tmp_path, "2026-10-30-wt-bbbbbbbb", FLM_BYTES, build_all([b"new"]))
    _store(tmp_path, "2026-11-01-wt-cccccccc", b"another film", build_all([b"other"]))
    assert resolve_all(film, tmp_path) == newest / "BALLOON.ALL"


def test_a_changed_stored_archive_is_an_error_naming_the_id(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _store(tmp_path, "2026-10-28-wt-aaaaaaaa", FLM_BYTES, build_all([b"old"]))
    newest = _store(tmp_path, "2026-10-30-wt-bbbbbbbb", FLM_BYTES, build_all([b"new"]))
    (newest / "BALLOON.ALL").write_bytes(b"tampered")
    with pytest.raises(ArchiveError, match="2026-10-30-wt-bbbbbbbb"):
        resolve_all(film, tmp_path)


def test_a_changed_stored_archive_says_how_to_recover(tmp_path: Path) -> None:
    film = _film(tmp_path)
    stored = _store(tmp_path, "2026-10-30-wt-bbbbbbbb", FLM_BYTES, build_all([b"new"]))
    (stored / "BALLOON.ALL").write_bytes(b"tampered")
    with pytest.raises(ArchiveError, match=r"delete .*2026-10-30-wt-bbbbbbbb.* and rerun"):
        resolve_all(film, tmp_path)


@pytest.mark.parametrize("text", ["not json", "[]", '{"film": "BALLOON.FLM"}'])
def test_a_malformed_meta_is_an_archive_error_naming_the_id(tmp_path: Path, text: str) -> None:
    film = _film(tmp_path)
    stored = _store(tmp_path, "2026-10-30-wt-bbbbbbbb", FLM_BYTES, build_all([b"new"]))
    (stored / META_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(ArchiveError, match="2026-10-30-wt-bbbbbbbb"):
        resolve_all(film, tmp_path)


def test_nothing_found_names_make_all(tmp_path: Path) -> None:
    film = _film(tmp_path)
    with pytest.raises(ArchiveMissing, match=r"mise run make-all -- --film"):
        resolve_all(film, tmp_path)
