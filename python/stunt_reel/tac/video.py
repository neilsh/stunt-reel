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

from stunt_reel.parity_artifacts import PaletteChange, PaletteLog, TickLog
from stunt_reel.tac import luagen, plan

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "VIDEO_MAX_FRAMES",
    "VideoCaptureError",
    "VideoLog",
    "decode_video_log",
    "film_start_frame",
]

#: Cap on a recording, in emulated frames: 7.1 minutes at 70.09 Hz, well past the longest
#: survey film (about 257 s).
VIDEO_MAX_FRAMES: int = 30000
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
        data = bytes.fromhex(hexed)
        if len(data) != _BAND_BYTES or not 0 <= int(band_text) < luagen.PALETTE_BANDS:
            raise VideoCaptureError(f"palette band {band_text} at frame {frame_text} is malformed")
        by_frame.setdefault(int(frame_text), {})[int(band_text)] = data
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
    """Decode the output table :func:`~stunt_reel.tac.luagen.video_script` returns."""
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
        frames.append(int(f))
        film.append(int(t))
        ticks.append(int(g))
    pal0 = bytes.fromhex(_text(output, "pal0"))
    if len(pal0) != plan.PALETTE_BYTES:
        raise VideoCaptureError(f"the initial palette holds {len(pal0)} bytes")
    initial = tuple(plan.dac_rgb(pal0))
    return VideoLog(
        capture_start_frame=int(start),
        end=end,
        log=TickLog(frame=tuple(frames), film_tick=tuple(film), global_tick=tuple(ticks)),
        palettes=PaletteLog(
            initial=initial, changes=_decode_changes(_text(output, "pal"), initial)
        ),
    )


def film_start_frame(log: TickLog) -> int:
    """The first logged frame whose film clock differs from the row before it."""
    for index in range(1, len(log.frame)):
        if log.film_tick[index] != log.film_tick[index - 1]:
            return log.frame[index]
    raise VideoCaptureError("the film clock never moved")
