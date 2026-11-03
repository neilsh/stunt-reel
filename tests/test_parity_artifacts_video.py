"""Offline tests for the video capture document in the Python parity artifact adapter (synthetic documents only)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from artifact_helpers import (
    sample_video,
    write_json,
)
from stunt_reel.parity_artifacts import (
    ArtifactError,
    PaletteChange,
    load_video_capture,
    write_video_capture,
)


def test_video_capture_round_trips(tmp_path: Path) -> None:
    document = write_video_capture(tmp_path, sample_video(), diagnostics={"note": "kept"})
    assert document["kind"] == "video"
    assert document["note"] == "kept"
    assert load_video_capture(tmp_path) == sample_video()


def test_video_capture_records_the_engine_hash_when_it_has_one(tmp_path: Path) -> None:
    named = replace(sample_video(), playone_sha256="ab" * 32)
    document = write_video_capture(tmp_path, named, diagnostics={})
    assert document["playone_build"] == "synthetic"
    assert document["playone_sha256"] == "ab" * 32
    assert load_video_capture(tmp_path) == named


def test_a_video_capture_without_the_engine_hash_still_loads(tmp_path: Path) -> None:
    document = write_video_capture(tmp_path, sample_video(), diagnostics={})
    assert "playone_sha256" not in document
    assert load_video_capture(tmp_path).playone_sha256 is None


def test_the_video_fixture_loads() -> None:
    fixture = Path(__file__).parent / "fixtures" / "parity" / "video"
    capture = load_video_capture(fixture)
    assert capture.playone_sha256 is None  # the fixture predates the field
    assert len(capture.log.frame) == 4
    assert [change.frame for change in capture.palettes.changes] == [103]
    assert capture.film_start_frame == 103


def test_video_capture_rejects_a_frame_capture_and_a_bad_log(tmp_path: Path) -> None:
    document = write_video_capture(tmp_path, sample_video(), diagnostics={})
    del document["kind"]
    write_json(tmp_path / "meta.json", document)
    with pytest.raises(ArtifactError) as missing:
        load_video_capture(tmp_path)
    assert missing.value.kind == "missing"
    document["kind"] = "frames"
    write_json(tmp_path / "meta.json", document)
    with pytest.raises(ArtifactError) as wrong:
        load_video_capture(tmp_path)
    assert wrong.value.kind == "video_log"
    document["kind"] = "video"
    document["log"]["frame"] = [101, 103, 104, 105]
    write_json(tmp_path / "meta.json", document)
    with pytest.raises(ArtifactError, match="index 1"):
        load_video_capture(tmp_path)


def test_video_capture_validation_rules() -> None:
    base = sample_video()
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
