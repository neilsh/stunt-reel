"""Video capture: decode the log a recording script writes, and run the recording.

A video capture is one dosbox-automation AVI of the whole film plus a per-frame tick log and a
palette log, replacing a dump of every picked frame. This module decodes what
:func:`stunt_reel.tac.luagen.video_script` returns; every number in the log is an emulated frame
or a clock word, and every palette value is a 6-bit DAC unit scaled to 8 bits the way
:func:`stunt_reel.tac.plan.dac_rgb` does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from stunt_reel.avi import AviError, video_only
from stunt_reel.parity_artifacts import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    SCHEMA_VERSION,
    VIDEO_FILE,
    VIDEO_KIND,
    FilmId,
    Geometry,
    PaletteChange,
    PaletteLog,
    TickLog,
    VideoCapture,
    write_video_capture,
)
from stunt_reel.tac import luagen, plan
from stunt_reel.tac.framebuffer import END_HOLD_FRAMES

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from contextlib import AbstractContextManager
    from pathlib import Path

    from stunt_reel.tac.automation import ScriptRunner
    from stunt_reel.tac.playone import PlayoneLayout

__all__ = [
    "VIDEO_MAX_FRAMES",
    "VideoCaptureError",
    "VideoLog",
    "decode_video_log",
    "film_start_frame",
    "record_video",
]

#: Cap on a recording, in emulated frames: 7.1 minutes at 70.09 Hz, well past the longest
#: survey film (about 257 s).
VIDEO_MAX_FRAMES: int = 30000
#: Seconds a recording may take: the cap's worth of frames plus the encoder's time.
VIDEO_TIMEOUT_SECONDS: float = 1800.0
#: Frames the video and the log may differ by (the frame the recording starts on).
_FRAME_SLACK: int = 1
_BAND_ENTRIES: int = 256 // luagen.PALETTE_BANDS
_BAND_BYTES: int = _BAND_ENTRIES * 3


class VideoCaptureError(RuntimeError):
    """A recording or its log cannot be a capture."""


@dataclass(frozen=True)
class VideoLog:
    """What one recording script logged, decoded."""

    capture_start_frame: int
    end: str
    log: TickLog
    palettes: PaletteLog


def _text(output: Mapping[str, Any], key: str) -> str:
    value = output.get(key)
    if not isinstance(value, str) or not value.startswith("x"):
        raise VideoCaptureError(f"video output {key!r} is missing or lacks its letter prefix")
    return value[1:]


def _number(text: str, key: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise VideoCaptureError(f"video output {key!r}: {text!r} is not a number") from None


def _hex(text: str, key: str) -> bytes:
    try:
        return bytes.fromhex(text)
    except ValueError:
        raise VideoCaptureError(f"video output {key!r}: {text[:16]!r} is not hex") from None


def _fields(item: str, count: int, key: str) -> list[str]:
    parts = item.split(":")
    if len(parts) != count:
        raise VideoCaptureError(f"video output {key!r} has a malformed entry {item!r}")
    return parts


def _decode_changes(
    text: str, initial: tuple[tuple[int, int, int], ...]
) -> tuple[PaletteChange, ...]:
    """One change per frame, spanning its first to last changed band.

    Bands between them that did not change are filled from the palette as it stood, so a frame
    with bands 0 and 2 changed still reads as one contiguous write and the changes ascend.
    """
    by_frame: dict[int, dict[int, bytes]] = {}
    for item in filter(None, text.split(",")):
        frame_text, band_text, hexed = _fields(item, 3, "pal")
        data, band = _hex(hexed, "pal"), _number(band_text, "pal")
        if len(data) != _BAND_BYTES or not 0 <= band < luagen.PALETTE_BANDS:
            raise VideoCaptureError(f"palette band {band_text} at frame {frame_text} is malformed")
        by_frame.setdefault(_number(frame_text, "pal"), {})[band] = data
    state = list(initial)
    changes: list[PaletteChange] = []
    for frame in sorted(by_frame):
        bands = by_frame[frame]
        low, high = min(bands), max(bands)
        rgb: list[tuple[int, int, int]] = []
        for band in range(low, high + 1):
            span = slice(band * _BAND_ENTRIES, (band + 1) * _BAND_ENTRIES)
            if band in bands:
                state[span] = plan.dac_rgb(bands[band])
            rgb.extend(state[span])
        changes.append(PaletteChange(frame=frame, first=low * _BAND_ENTRIES, rgb=tuple(rgb)))
    return tuple(changes)


def decode_video_log(output: Mapping[str, Any]) -> VideoLog:
    """Decode the output table :func:`~stunt_reel.tac.luagen.video_script` returns.

    Raises ``VideoCaptureError`` for incomplete or malformed output, including a field that is
    not a number or not hex. Log ordering is checked when the capture is validated.
    """
    if output.get("done") is not True:
        raise VideoCaptureError("the recording script did not finish")
    start = _text(output, "cs")
    end = _text(output, "end")
    if end not in ("hold", "capped"):
        raise VideoCaptureError(f"the recording ended {end!r}, expected 'hold' or 'capped'")
    frames: list[int] = []
    film: list[int] = []
    ticks: list[int] = []
    for item in filter(None, _text(output, "log").split(",")):
        f, t, g = _fields(item, 3, "log")
        frames.append(_number(f, "log"))
        film.append(_number(t, "log"))
        ticks.append(_number(g, "log"))
    pal0 = _hex(_text(output, "pal0"), "pal0")
    if len(pal0) != plan.PALETTE_BYTES:
        raise VideoCaptureError(f"the initial palette holds {len(pal0)} bytes")
    initial = tuple(plan.dac_rgb(pal0))
    return VideoLog(
        capture_start_frame=_number(start, "cs"),
        end=end,
        log=TickLog(frame=tuple(frames), film_tick=tuple(film), global_tick=tuple(ticks)),
        palettes=PaletteLog(
            initial=initial, changes=_decode_changes(_text(output, "pal"), initial)
        ),
    )


def film_start_frame(log: TickLog) -> int:
    """The first logged frame whose film clock differs from the row before it.

    Raises ``VideoCaptureError`` if the clock never changes.
    """
    for index in range(1, len(log.frame)):
        if log.film_tick[index] != log.film_tick[index - 1]:
            return log.frame[index]
    raise VideoCaptureError("the film clock never moved")


def record_video(
    open_runner: Callable[[], AbstractContextManager[ScriptRunner]],
    out_dir: Path,
    recording_dir: Path,
    *,
    keys: Sequence[str],
    layout: PlayoneLayout,
    film: FilmId,
    provenance: Mapping[str, str],
    cap: int = VIDEO_MAX_FRAMES,
) -> VideoCapture:
    """Run the recording script, then file its AVI and log into *out_dir*.

    The emulator writes ``*.avi`` into *recording_dir* (its ``capture_dir``) and finishes the
    file when the runner's context closes, so the AVI is read after that. Its audio is stripped
    into ``out_dir / capture.avi``, the frame count must match the log's rows to within one,
    and ``meta.json`` is written last. A failure can leave the stripped AVI in *out_dir*.

    Raises ``VideoCaptureError`` for an unusable recording, including an AVI parsing error;
    runner, validation, and filesystem errors also propagate.
    """
    script = luagen.video_script(keys=keys, cap=cap, end_hold=END_HOLD_FRAMES, layout=layout)
    with open_runner() as runner:
        output = runner.run_script(script, timeout=VIDEO_TIMEOUT_SECONDS)
    decoded = decode_video_log(output)
    recordings = sorted(recording_dir.glob("*.avi"))
    if len(recordings) != 1:
        raise VideoCaptureError(
            f"expected one .avi in {recording_dir}, found "
            + (f"{len(recordings)}" if recordings else "no .avi")
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        video_frames = video_only(recordings[0], out_dir / VIDEO_FILE)
    except AviError as exc:
        raise VideoCaptureError(f"the recording cannot be used: {exc}") from exc
    rows = len(decoded.log.frame)
    if abs(video_frames - rows) > _FRAME_SLACK:
        raise VideoCaptureError(
            f"the recording holds {video_frames} video frames but the log has {rows} rows"
        )
    capture = VideoCapture(
        schema_version=SCHEMA_VERSION,
        kind=VIDEO_KIND,
        film=film,
        geometry=Geometry(width=CAPTURE_WIDTH, height=CAPTURE_HEIGHT),
        playone_build=layout.name,
        cpu_profile="capture",
        capture_start_frame=decoded.capture_start_frame,
        film_start_frame=film_start_frame(decoded.log),
        end=decoded.end,
        log=decoded.log,
        palettes=decoded.palettes,
    )
    write_video_capture(
        out_dir,
        capture,
        diagnostics={
            "video_frames": video_frames,
            "rows": rows,
            "palette_changes": len(decoded.palettes.changes),
            "dgroup_segment": f"{layout.ds:04X}",
            **provenance,
        },
    )
    return capture
