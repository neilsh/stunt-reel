"""Offline tests for the render store in the Python parity artifact adapter (synthetic documents only)."""

from __future__ import annotations

import struct
from compression import zstd
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from artifact_helpers import (
    raw_record,
    store_record,
    write_json,
)
from render_helpers import TINY, frame_for, write_store
from stunt_reel.parity_artifacts import (
    PALETTE_BYTES,
    RENDER_DOCUMENT,
    RENDER_INDEX_FILE,
    RENDER_LAYER_FILE,
    RENDER_PALETTE_FILE,
    RENDER_PREVIEW_DIR,
    ArtifactError,
    FilmId,
    RenderRecord,
    RenderStore,
    RenderStoreWriter,
    StoreSpan,
    read_page,
    read_render,
    write_render,
    write_render_store,
)


def _store_refusal(record: RenderRecord) -> str:
    with pytest.raises(ArtifactError) as refusal:
        record.validate()
    assert refusal.value.kind == "store"
    return str(refusal.value)


def test_a_palette_index_must_name_a_stored_palette() -> None:
    record = store_record((0, 1))
    bad = replace(record, ticks=(record.ticks[0], replace(record.ticks[1], palette_index=1)))
    assert "ticks[1].palette_index 1" in _store_refusal(bad)


def test_chunks_must_follow_the_seconds_of_their_ticks() -> None:
    three = store_record((0, 1, 50))
    stray = replace(three, chunks=(replace(three.chunks[0], ticks=3),))
    assert "holds tick 50, which is not in second 0" in _store_refusal(stray)
    two = store_record((0, 50))
    descending = replace(two, chunks=(two.chunks[0], replace(two.chunks[1], second=0)))
    assert "chunks[1]: second 0" in _store_refusal(descending)
    short = replace(three, chunks=three.chunks[:1])
    assert "hold 2 ticks but the record lists 3" in _store_refusal(short)
    long = replace(two, chunks=(two.chunks[0], replace(two.chunks[1], ticks=2)))
    assert "claims 2 ticks but only 1 remain" in _store_refusal(long)
    one = store_record((0,))
    empty = replace(one, chunks=(replace(one.chunks[0], ticks=0),))
    assert "holds no ticks" in _store_refusal(empty)


def test_chunks_must_tile_both_files() -> None:
    two = store_record((0, 50))
    gap = replace(
        two,
        chunks=(
            two.chunks[0],
            replace(two.chunks[1], index=StoreSpan(offset=11, length=10)),
        ),
    )
    assert "chunks[1]: offsets 11 and 10" in _store_refusal(gap)
    overflow = replace(
        two,
        chunks=(
            replace(two.chunks[0], index=StoreSpan(offset=0, length=2**64 - 1)),
            replace(two.chunks[1], index=StoreSpan(offset=2**64 - 1, length=10)),
        ),
    )
    assert "chunks[1]: lengths run past" in _store_refusal(overflow)


def test_locate_finds_a_tick_by_chunk_and_position() -> None:
    record = store_record((3, 7, 120, 149, 150))
    assert record.locate(7) == (0, 1)
    assert record.locate(149) == (1, 1)
    assert record.locate(150) == (2, 0)
    assert record.locate(8) is None


#: Ticks 7, 9 and 40 (second 0), none in second 1, 101 and 120 (second 2).
_STORE_TICKS = (7, 9, 40, 101, 120)


def _store(directory: Path) -> RenderRecord:
    return write_store(directory, _STORE_TICKS)


def test_every_tick_round_trips_across_seconds_and_an_empty_second(tmp_path: Path) -> None:
    record = _store(tmp_path)
    assert [(chunk.second, chunk.ticks) for chunk in record.chunks] == [(0, 3), (2, 2)]
    assert record.palette_count == 2
    assert [tick.palette_index for tick in record.ticks] == [0, 0, 1, 0, 1]
    store = RenderStore(tmp_path)
    assert store.ticks() == list(_STORE_TICKS)
    for tick in (*reversed(_STORE_TICKS), *_STORE_TICKS):
        assert store.frame(tick) == frame_for(tick)
    assert store.holds(101)
    assert not store.holds(8)
    with pytest.raises(ArtifactError, match="holds no render of tick 8"):
        store.frame(8)
    assert read_render(tmp_path / RENDER_DOCUMENT) == record


def test_each_second_has_an_indexed_preview_of_its_first_tick(tmp_path: Path) -> None:
    _store(tmp_path)
    previews = sorted(path.name for path in (tmp_path / RENDER_PREVIEW_DIR).iterdir())
    assert previews == ["sec_0000.png", "sec_0002.png"]
    frame = frame_for(101)
    with Image.open(tmp_path / RENDER_PREVIEW_DIR / "sec_0002.png") as image:
        assert image.mode == "P"
        assert image.size == (TINY.width, TINY.height)
        assert image.tobytes() == frame.indices
        assert bytes(image.getpalette() or []) == frame.palette


def test_read_page_reads_a_tick_through_the_store(tmp_path: Path) -> None:
    _store(tmp_path)
    page = read_page(RenderStore(tmp_path), 9)
    frame = frame_for(9)
    assert page.indices == frame.indices
    assert page.layers == struct.unpack("<12H", frame.layers)
    assert page.geometry == TINY


