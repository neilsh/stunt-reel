"""The video capture's Lua, its log decoding and the recording flow (no emulator starts here)."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from contextlib import nullcontext, suppress
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
from stunt_reel.tac import automation, luagen, playone, video
from stunt_reel.tac.automation import MockAutomation

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

    from stunt_reel.parity_artifacts import VideoCapture

pytestmark = pytest.mark.windows

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
        "log": "x101:7:0:5:0,102:7:1:5:1,103:8:2:6:2",
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
    assert f"0x{playone.UNPATCHED.slot_clock:04X}" in text
    assert f"0x{playone.UNPATCHED.slot_ticks:04X}" in text
    assert '":" .. sc .. ":" .. st' in text
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
    assert decoded.log.slot_clock == (5, 5, 6)
    assert decoded.log.slot_ticks == (0, 1, 2)
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
    assert loaded.playone_sha256 == playone.UNPATCHED.sha256
    assert json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))["playone_sha256"] == (
        playone.UNPATCHED.sha256
    )
    assert loaded.log.frame == (101, 102, 103)
    assert loaded.log.slot_clock == (5, 5, 6)
    assert loaded.video_frames == 3
    assert loaded.rows == 3
    assert loaded.palette_changes == 0
    assert loaded.film_ticks == (7, 8)
    assert loaded.captured_on == "2026-10-31"
    assert loaded.video is not None
    assert loaded.video.sha256 == hashlib.sha256((out_dir / VIDEO_FILE).read_bytes()).hexdigest()
    assert loaded.video.bytes == (out_dir / VIDEO_FILE).stat().st_size
    assert loaded.video.frame_rate == (2190197, 31250)
    assert loaded.layout == video.layout_offsets(playone.UNPATCHED)
    assert loaded.emulator is None


def test_layout_offsets_name_the_inferred_words() -> None:
    patch3 = video.layout_offsets(playone.PATCH3)
    assert (patch3.slot_clock, patch3.slot_ticks) == ("0x4220", "0x1C62")
    assert patch3.film_clock == "0x421C"
    assert patch3.inferred == ("slot_clock", "slot_ticks")
    assert video.layout_offsets(playone.UNPATCHED).inferred == ()


def test_emulator_info_reads_the_version_and_the_stage_conf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(automation, "emulator_version", lambda: "0.85.1")
    info = video.emulator_info()
    assert info is not None
    assert (info.name, info.version, info.core, info.cpu_cycles) == (
        "dosbox-automation",
        "0.85.1",
        "dynamic",
        "45000",
    )
    monkeypatch.setattr(automation, "emulator_version", lambda: None)
    assert video.emulator_info() is None


def test_record_video_refuses_a_frame_count_mismatch(tmp_path: Path) -> None:
    output = _output(log="x101:7:0:5:0,102:7:1:5:1,103:8:2:6:2,104:8:3:6:1,105:9:4:7:1")

    with pytest.raises(video.VideoCaptureError, match="3 video frames"):
        _record(tmp_path, output=output, video_frames=3)
    assert not (tmp_path / "out" / "meta.json").exists()


def test_record_video_refuses_no_recording(tmp_path: Path) -> None:
    with pytest.raises(video.VideoCaptureError, match=r"no \.avi"):
        _record(tmp_path, output=_output(), video_frames=None)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cs": "100"}, "prefix"),
        ({"end": "xunknown"}, "expected 'hold' or 'capped'"),
        ({"log": "x101:7"}, "malformed entry"),
        ({"log": "x101:7:0"}, "malformed entry"),
        ({"pal0": "x00"}, "initial palette"),
        ({"pal": "x103:8:" + "00" * 96}, "palette band"),
        ({"pal": "x103:0:00"}, "palette band"),
        ({"cs": "xabc"}, "'cs'.*not a number"),
        ({"log": "x101:x:0:5:0"}, "'log'.*not a number"),
        ({"log": "x101:7:0:5:x"}, "'log'.*not a number"),
        ({"pal0": "x0"}, "'pal0'.*not hex"),
        ({"pal": "x103:1:" + "zz" * 96}, "'pal'.*not hex"),
    ],
)
def test_decode_video_log_refuses_malformed_output(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(video.VideoCaptureError, match=message):
        video.decode_video_log(_output(**overrides))


def test_palette_changes_keep_prior_frames_when_filling_a_gap() -> None:
    pal = "x102:1:" + "3f" * 96 + ",103:0:" + "01" * 96 + ",103:2:" + "02" * 96
    changes = video.decode_video_log(_output(pal=pal)).palettes.changes
    assert [change.frame for change in changes] == [102, 103]
    assert changes[1].first == 0
    assert len(changes[1].rgb) == 96
    assert changes[1].rgb[32:64] == ((255, 255, 255),) * 32


@pytest.mark.parametrize("frame_count", [2, 4])
def test_record_video_accepts_one_frame_of_slack(tmp_path: Path, frame_count: int) -> None:
    out_dir, capture = _record(tmp_path, output=_output(), video_frames=frame_count)
    assert load_video_capture(out_dir) == capture


def test_record_video_refuses_malformed_avi_without_metadata(tmp_path: Path) -> None:
    recording = tmp_path / "recording"
    recording.mkdir()
    (recording / "bad.avi").write_bytes(b"not an avi")
    mock = MockAutomation(lambda _lua: _output())
    with pytest.raises(video.VideoCaptureError, match="recording cannot be used"):
        video.record_video(
            lambda: nullcontext(mock),
            tmp_path / "out",
            recording,
            keys=KEYS,
            layout=playone.UNPATCHED,
            film=FILM,
            provenance={},
        )
    assert not (tmp_path / "out" / "meta.json").exists()


def test_a_stream_log_may_carry_emulator_lines_after_the_trailer(
    tmp_path: Path, logs_dir: Path
) -> None:
    log = _stream_log("AAA", 3) + b"[F:00009 T:00:00:01.000] script completed: ok\n"
    (logs_dir / "lua-debug-1-a.log").write_bytes(log)

    video._file_stream("AAA", tmp_path / "stream.log", rows=3)


@pytest.mark.parametrize(
    ("log", "message"),
    [
        ("x101:7:0:5:0,103:8:1:6:1,104:9:2:7:1", "ascend by one"),
        ("x101:7:0:5:0,102:8:1:6:1,103:2:2:7:1", "film_tick falls"),
    ],
)
def test_record_video_reports_an_invalid_log_as_a_capture_error(
    tmp_path: Path, log: str, message: str
) -> None:
    # capture-video catches VideoCaptureError; a bare ArtifactError would end it in a traceback.
    with pytest.raises(video.VideoCaptureError, match=message):
        _record(tmp_path, output=_output(log=log), video_frames=3)
    assert not (tmp_path / "out" / "meta.json").exists()


_JUNK: tuple[object, ...] = (None, 5, "", "x", "xzz", "x-1", "x::", "x,,", "x1.5", "x 7")


def _corruptions() -> list[tuple[str, dict[str, object]]]:
    """Every key replaced with junk, and every sub-field of each key's first entry too."""
    base = _output(pal="x103:1:" + "3f" * 96)
    cases: list[tuple[str, dict[str, object]]] = []
    for key, value in base.items():
        cases.append((f"{key}=<deleted>", {k: v for k, v in base.items() if k != key}))
        cases.extend((f"{key}={junk!r}", {**base, key: junk}) for junk in _JUNK)
        if not isinstance(value, str):
            continue
        first, _, rest = value[1:].partition(",")
        parts = first.split(":")
        for index in range(len(parts)):
            for junk in ("", "zz", "-1", "1.5", "9" * 30):
                entry = ":".join(junk if i == index else p for i, p in enumerate(parts))
                text = "x" + entry + ("," + rest if rest else "")
                cases.append((f"{key}[{index}]={junk!r}", {**base, key: text}))
    return cases


