"""Conformance tests for the shared parity corpus (`tests/fixtures/parity/v1/` and `v3/`).

The corpus pins the wire contract this adapter shares with the Rust port. These tests read the
committed bytes and write only into `tmp_path`; a fixture is never rewritten, so `git status`
stays clean after a run. `v3/render/` (a render store) and `v1/report.json` are authored by the
Rust side, while `v1/meta.json` and `v1/meta_legacy.json` are authored through `write_capture`.

The adapter is also checked against the JSON Schemas generated from the `stunt-parity` types
(`crates/stunt-parity/schema/`, ADR 0011): every fixture under `tests/fixtures/parity/` and every
document the adapter writes must validate. A written document is held to a strict schema that
refuses a field the Rust type lacks, which catches a field renamed or dropped on the Rust side.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from artifact_helpers import sample_capture, sample_record, sample_report, sample_video
from render_helpers import tick_entry
from stunt_reel.parity_artifacts import (
    RENDER_SCHEMA_VERSION,
    SCHEMA_VERSION,
    ArtifactError,
    CapturedFrame,
    FilmId,
    Geometry,
    RenderStore,
    StoredFrame,
    read_capture,
    read_page,
    read_render,
    read_report,
    write_capture,
    write_render,
    write_render_store,
    write_report,
    write_video_capture,
)

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "parity" / "v1"
RENDER = CORPUS.parent / "v3" / "render"
SCHEMAS = Path(__file__).resolve().parents[1] / "crates" / "stunt-parity" / "schema"
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
    record = read_render(RENDER / "render.json")
    assert record.schema_version == RENDER_SCHEMA_VERSION
    assert record.film == FilmId(name="SYNTH.FLM", flm_bytes=17)
    assert record.geometry == Geometry(width=4, height=3, viewport_rows=2)
    assert [tick.tick for tick in record.ticks] == [7, 9, 30, 100, 149]
    assert [tick.palette_index for tick in record.ticks] == [0, 0, 1, 0, 1]
    assert [tick.credits for tick in record.ticks] == [False, True, False, False, False]
    assert record.palette_count == 2
    assert record.ticks[0].palette.sky == 0
    assert record.ticks[0].palette.brightness == 32768
    assert record.ticks[0].palette.saturation == 32768

    write_render(tmp_path / "render.json", record)
    back = read_render(tmp_path / "render.json")

    assert back.schema_version == record.schema_version
    assert back.film == record.film
    assert back.geometry == record.geometry
    assert back.palette_count == record.palette_count
    assert back.chunks == record.chunks
    assert back.adapter == record.adapter
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
    assert back.adapter == report.adapter
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
    page = read_page(RenderStore(RENDER), 7)
    assert page.geometry == geometry
    assert len(page.indices) == geometry.width * geometry.height == 12
    assert len(page.layers) == geometry.width * geometry.height == 12
    assert page.indices == bytes([180, 180, 180, 180, 0, 40, 40, 0, 0, 0, 0, 0])
    assert page.layers == (0, 0, 0, 0, 0, 16, 16, 0, 16, 16, 16, 16)

    # The planes span the full 4x3 raster and the reader keeps all twelve layers;
    # only the actor scan narrows to the 2-row viewport, so row 2 is ignored.
    assert page.actor_pixels() == [5, 6]


def test_read_page_keeps_the_high_byte_of_a_layer_id(tmp_path: Path) -> None:
    # The corpus page carries only 0x0000 and 0x0010, which a decoder reading the
    # low byte alone would also produce. 0x0100 separates the two: its low byte is
    # below the actor threshold, so a low-byte decoder sees no actor at all.
    geometry = Geometry(width=4, height=3, viewport_rows=2)
    layer_bytes = bytearray(24)
    layer_bytes[2 * 5 : 2 * 5 + 2] = (0x0100).to_bytes(2, "little")
    frame = StoredFrame(indices=bytes(12), layers=bytes(layer_bytes), palette=bytes(768))
    write_render_store(tmp_path, FilmId(), geometry, [(tick_entry(7), frame)], adapter=None)

    page = read_page(RenderStore(tmp_path), 7)

    assert page.layers[5] == 0x0100
    assert page.actor_pixels() == [5]


def test_a_viewport_taller_than_the_raster_is_refused(tmp_path: Path) -> None:
    frame = StoredFrame(indices=bytes(12), layers=bytes(24), palette=bytes(768))
    with pytest.raises(ArtifactError, match="viewport_rows") as invalid:
        write_render_store(
            tmp_path,
            FilmId(),
            Geometry(width=4, height=3, viewport_rows=4),
            [(tick_entry(7), frame)],
            adapter=None,
        )
    assert invalid.value.kind == "geometry"


def _schema(kind: str, *, strict: bool) -> Draft202012Validator:
    """Validator for one document kind, from the schema `stunt-parity` generates.

    `strict` refuses a property the schema does not name, at every object that lists any. The
    derive leaves objects open because serde ignores unknown fields, so a renamed optional field
    on the Rust side would otherwise still validate what the adapter writes under the old name.
    """
    schema = json.loads((SCHEMAS / f"{kind}.schema.json").read_text(encoding="utf-8"))
    if strict:
        _close_objects(schema)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _close_objects(node: object) -> None:
    if isinstance(node, dict):
        if "properties" in node:
            node["additionalProperties"] = False
        for child in node.values():
            _close_objects(child)
    elif isinstance(node, list):
        for child in node:
            _close_objects(child)


def _assert_valid(validator: Draft202012Validator, document: object, label: str) -> None:
    problems = sorted(
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(document)
    )
    assert not problems, f"{label} does not conform to its schema:\n" + "\n".join(problems)


def _kind_of(path: Path, document: dict[str, Any]) -> str:
    if path.name == "render.json":
        return "render"
    if path.name == "report.json":
        return "report"
    assert path.name.startswith("meta"), f"{path} is not a parity document"
    return "video" if document.get("kind") == "video" else "capture"


def _fixture_documents() -> list[Path]:
    return sorted(
        path
        for pattern in ("**/render.json", "**/report.json", "**/meta*.json")
        for path in CORPUS.parent.glob(pattern)
    )


def test_a_schema_exists_for_every_document_kind() -> None:
    assert sorted(path.name for path in SCHEMAS.glob("*.schema.json")) == [
        "capture.schema.json",
        "render.schema.json",
        "report.schema.json",
        "video.schema.json",
    ]


def test_the_fixtures_cover_every_document_kind() -> None:
    kinds = {
        _kind_of(path, json.loads(path.read_text(encoding="utf-8")))
        for path in _fixture_documents()
    }
    assert kinds == {"render", "report", "capture", "video"}


@pytest.mark.parametrize(
    "path",
    _fixture_documents(),
    ids=lambda path: str(path.relative_to(CORPUS.parent)),
)
def test_a_fixture_the_adapter_reads_conforms_to_the_schema(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    _assert_valid(_schema(_kind_of(path, document), strict=False), document, str(path))


def test_every_document_the_adapter_writes_conforms_to_the_schema(tmp_path: Path) -> None:
    written: list[tuple[str, Path]] = []

    # Each kind is written from the Rust-authored fixture, which sets every optional field it
    # can, and from the adapter's own sample.
    for index, record in enumerate((read_render(RENDER / "render.json"), sample_record())):
        path = tmp_path / f"render_{index}.json"
        write_render(path, record)
        written.append(("render", path))
    store = tmp_path / "store"
    frame = StoredFrame(indices=bytes(12), layers=bytes(24), palette=bytes(768))
    write_render_store(
        store,
        FilmId(name="SYNTH.FLM"),
        Geometry(width=4, height=3, viewport_rows=2),
        [(tick_entry(7), frame)],
        adapter=None,
    )
    written.append(("render", store / "render.json"))

    for index, report in enumerate((read_report(CORPUS / "report.json"), sample_report())):
        path = tmp_path / f"report_{index}.json"
        write_report(path, report)
        written.append(("report", path))

    for index, capture in enumerate((read_capture(CORPUS), sample_capture())):
        directory = tmp_path / f"capture_{index}"
        directory.mkdir()
        write_capture(directory, capture)
        written.append(("capture", directory / "meta.json"))

    video = tmp_path / "video"
    video.mkdir()
    write_video_capture(video, sample_video(), diagnostics={})
    written.append(("video", video / "meta.json"))

    assert {kind for kind, _ in written} == {"render", "report", "capture", "video"}
    for kind, path in written:
        document = json.loads(path.read_text(encoding="utf-8"))
        _assert_valid(_schema(kind, strict=True), document, str(path.relative_to(tmp_path)))


def test_a_field_the_schema_lacks_is_refused_in_a_written_document() -> None:
    document = json.loads((CORPUS / "report.json").read_text(encoding="utf-8"))
    document["renamed_on_the_rust_side"] = 1
    _assert_valid(_schema("report", strict=False), document, "lenient")
    with pytest.raises(AssertionError, match="renamed_on_the_rust_side"):
        _assert_valid(_schema("report", strict=True), document, "strict")
