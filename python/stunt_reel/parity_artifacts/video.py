"""The video capture document: a video capture directory's ``meta.json``, frame log and palette
history.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from stunt_reel.parity_artifacts._fields import (
    CAPTURE_META,
    PALETTE_ENTRIES,
    SCHEMA_VERSION,
    ArtifactError,
    _as_array,
    _as_object,
    _as_string,
    _as_unsigned,
    _error,
    _optional_string,
    _optional_unsigned,
    _read_json,
    _write_json,
    _wrong_type,
)
from stunt_reel.parity_artifacts.capture import _merge_diagnostics
from stunt_reel.parity_artifacts.render import (
    FilmId,
    Geometry,
    _film_object,
    _geometry_document,
    _geometry_object,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


#: File name of the recorded video inside a video capture directory.
VIDEO_FILE = "capture.avi"
#: The ``kind`` a video capture's ``meta.json`` carries.
VIDEO_KIND = "video"


_VIDEO_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "film",
        "geometry",
        "playone_build",
        "playone_sha256",
        "cpu_profile",
        "capture_start_frame",
        "film_start_frame",
        "end",
        "log",
        "palettes",
        "video_frames",
        "rows",
        "palette_changes",
        "dgroup_segment",
        "captured_on",
        "checkout",
        "sound_samples",
        "video",
        "emulator",
        "layout",
        "film_ticks",
    }
)
_CAPTURE_ENDS = ("hold", "capped")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_U64 = 0xFFFFFFFFFFFFFFFF
_U32 = 0xFFFFFFFF


def _video_error(message: str, path: Path | None) -> ArtifactError:
    return _error("video_log", f"video log: {message}", path)


@dataclass(frozen=True)
class TickLog:
    """Per-frame clocks, one entry per recorded video frame, as parallel columns."""

    frame: tuple[int, ...]
    film_tick: tuple[int, ...]
    global_tick: tuple[int, ...]
    #: Slot pass clock and ticks word per frame (ADR 0057); both or neither.
    slot_clock: tuple[int, ...] | None = None
    slot_ticks: tuple[int, ...] | None = None


@dataclass(frozen=True)
class PaletteChange:
    """A run of palette entries the game rewrote at one frame."""

    frame: int
    first: int
    rgb: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class PaletteLog:
    """The palette at the start of the log and every later write."""

    initial: tuple[tuple[int, int, int], ...]
    changes: tuple[PaletteChange, ...]


@dataclass(frozen=True)
class VideoFileInfo:
    """The recorded video beside ``meta.json``: as the emulator wrote it, audio stripped."""

    file: str
    sha256: str
    bytes: int
    codec: str
    #: Exact frame rate as numerator and denominator; containers round it.
    frame_rate: tuple[int, int]


@dataclass(frozen=True)
class EmulatorInfo:
    """The emulator that recorded the film, and the stage conf's ``core`` and ``cpu_cycles``."""

    name: str
    version: str
    core: str
    cpu_cycles: str


@dataclass(frozen=True)
class LayoutOffsets:
    """The DGROUP offsets the log read, as ``0x`` plus four upper-case hex digits."""

    film_clock: str
    global_tick: str
    working_palette: str
    slot_clock: str | None = None
    slot_ticks: str | None = None
    #: Names of the offsets above that were inferred, not read from the build's code (ADR 0057).
    inferred: tuple[str, ...] = ()