@pytest.mark.parametrize(
    "output", [case for _, case in _corruptions()], ids=[i for i, _ in _corruptions()]
)
def test_decode_video_log_raises_only_video_capture_error(output: dict[str, object]) -> None:
    # A garbled field either decodes or raises the capture's own error; a bare ValueError or
    # TypeError would surface as a traceback instead of a refused capture.
    with suppress(video.VideoCaptureError):
        video.decode_video_log(output)


def test_video_script_without_a_token_logs_no_pictures() -> None:
    text = _script()

    assert "debugmsg" not in text


def test_the_stream_header_is_the_scripts_first_statement() -> None:
    text = _script(stream_token="ab12")  # noqa: S106 - a log token, not a secret

    assert text.startswith('dosbox.debugmsg("hab12:')


@pytest.mark.parametrize("layout", [playone.UNPATCHED, playone.PATCH3])
def test_video_script_with_a_token_logs_one_picture_a_frame(layout: playone.PlayoneLayout) -> None:
    text = _script(stream_token="ab12", layout=layout)  # noqa: S106 - a log token, not a secret

    page_a, page_b = layout.composed_pages
    assert f'dosbox.debugmsg("hab12:{layout.name}:1")' in text
    assert f"dosbox.mem_read_word(DS, 0x{page_a:04X})" in text
    assert f"dosbox.mem_read_word(DS, 0x{page_b:04X})" in text
    assert text.count('dosbox.debugmsg("p"') == 1
    loop = text[text.index("for i = 1") : text.index("dosbox.capture_stop()")]
    assert 'dosbox.debugmsg("p"' in loop
    assert text.index('dosbox.debugmsg("hab12') < text.index("for i = 1")
    assert text.count('dosbox.debugmsg("e" .. out["end"])') == 1
    assert text.index('dosbox.debugmsg("e"') < text.index("dosbox.capture_stop()")