def test_rewriting_a_store_withdraws_its_record_first(tmp_path: Path) -> None:
    write_store(tmp_path, _STORE_TICKS)
    with pytest.raises(ArtifactError, match="at least one tick"):
        write_render_store(tmp_path, FilmId(), TINY, [])
    assert not (tmp_path / RENDER_DOCUMENT).exists()
    with pytest.raises(ArtifactError, match="re-render"):
        RenderStore(tmp_path)


def test_a_render_without_ticks_writes_no_store(tmp_path: Path) -> None:
    writer = RenderStoreWriter(tmp_path, TINY)
    assert writer.finish() is None
    assert not (tmp_path / RENDER_INDEX_FILE).exists()
    assert not (tmp_path / RENDER_PREVIEW_DIR).exists()


def test_the_writer_refuses_bad_planes_and_unordered_ticks(tmp_path: Path) -> None:
    writer = RenderStoreWriter(tmp_path, TINY)
    frame = frame_for(3)
    with pytest.raises(ArtifactError, match="expected 12 and 24 for 4x3"):
        writer.push(3, frame.palette, frame.indices[:11], frame.layers)
    with pytest.raises(ArtifactError, match="palette holds 767 bytes"):
        writer.push(3, frame.palette[:-1], frame.indices, frame.layers)
    writer.push(3, frame.palette, frame.indices, frame.layers)
    with pytest.raises(ArtifactError, match="tick 3 does not follow tick 3"):
        writer.push(3, frame.palette, frame.indices, frame.layers)


def test_a_plane_file_of_the_wrong_size_is_refused(tmp_path: Path) -> None:
    _store(tmp_path)
    path = tmp_path / RENDER_LAYER_FILE
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ArtifactError, match="chunks end at") as refusal:
        RenderStore(tmp_path)
    assert refusal.value.path == path


def test_a_corrupt_chunk_names_its_second_and_file(tmp_path: Path) -> None:
    record = _store(tmp_path)
    span = record.chunks[1].index
    path = tmp_path / RENDER_INDEX_FILE
    data = bytearray(path.read_bytes())
    data[span.offset : span.offset + span.length] = b"\xaa" * span.length
    path.write_bytes(bytes(data))
    store = RenderStore(tmp_path)
    assert store.frame(7) == frame_for(7)
    with pytest.raises(ArtifactError, match="second 2") as refusal:
        store.frame(101)
    assert refusal.value.path == path


def test_a_chunk_of_the_wrong_decoded_length_names_its_second_and_file(tmp_path: Path) -> None:
    record = _store(tmp_path)
    path = tmp_path / RENDER_INDEX_FILE
    # Second 2 holds two 12-pixel ticks; store one byte too many.
    packed = zstd.compress(bytes(25))
    path.write_bytes(path.read_bytes()[: record.chunks[1].index.offset] + packed)
    longer = replace(record.chunks[1], index=replace(record.chunks[1].index, length=len(packed)))
    write_render(tmp_path / RENDER_DOCUMENT, replace(record, chunks=(record.chunks[0], longer)))
    store = RenderStore(tmp_path)
    assert store.frame(7) == frame_for(7)
    with pytest.raises(ArtifactError, match="second 2 decompresses to 25 bytes, expected 24") as (
        refusal
    ):
        store.frame(101)
    assert refusal.value.path == path


def test_palettes_of_the_wrong_length_are_refused(tmp_path: Path) -> None:
    _store(tmp_path)
    for count in (1, 3):
        (tmp_path / RENDER_PALETTE_FILE).write_bytes(zstd.compress(bytes(count * PALETTE_BYTES)))
        with pytest.raises(ArtifactError, match="expected 1536 for 2 palettes"):
            RenderStore(tmp_path)


def test_a_version_1_render_is_refused_with_the_re_render_action(tmp_path: Path) -> None:
    write_json(tmp_path / "render.json", raw_record(1))
    with pytest.raises(ArtifactError, match="re-render") as refusal:
        RenderStore(tmp_path)
    assert refusal.value.kind == "unsupported_version"


def test_the_rust_v3_fixture_reads_the_same_planes() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "parity" / "v3" / "render"
    store = RenderStore(fixture)
    assert store.ticks() == [7, 9, 30, 100, 149]
    assert [(chunk.second, chunk.ticks) for chunk in store.record.chunks] == [(0, 3), (2, 2)]
    tick7 = store.frame(7)
    assert tick7.indices == bytes([180] * 4 + [0, 40, 40, 0] + [0] * 4)
    assert struct.unpack("<12H", tick7.layers) == (0,) * 4 + (0, 16, 16, 0) + (16,) * 4
    for tick in (9, 30, 100, 149):
        shifted = bytes((value + tick - 7) % 256 for value in tick7.indices)
        assert store.frame(tick).indices == shifted
        assert store.frame(tick).layers == tick7.layers
    grey = bytes(value for entry in range(256) for value in (entry, entry, entry))
    second = bytes(value for entry in range(256) for value in (255 - entry, entry, 0))
    assert [store.frame(tick).palette for tick in store.ticks()] == [
        grey,
        grey,
        second,
        grey,
        second,
    ]
