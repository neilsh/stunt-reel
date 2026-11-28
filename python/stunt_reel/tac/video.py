"""Video capture: decode the log a recording script writes, and run the recording.

A video capture is one dosbox-automation AVI of the whole film plus a per-frame tick log and a
palette log, replacing a dump of every picked frame. This module decodes what
:func:`stunt_reel.tac.luagen.video_script` returns; every number in the log is an emulated frame
or a clock word, and every palette value is a 6-bit DAC unit scaled to 8 bits the way
:func:`stunt_reel.tac.plan.dac_rgb` does.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

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
    "stream_segments",
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
#: Bytes of an emulator debug log searched for the stream's header line.
_LOG_HEAD_BYTES: int = 4096


class StreamScriptRunner(Protocol):
    """A script runner that can send the script's debugmsg calls to the emulator's log file."""

    def run_script(self, text: str, *, timeout: float, debug: bool) -> dict[str, Any]:
        """Run *text* with debug logging on and return its output table."""
        ...


def emulator_log_dir() -> Path:
    """The directory where dosbox-automation writes its ``lua-debug-*.log`` files (Linux layout,
    observed on a cloud session; other platforms are untested)."""
    config = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config) / "dosbox-automation" / "logs"


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


def _find_stream_log(token: str, log_dir: Path) -> Path:
    """The one emulator debug log in *log_dir* whose first bytes carry this run's header line.

    Raises ``VideoCaptureError`` if none or several do (runs may share the directory).
    """
    header = f"debugmsg: h{token}:".encode()
    matches = []
    for path in sorted(log_dir.glob("lua-debug-*.log")):
        with path.open("rb") as handle:
            if header in handle.read(_LOG_HEAD_BYTES):
                matches.append(path)
    if len(matches) != 1:
        found = f"{len(matches)}" if matches else "no"
        raise VideoCaptureError(
            f"expected one emulator log for this run in {log_dir}, found {found}"
        )
    return matches[0]


def _file_stream(token: str, stream_to: Path, rows: int) -> None:
    """Move this run's emulator log to *stream_to* and check it (see :func:`_check_stream`)."""
    shutil.move(_find_stream_log(token, emulator_log_dir()), stream_to)
    _check_stream(stream_to, rows)


def _check_stream(stream_to: Path, rows: int) -> None:
    """Check a stream log holds one ``p`` line per row and an ``e`` trailer after its last one.

    The emulator adds its own lines after the trailer, which are allowed. It is read a line at a
    time: it runs to hundreds of megabytes.
    """
    pictures = 0
    closed = False
    with stream_to.open("rb") as handle:
        for line in handle:
            if b"debugmsg: p" in line:
                pictures += 1
                closed = False
            elif b"debugmsg: e" in line:
                closed = True
    if not closed:
        raise VideoCaptureError(f"the stream log {stream_to} lacks its end trailer")
    if pictures != rows:
        raise VideoCaptureError(
            f"the stream log holds {pictures} pictures but the log has {rows} rows"
        )


def stream_segments(first: int, last: int, length: int) -> list[tuple[int, int]]:
    """Inclusive frame ranges of at most *length* frames covering *first* to *last*.

    Consecutive ranges share exactly one frame, so each segment's first picture is the one the
    previous segment ended on, and merging drops the repeat. One range when the frames fit.
    Raises ``ValueError`` for *length* below 2 or *last* below *first*.
    """
    if length < 2:
        raise ValueError(f"a segment holds at least 2 frames, got {length}")
    if last < first:
        raise ValueError(f"the frames {first}..{last} are empty")
    ranges: list[tuple[int, int]] = []
    start = first
    while True:
        end = min(start + length - 1, last)
        ranges.append((start, end))
        if end == last:
            return ranges
        start = end


