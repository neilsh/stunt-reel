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
    VIDEO_FILE,
    ArtifactError,
    PaletteChange,
    VideoFileInfo,
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


def test_the_video_fixture_with_slot_columns_loads() -> None:
    fixture = Path(__file__).parent / "fixtures" / "parity" / "video" / "with-slots"
    capture = load_video_capture(fixture)
    assert capture.log.slot_clock == (5, 5, 6, 7)
    assert capture.log.slot_ticks == (0, 1, 2, 1)
    assert capture.film_ticks == (7, 9)
    assert capture.video is not None
    assert capture.video.frame_rate == (2190197, 31250)
    assert capture.layout is not None
    assert capture.layout.inferred == ("slot_clock", "slot_ticks")
    assert capture.emulator is not None
    assert capture.emulator.cpu_cycles == "45000"
    assert capture.sound_samples == "stubbed"


def test_slot_columns_round_trip_and_are_omitted_when_absent(tmp_path: Path) -> None:
    plain = write_video_capture(tmp_path, sample_video(), diagnostics={})
    assert "slot_clock" not in plain["log"]
    base = sample_video()
    paired = replace(base, log=replace(base.log, slot_clock=(5, 5, 6, 7), slot_ticks=(0, 1, 2, 1)))
    document = write_video_capture(tmp_path, paired, diagnostics={})
    assert document["log"]["slot_ticks"] == [0, 1, 2, 1]
    assert load_video_capture(tmp_path) == paired


def test_slot_columns_come_together_and_match_the_log_length() -> None:
    base = sample_video()
    for log, text in (
        (replace(base.log, slot_clock=(5, 5, 6, 7)), "together"),
        (replace(base.log, slot_ticks=(0, 1, 2, 1)), "together"),
        (replace(base.log, slot_clock=(5, 5, 6, 7), slot_ticks=(0, 1, 2)), "slot_ticks"),
    ):
        with pytest.raises(ArtifactError, match=text):
            replace(base, log=log).validate()


def test_a_slot_column_in_a_document_is_read_and_a_lone_one_refused(tmp_path: Path) -> None:
    document = write_video_capture(tmp_path, sample_video(), diagnostics={})
    document["log"]["slot_clock"] = [5, 5, 6, 7]
    write_json(tmp_path / "meta.json", document)
    with pytest.raises(ArtifactError, match="together"):
        load_video_capture(tmp_path)
    document["log"]["slot_ticks"] = [0, 1, 2, 70000]
    write_json(tmp_path / "meta.json", document)
    with pytest.raises(ArtifactError, match="slot_ticks"):
        load_video_capture(tmp_path)


def test_whole_film_fields_must_agree_with_the_log() -> None:
    base = sample_video()
    for bad, text in (
        (replace(base, rows=5), "rows is 5"),
        (replace(base, palette_changes=0), "palette_changes is 0"),
        (replace(base, film_ticks=(7, 10)), "film_ticks"),
        (replace(base, video=VideoFileInfo("x.avi", "ab" * 32, 1, "zmbv", (1, 1))), "video.file"),
        (replace(base, video=VideoFileInfo(VIDEO_FILE, "AB" * 32, 1, "zmbv", (1, 1))), "sha256"),
    ):
        with pytest.raises(ArtifactError, match=text):
            bad.validate()


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
