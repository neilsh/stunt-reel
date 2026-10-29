"""Conformance tests for the shared parity corpus (`tests/fixtures/parity/v1/`).

The corpus pins the wire contract this adapter shares with the Rust port. These tests read the
committed bytes and write only into `tmp_path`; a fixture is never rewritten, so `git status`
stays clean after a run. `render.json` and `report.json` are authored by the Rust side, while
`meta.json` and `meta_legacy.json` are authored through `write_capture`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stunt_reel.parity_artifacts import (
    SCHEMA_VERSION,
    ArtifactError,
    CapturedFrame,
    FilmId,
    Geometry,
    read_capture,
    read_page,
    read_render,
    read_report,
    render_plane_paths,
    write_capture,
    write_render,
    write_report,
)

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "parity" / "v1"
APPROX_REL = 1e-6
APPROX_ABS = 1e-9


def _assert_close(actual: float, expected: float) -> None:
    assert actual == pytest.approx(expected, rel=APPROX_REL, abs=APPROX_ABS)


def _assert_close_optional(actual: float | None, expected: float | None) -> None:
    assert (actual is None) == (expected is None)
    if actual is not None and expected is not None:
        _assert_close(actual, expected)


def _assert_close_map(actual: dict[str, float] | None, expected: dict[str, float] | None) -> None:
    assert (actual is None) == (expected is None)
    if actual is None or expected is None:
        return
    assert actual.keys() == expected.keys()
    for key, value in expected.items():
        _assert_close(actual[key], value)


def test_render_fixture_round_trips_through_the_adapter(tmp_path: Path) -> None:
    record = read_render(CORPUS / "render.json")
    assert record.schema_version == SCHEMA_VERSION
    assert record.film == FilmId(name="SYNTH.FLM", flm_bytes=17)
    assert record.geometry == Geometry(width=4, height=3, viewport_rows=2)
    assert [tick.tick for tick in record.ticks] == [7, 9]
    assert record.ticks[0].palette.sky == 0
    assert record.ticks[0].palette.brightness == 32768
    assert record.ticks[0].palette.saturation == 32768

    write_render(tmp_path / "render.json", record)
    back = read_render(tmp_path / "render.json")

    assert back.schema_version == record.schema_version
    assert back.film == record.film
    assert back.geometry == record.geometry
    assert len(back.ticks) == len(record.ticks)
    for back_tick, tick in zip(back.ticks, record.ticks, strict=True):
        assert back_tick.tick == tick.tick
        assert back_tick.palette == tick.palette
        assert back_tick.camera.eye == pytest.approx(
            tick.camera.eye, rel=APPROX_REL, abs=APPROX_ABS
        )
        assert back_tick.camera.target == pytest.approx(
            tick.camera.target, rel=APPROX_REL, abs=APPROX_ABS
        )
        _assert_close(back_tick.camera.fov_degrees, tick.camera.fov_degrees)
        _assert_close(back_tick.camera.roll_radians, tick.camera.roll_radians)


def test_capture_fixtures_round_trip_through_the_adapter(tmp_path: Path) -> None:
    document = json.loads((CORPUS / "meta.json").read_text(encoding="utf-8"))
    assert document["palette_source"] == "measured"
    assert document["frames"][0]["palette_source"] == "measured"

    capture = read_capture(CORPUS)
    assert capture.schema_version == SCHEMA_VERSION
    assert capture.film == FilmId(name="SYNTH.FLM", flm_bytes=17)
    assert capture.geometry == Geometry(width=4, height=3)
    assert capture.frames == (
        CapturedFrame(
            ordinal=1,
            film_tick=7,
            frame_file="tick_0001.idx",
            palette_file="palettes_0001.json",
        ),
        CapturedFrame(
            ordinal=2,
            film_tick=9,
            frame_file="tick_0002.idx",
            palette_file="palettes_0002.json",
        ),
    )

    legacy_document = json.loads((CORPUS / "meta_legacy.json").read_text(encoding="utf-8"))
    assert "schema_version" not in legacy_document
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "meta.json").write_bytes((CORPUS / "meta_legacy.json").read_bytes())
    legacy = read_capture(legacy_dir)
    assert legacy.schema_version == SCHEMA_VERSION
    assert legacy.film == FilmId(name="SYNTH.FLM")
    assert legacy.frames == capture.frames

    written = tmp_path / "written"
    written.mkdir()
    write_capture(written, capture)
    assert read_capture(written) == capture


def test_report_fixture_round_trips_through_the_adapter(tmp_path: Path) -> None:
    report = read_report(CORPUS / "report.json")
    report.validate()
    assert report.reference_frames == 3
    assert report.frames == 2
    assert report.scored_frames == 1
    assert report.excluded_frames == 1
    assert report.sky_indices == (228, 238)
    _assert_close(report.mean_ssim, 0.74185)
    assert report.per_frame[1].index_agreement is None
    assert report.per_frame[1].loss_by_class is None
    assert report.per_frame[1].authored_fade_level is None

    write_report(tmp_path / "report.json", report)
    back = read_report(tmp_path / "report.json")
    back.validate()

    assert back.reference_frames == report.reference_frames
    assert back.frames == report.frames
    assert back.unmatched == report.unmatched
    assert back.sky_indices == report.sky_indices
    assert back.i6_gate == report.i6_gate
    assert back.scored_frames == report.scored_frames
    assert back.excluded_frames == report.excluded_frames
    _assert_close(back.mean_ssim, report.mean_ssim)
    _assert_close(back.min_ssim, report.min_ssim)
    _assert_close(back.mean_iou, report.mean_iou)
    _assert_close(back.min_fade_level, report.min_fade_level)
    _assert_close_optional(back.mean_ssim_scored, report.mean_ssim_scored)
    _assert_close_optional(back.mean_iou_scored, report.mean_iou_scored)
    _assert_close_optional(back.mean_index_agreement_scored, report.mean_index_agreement_scored)
    _assert_close_map(back.mean_loss_by_class_scored, report.mean_loss_by_class_scored)

    assert len(back.per_frame) == len(report.per_frame)
    for back_frame, frame in zip(back.per_frame, report.per_frame, strict=True):
        assert back_frame.ordinal == frame.ordinal
        assert back_frame.film_tick == frame.film_tick
        assert back_frame.scored == frame.scored
        _assert_close(back_frame.ssim, frame.ssim)
        _assert_close(back_frame.iou, frame.iou)
        _assert_close_optional(back_frame.index_agreement, frame.index_agreement)
        _assert_close_map(back_frame.loss_by_class, frame.loss_by_class)
        _assert_close_optional(back_frame.fade_level, frame.fade_level)
        _assert_close_optional(back_frame.authored_fade_level, frame.authored_fade_level)


def test_page_fixture_reads_through_one_reader() -> None:
    geometry = Geometry(width=4, height=3, viewport_rows=2)
    page = read_page(CORPUS / "pages", 7, geometry)
    assert page.geometry == geometry
    assert len(page.indices) == geometry.width * geometry.height == 12
    assert len(page.layers) == geometry.width * geometry.height == 12
    assert page.indices == bytes([180, 180, 180, 180, 0, 40, 40, 0, 0, 0, 0, 0])
    assert page.layers == (0, 0, 0, 0, 0, 16, 16, 0, 16, 16, 16, 16)

    # The files span the full 4x3 raster and the reader keeps all twelve layers;
    # only the actor scan narrows to the 2-row viewport, so row 2 is ignored.
    assert page.actor_pixels() == [5, 6]


def test_read_page_names_a_plane_of_the_wrong_size(tmp_path: Path) -> None:
    geometry = Geometry(width=4, height=3, viewport_rows=2)
    index_path, layer_path = render_plane_paths(tmp_path, 7)

    index_path.write_bytes(b"\x00" * 11)
    layer_path.write_bytes(b"\x00" * 24)
    with pytest.raises(ArtifactError, match=r"tick_00007\.idx") as truncated:
        read_page(tmp_path, 7, geometry)
    assert truncated.value.kind == "geometry"

    index_path.write_bytes(b"\x00" * 12)
    layer_path.write_bytes(b"\x00" * 26)
    with pytest.raises(ArtifactError, match=r"tick_00007\.layer") as oversized:
        read_page(tmp_path, 7, geometry)
    assert oversized.value.kind == "geometry"


def test_read_page_keeps_the_high_byte_of_a_layer_id(tmp_path: Path) -> None:
    # The corpus page carries only 0x0000 and 0x0010, which a decoder reading the
    # low byte alone would also produce. 0x0100 separates the two: its low byte is
    # below the actor threshold, so a low-byte decoder sees no actor at all.
    geometry = Geometry(width=4, height=3, viewport_rows=2)
    index_path, layer_path = render_plane_paths(tmp_path, 7)
    index_path.write_bytes(bytes(12))
    layer_bytes = bytearray(24)
    layer_bytes[2 * 5 : 2 * 5 + 2] = (0x0100).to_bytes(2, "little")
    layer_path.write_bytes(layer_bytes)

    page = read_page(tmp_path, 7, geometry)

    assert page.layers[5] == 0x0100
    assert page.actor_pixels() == [5]


def test_read_page_rejects_a_viewport_taller_than_the_raster(tmp_path: Path) -> None:
    index_path, layer_path = render_plane_paths(tmp_path, 7)
    index_path.write_bytes(bytes(12))
    layer_path.write_bytes(bytes(24))

    with pytest.raises(ArtifactError, match=r"tick_00007\.idx") as invalid:
        read_page(tmp_path, 7, Geometry(width=4, height=3, viewport_rows=4))
    assert invalid.value.kind == "geometry"
