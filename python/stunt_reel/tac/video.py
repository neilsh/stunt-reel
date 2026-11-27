"""Video capture: decode the log a recording script writes, and run the recording.

A video capture is one dosbox-automation AVI of the whole film plus a per-frame tick log and a
palette log, replacing a dump of every picked frame. This module decodes what
:func:`stunt_reel.tac.luagen.video_script` returns; every number in the log is an emulated frame
or a clock word, and every palette value is a 6-bit DAC unit scaled to 8 bits the way
:func:`stunt_reel.tac.plan.dac_rgb` does.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from stunt_reel.avi import AviError, video_only
from stunt_reel.parity_artifacts import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    SCHEMA_VERSION,
    VIDEO_FILE,
    VIDEO_KIND,
    ArtifactError,
    EmulatorInfo,
    FilmId,
    Geometry,
    LayoutOffsets,
    PaletteChange,
    PaletteLog,
    TickLog,
    VideoCapture,
    VideoFileInfo,
    write_video_capture,
)
from stunt_reel.tac import automation, luagen, plan, staging
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
    "emulator_info",
    "film_start_frame",
    "layout_offsets",
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
#: The emulator's exact frame rate as numerator and denominator, which containers round.
FRAME_RATE: tuple[int, int] = (2190197, 31250)
#: The codec of the emulator's recording.
VIDEO_CODEC: str = "zmbv"
EMULATOR_NAME: str = "dosbox-automation"


class VideoCaptureError(RuntimeError):
    """A recording or its log cannot be a capture."""


class FilmClockStuck(VideoCaptureError):  # noqa: N818 - the agreed interface name
    """The film clock never moved: the signature of a stalled build, not a bad recording."""


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
    slot_clock: list[int] = []
    slot_ticks: list[int] = []
    for item in filter(None, _text(output, "log").split(",")):
        f, t, g, sc, st = _fields(item, 5, "log")
        frames.append(_number(f, "log"))
        film.append(_number(t, "log"))
        ticks.append(_number(g, "log"))
        slot_clock.append(_number(sc, "log"))
        slot_ticks.append(_number(st, "log"))
    pal0 = _hex(_text(output, "pal0"), "pal0")
    if len(pal0) != plan.PALETTE_BYTES:
        raise VideoCaptureError(f"the initial palette holds {len(pal0)} bytes")
    initial = tuple(plan.dac_rgb(pal0))
    return VideoLog(
        capture_start_frame=_number(start, "cs"),
        end=end,
        log=TickLog(
            frame=tuple(frames),
            film_tick=tuple(film),
            global_tick=tuple(ticks),
            slot_clock=tuple(slot_clock),
            slot_ticks=tuple(slot_ticks),
        ),
        palettes=PaletteLog(
            initial=initial, changes=_decode_changes(_text(output, "pal"), initial)
        ),
    )


def emulator_info(cpu: staging.CpuProfile = "capture") -> EmulatorInfo | None:
    """The emulator and the *cpu* profile's conf values, or None if its version cannot be read."""
    version = automation.emulator_version()
    if version is None:
        return None
    core, cycles = staging.cpu_settings(cpu)
    return EmulatorInfo(name=EMULATOR_NAME, version=version, core=core, cpu_cycles=cycles)


def layout_offsets(layout: PlayoneLayout) -> LayoutOffsets:
    """The DGROUP offsets a recording's log reads, with the inferred ones named."""
    read = {
        "film_clock": layout.film_clock,
        "global_tick": layout.global_tick,
        "working_palette": layout.working_palette,
        "slot_clock": layout.slot_clock,
        "slot_ticks": layout.slot_ticks,
    }
    return LayoutOffsets(
        **{name: f"0x{offset:04X}" for name, offset in read.items()},
        inferred=tuple(name for name in layout.inferred if name in read),
    )


def film_start_frame(log: TickLog) -> int:
    """The first logged frame whose film clock differs from the row before it.

    Raises ``VideoCaptureError`` if the clock never changes.
    """
    for index in range(1, len(log.frame)):
        if log.film_tick[index] != log.film_tick[index - 1]:
            return log.frame[index]
    raise FilmClockStuck("the film clock never moved")


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
    emulator: EmulatorInfo | None = None,
) -> VideoCapture:
    """Run the recording script, then file its AVI and log into *out_dir*.

    The emulator writes one ``*.avi`` into *recording_dir* (its ``capture_dir``); it is read
    after the runner closes. Its audio is stripped into ``out_dir / capture.avi``, whose frame
    count must match the log's rows to within one, and ``meta.json`` is written last, recording
    the AVI's hash, the layout read, the film ticks and *emulator* when given. A failure can
    leave the stripped AVI in *out_dir*.

    Raises ``VideoCaptureError`` for an unusable recording: no or several ``.avi``, an AVI
    parsing error, a frame-count mismatch, a log the capture document refuses (frames that
    skip, a film clock that falls) or a failed ``meta.json`` write. Runner and other filesystem
    errors propagate.
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
    stripped = out_dir / VIDEO_FILE
    capture = VideoCapture(
        schema_version=SCHEMA_VERSION,
        kind=VIDEO_KIND,
        film=film,
        geometry=Geometry(width=CAPTURE_WIDTH, height=CAPTURE_HEIGHT),
        playone_build=layout.name,
        playone_sha256=layout.sha256,
        cpu_profile="capture",
        capture_start_frame=decoded.capture_start_frame,
        film_start_frame=film_start_frame(decoded.log),
        end=decoded.end,
        log=decoded.log,
        palettes=decoded.palettes,
        video_frames=video_frames,
        rows=rows,
        palette_changes=len(decoded.palettes.changes),
        dgroup_segment=f"{layout.ds:04X}",
        captured_on=provenance.get("captured_on"),
        checkout=provenance.get("checkout"),
        sound_samples=provenance.get("sound_samples"),
        video=VideoFileInfo(
            file=VIDEO_FILE,
            sha256=hashlib.sha256(stripped.read_bytes()).hexdigest(),
            bytes=stripped.stat().st_size,
            codec=VIDEO_CODEC,
            frame_rate=FRAME_RATE,
        ),
        emulator=emulator,
        layout=layout_offsets(layout),
        film_ticks=(decoded.log.film_tick[0], decoded.log.film_tick[-1]),
    )
    try:
        write_video_capture(out_dir, capture, diagnostics={})
    except ArtifactError as exc:
        raise VideoCaptureError(f"meta.json was not written: {exc}") from exc
    return capture
