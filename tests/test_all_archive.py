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
    check_archive,
    publish_archive,
    resolve_all,
)


CHUNKS = [b"alpha", b"bb", b"c" * 9]


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


SLUG = "vault-balloon"


def test_publish_writes_meta_last_and_renames(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    target = publish_archive(tmp_path, SLUG, "BALLOON.FLM", data, _meta(data))
    assert target == tmp_path / parity_layout.archive_path(SLUG, "001")
    assert (target / "BALLOON.ALL").read_bytes() == data
    assert ArchiveMeta.from_json(
        (target / "meta.json").read_text(encoding="utf-8")
    ).all_bytes == len(data)
    assert sorted(p.name for p in target.parent.iterdir()) == ["001"]


def test_publish_adds_the_next_run_and_never_touches_an_earlier_one(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    first = publish_archive(tmp_path, SLUG, "BALLOON.FLM", data, _meta(data))
    before = {p.name: p.read_bytes() for p in first.iterdir()}
    second = publish_archive(tmp_path, SLUG, "BALLOON.FLM", build_all([b"other"]), _meta(data))
    assert second.name == "002"
    assert {p.name: p.read_bytes() for p in first.iterdir()} == before


def test_a_held_claim_or_partial_keeps_its_number(tmp_path: Path) -> None:
    data = build_all(CHUNKS)
    parent = tmp_path / parity_layout.archives_root(SLUG)
    (parent / "001.lock").mkdir(parents=True)
    (parent / "002.partial").mkdir()
    target = publish_archive(tmp_path, SLUG, "BALLOON.FLM", data, _meta(data))
    assert target.name == "003"
    assert (parent / "001.lock").is_dir()


def test_publish_releases_its_claim_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = build_all(CHUNKS)

    def full_disk(*_args: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", full_disk)
    with pytest.raises(OSError, match="disk full"):
        publish_archive(tmp_path, SLUG, "BALLOON.FLM", data, _meta(data))
    parent = tmp_path / parity_layout.archives_root(SLUG)
    assert not list(parent.glob("*.lock"))
    assert not (parent / "001").exists()


FLM_BYTES = b"FILM-balloon"


def _store(root: Path, flm: bytes, archive: bytes) -> Path:
    meta = ArchiveMeta(
        film="BALLOON.FLM",
        flm_bytes=len(flm),
        flm_sha256=hashlib.sha256(flm).hexdigest(),
        all_bytes=len(archive),
        all_sha256=hashlib.sha256(archive).hexdigest(),
    )
    return publish_archive(root, SLUG, "BALLOON.FLM", archive, meta)


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
    _store(tmp_path, FLM_BYTES, build_all([b"stored"]))
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
    _store(tmp_path, FLM_BYTES, build_all([b"old"]))
    newest = _store(tmp_path, FLM_BYTES, build_all([b"new"]))
    _store(tmp_path, b"another film", build_all([b"other"]))
    assert resolve_all(film, tmp_path) == newest / "BALLOON.ALL"


def test_a_changed_stored_archive_is_an_error_naming_the_id(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _store(tmp_path, FLM_BYTES, build_all([b"old"]))
    newest = _store(tmp_path, FLM_BYTES, build_all([b"new"]))
    (newest / "BALLOON.ALL").write_bytes(b"tampered")
    with pytest.raises(ArchiveError, match="002"):
        resolve_all(film, tmp_path)


def test_a_changed_stored_archive_says_how_to_recover(tmp_path: Path) -> None:
    film = _film(tmp_path)
    stored = _store(tmp_path, FLM_BYTES, build_all([b"new"]))
    (stored / "BALLOON.ALL").write_bytes(b"tampered")
    with pytest.raises(ArchiveError, match=r"delete .*001.* and rerun"):
        resolve_all(film, tmp_path)


@pytest.mark.parametrize("text", ["not json", "[]", '{"film": "BALLOON.FLM"}'])
def test_a_malformed_meta_is_an_archive_error_naming_the_id(tmp_path: Path, text: str) -> None:
    film = _film(tmp_path)
    stored = _store(tmp_path, FLM_BYTES, build_all([b"new"]))
    (stored / META_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(ArchiveError, match="001"):
        resolve_all(film, tmp_path)


def test_nothing_found_names_make_all(tmp_path: Path) -> None:
    film = _film(tmp_path)
    with pytest.raises(ArchiveMissing, match=r"mise run make-all -- --film"):
        resolve_all(film, tmp_path)
