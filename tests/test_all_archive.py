"""Generated ``.ALL`` archives: the structural check and the add-only publish."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from archive_helpers import build_all
from stunt_reel import parity_layout
from stunt_reel.all_archive import (
    ArchiveError,
    ArchiveMeta,
    ArchiveTaken,
    check_archive,
    publish_archive,
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