@dataclass(frozen=True)
class VideoCapture:
    """Document written by the video capture harness as ``meta.json``."""

    schema_version: int
    kind: str
    film: FilmId
    geometry: Geometry
    playone_build: str
    cpu_profile: str
    capture_start_frame: int
    film_start_frame: int
    end: str
    log: TickLog
    palettes: PaletteLog
    #: SHA-256 of the ``PLAYONE.EXE`` that ran; absent from captures made before it was recorded.
    playone_sha256: str | None = None
    #: Whole-film fields; each is absent from a capture made before it was recorded.
    video_frames: int | None = None
    rows: int | None = None
    palette_changes: int | None = None
    dgroup_segment: str | None = None
    captured_on: str | None = None
    checkout: str | None = None
    sound_samples: str | None = None
    video: VideoFileInfo | None = None
    emulator: EmulatorInfo | None = None
    layout: LayoutOffsets | None = None
    film_ticks: tuple[int, int] | None = None

    def video_index(self, frame: int) -> int | None:
        """Index of capture *frame* relative to recording start, or ``None`` before it.

        The result is not checked against the recording's length. The log row of *frame* is one
        lower (``capture_start_frame + 1`` is row 0, AVI frame 0).
        """
        index = frame - self.capture_start_frame
        return index if index >= 0 else None

    def validate(self, path: Path | None = None) -> None:
        """Check the schema version, kind, geometry, log columns and palette history."""
        if self.schema_version != SCHEMA_VERSION:
            raise _error(
                "unsupported_version",
                f"unsupported schema version {self.schema_version}; expected {SCHEMA_VERSION}",
                path,
            )
        if not self.kind:
            raise _error("missing", "missing field kind", path)
        if self.kind != VIDEO_KIND:
            raise _video_error(f"kind is {self.kind!r}, expected {VIDEO_KIND!r}", path)
        if self.end not in _CAPTURE_ENDS:
            raise _video_error(f"end is {self.end!r}, expected one of {_CAPTURE_ENDS}", path)
        self.geometry.validate(path)
        self._validate_log(path)
        self._validate_palettes(path)
        self._validate_summary(path)

    def _validate_log(self, path: Path | None) -> None:
        log = self.log
        rows = len(log.frame)
        if len(log.film_tick) != rows or len(log.global_tick) != rows:
            raise _video_error(
                f"log columns differ in length: frame {rows}, film_tick {len(log.film_tick)}, "
                f"global_tick {len(log.global_tick)}",
                path,
            )
        if (log.slot_clock is None) != (log.slot_ticks is None):
            raise _video_error("slot_clock and slot_ticks must come together", path)
        if (
            log.slot_clock is not None
            and log.slot_ticks is not None
            and (len(log.slot_clock) != rows or len(log.slot_ticks) != rows)
        ):
            raise _video_error(
                f"log columns differ in length: frame {rows}, slot_clock "
                f"{len(log.slot_clock)}, slot_ticks {len(log.slot_ticks)}",
                path,
            )
        for index in range(1, rows):
            if log.frame[index] != log.frame[index - 1] + 1:
                raise _video_error(
                    f"frames must ascend by one: index {index} is {log.frame[index]} "
                    f"after {log.frame[index - 1]}",
                    path,
                )
        if self.film_start_frame not in log.frame:
            raise _video_error(
                f"film_start_frame {self.film_start_frame} is not a logged frame", path
            )
        start = log.frame.index(self.film_start_frame)
        for offset in range(start + 1, rows):
            if log.film_tick[offset] < log.film_tick[offset - 1]:
                raise _video_error(
                    f"film_tick falls at frame {log.frame[offset]}: {log.film_tick[offset]} "
                    f"after {log.film_tick[offset - 1]}",
                    path,
                )

    def _validate_summary(self, path: Path | None) -> None:
        """Check the whole-film fields against the log they summarise."""
        counts = (
            ("rows", self.rows, len(self.log.frame)),
            ("palette_changes", self.palette_changes, len(self.palettes.changes)),
        )
        for name, stated, actual in counts:
            if stated is not None and stated != actual:
                raise _video_error(f"{name} is {stated}, the log holds {actual}", path)
        if self.film_ticks is not None:
            logged = (self.log.film_tick[0], self.log.film_tick[-1]) if self.log.film_tick else None
            if logged != self.film_ticks:
                raise _video_error(
                    f"film_ticks {self.film_ticks} differ from the log's {logged}", path
                )
        if self.video is not None:
            if self.video.file != VIDEO_FILE:
                raise _video_error(
                    f"video.file is {self.video.file!r}, expected {VIDEO_FILE!r}", path
                )
            if _SHA256.fullmatch(self.video.sha256) is None:
                raise _video_error("video.sha256 is not 64 lower-case hex digits", path)

    def _validate_palettes(self, path: Path | None) -> None:
        palettes = self.palettes
        if len(palettes.initial) != PALETTE_ENTRIES:
            raise _video_error(
                f"the initial palette must have {PALETTE_ENTRIES} entries, "
                f"got {len(palettes.initial)}",
                path,
            )
        low = self.log.frame[0] if self.log.frame else None
        high = self.log.frame[-1] if self.log.frame else None
        previous: int | None = None
        for index, change in enumerate(palettes.changes):
            if change.first + len(change.rgb) > PALETTE_ENTRIES:
                raise _video_error(
                    f"palette change {index} writes {len(change.rgb)} entries from "
                    f"{change.first}, past entry {PALETTE_ENTRIES - 1}",
                    path,
                )
            if previous is not None and change.frame <= previous:
                raise _video_error(
                    f"palette changes must ascend: change {index} is at frame {change.frame}",
                    path,
                )
            previous = change.frame
            if low is None or high is None or not low <= change.frame <= high:
                raise _video_error(
                    f"palette change {index} at frame {change.frame} lies outside the log",
                    path,
                )