def test_video_script_refuses_a_token_that_is_not_alphanumeric() -> None:
    with pytest.raises(ValueError, match="alphanumeric"):
        _script(stream_token='a"b')  # noqa: S106 - a log token, not a secret


def _stream_log(token: str, pictures: int, *, end: bool = True, header: bool = True) -> bytes:
    lines = [f"debugmsg: h{token}:UNPATCHED:1"] if header else []
    lines += [f"debugmsg: p{n}:1:{'00' * 4}" for n in range(pictures)]
    if end:
        lines.append("debugmsg: exhold")
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture
def logs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(video, "emulator_log_dir", lambda: logs)
    return logs


def test_the_stream_finder_picks_the_log_that_carries_its_token(logs_dir: Path) -> None:
    (logs_dir / "lua-debug-1-a.log").write_bytes(_stream_log("AAA", 1))
    (logs_dir / "lua-debug-2-b.log").write_bytes(_stream_log("BBB", 1))

    assert video._find_stream_log("BBB", logs_dir) == logs_dir / "lua-debug-2-b.log"


def test_the_emulator_log_dir_follows_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert video.emulator_log_dir() == tmp_path / "xdg" / "dosbox-automation" / "logs"

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert video.emulator_log_dir() == tmp_path / "local" / "dosbox-automation" / "logs"


def test_the_stream_finder_refuses_no_log_and_two_logs(logs_dir: Path) -> None:
    (logs_dir / "lua-debug-1-a.log").write_bytes(_stream_log("AAA", 1))
    (logs_dir / "lua-debug-2-b.log").write_bytes(_stream_log("AAA", 1))

    with pytest.raises(video.VideoCaptureError, match="found 2"):
        video._find_stream_log("AAA", logs_dir)
    with pytest.raises(video.VideoCaptureError, match="found no"):
        video._find_stream_log("ZZZ", logs_dir)


def test_a_stream_log_is_moved_when_its_pictures_and_trailer_match(
    tmp_path: Path, logs_dir: Path
) -> None:
    source = logs_dir / "lua-debug-1-a.log"
    source.write_bytes(_stream_log("AAA", 3))
    dest = tmp_path / "out" / "stream.log"
    dest.parent.mkdir()

    video._file_stream("AAA", dest, rows=3)

    assert dest.read_bytes() == _stream_log("AAA", 3)
    assert not source.exists()


