"""Offline tests for the capture document in the Python parity artifact adapter (synthetic documents only)."""

from __future__ import annotations

import json
from dataclasses import replace
lazy from pathlib import Path

import pytest

from artifact_helpers import (
    capture_meta,
    sample_capture,
    write_json,
)
from stunt_reel.parity_artifacts import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    SCHEMA_VERSION,
    ArtifactError,
    CapturedFrame,
    FilmId,
    Geometry,
    read_capture,
    read_capture_palette,
    write_capture,
)


def test_read_capture_defaults_version_geometry_and_file_names(tmp_path: Path) -> None:
    write_json(tmp_path / "meta.json", capture_meta())
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
    document = write_capture(tmp_path, sample_capture())
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["width"] == CAPTURE_WIDTH
    assert document["height"] == CAPTURE_HEIGHT
    assert read_capture(tmp_path) == sample_capture()


def test_write_capture_keeps_diagnostics_beside_the_port_fields(tmp_path: Path) -> None:
    document = write_capture(
        tmp_path,
        sample_capture(),
        diagnostics={"palette_source": "dacpal", "dgroup_segment": "1575"},
        frame_diagnostics=({"global_tick": 12}, {"global_tick": 13}),
    )
    assert document["palette_source"] == "dacpal"
    assert document["frames"][0]["global_tick"] == 12
    on_disk = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert on_disk["palette_source"] == "dacpal"
    assert on_disk["frames"][1]["global_tick"] == 13
    assert read_capture(tmp_path) == sample_capture()


def test_a_capture_diagnostic_cannot_shadow_a_port_field(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="overwrite a capture document field") as refusal:
        write_capture(tmp_path, sample_capture(), diagnostics={"width": 1})
    assert refusal.value.kind == "conflict"
    assert not (tmp_path / "meta.json").exists()

    with pytest.raises(ArtifactError, match=r"frames\[0\]\.film_tick"):
        write_capture(tmp_path, sample_capture(), frame_diagnostics=({"film_tick": 7}, {}))


def test_a_capture_without_a_film_tick_is_rejected(tmp_path: Path) -> None:
    meta = capture_meta()
    meta["frames"] = [{"film_tick": 1}, {}]
    write_json(tmp_path / "meta.json", meta)
    with pytest.raises(ArtifactError, match=r"frames\[1\]\.film_tick must be an integer"):
        read_capture(tmp_path)


def test_a_capture_frame_file_must_be_a_basename(tmp_path: Path) -> None:
    meta = capture_meta()
    meta["frames"] = [{"film_tick": 1, "frame_file": "../tick_0001.idx"}]
    write_json(tmp_path / "meta.json", meta)
    with pytest.raises(ArtifactError, match="frame_file must be a basename") as refusal:
        read_capture(tmp_path)
    assert refusal.value.kind == "frame"


@pytest.mark.parametrize("name", ["frames/", "frames/../tick_0001.idx", "frames/frames/t.idx"])
def test_only_one_frames_directory_is_allowed_in_a_frame_file(tmp_path: Path, name: str) -> None:
    meta = capture_meta()
    meta["frames"] = [{"film_tick": 1, "frame_file": name}]
    write_json(tmp_path / "meta.json", meta)
    with pytest.raises(ArtifactError, match="frame_file must be a basename"):
        read_capture(tmp_path)


def test_a_frame_file_may_sit_under_frames(tmp_path: Path) -> None:
    meta = capture_meta()
    meta["frames"] = [
        {
            "film_tick": 1,
            "frame_file": "frames/tick_0001.idx",
            "palette_file": "frames/palettes_0001.json",
        }
    ]
    write_json(tmp_path / "meta.json", meta)
    assert read_capture(tmp_path).frames[0].frame_file == "frames/tick_0001.idx"


def test_a_capture_palette_file_must_be_a_basename(tmp_path: Path) -> None:
    meta = capture_meta()
    meta["frames"] = [{"film_tick": 1, "palette_file": "palettes/0001.json"}]
    write_json(tmp_path / "meta.json", meta)
    with pytest.raises(ArtifactError, match="palette_file must be a basename") as refusal:
        read_capture(tmp_path)
    assert refusal.value.kind == "frame"


def test_capture_without_a_version_reads_as_version_one_and_future_versions_fail(
    tmp_path: Path,
) -> None:
    meta = capture_meta()
    assert read_capture(write_json(tmp_path / "meta.json", meta).parent).schema_version == 1
    meta["schema_version"] = 9
    with pytest.raises(ArtifactError, match="schema version 9") as refusal:
        read_capture(write_json(tmp_path / "meta.json", meta).parent)
    assert refusal.value.kind == "unsupported_version"


def test_capture_palette_is_256_rgb_triples(tmp_path: Path) -> None:
    entries = [[0, 0, 0] for _ in range(255)] + [[255, 0, 255]]
    palette = read_capture_palette(write_json(tmp_path / "palettes_0001.json", entries))
    assert len(palette) == 256
    assert palette[-1] == (255, 0, 255)


def test_capture_palette_names_a_short_palette(tmp_path: Path) -> None:
    entries = [[0, 0, 0] for _ in range(255)]
    with pytest.raises(ArtifactError, match="256 RGB triples, got 255"):
        read_capture_palette(write_json(tmp_path / "palettes_0001.json", entries))


def test_capture_palette_names_a_short_triple(tmp_path: Path) -> None:
    entries = [[0, 0]] + [[0, 0, 0] for _ in range(255)]
    with pytest.raises(ArtifactError, match=r"\[0\] must be at least 3 channel values"):
        read_capture_palette(write_json(tmp_path / "palettes_0001.json", entries))


def test_a_capture_with_a_viewport_is_refused(tmp_path: Path) -> None:
    capture = replace(sample_capture(), geometry=Geometry(width=320, height=200, viewport_rows=185))
    with pytest.raises(ArtifactError, match="a capture has no viewport_rows"):
        write_capture(tmp_path, capture)