def _check_segment(output: Mapping[str, Any], first: int, last: int, started: int) -> None:
    """Refuse a segment pass that did not finish, went out of order or began another frame."""
    if output.get("done") is not True:
        raise VideoCaptureError(f"segment {first}..{last} did not finish")
    if "bad" in output:
        bad = _number(_text(output, "bad"), "bad")
        raise VideoCaptureError(
            f"segment {first}..{last} reached frame {bad} out of order, so its frames differ"
        )
    begun = _number(_text(output, "cs"), "cs")
    if begun != started:
        raise VideoCaptureError(
            f"segment {first}..{last} began its capture at frame {begun}, not {started}"
        )


def _merge_streams(
    sources: Sequence[Path], stream_to: Path, first: int, last: int, end: str
) -> None:
    """Write the segments' pictures as one stream log, in frame order, to *stream_to*.

    The first segment's header opens the stream. Each later segment's first picture must equal
    the previous segment's last, byte for byte, and is dropped. Other lines (segment trailers,
    the emulator's own) are dropped too. A trailer ``e<end>`` (``end`` without its ``x``) closes
    it. Raises ``VideoCaptureError`` for a repeat that differs, frames out of order, or a stream
    that does not cover *first* to *last*. Each source is read a line at a time.
    """
    expected = first
    previous: bytes | None = None
    prefix: bytes | None = None
    header: bytes | None = None
    with stream_to.open("wb") as out:
        for index, source in enumerate(sources):
            overlap_checked = index == 0
            with source.open("rb") as handle:
                for line in handle:
                    at = line.find(b"debugmsg: ")
                    if at < 0:
                        continue
                    payload = line[at + len(b"debugmsg: ") :].rstrip(b"\r\n")
                    if payload.startswith(b"h"):
                        if header is None and index == 0:
                            header = line
                            out.write(line)
                        continue
                    if not payload.startswith(b"p"):
                        continue
                    frame = _number(payload[1:].split(b":")[0].decode(), "stream picture")
                    if not overlap_checked:
                        if payload != previous:
                            raise VideoCaptureError(
                                f"segment {index + 1} differs from the one before it at frame "
                                f"{frame}: its first picture is not the last one before"
                            )
                        overlap_checked = True
                        continue
                    if frame != expected:
                        raise VideoCaptureError(
                            f"the stream reached frame {frame} where frame {expected} was due"
                        )
                    expected += 1
                    previous, prefix = payload, line[:at]
                    out.write(line)
            if not overlap_checked:
                raise VideoCaptureError(f"segment {index + 1} logged no pictures")
        if header is None:
            raise VideoCaptureError("the first segment's stream has no header line")
        if prefix is None or expected != last + 1:
            raise VideoCaptureError(f"the segments end at frame {expected - 1}, not {last}")
        out.write(prefix + b"debugmsg: e" + b"x" + end.encode() + b"\n")