@pytest.mark.parametrize(
    ("log", "message"),
    [
        (_stream_log("AAA", 2), "2 pictures but the log has 3 rows"),
        (_stream_log("AAA", 3, end=False), "end trailer"),
        (
            _stream_log("AAA", 3, end=False) + b"debugmsg: exhold\ndebugmsg: p3:1:00\n",
            "end trailer",
        ),
    ],
)
def test_a_stream_log_that_does_not_match_is_refused(
    tmp_path: Path, logs_dir: Path, log: bytes, message: str
) -> None:
    (logs_dir / "lua-debug-1-a.log").write_bytes(log)
    dest = tmp_path / "stream.log"

    with pytest.raises(video.VideoCaptureError, match=message):
        video._file_stream("AAA", dest, rows=3)


class _StreamRunner:
    """A runner that writes the emulator's debug log for the script's token, as dosbox would."""

    def __init__(self, logs: Path, output: dict[str, object]) -> None:
        self._logs = logs
        self._output = output
        self.debug: list[bool] = []

    def run_script(self, text: str, *, timeout: float, debug: bool = False) -> dict[str, object]:  # noqa: ARG002
        self.debug.append(debug)
        token = re.search(r'debugmsg\("h([A-Za-z0-9]+):', text)
        assert token is not None
        if debug:
            (self._logs / "lua-debug-9-run.log").write_bytes(_stream_log(token[1], 3))
        return self._output


def test_record_video_with_a_stream_runs_in_debug_and_files_the_log(
    tmp_path: Path, logs_dir: Path
) -> None:
    out_dir, recording = tmp_path / "out", tmp_path / "recording"
    recording.mkdir()
    (recording / "capture-0001.avi").write_bytes(build_avi([bytes([n]) * 3 for n in range(3)], []))
    runner = _StreamRunner(logs_dir, _output())

    video.record_video(
        lambda: nullcontext(runner),
        out_dir,
        recording,
        keys=KEYS,
        layout=playone.UNPATCHED,
        film=FILM,
        provenance={},
        stream_to=out_dir / "stream.log",
    )

    assert runner.debug == [True]
    assert (out_dir / "stream.log").exists()
    assert not (logs_dir / "lua-debug-9-run.log").exists()
    assert (out_dir / "meta.json").exists()