def _column(value: Any, path: Path | None, field_name: str, maximum: int) -> tuple[int, ...]:
    return tuple(
        _as_unsigned(item, path, f"{field_name}[{index}]", maximum)
        for index, item in enumerate(_as_array(value, path, field_name))
    )


def _optional_column(
    log: Mapping[str, Any], path: Path | None, name: str
) -> tuple[int, ...] | None:
    if log.get(name) is None:
        return None
    return _column(log[name], path, f"log.{name}", 0xFFFF)


def _rgb_entries(
    value: Any, path: Path | None, field_name: str
) -> tuple[tuple[int, int, int], ...]:
    entries: list[tuple[int, int, int]] = []
    for index, item in enumerate(_as_array(value, path, field_name)):
        triple = _as_array(item, path, f"{field_name}[{index}]")
        if len(triple) != 3:
            raise _wrong_type(path, f"{field_name}[{index}]", "3 channel values")
        entries.append(
            (
                _as_unsigned(triple[0], path, f"{field_name}[{index}][0]", 0xFF),
                _as_unsigned(triple[1], path, f"{field_name}[{index}][1]", 0xFF),
                _as_unsigned(triple[2], path, f"{field_name}[{index}][2]", 0xFF),
            )
        )
    return tuple(entries)


def _palette_change_object(value: Any, path: Path | None, index: int) -> PaletteChange:
    where = f"palettes.changes[{index}]"
    entry = _as_object(value, path, where)
    return PaletteChange(
        frame=_as_unsigned(entry.get("frame"), path, f"{where}.frame", _U64),
        first=_as_unsigned(entry.get("first"), path, f"{where}.first", 0xFFFF),
        rgb=_rgb_entries(entry.get("rgb"), path, f"{where}.rgb"),
    )


def _optional[T](value: Any, path: Path | None, parse: Callable[[Any, Path | None], T]) -> T | None:
    return None if value is None else parse(value, path)


def _file_info_object(value: Any, path: Path | None) -> VideoFileInfo:
    entry = _as_object(value, path, "video")
    rate = _as_array(entry.get("frame_rate"), path, "video.frame_rate")
    if len(rate) != 2:
        raise _wrong_type(path, "video.frame_rate", "a numerator and a denominator")
    return VideoFileInfo(
        file=_as_string(entry.get("file"), path, "video.file"),
        sha256=_as_string(entry.get("sha256"), path, "video.sha256"),
        bytes=_as_unsigned(entry.get("bytes"), path, "video.bytes", _U64),
        codec=_as_string(entry.get("codec"), path, "video.codec"),
        frame_rate=(
            _as_unsigned(rate[0], path, "video.frame_rate[0]", _U32),
            _as_unsigned(rate[1], path, "video.frame_rate[1]", _U32),
        ),
    )


def _emulator_object(value: Any, path: Path | None) -> EmulatorInfo:
    entry = _as_object(value, path, "emulator")
    return EmulatorInfo(
        name=_as_string(entry.get("name"), path, "emulator.name"),
        version=_as_string(entry.get("version"), path, "emulator.version"),
        core=_as_string(entry.get("core"), path, "emulator.core"),
        cpu_cycles=_as_string(entry.get("cpu_cycles"), path, "emulator.cpu_cycles"),
    )