def _record_segments(
    open_segment: Callable[[Path], Callable[[], AbstractContextManager[ScriptRunner]]],
    recording_dir: Path,
    stream_to: Path,
    decoded: VideoLog,
    *,
    keys: Sequence[str],
    layout: PlayoneLayout,
    length: int,
    progress: Callable[[str], None] | None,
) -> None:
    """Replay the film in segments, one emulator run each, and merge their pictures into *stream_to*.

    Each segment runs in its own empty capture directory beside *recording_dir*, deleted once the
    segment passes. The segment logs are deleted only after the merged stream is written.
    """
    frames = decoded.log.frame
    if not frames:
        raise VideoCaptureError("the recording logged no frames to stream")
    first, last = frames[0], frames[-1]
    if frames != tuple(range(first, last + 1)):
        raise VideoCaptureError("the recording's frames are not consecutive, so no segment fits")
    ranges = stream_segments(first, last, length)
    sources: list[Path] = []
    for number, (start, stop) in enumerate(ranges, start=1):
        if progress is not None:
            progress(f"segment {number} of {len(ranges)}: frames {start} to {stop}")
        token = secrets.token_hex(8)
        script = luagen.segment_script(
            keys=keys, layout=layout, first=start, last=stop, stream_token=token
        )
        capture_dir = recording_dir.parent / f"segment-{number:03d}"
        capture_dir.mkdir()
        with open_segment(capture_dir)() as runner:
            streaming = cast("StreamScriptRunner", runner)
            output = streaming.run_script(script, timeout=VIDEO_TIMEOUT_SECONDS, debug=True)
        _check_segment(output, start, stop, decoded.capture_start_frame)
        sources.append(_find_stream_log(token, emulator_log_dir()))
        shutil.rmtree(capture_dir)
    _merge_streams(sources, stream_to, first, last, decoded.end)
    _check_stream(stream_to, len(frames))
    for source in sources:
        source.unlink()


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
    stream_to: Path | None = None,
    stream_segment: int | None = None,
    open_segment: Callable[[Path], Callable[[], AbstractContextManager[ScriptRunner]]]
    | None = None,
    progress: Callable[[str], None] | None = None,
) -> VideoCapture:
    """Run the recording script, then file its AVI and log into *out_dir*.

    The emulator writes one ``*.avi`` into *recording_dir* (its ``capture_dir``); it is read
    after the runner closes. Its audio is stripped into ``out_dir / capture.avi``, whose frame
    count must match the log's rows to within one, and ``meta.json`` is written last, recording
    the AVI's hash, the layout read, the film ticks and *emulator* when given. A failure can
    leave the stripped AVI, and with *stream_to* the moved ``stream.log``, in *out_dir*, and a
    failed run leaves the emulator's debug log in its log directory.

    With *stream_to* each frame's composed picture is also logged by debugmsg; the emulator's
    log of that run is moved there and checked (see :func:`_file_stream`).

    With *stream_segment* (at least 2 frames) the recording runs first without the stream, then
    the film is replayed in segments of that many frames, each a fresh emulator run through
    *open_segment* (given an empty capture directory it writes into), and the pictures are merged
    into *stream_to* (see :func:`_record_segments`). *progress* receives a line per segment.

    Raises ``VideoCaptureError`` for an unusable recording: no or several ``.avi``, an AVI
    parsing error, a frame-count mismatch, a log the capture document refuses (frames that
    skip, a film clock that falls), a stream log that is missing or does not match, a segment
    that does not match the recording, or a failed ``meta.json`` write. Runner and other
    filesystem errors propagate. Raises ``ValueError`` for *stream_segment* without *stream_to*
    or *open_segment*, or below 2.
    """
    if stream_segment is not None and (stream_to is None or open_segment is None):
        raise ValueError("a segmented stream needs stream_to and open_segment")
    segmented = stream_segment is not None
    token = secrets.token_hex(8) if stream_to is not None and not segmented else None
    script = luagen.video_script(
        keys=keys, cap=cap, end_hold=END_HOLD_FRAMES, layout=layout, stream_token=token
    )
    with open_runner() as runner:
        if token is None:
            output = runner.run_script(script, timeout=VIDEO_TIMEOUT_SECONDS)
        else:
            streaming = cast("StreamScriptRunner", runner)
            output = streaming.run_script(script, timeout=VIDEO_TIMEOUT_SECONDS, debug=True)
    decoded = decode_video_log(output)
    recordings = sorted(recording_dir.glob("*.avi"))
    if len(recordings) != 1:
        raise VideoCaptureError(
            f"expected one .avi in {recording_dir}, found "
            + (f"{len(recordings)}" if recordings else "no .avi")
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    if stream_to is not None and token is not None:
        _file_stream(token, stream_to, len(decoded.log.frame))
    elif stream_to is not None and stream_segment is not None and open_segment is not None:
        _record_segments(
            open_segment,
            recording_dir,
            stream_to,
            decoded,
            keys=keys,
            layout=layout,
            length=stream_segment,
            progress=progress,
        )
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