#: The single-pass scripts as they were before the segment refactor; their text must not change.
_GOLDEN_PLAIN = r"""local DS = 0x0F46
local out = dosbox.output
local function wait_until(f) while dosbox.frame() < f do dosbox.wait_frames(1) end end
local H = {}
for i = 0, 255 do H[string.char(i)] = string.format("%02x", i) end
wait_until(1200)
for _, k in ipairs({"KBD_c", "KBD_enter"}) do
  dosbox.wait_frames(20); dosbox.key(k, true); dosbox.wait_frames(5); dosbox.key(k, false)
end
dosbox.mouse_move(-2000, 2000)
dosbox.capture_start()
out.cs = "x" .. dosbox.frame()
out.pal0 = "x" .. dosbox.mem_read(DS, 0x2768, 768):gsub(".", H)
local tr, pl, lt, hold, ppal = {}, {}, -1, 0, dosbox.mem_read(DS, 0x2768, 768)
out["end"] = "xcapped"
for i = 1, 500 do
  dosbox.wait_frames(1)
  local f = dosbox.frame()
  local t = dosbox.mem_read_word(DS, 0x4896); local g = dosbox.mem_read_word(DS, 0x22B8)
  local sc = dosbox.mem_read_word(DS, 0x489A); local st = dosbox.mem_read_word(DS, 0x22DC)
  tr[#tr + 1] = f .. ":" .. t .. ":" .. g .. ":" .. sc .. ":" .. st
  local pal = dosbox.mem_read(DS, 0x2768, 768)
  if pal ~= ppal then
    for b = 0, 7 do
      local s = pal:sub(b * 96 + 1, b * 96 + 96)
      if s ~= ppal:sub(b * 96 + 1, b * 96 + 96) then pl[#pl + 1] = f .. ":" .. b .. ":" .. s:gsub(".", H) end
    end
    ppal = pal
  end
  if t == lt then hold = hold + 1 else hold = 0; lt = t end
  if t > 0 and hold >= 30 then out["end"] = "xhold"; break end
end
dosbox.capture_stop()
out.log = "x" .. table.concat(tr, ",")
out.pal = "x" .. table.concat(pl, ",")
out.done = true
"""
_GOLDEN_STREAMED = r"""dosbox.debugmsg("hab12:patch3:1")
local DS = 0x0E66
local out = dosbox.output
local function wait_until(f) while dosbox.frame() < f do dosbox.wait_frames(1) end end
local H = {}
for i = 0, 255 do H[string.char(i)] = string.format("%02x", i) end
wait_until(1200)
for _, k in ipairs({"KBD_c", "KBD_enter"}) do
  dosbox.wait_frames(20); dosbox.key(k, true); dosbox.wait_frames(5); dosbox.key(k, false)
end
dosbox.mouse_move(-2000, 2000)
dosbox.capture_start()
out.cs = "x" .. dosbox.frame()
out.pal0 = "x" .. dosbox.mem_read(DS, 0x20EE, 768):gsub(".", H)
local tr, pl, lt, hold, ppal = {}, {}, -1, 0, dosbox.mem_read(DS, 0x20EE, 768)
out["end"] = "xcapped"
for i = 1, 500 do
  dosbox.wait_frames(1)
  local f = dosbox.frame()
  local w0 = dosbox.mem_read_word(DS, 0x1C50); local w1 = dosbox.mem_read_word(DS, 0x1C52)
  local b0 = dosbox.mem_read(w0, 0, 61440); local b1 = dosbox.mem_read(w1, 0, 61440)
  local a = dosbox.mem_read(0xA000, 0, 61440)
  local fl = (a == b0 and 1 or 0) + (a == b1 and 2 or 0)
  dosbox.debugmsg("p" .. f .. ":" .. fl .. ":" .. (fl == 1 and b0 or b1):gsub(".", H))
  local t = dosbox.mem_read_word(DS, 0x421C); local g = dosbox.mem_read_word(DS, 0x1C3E)
  local sc = dosbox.mem_read_word(DS, 0x4220); local st = dosbox.mem_read_word(DS, 0x1C62)
  tr[#tr + 1] = f .. ":" .. t .. ":" .. g .. ":" .. sc .. ":" .. st
  local pal = dosbox.mem_read(DS, 0x20EE, 768)
  if pal ~= ppal then
    for b = 0, 7 do
      local s = pal:sub(b * 96 + 1, b * 96 + 96)
      if s ~= ppal:sub(b * 96 + 1, b * 96 + 96) then pl[#pl + 1] = f .. ":" .. b .. ":" .. s:gsub(".", H) end
    end
    ppal = pal
  end
  if t == lt then hold = hold + 1 else hold = 0; lt = t end
  if t > 0 and hold >= 30 then out["end"] = "xhold"; break end
end
dosbox.debugmsg("e" .. out["end"])
dosbox.capture_stop()
out.log = "x" .. table.concat(tr, ",")
out.pal = "x" .. table.concat(pl, ",")
out.done = true
"""


def test_the_single_pass_scripts_are_unchanged() -> None:
    assert _script() == _GOLDEN_PLAIN
    assert _script(stream_token="ab12", layout=playone.PATCH3) == _GOLDEN_STREAMED  # noqa: S106 - a log token, not a secret


@pytest.mark.parametrize(
    ("first", "last", "length", "expected"),
    [
        (101, 105, 10, [(101, 105)]),
        (101, 101, 100, [(101, 101)]),
        (0, 10, 5, [(0, 4), (4, 8), (8, 10)]),
        (0, 8, 5, [(0, 4), (4, 8)]),
        (0, 3, 2, [(0, 1), (1, 2), (2, 3)]),
    ],
)
def test_stream_segments_cover_the_frames_with_one_frame_overlaps(
    first: int, last: int, length: int, expected: list[tuple[int, int]]
) -> None:
    ranges = video.stream_segments(first, last, length)

    assert ranges == expected
    assert ranges[0][0] == first
    assert ranges[-1][1] == last
    assert all(b - a + 1 <= length for a, b in ranges)
    assert all(next_a == prev_b for (_, prev_b), (next_a, _) in itertools.pairwise(ranges))


