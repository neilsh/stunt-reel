"""The video capture's Lua, its log decoding and the recording flow (no emulator starts here)."""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

import pytest

from pytest_helpers import build_avi
from stunt_reel.parity_artifacts import (
    VIDEO_FILE,
    FilmId,
    PaletteLog,
    TickLog,
    load_video_capture,
)
from stunt_reel.tac import luagen, playone, video
from stunt_reel.tac.automation import MockAutomation

if TYPE_CHECKING:
    from pathlib import Path

KEYS = ["KBD_c", "KBD_enter"]


def _script(**kwargs: object) -> str:
    args: dict[str, object] = {
        "keys": KEYS,
        "cap": 500,
        "end_hold": 30,
        "layout": playone.UNPATCHED,
    }
    args.update(kwargs)
    return luagen.video_script(**args)  # type: ignore[arg-type]


def _output(**overrides: object) -> dict[str, object]:
    out: dict[str, object] = {
        "cs": "x100",
        "log": "x101:7:0,102:7:1,103:8:2",
        "pal0": "x" + "00" * 768,
        "pal": "x",
        "end": "xhold",
        "done": True,
    }
    out.update(overrides)
    return out


def test_video_script_logs_rows_and_palette_bands() -> None:
    text = _script()

    assert "dosbox.capture_start()" in text
    assert "dosbox.capture_stop()" in text
    assert f"0x{playone.UNPATCHED.film_clock:04X}" in text
    assert "for b = 0, 7 do" in text
    assert "for i = 1, 500 do" in text
    assert "hold >= 30" in text
    assert text.index("dosbox.capture_start()") > text.index("dosbox.key(k, false)")


def test_video_script_rejects_a_cap_below_one() -> None:
    with pytest.raises(ValueError, match="cap"):
        _script(cap=0)


def test_video_script_rejects_an_end_hold_below_one() -> None:
    with pytest.raises(ValueError, match="end_hold"):
        _script(end_hold=0)


def test_decode_video_log_reads_rows() -> None:
    decoded = video.decode_video_log(_output())

    assert decoded.capture_start_frame == 100
    assert decoded.log.frame == (101, 102, 103)
    assert decoded.log.film_tick == (7, 7, 8)
    assert decoded.log.global_tick == (0, 1, 2)
    assert decoded.end == "hold"
    assert decoded.palettes.changes == ()
    assert len(decoded.palettes.initial) == 256


def test_a_palette_band_becomes_a_32_entry_change() -> None:
    decoded = video.decode_video_log(_output(pal="x103:1:" + "3f" * 96))

    (change,) = decoded.palettes.changes
    assert change.frame == 103
    assert change.first == 32
    assert change.rgb == ((255, 255, 255),) * 32


def test_a_script_that_did_not_finish_is_an_error() -> None:
    with pytest.raises(video.VideoCaptureError, match="finish"):
        video.decode_video_log(_output(done=False))


def test_film_start_is_the_first_moving_row() -> None:
    log = TickLog(frame=(101, 102, 103), film_tick=(7, 7, 8), global_tick=(0, 1, 2))

    assert video.film_start_frame(log) == 103


def test_a_clock_that_never_moves_is_an_error() -> None:
    log = TickLog(frame=(101, 102), film_tick=(0, 0), global_tick=(0, 1))

    with pytest.raises(video.VideoCaptureError, match="the film clock never moved"):
        video.film_start_frame(log)


def test_the_palette_log_type_is_the_artifact_one() -> None:
    assert isinstance(video.decode_video_log(_output()).palettes, PaletteLog)


def test_bands_of_one_frame_merge_into_one_change_filled_from_the_prior_palette() -> None:
    pal = "x103:0:" + "3f" * 96 + ",103:2:" + "3f" * 96
    decoded = video.decode_video_log(_output(pal=pal))

    (change,) = decoded.palettes.changes
    assert (change.first, len(change.rgb)) == (0, 96)
    assert change.rgb[32] == (0, 0, 0)
    assert change.rgb[64] == (255, 255, 255)


FILM = FilmId(name="CTRY.FLM", flm_bytes=19, flm_sha256="0" * 64)


def _record(
    tmp_path: Path, *, output: dict[str, Any], video_frames: int | None, audio: bool = True
) -> tuple[Path, Any]:
    out_dir, recording = tmp_path / "out", tmp_path / "recording"
    out_dir.mkdir()
    recording.mkdir()

    def handler(_lua: str) -> dict[str, Any]:
        if video_frames is not None:
            frames = [bytes([n]) * 3 for n in range(video_frames)]
            sound = [b"s" * 5] * video_frames if audio else []
            (recording / "capture-0001.avi").write_bytes(build_avi(frames, sound))
        return output

    mock = MockAutomation(handler)
    result = video.record_video(
        lambda: nullcontext(mock),
        out_dir,
        recording,
        keys=KEYS,
        layout=playone.UNPATCHED,
        film=FILM,
        provenance={"captured_on": "2026-10-31"},
    )
    return out_dir, result


def test_record_video_writes_meta_last_and_strips_audio(tmp_path: Path) -> None:
    out_dir, result = _record(tmp_path, output=_output(), video_frames=3)

    assert b"01wb" not in (out_dir / VIDEO_FILE).read_bytes()
    loaded = load_video_capture(out_dir)
    assert loaded == result
    assert loaded.end == "hold"
    assert loaded.film_start_frame == 103
    assert loaded.playone_build == playone.UNPATCHED.name
    assert loaded.log.frame == (101, 102, 103)


def test_record_video_refuses_a_frame_count_mismatch(tmp_path: Path) -> None:
    output = _output(log="x101:7:0,102:7:1,103:8:2,104:8:3,105:9:4")

    with pytest.raises(video.VideoCaptureError, match="3 video frames"):
        _record(tmp_path, output=output, video_frames=3)
    assert not (tmp_path / "out" / "meta.json").exists()


def test_record_video_refuses_no_recording(tmp_path: Path) -> None:
    with pytest.raises(video.VideoCaptureError, match=r"no \.avi"):
        _record(tmp_path, output=_output(), video_frames=None)