def _layout_object(value: Any, path: Path | None) -> LayoutOffsets:
    entry = _as_object(value, path, "layout")
    inferred = entry.get("inferred")
    return LayoutOffsets(
        film_clock=_as_string(entry.get("film_clock"), path, "layout.film_clock"),
        global_tick=_as_string(entry.get("global_tick"), path, "layout.global_tick"),
        working_palette=_as_string(entry.get("working_palette"), path, "layout.working_palette"),
        slot_clock=_optional_string(entry.get("slot_clock"), path, "layout.slot_clock"),
        slot_ticks=_optional_string(entry.get("slot_ticks"), path, "layout.slot_ticks"),
        inferred=()
        if inferred is None
        else tuple(
            _as_string(item, path, f"layout.inferred[{index}]")
            for index, item in enumerate(_as_array(inferred, path, "layout.inferred"))
        ),
    )


def _film_ticks_object(value: Any, path: Path | None) -> tuple[int, int]:
    pair = _as_array(value, path, "film_ticks")
    if len(pair) != 2:
        raise _wrong_type(path, "film_ticks", "a first and a last film tick")
    return (
        _as_unsigned(pair[0], path, "film_ticks[0]", _U32),
        _as_unsigned(pair[1], path, "film_ticks[1]", _U32),
    )


def _video_object(document: Mapping[str, Any], path: Path | None) -> VideoCapture:
    """A video capture from its ``meta.json`` shape; unknown diagnostic keys are ignored."""
    if "kind" not in document:
        raise _error("missing", "missing field kind", path)
    log = _as_object(document.get("log"), path, "log")
    palettes = _as_object(document.get("palettes"), path, "palettes")
    changes = tuple(
        _palette_change_object(value, path, index)
        for index, value in enumerate(_as_array(palettes.get("changes"), path, "palettes.changes"))
    )
    return VideoCapture(
        schema_version=_as_unsigned(document.get("schema_version"), path, "schema_version", _U32),
        kind=_as_string(document["kind"], path, "kind"),
        film=_film_object(document, path),
        geometry=_geometry_object(_as_object(document.get("geometry"), path, "geometry"), path),
        playone_build=_as_string(document.get("playone_build"), path, "playone_build"),
        playone_sha256=_optional_string(document.get("playone_sha256"), path, "playone_sha256"),
        cpu_profile=_as_string(document.get("cpu_profile"), path, "cpu_profile"),
        capture_start_frame=_as_unsigned(
            document.get("capture_start_frame"), path, "capture_start_frame", _U64
        ),
        film_start_frame=_as_unsigned(
            document.get("film_start_frame"), path, "film_start_frame", _U64
        ),
        end=_as_string(document.get("end"), path, "end"),
        log=TickLog(
            frame=_column(log.get("frame"), path, "log.frame", _U64),
            film_tick=_column(log.get("film_tick"), path, "log.film_tick", _U32),
            global_tick=_column(log.get("global_tick"), path, "log.global_tick", _U32),
            slot_clock=_optional_column(log, path, "slot_clock"),
            slot_ticks=_optional_column(log, path, "slot_ticks"),
        ),
        palettes=PaletteLog(
            initial=_rgb_entries(palettes.get("initial"), path, "palettes.initial"),
            changes=changes,
        ),
        video_frames=_optional_unsigned(document.get("video_frames"), path, "video_frames", _U64),
        rows=_optional_unsigned(document.get("rows"), path, "rows", _U64),
        palette_changes=_optional_unsigned(
            document.get("palette_changes"), path, "palette_changes", _U64
        ),
        dgroup_segment=_optional_string(document.get("dgroup_segment"), path, "dgroup_segment"),
        captured_on=_optional_string(document.get("captured_on"), path, "captured_on"),
        checkout=_optional_string(document.get("checkout"), path, "checkout"),
        sound_samples=_optional_string(document.get("sound_samples"), path, "sound_samples"),
        video=_optional(document.get("video"), path, _file_info_object),
        emulator=_optional(document.get("emulator"), path, _emulator_object),
        layout=_optional(document.get("layout"), path, _layout_object),
        film_ticks=_optional(document.get("film_ticks"), path, _film_ticks_object),
    )