@pytest.mark.parametrize(
    ("first", "last", "length", "message"),
    [(0, 10, 1, "at least 2"), (0, 10, 0, "at least 2"), (5, 4, 100, "are empty")],
)
def test_stream_segments_refuse_a_short_segment_or_empty_frames(
    first: int, last: int, length: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        video.stream_segments(first, last, length)


def test_segment_script_boots_then_skips_and_logs_each_frame_of_its_range() -> None:
    text = luagen.segment_script(
        keys=KEYS,
        layout=playone.PATCH3,
        first=500,
        last=699,
        stream_token="ab12",  # noqa: S106 - a log token
    )

    assert text.startswith('dosbox.debugmsg("hab12:patch3:1")\n')
    assert text.index('dosbox.debugmsg("hab12') < text.index("wait_until(1200)")
    assert text.index("dosbox.key(k, false)") < text.index("dosbox.capture_start()")
    assert text.index("dosbox.capture_start()") < text.index("while dosbox.frame() < 499 do")
    assert "dosbox.wait_frames(math.min(499 - dosbox.frame(), 500))" in text
    assert "for e = 500, 699 do" in text
    assert "  dosbox.wait_frames(1)\n  local f = dosbox.frame()\n" in text
    assert 'if f ~= e then out.bad = "x" .. f; break end' in text
    assert (
        text.index("for e = 500")
        < text.index('dosbox.debugmsg("p"')
        < text.index('dosbox.debugmsg("exseg")')
    )
    assert text.endswith('dosbox.debugmsg("exseg")\ndosbox.capture_stop()\nout.done = true\n')
    assert 'out.cs = "x" .. dosbox.frame()' in text


def test_segment_script_from_frame_one_has_nothing_to_skip() -> None:
    text = luagen.segment_script(
        keys=KEYS,
        layout=playone.UNPATCHED,
        first=1,
        last=3,
        stream_token="a",  # noqa: S106 - a log token
    )

    assert "while dosbox.frame() < 0 do" in text


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"first": 0, "last": 5}, "first must be at least 1"),
        ({"first": 6, "last": 5}, "is empty"),
        ({"first": 1, "last": 5, "stream_token": 'a"b'}, "alphanumeric"),
    ],
)
def test_segment_script_refuses_bad_bounds_and_tokens(
    kwargs: dict[str, object], message: str
) -> None:
    args: dict[str, object] = {"keys": KEYS, "layout": playone.UNPATCHED, "stream_token": "ab12"}
    args.update(kwargs)
    with pytest.raises(ValueError, match=message):
        luagen.segment_script(**args)  # type: ignore[arg-type]


def _frame_line(frame: int, *, hex_byte: str = "00") -> bytes:
    prefix = f"[F:{frame:05d} T:00:00:01.000] "
    return f"{prefix}debugmsg: p{frame}:1:{hex_byte * 4}\n".encode()


class _SegmentRunner:
    """Answers a recording as dosbox would: pass 0 plain, each segment with its own debug log."""

    def __init__(
        self,
        logs: Path,
        pass0: dict[str, object],
        *,
        cs: str = "x100",
        differ_at: int | None = None,
        silent_segment: int | None = None,
    ) -> None:
        self._logs = logs
        self._pass0 = pass0
        self._cs = cs
        self._differ_at = differ_at
        self._silent = silent_segment
        self.segments: list[tuple[int, int]] = []
        self.debug: list[bool] = []

    def run_script(
        self,
        text: str,
        *,
        timeout: float,  # noqa: ARG002
        debug: bool = False,
    ) -> dict[str, object]:
        self.debug.append(debug)
        if not debug:
            return self._pass0
        token = re.search(r'debugmsg\("h([A-Za-z0-9]+):', text)
        span = re.search(r"for e = (\d+), (\d+) do", text)
        assert token is not None
        assert span is not None
        first, last = int(span[1]), int(span[2])
        self.segments.append((first, last))
        number = len(self.segments)
        if number != self._silent:
            lines = [f"[F:00001 T:00:00:00.000] debugmsg: h{token[1]}:UNPATCHED:1\n".encode()]
            for frame in range(first, last + 1):
                hex_byte = "ff" if first == frame == self._differ_at else "00"
                lines.append(_frame_line(frame, hex_byte=hex_byte))
            lines.append(b"[F:00009 T:00:00:01.000] debugmsg: exseg\n")
            lines.append(b"[F:00010 T:00:00:01.000] script completed: ok\n")
            (self._logs / f"lua-debug-{number}-seg.log").write_bytes(b"".join(lines))
        return {"done": True, "cs": self._cs}


