"""The video capture's Lua, its log decoding and the recording flow (no emulator starts here)."""

from __future__ import annotations

import pytest

from stunt_reel.parity_artifacts import PaletteLog, TickLog
from stunt_reel.tac import luagen, playone, video

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