def _log_document(log: TickLog) -> dict[str, Any]:
    document: dict[str, Any] = {
        "frame": list(log.frame),
        "film_tick": list(log.film_tick),
        "global_tick": list(log.global_tick),
    }
    if log.slot_clock is not None:
        document["slot_clock"] = list(log.slot_clock)
    if log.slot_ticks is not None:
        document["slot_ticks"] = list(log.slot_ticks)
    return document


def _video_document(capture: VideoCapture) -> dict[str, Any]:
    film: dict[str, Any] = {}
    if capture.film.name is not None:
        film["name"] = capture.film.name
    if capture.film.flm_bytes is not None:
        film["flm_bytes"] = capture.film.flm_bytes
    if capture.film.flm_sha256 is not None:
        film["flm_sha256"] = capture.film.flm_sha256
    if capture.film.all_sha256 is not None:
        film["all_sha256"] = capture.film.all_sha256
    build: dict[str, Any] = {"playone_build": capture.playone_build}
    if capture.playone_sha256 is not None:
        build["playone_sha256"] = capture.playone_sha256
    document = {
        "schema_version": capture.schema_version,
        "kind": capture.kind,
        "film": film,
        "geometry": _geometry_document(capture.geometry),
        **build,
        "cpu_profile": capture.cpu_profile,
        "capture_start_frame": capture.capture_start_frame,
        "film_start_frame": capture.film_start_frame,
        "end": capture.end,
        "log": _log_document(capture.log),
        "palettes": {
            "initial": [list(entry) for entry in capture.palettes.initial],
            "changes": [
                {
                    "frame": change.frame,
                    "first": change.first,
                    "rgb": [list(entry) for entry in change.rgb],
                }
                for change in capture.palettes.changes
            ],
        },
    }
    document.update(_summary_document(capture))
    return document


def _summary_document(capture: VideoCapture) -> dict[str, Any]:
    """The optional whole-film fields the capture carries, in schema order."""
    scalars = {
        "video_frames": capture.video_frames,
        "rows": capture.rows,
        "palette_changes": capture.palette_changes,
        "dgroup_segment": capture.dgroup_segment,
        "captured_on": capture.captured_on,
        "checkout": capture.checkout,
        "sound_samples": capture.sound_samples,
    }
    document: dict[str, Any] = {k: v for k, v in scalars.items() if v is not None}
    if capture.video is not None:
        document["video"] = {
            "file": capture.video.file,
            "sha256": capture.video.sha256,
            "bytes": capture.video.bytes,
            "codec": capture.video.codec,
            "frame_rate": list(capture.video.frame_rate),
        }
    if capture.emulator is not None:
        document["emulator"] = {
            "name": capture.emulator.name,
            "version": capture.emulator.version,
            "core": capture.emulator.core,
            "cpu_cycles": capture.emulator.cpu_cycles,
        }
    if capture.layout is not None:
        layout = capture.layout
        offsets = {
            "film_clock": layout.film_clock,
            "global_tick": layout.global_tick,
            "working_palette": layout.working_palette,
            "slot_clock": layout.slot_clock,
            "slot_ticks": layout.slot_ticks,
        }
        document["layout"] = {k: v for k, v in offsets.items() if v is not None}
        if layout.inferred:
            document["layout"]["inferred"] = list(layout.inferred)
    if capture.film_ticks is not None:
        document["film_ticks"] = list(capture.film_ticks)
    return document


def load_video_capture(directory: Path) -> VideoCapture:
    """Read and validate a video capture directory's ``meta.json``."""
    path = directory / CAPTURE_META
    capture = _video_object(_as_object(_read_json(path), path, "the capture metadata"), path)
    capture.validate(path)
    return capture


def write_video_capture(
    directory: Path,
    capture: VideoCapture,
    *,
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and write a video capture's ``meta.json`` last, returning the document.

    Written through a temporary file and rename like ``write_capture``; a
    diagnostic may not overwrite a field the port owns.
    """
    path = directory / CAPTURE_META
    capture.validate(path)
    document = _video_document(capture)
    _merge_diagnostics(document, diagnostics, _VIDEO_FIELDS, path)
    _write_json(path, document)
    return document