def _pass0(frames: int) -> dict[str, object]:
    rows = ",".join(f"{101 + n}:{7 if n == 0 else 8}:{n}:5:{n}" for n in range(frames))
    return _output(log=f"x{rows}")


def _segmented(
    tmp_path: Path,
    logs_dir: Path,
    *,
    frames: int = 7,
    segment: int = 3,
    runner_args: dict[str, Any] | None = None,
) -> tuple[Path, _SegmentRunner, Path, VideoCapture]:
    out_dir, recording = tmp_path / "out", tmp_path / "recording"
    recording.mkdir()
    (recording / "capture-0001.avi").write_bytes(
        build_avi([bytes([n]) * 3 for n in range(frames)], [])
    )
    runner = _SegmentRunner(logs_dir, _pass0(frames), **(runner_args or {}))

    def open_segment(capture_dir: Path) -> Callable[[], AbstractContextManager[Any]]:
        assert capture_dir.is_dir()
        return lambda: nullcontext(runner)

    progress: list[str] = []
    capture = video.record_video(
        lambda: nullcontext(runner),
        out_dir,
        recording,
        keys=KEYS,
        layout=playone.UNPATCHED,
        film=FILM,
        provenance={},
        stream_to=out_dir / "stream.log",
        stream_segment=segment,
        open_segment=open_segment,
        progress=progress.append,
    )
    assert progress[0] == "segment 1 of 3: frames 101 to 103"
    return out_dir, runner, recording, capture


def test_a_segmented_stream_merges_the_segments_into_one_log(
    tmp_path: Path, logs_dir: Path
) -> None:
    out_dir, runner, recording, capture = _segmented(tmp_path, logs_dir)

    assert runner.debug == [False, True, True, True]
    assert runner.segments == [(101, 103), (103, 105), (105, 107)]
    lines = (out_dir / "stream.log").read_bytes().splitlines(keepends=True)
    assert lines[0].startswith(b"[F:00001 T:00:00:00.000] debugmsg: h")
    assert lines[0].endswith(b":UNPATCHED:1\n")
    assert lines[1:-1] == [_frame_line(frame) for frame in range(101, 108)]
    assert lines[-1] == b"[F:00107 T:00:00:01.000] debugmsg: exhold\n"
    assert capture.rows == 7
    assert not any(logs_dir.glob("lua-debug-*.log"))
    assert not list(recording.parent.glob("segment-*"))
    assert (out_dir / "meta.json").exists()


def test_an_overlap_that_differs_is_refused_naming_the_frame(
    tmp_path: Path, logs_dir: Path
) -> None:
    with pytest.raises(video.VideoCaptureError, match=r"segment 3 differs.*frame 105"):
        _segmented(tmp_path, logs_dir, runner_args={"differ_at": 105})
    assert not (tmp_path / "out" / "meta.json").exists()


def test_a_segment_that_began_another_frame_is_refused(tmp_path: Path, logs_dir: Path) -> None:
    with pytest.raises(video.VideoCaptureError, match="began its capture at frame 102, not 100"):
        _segmented(tmp_path, logs_dir, runner_args={"cs": "x102"})


def test_a_segment_without_its_log_is_refused(tmp_path: Path, logs_dir: Path) -> None:
    with pytest.raises(video.VideoCaptureError, match="found no"):
        _segmented(tmp_path, logs_dir, runner_args={"silent_segment": 2})


def test_a_segmented_stream_needs_its_opener(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="stream_to and open_segment"):
        video.record_video(
            lambda: nullcontext(MockAutomation(lambda _lua: _output())),
            tmp_path / "out",
            tmp_path,
            keys=KEYS,
            layout=playone.UNPATCHED,
            film=FILM,
            provenance={},
            stream_segment=100,
        )
