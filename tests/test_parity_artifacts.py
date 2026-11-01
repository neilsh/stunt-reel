"""Offline tests for the Python parity artifact adapter (synthetic documents only)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.parity_artifacts import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    SCHEMA_VERSION,
    ArtifactError,
    CameraPose,
    CapturedFrame,
    CaptureSet,
    FilmId,
    FrameReport,
    Geometry,
    I6Gate,
    PaletteChange,
    PaletteLog,
    RenderPalette,
    RenderRecord,
    RenderTick,
    Report,
    RetimedDocuments,
    TickLog,
    VideoCapture,
    frames_for_captured_ticks,
    load_video_capture,
    open_render,
    read_capture,
    read_capture_palette,
    read_render,
    read_report,
    render_plane_paths,
    retime_document,
    tick_stem,
    write_capture,
    write_render,
    write_report,
    write_retimed_documents,
    write_video_capture,
)


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _geometry() -> Geometry:
    return Geometry(width=320, height=200, viewport_rows=185)


def _tick(tick: int) -> RenderTick:
    return RenderTick(
        tick=tick,
        palette=RenderPalette(sky=0x2000, brightness=0x8000, saturation=0x8000),
        camera=CameraPose(
            eye=(0.0, 10.0, 50.0),
            target=(0.0, 0.0, 0.0),
            fov_degrees=45.0,
            roll_radians=0.0,
        ),
    )


def _record(ticks: tuple[int, ...] = (10, 12)) -> RenderRecord:
    return RenderRecord(
        schema_version=SCHEMA_VERSION,
        film=FilmId(name="CTRY.FLM", flm_bytes=100),
        geometry=_geometry(),
        ticks=tuple(_tick(tick) for tick in ticks),
    )


def _raw_record(schema_version: int = SCHEMA_VERSION) -> dict[str, Any]:
    """A document shaped exactly as serde writes it, to pin cross-language loading."""
    return {
        "schema_version": schema_version,
        "film": {"name": "CTRY.FLM", "flm_bytes": 100},
        "geometry": {"width": 320, "height": 200, "viewport_rows": 185},
        "ticks": [
            {
                "tick": 10,
                "palette": {"sky": 0x2000, "brightness": 0x8000, "saturation": 0x8000},
                "camera": {
                    "eye": [0.0, 10.0, 50.0],
                    "target": [0.0, 0.0, 0.0],
                    "fov_degrees": 45.0,
                    "roll_radians": 0.0,
                },
            }
        ],
    }


def test_a_render_record_round_trips_through_json(tmp_path: Path) -> None:
    path = tmp_path / "render.json"
    record = _record()
    write_render(path, record)
    assert read_render(path) == record
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["film"] == {"name": "CTRY.FLM", "flm_bytes": 100}
    assert document["geometry"] == {"width": 320, "height": 200, "viewport_rows": 185}
    assert [entry["tick"] for entry in document["ticks"]] == [10, 12]
    assert document["ticks"][0]["palette"]["sky"] == 0x2000
    assert document["ticks"][0]["camera"]["eye"] == [0.0, 10.0, 50.0]


def test_a_document_written_by_the_rust_side_loads_and_extra_keys_are_ignored(
    tmp_path: Path,
) -> None:
    record = read_render(_write_json(tmp_path / "render.json", _raw_record()))
    assert record.schema_version == SCHEMA_VERSION
    assert record.film == FilmId(name="CTRY.FLM", flm_bytes=100)
    assert record.geometry == _geometry()
    assert record.ticks == (_tick(10),)
    extra = _raw_record()
    extra["future_top"] = {"kept": True}
    assert read_render(_write_json(tmp_path / "extra.json", extra)) == record


def test_an_unsupported_version_is_rejected_and_names_the_directory(tmp_path: Path) -> None:
    _write_json(tmp_path / "render.json", _raw_record(9))
    with pytest.raises(ArtifactError, match="schema version 9") as refusal:
        read_render(tmp_path / "render.json")
    assert refusal.value.kind == "unsupported_version"
    with pytest.raises(ArtifactError) as from_directory:
        open_render(tmp_path)
    assert from_directory.value.kind == "unsupported_version"
    assert from_directory.value.path == tmp_path / "render.json"


@pytest.mark.parametrize(
    ("geometry", "message"),
    [
        (Geometry(width=0, height=200), "width and height must be positive"),
        (
            Geometry(width=320, height=200, viewport_rows=201),
            "viewport_rows must be between 1 and height",
        ),
    ],
)
def test_geometry_is_validated_before_anything_is_read(
    tmp_path: Path, geometry: Geometry, message: str
) -> None:
    record = RenderRecord(SCHEMA_VERSION, FilmId(), geometry, ())
    with pytest.raises(ArtifactError, match=message) as refusal:
        write_render(tmp_path / "render.json", record)
    assert refusal.value.kind == "geometry"


def test_tick_ordering_is_checked(tmp_path: Path) -> None:
    duplicate = RenderRecord(SCHEMA_VERSION, FilmId(), _geometry(), (_tick(10), _tick(10)))
    with pytest.raises(ArtifactError, match="duplicate tick at index 1") as repeat:
        duplicate.validate(tmp_path / "render.json")
    assert repeat.value.kind == "ordering"
    unordered = RenderRecord(SCHEMA_VERSION, FilmId(), _geometry(), (_tick(12), _tick(10)))
    with pytest.raises(ArtifactError, match="not strictly ascending at index 1"):
        unordered.validate()


def test_film_conflicts_need_both_sides() -> None:
    named = FilmId(name="CTRY.FLM", flm_bytes=100)
    assert not named.names_conflict(FilmId())
    assert not named.names_conflict(FilmId(name="ctry.flm"))
    assert named.names_conflict(FilmId(name="INTRO.FLM"))
    assert not named.bytes_conflict(FilmId())
    assert named.bytes_conflict(FilmId(flm_bytes=101))


def test_open_render_prefers_the_record_to_the_legacy_sidecar(tmp_path: Path) -> None:
    write_render(tmp_path / "render.json", _record())
    _write_json(
        tmp_path / "palette_controls.json",
        {
            "film": "INTRO.FLM",
            "flm_bytes": 1,
            "ticks": [{"tick": 10, "sky": 1, "brightness": 2, "saturation": 3}],
        },
    )
    controls = open_render(tmp_path)
    assert controls.legacy is False
    assert controls.geometry == _geometry()
    assert controls.film == FilmId(name="CTRY.FLM", flm_bytes=100)
    assert controls.controls[10].sky == 0x2000
    assert controls.warnings == ()


def test_open_render_reads_the_legacy_sidecar_without_geometry(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "palette_controls.json",
        {
            "film": "CTRY.FLM",
            "flm_bytes": 100,
            "future_top": True,
            "ticks": [
                {"tick": 7, "sky": 45, "brightness": 32768, "saturation": 32768, "camera": {}}
            ],
        },
    )
    controls = open_render(tmp_path)
    assert controls.legacy is True
    assert controls.geometry is None
    assert controls.record is None
    assert controls.film == FilmId(name="CTRY.FLM", flm_bytes=100)
    assert controls.controls == {7: RenderPalette(sky=45, brightness=32768, saturation=32768)}
    assert controls.warnings
    assert "render.json" in controls.warnings[0]


def test_open_render_accepts_a_sidecar_without_ticks(tmp_path: Path) -> None:
    _write_json(tmp_path / "palette_controls.json", {"film": "CTRY.FLM"})
    controls = open_render(tmp_path)
    assert controls.legacy is True
    assert controls.controls == {}


def test_open_render_refuses_a_directory_with_neither_document(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="re-render") as refusal:
        open_render(tmp_path)
    assert refusal.value.kind == "missing"
    assert refusal.value.path == tmp_path


def _capture_meta() -> dict[str, Any]:
    return {
        "film": "CTRY.FLM",
        "flm_bytes": 100,
        "flm_sha256": "abc",
        "frames": [
            {"ordinal": 1, "film_tick": 9, "global_tick": 12, "distinct_indices": 58},
            {"film_tick": 10, "frame_file": "other.idx", "palette_file": "palettes_0002.json"},
        ],
    }


def _capture() -> CaptureSet:
    return CaptureSet(
        schema_version=SCHEMA_VERSION,
        film=FilmId(name="CTRY.FLM", flm_bytes=100, flm_sha256="abc"),
        geometry=Geometry(width=320, height=200),
        frames=(
            CapturedFrame(
                ordinal=1,
                film_tick=9,
                frame_file="tick_0001.idx",
                palette_file="palettes_0001.json",
            ),
            CapturedFrame(
                ordinal=2,
                film_tick=10,
                frame_file="other.idx",
                palette_file="palettes_0002.json",
            ),
        ),
    )


def test_read_capture_defaults_version_geometry_and_file_names(tmp_path: Path) -> None:
    _write_json(tmp_path / "meta.json", _capture_meta())
    capture = read_capture(tmp_path)
    assert capture.schema_version == SCHEMA_VERSION
    assert capture.film == FilmId(name="CTRY.FLM", flm_bytes=100, flm_sha256="abc")
    assert capture.geometry == Geometry(width=CAPTURE_WIDTH, height=CAPTURE_HEIGHT)
    assert capture.frames[0] == CapturedFrame(
        ordinal=1,
        film_tick=9,
        frame_file="tick_0001.idx",
        palette_file="palettes_0001.json",
    )
    assert capture.frames[1].film_tick == 10
    assert capture.frames[1].frame_file == "other.idx"
    assert capture.frames[1].ordinal == 2


def test_write_capture_emits_the_port_document_and_round_trips(tmp_path: Path) -> None:
    document = write_capture(tmp_path, _capture())
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["width"] == CAPTURE_WIDTH
    assert document["height"] == CAPTURE_HEIGHT
    assert read_capture(tmp_path) == _capture()


def test_write_capture_keeps_diagnostics_beside_the_port_fields(tmp_path: Path) -> None:
    document = write_capture(
        tmp_path,
        _capture(),
        diagnostics={"palette_source": "dacpal", "dgroup_segment": "1575"},
        frame_diagnostics=({"global_tick": 12}, {"global_tick": 13}),
    )
    assert document["palette_source"] == "dacpal"
    assert document["frames"][0]["global_tick"] == 12
    on_disk = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert on_disk["palette_source"] == "dacpal"
    assert on_disk["frames"][1]["global_tick"] == 13
    assert read_capture(tmp_path) == _capture()


def test_a_capture_diagnostic_cannot_shadow_a_port_field(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="overwrite a capture document field") as refusal:
        write_capture(tmp_path, _capture(), diagnostics={"width": 1})
    assert refusal.value.kind == "conflict"
    assert not (tmp_path / "meta.json").exists()

    with pytest.raises(ArtifactError, match=r"frames\[0\]\.film_tick"):
        write_capture(tmp_path, _capture(), frame_diagnostics=({"film_tick": 7}, {}))


def test_a_capture_without_a_film_tick_is_rejected(tmp_path: Path) -> None:
    meta = _capture_meta()
    meta["frames"] = [{"film_tick": 1}, {}]
    _write_json(tmp_path / "meta.json", meta)
    with pytest.raises(ArtifactError, match=r"frames\[1\]\.film_tick must be an integer"):
        read_capture(tmp_path)


def test_a_capture_frame_file_must_be_a_basename(tmp_path: Path) -> None:
    meta = _capture_meta()
    meta["frames"] = [{"film_tick": 1, "frame_file": "../tick_0001.idx"}]
    _write_json(tmp_path / "meta.json", meta)
    with pytest.raises(ArtifactError, match="frame_file must be a basename") as refusal:
        read_capture(tmp_path)
    assert refusal.value.kind == "frame"


@pytest.mark.parametrize("name", ["frames/", "frames/../tick_0001.idx", "frames/frames/t.idx"])
def test_only_one_frames_directory_is_allowed_in_a_frame_file(tmp_path: Path, name: str) -> None:
    meta = _capture_meta()
    meta["frames"] = [{"film_tick": 1, "frame_file": name}]
    _write_json(tmp_path / "meta.json", meta)
    with pytest.raises(ArtifactError, match="frame_file must be a basename"):
        read_capture(tmp_path)


def test_a_frame_file_may_sit_under_frames(tmp_path: Path) -> None:
    meta = _capture_meta()
    meta["frames"] = [
        {
            "film_tick": 1,
            "frame_file": "frames/tick_0001.idx",
            "palette_file": "frames/palettes_0001.json",
        }
    ]
    _write_json(tmp_path / "meta.json", meta)
    assert read_capture(tmp_path).frames[0].frame_file == "frames/tick_0001.idx"


def test_a_capture_palette_file_must_be_a_basename(tmp_path: Path) -> None:
    meta = _capture_meta()
    meta["frames"] = [{"film_tick": 1, "palette_file": "palettes/0001.json"}]
    _write_json(tmp_path / "meta.json", meta)
    with pytest.raises(ArtifactError, match="palette_file must be a basename") as refusal:
        read_capture(tmp_path)
    assert refusal.value.kind == "frame"


def test_capture_without_a_version_reads_as_version_one_and_future_versions_fail(
    tmp_path: Path,
) -> None:
    meta = _capture_meta()
    assert read_capture(_write_json(tmp_path / "meta.json", meta).parent).schema_version == 1
    meta["schema_version"] = 9
    with pytest.raises(ArtifactError, match="schema version 9") as refusal:
        read_capture(_write_json(tmp_path / "meta.json", meta).parent)
    assert refusal.value.kind == "unsupported_version"


def test_capture_palette_is_256_rgb_triples(tmp_path: Path) -> None:
    entries = [[0, 0, 0] for _ in range(255)] + [[255, 0, 255]]
    palette = read_capture_palette(_write_json(tmp_path / "palettes_0001.json", entries))
    assert len(palette) == 256
    assert palette[-1] == (255, 0, 255)


def test_capture_palette_names_a_short_palette(tmp_path: Path) -> None:
    entries = [[0, 0, 0] for _ in range(255)]
    with pytest.raises(ArtifactError, match="256 RGB triples, got 255"):
        read_capture_palette(_write_json(tmp_path / "palettes_0001.json", entries))


def test_capture_palette_names_a_short_triple(tmp_path: Path) -> None:
    entries = [[0, 0]] + [[0, 0, 0] for _ in range(255)]
    with pytest.raises(ArtifactError, match=r"\[0\] must be at least 3 channel values"):
        read_capture_palette(_write_json(tmp_path / "palettes_0001.json", entries))


def _report() -> Report:
    return Report(
        per_frame=(
            FrameReport(
                film_tick=9,
                ssim=0.7,
                iou=0.9,
                ordinal=1,
                index_agreement=0.5,
                loss_by_class={"sky": 0.1},
                fade_level=1.0,
                authored_fade_level=1.0,
                scored=True,
            ),
            FrameReport(film_tick=10, ssim=0.6, iou=0.8, ordinal=2, scored=False),
        ),
        reference_frames=2,
        frames=2,
        unmatched=0,
        sky_indices=(227, 238),
        mean_ssim=0.65,
        min_ssim=0.6,
        mean_iou=0.85,
        min_fade_level=0.25,
        mean_ssim_scored=0.7,
        i6_gate=I6Gate(initial=False, sign_off=False),
        mean_iou_scored=0.9,
        mean_index_agreement_scored=0.5,
        mean_loss_by_class_scored={"sky": 0.1},
        scored_frames=1,
        excluded_frames=1,
    )


def test_a_report_round_trips_through_json(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    report = _report()
    write_report(path, report)
    assert read_report(path) == report
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["mean_ssim_scored"] == 0.7
    assert document["i6_gate"] == {"initial": False, "sign_off": False}
    assert document["per_frame"][0]["scored"] is True


def test_an_old_report_without_optional_fields_still_loads(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path / "report.json",
        {"per_frame": [{"film_tick": 9, "ssim": 0.7, "iou": 0.9}]},
    )
    report = read_report(path)
    assert report.per_frame == (FrameReport(film_tick=9, ssim=0.7, iou=0.9),)
    assert report.scored_frames == 0
    assert report.i6_gate == I6Gate()
    assert report.headline() == (0.0, 0.0)


def test_headline_prefers_the_scored_means() -> None:
    assert _report().headline() == (0.7, 0.9)
    all_frames = Report(
        per_frame=(),
        mean_ssim=0.5,
        mean_iou=0.6,
        mean_ssim_scored=None,
        mean_iou_scored=None,
    )
    assert all_frames.headline() == (0.5, 0.6)


def test_write_report_checks_the_identities() -> None:
    broken = Report(per_frame=(), reference_frames=1)
    with pytest.raises(ArtifactError, match="reference_frames must equal"):
        write_report(Path("unused.json"), broken)


def test_frames_for_captured_ticks_maps_capture_ticks_to_frame_numbers() -> None:
    # frame n renders tick n - 1, and the range is half-open
    assert frames_for_captured_ticks([769, 3640, 1000]) == "770..3642"
    assert frames_for_captured_ticks([10]) == "11..12"


def test_frames_for_captured_ticks_needs_a_capture() -> None:
    with pytest.raises(ArtifactError, match="no --frames range"):
        frames_for_captured_ticks([])


def test_tick_names_live_in_the_adapter(tmp_path: Path) -> None:
    assert tick_stem(7) == "tick_00007"
    assert render_plane_paths(tmp_path, 7) == (
        tmp_path / "tick_00007.idx",
        tmp_path / "tick_00007.layer",
    )


def test_retime_document_relabels_ticks_and_preserves_unknown_keys() -> None:
    document: dict[str, Any] = {
        "schema_version": 1,
        "future_top": {"kept": True},
        "film": {"name": "CTRY.FLM"},
        "geometry": {"width": 320, "height": 200},
        "ticks": [
            {
                "tick": 11,
                "future_entry": [1, 2],
                "palette": {"sky": 1, "brightness": 2, "saturation": 3},
            },
            {"tick": 13, "palette": {"sky": 4, "brightness": 5, "saturation": 6}},
        ],
    }
    shifted = retime_document(document, [(10, 11), (12, 13), (14, 15)])
    assert [entry["tick"] for entry in shifted["ticks"]] == [10, 12]
    assert shifted["future_top"] == {"kept": True}
    assert shifted["ticks"][0]["future_entry"] == [1, 2]
    assert shifted["ticks"][0]["palette"] == {"sky": 1, "brightness": 2, "saturation": 3}
    assert [entry["tick"] for entry in document["ticks"]] == [11, 13]


def test_retime_document_writes_an_empty_tick_list_when_none_exist() -> None:
    assert retime_document({"film": "CTRY.FLM"}, [(1, 1)]) == {
        "film": "CTRY.FLM",
        "ticks": [],
    }


def test_write_retimed_documents_rewrites_both_documents(tmp_path: Path) -> None:
    source = tmp_path / "ours"
    source.mkdir()
    write_render(source / "render.json", _record((10, 12)))
    record_document = json.loads((source / "render.json").read_text(encoding="utf-8"))
    record_document["future_top"] = {"kept": True}
    _write_json(source / "render.json", record_document)
    _write_json(
        source / "palette_controls.json",
        {
            "film": "CTRY.FLM",
            "future_top": True,
            "ticks": [
                {"tick": 10, "sky": 45, "brightness": 32768, "saturation": 32768},
                {"tick": 12, "sky": 46, "brightness": 32768, "saturation": 32768},
            ],
        },
    )
    out = tmp_path / "out"
    written = write_retimed_documents(source, out, [(11, 10), (13, 12)])
    assert written == RetimedDocuments(record_written=True, sidecar_written=True)
    shifted = read_render(out / "render.json")
    assert [tick.tick for tick in shifted.ticks] == [11, 13]
    assert shifted.ticks[1].palette == _record().ticks[1].palette
    shifted_document = json.loads((out / "render.json").read_text(encoding="utf-8"))
    assert shifted_document["future_top"] == {"kept": True}
    sidecar = json.loads((out / "palette_controls.json").read_text(encoding="utf-8"))
    assert sidecar["future_top"] is True
    assert [entry["tick"] for entry in sidecar["ticks"]] == [11, 13]


def test_write_retimed_documents_keeps_only_the_documents_that_exist(tmp_path: Path) -> None:
    record_only = tmp_path / "record_only"
    record_only.mkdir()
    write_render(record_only / "render.json", _record((10,)))
    first = tmp_path / "first"
    assert write_retimed_documents(record_only, first, [(11, 10)]) == RetimedDocuments(
        record_written=True, sidecar_written=False
    )
    assert (first / "render.json").is_file()
    assert not (first / "palette_controls.json").exists()

    sidecar_only = tmp_path / "sidecar_only"
    sidecar_only.mkdir()
    _write_json(
        sidecar_only / "palette_controls.json",
        {"film": "CTRY.FLM", "ticks": [{"tick": 10, "sky": 1, "brightness": 2, "saturation": 3}]},
    )
    second = tmp_path / "second"
    assert write_retimed_documents(sidecar_only, second, [(11, 10)]) == RetimedDocuments(
        record_written=False, sidecar_written=True
    )
    assert not (second / "render.json").exists()
    sidecar = json.loads((second / "palette_controls.json").read_text(encoding="utf-8"))
    assert [entry["tick"] for entry in sidecar["ticks"]] == [11]


def _video() -> VideoCapture:
    return VideoCapture(
        schema_version=SCHEMA_VERSION,
        kind="video",
        film=FilmId(name="SYNTH.FLM", flm_bytes=4, flm_sha256="00"),
        geometry=Geometry(width=4, height=2),
        playone_build="synthetic",
        cpu_profile="capture",
        capture_start_frame=100,
        film_start_frame=103,
        end="hold",
        log=TickLog(frame=(101, 102, 103, 104), film_tick=(7, 7, 8, 9), global_tick=(0, 1, 2, 3)),
        palettes=PaletteLog(
            initial=tuple((i, i, i) for i in range(256)),
            changes=(PaletteChange(frame=103, first=32, rgb=((255, 0, 0),) * 32),),
        ),
    )


def test_video_capture_round_trips(tmp_path: Path) -> None:
    document = write_video_capture(tmp_path, _video(), diagnostics={"note": "kept"})
    assert document["kind"] == "video"
    assert document["note"] == "kept"
    assert load_video_capture(tmp_path) == _video()


def test_the_video_fixture_loads() -> None:
    fixture = Path(__file__).parent / "fixtures" / "parity" / "video"
    capture = load_video_capture(fixture)
    assert len(capture.log.frame) == 4
    assert [change.frame for change in capture.palettes.changes] == [103]
    assert capture.film_start_frame == 103


def test_video_capture_rejects_a_frame_capture_and_a_bad_log(tmp_path: Path) -> None:
    document = write_video_capture(tmp_path, _video(), diagnostics={})
    del document["kind"]
    _write_json(tmp_path / "meta.json", document)
    with pytest.raises(ArtifactError) as missing:
        load_video_capture(tmp_path)
    assert missing.value.kind == "missing"
    document["kind"] = "frames"
    _write_json(tmp_path / "meta.json", document)
    with pytest.raises(ArtifactError) as wrong:
        load_video_capture(tmp_path)
    assert wrong.value.kind == "video_log"
    document["kind"] = "video"
    document["log"]["frame"] = [101, 103, 104, 105]
    _write_json(tmp_path / "meta.json", document)
    with pytest.raises(ArtifactError, match="index 1"):
        load_video_capture(tmp_path)


def test_video_capture_validation_rules() -> None:
    base = _video()
    for bad, text in (
        (replace(base, log=replace(base.log, global_tick=(0, 1, 2))), "length"),
        (replace(base, log=replace(base.log, film_tick=(7, 7, 9, 8))), "frame 104"),
        (replace(base, film_start_frame=200), "film_start_frame"),
        (replace(base, palettes=replace(base.palettes, initial=base.palettes.initial[:-1])), "256"),
        (
            replace(
                base,
                palettes=replace(
                    base.palettes,
                    changes=(PaletteChange(frame=103, first=250, rgb=((1, 2, 3),) * 32),),
                ),
            ),
            "past entry",
        ),
        (
            replace(
                base,
                palettes=replace(
                    base.palettes,
                    changes=(PaletteChange(frame=105, first=0, rgb=((1, 2, 3),)),),
                ),
            ),
            "outside the log",
        ),
    ):
        with pytest.raises(ArtifactError, match=text):
            bad.validate()
    assert base.video_index(101) == 1
    assert base.video_index(99) is None
