"""Typed readers and writers for the parity artifacts, standard library only.

This is the Python mirror of the Rust port in ``crates/stunt-parity``: the same
documents, field names, schema version and validation rules, so a ``render.json``
written by either side loads in the other. The module is the one home for artifact
names, tick file naming, the capture ``--frames`` mapping, the capture document
writer and the retime document rewrite; callers stop hard-coding the 320x200
raster, the 185-row viewport or the actor layer id.

The capture writer emits the port's document first and then merges the harness's
diagnostic keys (``palette_source``, ``global_tick`` and so on). Those keys are
capture evidence, not parity contract: the port does not read them, and a
diagnostic may not shadow a field the port owns.

``render.json`` is the typed render record (ADR 0005) and the table of contents of
the render store beside it (ADR 0027): ``frames.zst``, ``layers.zst`` and
``palettes.zst``, read by :class:`RenderStore` and written by
:class:`RenderStoreWriter` with the standard library's ``compression.zstd``. Reports
keep serde-defaulted optional fields, so a report written before a field existed
still loads.

Errors are ``ArtifactError`` (a ``ValueError`, so the parity scripts' existing
handlers keep working), naming the file and the field.
"""

from __future__ import annotations

import json
import shutil
import struct
import zlib
from collections import OrderedDict
from compression import zstd
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

__all__ = [
    "CAPTURE_HEIGHT",
    "CAPTURE_META",
    "CAPTURE_WIDTH",
    "LAYER_FIRST_ACTOR",
    "PALETTE_BYTES",
    "PALETTE_ENTRIES",
    "RENDER_CHUNK_TICKS",
    "RENDER_DOCUMENT",
    "RENDER_INDEX_FILE",
    "RENDER_LAYER_FILE",
    "RENDER_PALETTE_FILE",
    "RENDER_PREVIEW_DIR",
    "RENDER_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "VIDEO_FILE",
    "ArtifactError",
    "CameraPose",
    "CaptureSet",
    "CapturedFrame",
    "FilmId",
    "FrameReport",
    "Geometry",
    "I6Gate",
    "Page",
    "PaletteChange",
    "PaletteLog",
    "RenderChunk",
    "RenderControls",
    "RenderPalette",
    "RenderRecord",
    "RenderStore",
    "RenderStoreWriter",
    "RenderTick",
    "Report",
    "StoreSpan",
    "StoredFrame",
    "TickLog",
    "VideoCapture",
    "frames_for_captured_ticks",
    "load_video_capture",
    "open_render",
    "read_capture",
    "read_capture_palette",
    "read_page",
    "read_render",
    "read_report",
    "write_capture",
    "write_render",
    "write_render_store",
    "write_report",
    "write_video_capture",
]

#: Version carried by a capture's ``meta.json``, frame or video (port constant).
SCHEMA_VERSION = 1
#: Version carried by ``render.json`` (port constant).
RENDER_SCHEMA_VERSION = 2
#: Document written beside a render directory's frames, last.
RENDER_DOCUMENT = "render.json"
#: Capture directory description written by ``mise run capture-ref``.
CAPTURE_META = "meta.json"
#: Width of the Mode 13h raster a capture without a width was made at.
CAPTURE_WIDTH = 320
#: Height of the Mode 13h raster a capture without a height was made at.
CAPTURE_HEIGHT = 200
#: A render's index planes, one byte per pixel, a zstd frame per film second.
RENDER_INDEX_FILE = "frames.zst"
#: A render's layer planes, one little-endian u16 per pixel, chunked like the index planes.
RENDER_LAYER_FILE = "layers.zst"
#: A render's distinct palettes, :data:`PALETTE_BYTES` each, as one zstd frame.
RENDER_PALETTE_FILE = "palettes.zst"
#: One indexed PNG per film second of a render, for people.
RENDER_PREVIEW_DIR = "preview"
#: Film ticks per render chunk: one film second of the authored 50 Hz clock [I4].
RENDER_CHUNK_TICKS = 50
#: Bytes of one stored render palette: 256 RGB triples.
PALETTE_BYTES = 768
#: zstd level of every render chunk (mirrors the Rust ``render_store``).
_ZSTD_LEVEL = 3
#: Decoded chunks a :class:`RenderStore` keeps, so a reader reaching back one second does
#: not decode twice.
_CACHED_CHUNKS = 2
#: Entries in a capture's ``palettes_%04d.json``; Mode 13h has a 256-entry palette.
PALETTE_ENTRIES = 256
#: First layer id an actor draw writes (mirrors ``stunt_render::LAYER_FIRST_ACTOR``).
LAYER_FIRST_ACTOR = 16
#: Zero-padding of a capture ordinal in its default raster file names.
CAPTURE_ORDINAL_WIDTH = 4
#: The one subdirectory of a capture a frame or palette file name may point into (ADR 0024).
CAPTURE_FRAMES_DIR = "frames"
#: File name of the recorded video inside a video capture directory.
VIDEO_FILE = "capture.avi"
#: The ``kind`` a video capture's ``meta.json`` carries.
VIDEO_KIND = "video"


class ArtifactError(ValueError):
    """A parity artifact that is absent, malformed or does not satisfy its schema.

    ``kind`` names the failure so a caller can act on it without parsing the
    message: ``missing``, ``wrong_type``, ``unsupported_version``,
    ``ordering``, ``conflict``, ``geometry``, ``frame``,
    ``report_inconsistent``, ``video_log``, ``store`` or ``io``.

    This is deliberately not a frozen dataclass like the records: Python assigns
    ``__traceback__`` on the exception instance, which a frozen dataclass refuses.
    ``ValueError`` keeps the parity scripts' existing handlers working.
    """

    def __init__(self, kind: str, message: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.path = path

    def __str__(self) -> str:
        if self.path is None:
            return self.message
        return f"{self.path}: {self.message}"


def _error(kind: str, message: str, path: Path | None = None) -> ArtifactError:
    return ArtifactError(kind=kind, message=message, path=path)


def _wrong_type(path: Path | None, field_name: str, expected: str) -> ArtifactError:
    return _error("wrong_type", f"{field_name} must be {expected}", path)


def _read_json(path: Path) -> Any:
    """Parse *path*, reporting an unreadable or malformed file as an artifact error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise _error("missing", f"the file must be readable ({err})", path) from err
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        raise _error("wrong_type", "the file must be valid JSON", path) from err


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    """Write *document* through a temporary file and rename, so readers never see half."""
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except OSError as err:
        temporary.unlink(missing_ok=True)
        raise _error("io", f"write failed ({err})", path) from err


def _as_object(value: Any, path: Path | None, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _wrong_type(path, field_name, "an object")
    return cast("dict[str, Any]", value)


def _as_array(value: Any, path: Path | None, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise _wrong_type(path, field_name, "an array")
    return value


def _as_string(value: Any, path: Path | None, field_name: str) -> str:
    if not isinstance(value, str):
        raise _wrong_type(path, field_name, "a string")
    return value


def _as_bool(value: Any, path: Path | None, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise _wrong_type(path, field_name, "true or false")
    return value


def _as_int(value: Any, path: Path | None, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _wrong_type(path, field_name, "an integer")
    return value


def _as_unsigned(value: Any, path: Path | None, field_name: str, maximum: int) -> int:
    number = _as_int(value, path, field_name)
    if not 0 <= number <= maximum:
        raise _wrong_type(path, field_name, f"an integer between 0 and {maximum}")
    return number


def _as_float(value: Any, path: Path | None, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _wrong_type(path, field_name, "a number")
    return float(value)


def _optional_string(value: Any, path: Path | None, field_name: str) -> str | None:
    return None if value is None else _as_string(value, path, field_name)


def _optional_int(value: Any, path: Path | None, field_name: str) -> int | None:
    return None if value is None else _as_int(value, path, field_name)


def _optional_float(value: Any, path: Path | None, field_name: str) -> float | None:
    return None if value is None else _as_float(value, path, field_name)


def _optional_bool(value: Any, path: Path | None, field_name: str) -> bool | None:
    return None if value is None else _as_bool(value, path, field_name)


def _number_map(value: Any, path: Path | None, field_name: str) -> dict[str, float] | None:
    if value is None:
        return None
    raw = _as_object(value, path, field_name)
    return {key: _as_float(entry, path, f"{field_name}.{key}") for key, entry in raw.items()}


def _vector3(value: Any, path: Path | None, field_name: str) -> tuple[float, float, float]:
    entries = _as_array(value, path, field_name)
    if len(entries) != 3:
        raise _wrong_type(path, field_name, "an array of 3 numbers")
    return (
        _as_float(entries[0], path, f"{field_name}[0]"),
        _as_float(entries[1], path, f"{field_name}[1]"),
        _as_float(entries[2], path, f"{field_name}[2]"),
    )


@dataclass(frozen=True)
class FilmId:
    """Identity of the film an artifact was produced from.

    Every field is optional because older captures and renders may lack it; a
    mismatch is only reported when both sides carry the same field.
    """

    name: str | None = None
    flm_bytes: int | None = None
    flm_sha256: str | None = None
    #: Hash of the ``.ALL`` the capture played, so a later ``make-all`` cannot hide which one it was.
    all_sha256: str | None = None

    def names_conflict(self, other: FilmId) -> bool:
        """Whether both sides name a film and the names differ, ignoring case."""
        if self.name is None or other.name is None:
            return False
        return self.name.lower() != other.name.lower()

    def bytes_conflict(self, other: FilmId) -> bool:
        """Whether both sides recorded a byte length and the lengths differ."""
        if self.flm_bytes is None or other.flm_bytes is None:
            return False
        return self.flm_bytes != other.flm_bytes


@dataclass(frozen=True)
class Geometry:
    """Raster geometry an artifact describes."""

    width: int
    height: int
    viewport_rows: int | None = None

    def validate(self, path: Path | None = None) -> None:
        """Check that the raster is positive and the viewport fits inside it."""
        if self.width <= 0 or self.height <= 0:
            raise _error("geometry", "invalid geometry: width and height must be positive", path)
        if self.viewport_rows is not None and not 1 <= self.viewport_rows <= self.height:
            raise _error(
                "geometry",
                "invalid geometry: viewport_rows must be between 1 and height",
                path,
            )

    def plane_rows(self) -> int:
        """Rows a rendered plane spans: the viewport when narrowed, else the height."""
        return self.viewport_rows if self.viewport_rows is not None else self.height


@dataclass(frozen=True)
class Page:
    """One render page's planes: the full raster, with the viewport only narrowing scans."""

    indices: bytes
    layers: tuple[int, ...]
    geometry: Geometry

    def actor_pixels(self) -> list[int]:
        """Pixel offsets (within the viewport) drawn by an actor (layer id >= first actor)."""
        width, rows = self.geometry.width, self.geometry.plane_rows()
        return [pixel for pixel in range(width * rows) if self.layers[pixel] >= LAYER_FIRST_ACTOR]


@dataclass(frozen=True)
class RenderPalette:
    """Film palette controls the frame at a tick was drawn with."""

    sky: int
    brightness: int
    saturation: int


@dataclass(frozen=True)
class CameraPose:
    """Camera pose a frame was drawn from."""

    eye: tuple[float, float, float]
    target: tuple[float, float, float]
    fov_degrees: float
    roll_radians: float


@dataclass(frozen=True)
class RenderTick:
    """One rendered tick: its film clock, how it was drawn, and which stored palette it shows."""

    tick: int
    palette: RenderPalette
    camera: CameraPose
    palette_index: int


@dataclass(frozen=True)
class StoreSpan:
    """A byte range of one of a render's plane files."""

    offset: int
    length: int


@dataclass(frozen=True)
class RenderChunk:
    """One film second of a render: an independent zstd frame in each plane file."""

    second: int
    ticks: int
    index: StoreSpan
    layer: StoreSpan


@dataclass(frozen=True)
class RenderRecord:
    """Document written beside a render directory's plane files, last."""

    schema_version: int
    film: FilmId
    geometry: Geometry
    ticks: tuple[RenderTick, ...]
    palette_count: int
    chunks: tuple[RenderChunk, ...]

    def validate(self, path: Path | None = None) -> None:
        """Check the version, geometry, tick ordering, palette indices and chunk table."""
        if self.schema_version != RENDER_SCHEMA_VERSION:
            raise _error(
                "unsupported_version",
                f"unsupported schema version {self.schema_version}; "
                f"expected {RENDER_SCHEMA_VERSION}",
                path,
            )
        self.geometry.validate(path)
        for index, pair in enumerate(zip(self.ticks, self.ticks[1:], strict=False)):
            if pair[0].tick == pair[1].tick:
                raise _error("ordering", f"duplicate tick at index {index + 1}", path)
            if pair[0].tick > pair[1].tick:
                raise _error(
                    "ordering", f"ticks are not strictly ascending at index {index + 1}", path
                )
        for index, tick in enumerate(self.ticks):
            if tick.palette_index >= self.palette_count:
                raise _error(
                    "store",
                    f"render store: ticks[{index}].palette_index {tick.palette_index} is not "
                    f"below palette_count {self.palette_count}",
                    path,
                )
        self._validate_chunks(path)

    def _validate_chunks(self, path: Path | None) -> None:
        next_tick = 0
        ends = [0, 0]
        previous: int | None = None
        for number, chunk in enumerate(self.chunks):

            def at(reason: str, number: int = number) -> ArtifactError:
                return _error("store", f"render store: chunks[{number}]: {reason}", path)

            if previous is not None and chunk.second <= previous:
                raise at(f"second {chunk.second} does not follow the previous chunk's")
            previous = chunk.second
            if chunk.ticks == 0:
                raise at("holds no ticks")
            if chunk.index.offset != ends[0] or chunk.layer.offset != ends[1]:
                raise at(
                    f"offsets {chunk.index.offset} and {chunk.layer.offset} do not continue the "
                    f"previous chunk (expected {ends[0]} and {ends[1]})"
                )
            ends[0] += chunk.index.length
            ends[1] += chunk.layer.length
            end = next_tick + chunk.ticks
            if end > len(self.ticks):
                raise at(
                    f"claims {chunk.ticks} ticks but only {len(self.ticks) - next_tick} remain"
                )
            for entry in self.ticks[next_tick:end]:
                if entry.tick // RENDER_CHUNK_TICKS != chunk.second:
                    raise at(f"holds tick {entry.tick}, which is not in second {chunk.second}")
            next_tick = end
        if next_tick != len(self.ticks):
            raise _error(
                "store",
                f"render store: the chunks hold {next_tick} ticks but the record lists "
                f"{len(self.ticks)}",
                path,
            )

    def locate(self, tick: int) -> tuple[int, int] | None:
        """``(chunk, position)`` of *tick*'s planes, or ``None`` when the render lacks it."""
        first = 0
        for number, chunk in enumerate(self.chunks):
            end = first + chunk.ticks
            for position, entry in enumerate(self.ticks[first:end]):
                if entry.tick == tick:
                    return number, position
            first = end
        return None


@dataclass(frozen=True)
class CapturedFrame:
    """One captured frame's place in a capture directory."""

    ordinal: int
    film_tick: int
    frame_file: str
    palette_file: str


@dataclass(frozen=True)
class CaptureSet:
    """Document written by the capture harness as ``meta.json``.

    A capture without ``schema_version`` reads as the current version, so a
    legacy document and a new one are the same value here.
    """

    schema_version: int
    film: FilmId
    geometry: Geometry
    frames: tuple[CapturedFrame, ...]

    def validate(self, path: Path | None = None) -> None:
        """Check the schema version, geometry and frame identity."""
        if self.schema_version != SCHEMA_VERSION:
            raise _error(
                "unsupported_version",
                f"unsupported schema version {self.schema_version}; expected {SCHEMA_VERSION}",
                path,
            )
        self.geometry.validate(path)
        for frame in self.frames:
            if not frame.frame_file or not frame.palette_file:
                raise _error(
                    "frame",
                    f"frame {frame.ordinal}: frame_file and palette_file are required",
                    path,
                )
            for field_name, name in (
                ("frame_file", frame.frame_file),
                ("palette_file", frame.palette_file),
            ):
                leaf = name.removeprefix(f"{CAPTURE_FRAMES_DIR}/")
                if not leaf or "/" in leaf or "\\" in name:
                    raise _error(
                        "frame",
                        f"frame {frame.ordinal}: {field_name} must be a basename, "
                        f"optionally under {CAPTURE_FRAMES_DIR}/",
                        path,
                    )


@dataclass(frozen=True)
class I6Gate:
    """Whether the scored mean SSIM reaches each I6 threshold."""

    initial: bool = False
    sign_off: bool = False


@dataclass(frozen=True)
class FrameReport:
    """One matched frame's measurements."""

    film_tick: int
    ssim: float
    iou: float
    ordinal: int = 0
    index_agreement: float | None = None
    loss_by_class: dict[str, float] | None = None
    fade_level: float | None = None
    authored_fade_level: float | None = None
    scored: bool | None = None


@dataclass(frozen=True)
class Report:
    """The ``report.json`` document."""

    per_frame: tuple[FrameReport, ...]
    reference_frames: int = 0
    frames: int = 0
    unmatched: int = 0
    sky_indices: tuple[int, int] = (0, 0)
    mean_ssim: float = 0.0
    min_ssim: float = 0.0
    mean_iou: float = 0.0
    min_fade_level: float = 0.0
    mean_ssim_scored: float | None = None
    i6_gate: I6Gate = field(default_factory=I6Gate)
    mean_iou_scored: float | None = None
    mean_index_agreement_scored: float | None = None
    mean_loss_by_class_scored: dict[str, float] | None = None
    scored_frames: int = 0
    excluded_frames: int = 0

    def headline(self) -> tuple[float, float]:
        """Headline SSIM and mask IoU: the scored means, else every matched frame."""
        ssim = self.mean_ssim_scored if self.mean_ssim_scored is not None else self.mean_ssim
        iou = self.mean_iou_scored if self.mean_iou_scored is not None else self.mean_iou
        return ssim, iou

    def validate(self, path: Path | None = None) -> None:
        """Check the arithmetic identities the report promises."""
        if self.reference_frames != self.frames + self.unmatched:
            raise _error(
                "report_inconsistent",
                "report is inconsistent: reference_frames must equal frames + unmatched",
                path,
            )
        if self.frames != self.scored_frames + self.excluded_frames:
            raise _error(
                "report_inconsistent",
                "report is inconsistent: frames must equal scored_frames + excluded_frames",
                path,
            )
        if (
            self.mean_ssim_scored is None or self.mean_iou_scored is None
        ) and self.scored_frames != 0:
            raise _error(
                "report_inconsistent",
                "report is inconsistent: scored means must be present when scored_frames "
                "is non-zero",
                path,
            )
        if self.scored_frames == 0 and (
            self.mean_ssim_scored is not None or self.mean_iou_scored is not None
        ):
            raise _error(
                "report_inconsistent",
                "report is inconsistent: scored means must be null when no frame scored",
                path,
            )
        if self.scored_frames == 0 and self.i6_gate.initial:
            raise _error(
                "report_inconsistent",
                "report is inconsistent: the I6 gate cannot pass with no scored frame",
                path,
            )


@dataclass(frozen=True)
class RenderControls:
    """Palette controls, geometry and film identity of a render directory."""

    film: FilmId
    geometry: Geometry
    controls: dict[int, RenderPalette]
    record: RenderRecord


def _film_fields(document: Mapping[str, Any], path: Path | None) -> FilmId:
    """A film identity from top-level ``film``, ``flm_bytes`` and ``flm_sha256``."""
    return FilmId(
        name=_optional_string(document.get("film"), path, "film"),
        flm_bytes=_optional_int(document.get("flm_bytes"), path, "flm_bytes"),
        flm_sha256=_optional_string(document.get("flm_sha256"), path, "flm_sha256"),
        all_sha256=_optional_string(document.get("all_sha256"), path, "all_sha256"),
    )


def _film_object(document: Mapping[str, Any], path: Path | None) -> FilmId:
    """A film identity from the nested ``film`` object of a ``render.json``."""
    film = _as_object(document.get("film"), path, "film")
    return FilmId(
        name=_optional_string(film.get("name"), path, "film.name"),
        flm_bytes=_optional_int(film.get("flm_bytes"), path, "film.flm_bytes"),
        flm_sha256=_optional_string(film.get("flm_sha256"), path, "film.flm_sha256"),
        all_sha256=_optional_string(film.get("all_sha256"), path, "film.all_sha256"),
    )


def _geometry_document(geometry: Geometry) -> dict[str, Any]:
    document: dict[str, Any] = {"width": geometry.width, "height": geometry.height}
    if geometry.viewport_rows is not None:
        document["viewport_rows"] = geometry.viewport_rows
    return document


def _geometry_object(document: Mapping[str, Any], path: Path | None) -> Geometry:
    return Geometry(
        width=_as_unsigned(document.get("width"), path, "geometry.width", 0xFFFFFFFF),
        height=_as_unsigned(document.get("height"), path, "geometry.height", 0xFFFFFFFF),
        viewport_rows=(
            None
            if document.get("viewport_rows") is None
            else _as_unsigned(
                document.get("viewport_rows"), path, "geometry.viewport_rows", 0xFFFFFFFF
            )
        ),
    )


def _palette_object(
    document: Mapping[str, Any], path: Path | None, field_name: str
) -> RenderPalette:
    raw = _as_object(document.get(field_name), path, field_name)
    return RenderPalette(
        sky=_as_unsigned(raw.get("sky"), path, f"{field_name}.sky", 0xFFFF),
        brightness=_as_unsigned(raw.get("brightness"), path, f"{field_name}.brightness", 0xFFFF),
        saturation=_as_unsigned(raw.get("saturation"), path, f"{field_name}.saturation", 0xFFFF),
    )


def _camera_object(document: Mapping[str, Any], path: Path | None, field_name: str) -> CameraPose:
    raw = _as_object(document.get(field_name), path, field_name)
    return CameraPose(
        eye=_vector3(raw.get("eye"), path, f"{field_name}.eye"),
        target=_vector3(raw.get("target"), path, f"{field_name}.target"),
        fov_degrees=_as_float(raw.get("fov_degrees"), path, f"{field_name}.fov_degrees"),
        roll_radians=_as_float(raw.get("roll_radians"), path, f"{field_name}.roll_radians"),
    )


def _tick_object(value: Any, path: Path | None, field_name: str) -> RenderTick:
    raw = _as_object(value, path, field_name)
    return RenderTick(
        tick=_as_unsigned(raw.get("tick"), path, f"{field_name}.tick", 0xFFFFFFFF),
        palette=_palette_object(raw, path, "palette"),
        camera=_camera_object(raw, path, "camera"),
        palette_index=_as_unsigned(
            raw.get("palette_index"), path, f"{field_name}.palette_index", 0xFFFFFFFF
        ),
    )


def _render_record(document: Any, path: Path | None) -> RenderRecord:
    raw = _as_object(document, path, "the render record")
    ticks = _as_array(raw.get("ticks"), path, "ticks")
    geometry = _as_object(raw.get("geometry"), path, "geometry")
    return RenderRecord(
        schema_version=_as_unsigned(raw.get("schema_version"), path, "schema_version", 0xFFFFFFFF),
        film=_film_object(raw, path),
        geometry=_geometry_object(geometry, path),
        ticks=tuple(
            _tick_object(entry, path, f"ticks[{index}]") for index, entry in enumerate(ticks)
        ),
        palette_count=_as_unsigned(raw.get("palette_count"), path, "palette_count", 0xFFFFFFFF),
        chunks=tuple(
            _chunk_object(entry, path, f"chunks[{index}]")
            for index, entry in enumerate(_as_array(raw.get("chunks"), path, "chunks"))
        ),
    )


def _render_document(record: RenderRecord) -> dict[str, Any]:
    film: dict[str, Any] = {}
    if record.film.name is not None:
        film["name"] = record.film.name
    if record.film.flm_bytes is not None:
        film["flm_bytes"] = record.film.flm_bytes
    if record.film.flm_sha256 is not None:
        film["flm_sha256"] = record.film.flm_sha256
    ticks = [
        {
            "tick": tick.tick,
            "palette": {
                "sky": tick.palette.sky,
                "brightness": tick.palette.brightness,
                "saturation": tick.palette.saturation,
            },
            "camera": {
                "eye": list(tick.camera.eye),
                "target": list(tick.camera.target),
                "fov_degrees": tick.camera.fov_degrees,
                "roll_radians": tick.camera.roll_radians,
            },
            "palette_index": tick.palette_index,
        }
        for tick in record.ticks
    ]
    chunks = [
        {
            "second": chunk.second,
            "ticks": chunk.ticks,
            "index": {"offset": chunk.index.offset, "length": chunk.index.length},
            "layer": {"offset": chunk.layer.offset, "length": chunk.layer.length},
        }
        for chunk in record.chunks
    ]
    return {
        "schema_version": record.schema_version,
        "film": film,
        "geometry": _geometry_document(record.geometry),
        "ticks": ticks,
        "palette_count": record.palette_count,
        "chunks": chunks,
    }


def _capture_palette_object(document: Any, path: Path | None) -> tuple[tuple[int, int, int], ...]:
    entries = _as_array(document, path, "the palette")
    if len(entries) != PALETTE_ENTRIES:
        raise _wrong_type(path, "the palette", f"{PALETTE_ENTRIES} RGB triples, got {len(entries)}")
    palette: list[tuple[int, int, int]] = []
    for index, value in enumerate(entries):
        entry = _as_array(value, path, f"[{index}]")
        if len(entry) < 3:
            raise _wrong_type(path, f"[{index}]", "at least 3 channel values")
        palette.append(
            (
                _as_unsigned(entry[0], path, f"[{index}][0]", 0xFF),
                _as_unsigned(entry[1], path, f"[{index}][1]", 0xFF),
                _as_unsigned(entry[2], path, f"[{index}][2]", 0xFF),
            )
        )
    return tuple(palette)


def _frame_report_object(value: Any, path: Path | None, field_name: str) -> FrameReport:
    raw = _as_object(value, path, field_name)
    return FrameReport(
        film_tick=_as_int(raw.get("film_tick"), path, f"{field_name}.film_tick"),
        ssim=_as_float(raw.get("ssim"), path, f"{field_name}.ssim"),
        iou=_as_float(raw.get("iou"), path, f"{field_name}.iou"),
        ordinal=_as_int(raw.get("ordinal", 0), path, f"{field_name}.ordinal"),
        index_agreement=_optional_float(
            raw.get("index_agreement"), path, f"{field_name}.index_agreement"
        ),
        loss_by_class=_number_map(raw.get("loss_by_class"), path, f"{field_name}.loss_by_class"),
        fade_level=_optional_float(raw.get("fade_level"), path, f"{field_name}.fade_level"),
        authored_fade_level=_optional_float(
            raw.get("authored_fade_level"), path, f"{field_name}.authored_fade_level"
        ),
        scored=_optional_bool(raw.get("scored"), path, f"{field_name}.scored"),
    )


def _i6_gate_object(value: Any, path: Path | None, field_name: str) -> I6Gate:
    raw = _as_object(value, path, field_name)
    return I6Gate(
        initial=_as_bool(raw.get("initial", False), path, f"{field_name}.initial"),
        sign_off=_as_bool(raw.get("sign_off", False), path, f"{field_name}.sign_off"),
    )


def _sky_indices(value: Any, path: Path | None) -> tuple[int, int]:
    entries = _as_array(value, path, "sky_indices")
    if len(entries) != 2:
        raise _wrong_type(path, "sky_indices", "an array of 2 integers")
    return (
        _as_unsigned(entries[0], path, "sky_indices[0]", 0xFF),
        _as_unsigned(entries[1], path, "sky_indices[1]", 0xFF),
    )


def _report_object(document: Any, path: Path | None) -> Report:
    raw = _as_object(document, path, "the report")
    frames = _as_array(raw.get("per_frame"), path, "per_frame")
    return Report(
        per_frame=tuple(
            _frame_report_object(value, path, f"per_frame[{index}]")
            for index, value in enumerate(frames)
        ),
        reference_frames=_as_int(raw.get("reference_frames", 0), path, "reference_frames"),
        frames=_as_int(raw.get("frames", 0), path, "frames"),
        unmatched=_as_int(raw.get("unmatched", 0), path, "unmatched"),
        sky_indices=_sky_indices(raw.get("sky_indices", [0, 0]), path),
        mean_ssim=_as_float(raw.get("mean_ssim", 0.0), path, "mean_ssim"),
        min_ssim=_as_float(raw.get("min_ssim", 0.0), path, "min_ssim"),
        mean_iou=_as_float(raw.get("mean_iou", 0.0), path, "mean_iou"),
        min_fade_level=_as_float(raw.get("min_fade_level", 0.0), path, "min_fade_level"),
        mean_ssim_scored=_optional_float(raw.get("mean_ssim_scored"), path, "mean_ssim_scored"),
        i6_gate=_i6_gate_object(raw.get("i6_gate", {}), path, "i6_gate"),
        mean_iou_scored=_optional_float(raw.get("mean_iou_scored"), path, "mean_iou_scored"),
        mean_index_agreement_scored=_optional_float(
            raw.get("mean_index_agreement_scored"), path, "mean_index_agreement_scored"
        ),
        mean_loss_by_class_scored=_number_map(
            raw.get("mean_loss_by_class_scored"), path, "mean_loss_by_class_scored"
        ),
        scored_frames=_as_int(raw.get("scored_frames", 0), path, "scored_frames"),
        excluded_frames=_as_int(raw.get("excluded_frames", 0), path, "excluded_frames"),
    )


def _report_document(report: Report) -> dict[str, Any]:
    def frame_document(frame: FrameReport) -> dict[str, Any]:
        return {
            "ordinal": frame.ordinal,
            "film_tick": frame.film_tick,
            "ssim": frame.ssim,
            "iou": frame.iou,
            "index_agreement": frame.index_agreement,
            "loss_by_class": frame.loss_by_class,
            "fade_level": frame.fade_level,
            "authored_fade_level": frame.authored_fade_level,
            "scored": frame.scored,
        }

    return {
        "reference_frames": report.reference_frames,
        "frames": report.frames,
        "unmatched": report.unmatched,
        "sky_indices": list(report.sky_indices),
        "mean_ssim": report.mean_ssim,
        "min_ssim": report.min_ssim,
        "mean_iou": report.mean_iou,
        "min_fade_level": report.min_fade_level,
        "mean_ssim_scored": report.mean_ssim_scored,
        "i6_gate": {"initial": report.i6_gate.initial, "sign_off": report.i6_gate.sign_off},
        "mean_iou_scored": report.mean_iou_scored,
        "mean_index_agreement_scored": report.mean_index_agreement_scored,
        "mean_loss_by_class_scored": report.mean_loss_by_class_scored,
        "scored_frames": report.scored_frames,
        "excluded_frames": report.excluded_frames,
        "per_frame": [frame_document(frame) for frame in report.per_frame],
    }


def _store_span(value: Any, path: Path | None, field_name: str) -> StoreSpan:
    raw = _as_object(value, path, field_name)
    return StoreSpan(
        offset=_as_unsigned(raw.get("offset"), path, f"{field_name}.offset", 2**64 - 1),
        length=_as_unsigned(raw.get("length"), path, f"{field_name}.length", 2**64 - 1),
    )


def _chunk_object(value: Any, path: Path | None, field_name: str) -> RenderChunk:
    raw = _as_object(value, path, field_name)
    return RenderChunk(
        second=_as_unsigned(raw.get("second"), path, f"{field_name}.second", 0xFFFFFFFF),
        ticks=_as_unsigned(raw.get("ticks"), path, f"{field_name}.ticks", 0xFFFFFFFF),
        index=_store_span(raw.get("index"), path, f"{field_name}.index"),
        layer=_store_span(raw.get("layer"), path, f"{field_name}.layer"),
    )


def _indexed_png(width: int, height: int, palette: bytes, indices: bytes) -> bytes:
    """An 8-bit indexed PNG of *indices* in *palette*, standard library only."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body)
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + indices[y * width : (y + 1) * width] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
        + chunk(b"PLTE", palette)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@dataclass(frozen=True)
class StoredFrame:
    """One stored render tick: its planes and the palette its picture is drawn in.

    ``indices`` holds one byte per pixel over the full raster, ``layers`` one
    little-endian u16 per pixel, and ``palette`` 256 RGB triples; the picture is
    ``palette[index]`` at every pixel.
    """

    indices: bytes
    layers: bytes
    palette: bytes


class RenderStore:
    """Reads a render directory's store (ADR 0027), keeping the last two decoded chunks.

    Opening reads and validates ``render.json``, checks the two plane files against its
    chunk table and reads the palettes, so a later :meth:`frame` only decodes.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.record = _read_render_v2(directory)
        ends = (0, 0)
        if self.record.chunks:
            last = self.record.chunks[-1]
            ends = (last.index.offset + last.index.length, last.layer.offset + last.layer.length)
        if self.record.ticks:
            for name, end in zip((RENDER_INDEX_FILE, RENDER_LAYER_FILE), ends, strict=True):
                path = directory / name
                try:
                    size = path.stat().st_size
                except OSError as err:
                    raise _error("missing", f"the file must be readable ({err})", path) from err
                if size != end:
                    raise _error(
                        "store", f"holds {size} bytes but render.json's chunks end at {end}", path
                    )
        self._palettes = _read_palettes(directory / RENDER_PALETTE_FILE, self.record.palette_count)
        self._rows = {entry.tick: row for row, entry in enumerate(self.record.ticks)}
        self._cache: OrderedDict[int, tuple[bytes, bytes]] = OrderedDict()

    def ticks(self) -> list[int]:
        """The film ticks the render holds, ascending."""
        return [entry.tick for entry in self.record.ticks]

    def holds(self, tick: int) -> bool:
        """Whether the render holds film tick *tick*."""
        return tick in self._rows

    def frame(self, tick: int) -> StoredFrame:
        """The planes and palette of film tick *tick*, decoding its chunk unless cached."""
        slot = self.record.locate(tick)
        if slot is None:
            raise _error("missing", f"holds no render of tick {tick}", self.directory)
        chunk, position = slot
        indices, layers = self._decoded(chunk)
        pixels = self.record.geometry.width * self.record.geometry.height
        entry = self.record.ticks[self._rows[tick]]
        return StoredFrame(
            indices=indices[position * pixels : (position + 1) * pixels],
            layers=layers[position * pixels * 2 : (position + 1) * pixels * 2],
            palette=self._palettes[entry.palette_index],
        )

    def _decoded(self, chunk: int) -> tuple[bytes, bytes]:
        cached = self._cache.get(chunk)
        if cached is not None:
            self._cache.move_to_end(chunk)
            return cached
        entry = self.record.chunks[chunk]
        pixels = self.record.geometry.width * self.record.geometry.height * entry.ticks
        decoded = (
            self._read_chunk(RENDER_INDEX_FILE, entry.index, entry.second, pixels),
            self._read_chunk(RENDER_LAYER_FILE, entry.layer, entry.second, pixels * 2),
        )
        self._cache[chunk] = decoded
        while len(self._cache) > _CACHED_CHUNKS:
            self._cache.popitem(last=False)
        return decoded

    def _read_chunk(self, name: str, span: StoreSpan, second: int, expected: int) -> bytes:
        path = self.directory / name
        try:
            with path.open("rb") as handle:
                handle.seek(span.offset)
                packed = handle.read(span.length)
        except OSError as err:
            raise _error("missing", f"the file must be readable ({err})", path) from err
        try:
            raw = zstd.decompress(packed)
        except zstd.ZstdError as err:
            raise _error("store", f"second {second} does not decompress: {err}", path) from err
        if len(raw) != expected:
            raise _error(
                "store",
                f"second {second} decompresses to {len(raw)} bytes, expected {expected}",
                path,
            )
        return raw


def _read_render_v2(directory: Path) -> RenderRecord:
    """``render.json`` of a store, refusing another version before reading its fields."""
    path = directory / RENDER_DOCUMENT
    if not path.is_file():
        raise _error(
            "missing",
            f"has no {RENDER_DOCUMENT}; re-render it with the current stuntreel --headless --out-dir",
            directory,
        )
    document = _read_json(path)
    version = document.get("schema_version") if isinstance(document, dict) else None
    if version != RENDER_SCHEMA_VERSION:
        raise _error(
            "unsupported_version",
            f"unsupported schema version {version}; expected {RENDER_SCHEMA_VERSION}; re-render "
            f"{directory} with the current stuntreel --headless --out-dir",
            path,
        )
    record = _render_record(document, path)
    record.validate(path)
    return record


def _read_palettes(path: Path, count: int) -> tuple[bytes, ...]:
    """``palettes.zst``, which must hold exactly *count* palettes."""
    if count == 0 and not path.exists():
        return ()
    try:
        packed = path.read_bytes()
    except OSError as err:
        raise _error("missing", f"the file must be readable ({err})", path) from err
    try:
        raw = zstd.decompress(packed)
    except zstd.ZstdError as err:
        raise _error("store", f"does not decompress: {err}", path) from err
    expected = count * PALETTE_BYTES
    if len(raw) != expected:
        raise _error(
            "store", f"holds {len(raw)} bytes, expected {expected} for {count} palettes", path
        )
    return tuple(raw[at : at + PALETTE_BYTES] for at in range(0, expected, PALETTE_BYTES))


class RenderStoreWriter:
    """Writes a render's planes in tick order, a zstd chunk per film second (ADR 0027).

    Nothing is created until the first tick. The writer replaces its own files and
    ``preview/`` and leaves anything else in the directory.
    """

    def __init__(self, directory: Path, geometry: Geometry) -> None:
        self.directory = directory
        self.geometry = geometry
        self._pixels = geometry.width * geometry.height
        self._started = False
        self._ends = [0, 0]
        self._last_tick: int | None = None
        self._palettes: dict[bytes, int] = {}
        self._open: tuple[int, list[bytes], list[bytes]] | None = None
        self._chunks: list[RenderChunk] = []

    def push(self, tick: int, palette: bytes, indices: bytes, layers: bytes) -> int:
        """Append one tick and return the index of its palette in the store.

        *layers* is one little-endian u16 per pixel; *palette* 768 bytes.
        """
        if len(indices) != self._pixels or len(layers) != 2 * self._pixels:
            raise _error(
                "geometry",
                f"tick {tick} has {len(indices)} index and {len(layers)} layer bytes, expected "
                f"{self._pixels} and {2 * self._pixels} for "
                f"{self.geometry.width}x{self.geometry.height}",
                self.directory,
            )
        if len(palette) != PALETTE_BYTES:
            raise _error("store", f"tick {tick} palette holds {len(palette)} bytes", self.directory)
        if self._last_tick is not None and tick <= self._last_tick:
            raise _error(
                "ordering", f"tick {tick} does not follow tick {self._last_tick}", self.directory
            )
        if not self._started:
            self._start()
        second = tick // RENDER_CHUNK_TICKS
        if self._open is not None and self._open[0] != second:
            self._close_chunk()
        if self._open is None:
            preview = self.directory / RENDER_PREVIEW_DIR / f"sec_{second:04d}.png"
            preview.write_bytes(
                _indexed_png(self.geometry.width, self.geometry.height, palette, indices)
            )
            self._open = (second, [], [])
        self._open[1].append(bytes(indices))
        self._open[2].append(bytes(layers))
        self._last_tick = tick
        return self._palettes.setdefault(bytes(palette), len(self._palettes))

    def finish(self) -> tuple[int, tuple[RenderChunk, ...]] | None:
        """Write the last chunk and ``palettes.zst``: the palette count and chunk table.

        ``None`` when no tick was pushed.
        """
        if not self._started:
            return None
        self._close_chunk()
        packed = zstd.compress(b"".join(self._palettes), level=_ZSTD_LEVEL)
        (self.directory / RENDER_PALETTE_FILE).write_bytes(packed)
        return len(self._palettes), tuple(self._chunks)

    def _start(self) -> None:
        preview = self.directory / RENDER_PREVIEW_DIR
        if preview.is_dir():
            shutil.rmtree(preview)
        preview.mkdir(parents=True)
        for name in (RENDER_INDEX_FILE, RENDER_LAYER_FILE):
            (self.directory / name).write_bytes(b"")
        self._started = True

    def _close_chunk(self) -> None:
        if self._open is None:
            return
        second, indices, layers = self._open
        spans: list[StoreSpan] = []
        planes = (b"".join(indices), b"".join(layers))
        for slot, (name, raw) in enumerate(
            zip((RENDER_INDEX_FILE, RENDER_LAYER_FILE), planes, strict=True)
        ):
            packed = zstd.compress(raw, level=_ZSTD_LEVEL)
            with (self.directory / name).open("ab") as handle:
                handle.write(packed)
            spans.append(StoreSpan(offset=self._ends[slot], length=len(packed)))
            self._ends[slot] += len(packed)
        self._chunks.append(
            RenderChunk(second=second, ticks=len(indices), index=spans[0], layer=spans[1])
        )
        self._open = None


def write_render_store(
    directory: Path,
    film: FilmId,
    geometry: Geometry,
    frames: Iterable[tuple[RenderTick, StoredFrame]],
) -> RenderRecord:
    """Write a whole render store from *frames* in tick order, ``render.json`` last.

    Each tick's ``palette_index`` is assigned by the store; the one it carries is ignored.
    """
    writer = RenderStoreWriter(directory, geometry)
    ticks: list[RenderTick] = []
    for tick, frame in frames:
        index = writer.push(tick.tick, frame.palette, frame.indices, frame.layers)
        ticks.append(replace(tick, palette_index=index))
    table = writer.finish()
    if table is None:
        raise _error("missing", "a render store needs at least one tick", directory)
    palette_count, chunks = table
    record = RenderRecord(
        schema_version=RENDER_SCHEMA_VERSION,
        film=film,
        geometry=geometry,
        ticks=tuple(ticks),
        palette_count=palette_count,
        chunks=chunks,
    )
    write_render(directory / RENDER_DOCUMENT, record)
    return record


def read_page(store: RenderStore, tick: int) -> Page:
    """One stored tick's planes as a :class:`Page`, over the record's full raster.

    The planes span width * height pixels even when viewport_rows narrows the drawn
    scene; only Page.actor_pixels narrows its scan to the viewport.
    """
    frame = store.frame(tick)
    count = len(frame.layers) // 2
    return Page(
        indices=frame.indices,
        layers=struct.unpack(f"<{count}H", frame.layers),
        geometry=store.record.geometry,
    )


def frames_for_captured_ticks(ticks: Iterable[int]) -> str:
    """The ``--frames`` range covering the captured film ticks.

    Frame *n* renders tick *n - 1*, and the range is half-open, so a capture at
    film tick *t* needs the frame numbered *t + 1*: ``min + 1..max + 2``.
    """
    values = list(ticks)
    if not values:
        raise _error("missing", "a capture with no frames has no --frames range")
    return f"{min(values) + 1}..{max(values) + 2}"


def read_render(path: Path) -> RenderRecord:
    """Read and validate a ``render.json`` file."""
    record = _render_record(_read_json(path), path)
    record.validate(path)
    return record


def write_render(path: Path, record: RenderRecord) -> None:
    """Validate and write a ``render.json`` through a temporary file and rename."""
    record.validate(path)
    _write_json(path, _render_document(record))


def open_render(directory: Path) -> RenderControls:
    """Read a render directory's controls from its ``render.json``.

    A directory without one, or with another schema version, is refused with the
    re-render action (ADR 0005, ADR 0027).
    """
    record = _read_render_v2(directory)
    return RenderControls(
        film=record.film,
        geometry=record.geometry,
        controls={tick.tick: tick.palette for tick in record.ticks},
        record=record,
    )


#: Top-level fields the capture document owns; a diagnostic may not overwrite one.
_CAPTURE_FIELDS = frozenset(
    {
        "schema_version",
        "film",
        "flm_bytes",
        "flm_sha256",
        "all_sha256",
        "frames",
        "width",
        "height",
    }
)
#: Per-frame fields the capture document owns; a diagnostic may not overwrite one.
_CAPTURE_FRAME_FIELDS = frozenset({"ordinal", "film_tick", "frame_file", "palette_file"})


def _captured_frame_object(
    value: Any, path: Path | None, field_name: str, ordinal: int
) -> CapturedFrame:
    """One frame entry, defaulting the ordinal's file names when the legacy document omits them."""
    frame = _as_object(value, path, field_name)
    film_tick = _as_unsigned(frame.get("film_tick"), path, f"{field_name}.film_tick", 0xFFFFFFFF)
    frame_file = _optional_string(frame.get("frame_file"), path, f"{field_name}.frame_file")
    palette_file = _optional_string(frame.get("palette_file"), path, f"{field_name}.palette_file")
    default_frame = f"tick_{ordinal:0{CAPTURE_ORDINAL_WIDTH}d}.idx"
    default_palette = f"palettes_{ordinal:0{CAPTURE_ORDINAL_WIDTH}d}.json"
    return CapturedFrame(
        ordinal=ordinal,
        film_tick=film_tick,
        frame_file=default_frame if frame_file is None else frame_file,
        palette_file=default_palette if palette_file is None else palette_file,
    )


def _capture_object(document: Mapping[str, Any], path: Path | None) -> CaptureSet:
    """A capture set from the flat ``meta.json`` shape, applying the legacy defaults."""
    frames = _as_array(document.get("frames"), path, "frames")
    version = document.get("schema_version")
    return CaptureSet(
        schema_version=(
            SCHEMA_VERSION
            if version is None
            else _as_unsigned(version, path, "schema_version", 0xFFFFFFFF)
        ),
        film=_film_fields(document, path),
        geometry=Geometry(
            width=_as_unsigned(document.get("width", CAPTURE_WIDTH), path, "width", 0xFFFFFFFF),
            height=_as_unsigned(document.get("height", CAPTURE_HEIGHT), path, "height", 0xFFFFFFFF),
            viewport_rows=None,
        ),
        frames=tuple(
            _captured_frame_object(value, path, f"frames[{index}]", index + 1)
            for index, value in enumerate(frames)
        ),
    )


def _capture_document(capture: CaptureSet) -> dict[str, Any]:
    """The port's capture document, in the flat shape every capture already has."""
    document: dict[str, Any] = {"schema_version": capture.schema_version}
    if capture.film.name is not None:
        document["film"] = capture.film.name
    if capture.film.flm_bytes is not None:
        document["flm_bytes"] = capture.film.flm_bytes
    if capture.film.flm_sha256 is not None:
        document["flm_sha256"] = capture.film.flm_sha256
    if capture.film.all_sha256 is not None:
        document["all_sha256"] = capture.film.all_sha256
    document["frames"] = [
        {
            "ordinal": frame.ordinal,
            "film_tick": frame.film_tick,
            "frame_file": frame.frame_file,
            "palette_file": frame.palette_file,
        }
        for frame in capture.frames
    ]
    document["width"] = capture.geometry.width
    document["height"] = capture.geometry.height
    return document


def _merge_diagnostics(
    document: dict[str, Any],
    diagnostics: Mapping[str, Any] | None,
    owned: frozenset[str],
    path: Path | None,
    *,
    where: str | None = None,
) -> None:
    """Add evidence keys after the port document, refusing to shadow a port field."""
    if diagnostics is None:
        return
    for key, value in diagnostics.items():
        if key in owned:
            prefix = f"{where}." if where is not None else ""
            raise _error(
                "conflict",
                f"diagnostic {prefix}{key} would overwrite a capture document field",
                path,
            )
        document[key] = value


def read_capture(directory: Path) -> CaptureSet:
    """Read and validate a capture directory's ``meta.json``.

    A document without ``schema_version`` reads as the current version, and a
    frame without an ordinal or file names takes the capture-order defaults.
    """
    path = directory / CAPTURE_META
    capture = _capture_object(_as_object(_read_json(path), path, "the capture metadata"), path)
    capture.validate(path)
    return capture


def write_capture(
    directory: Path,
    capture: CaptureSet,
    *,
    diagnostics: Mapping[str, Any] | None = None,
    frame_diagnostics: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate and write a capture directory's ``meta.json``, returning the document.

    The port document is written first and through a temporary file and rename, so
    readers never see half a capture. ``diagnostics`` and ``frame_diagnostics``
    then add the harness's evidence keys; a diagnostic may not overwrite a field
    the port owns.
    """
    path = directory / CAPTURE_META
    capture.validate(path)
    document = _capture_document(capture)
    _merge_diagnostics(document, diagnostics, _CAPTURE_FIELDS, path)
    if frame_diagnostics is not None:
        frames = cast("list[dict[str, Any]]", document["frames"])
        if len(frame_diagnostics) != len(frames):
            raise _wrong_type(
                path,
                "frame_diagnostics",
                f"an array of {len(frames)} objects",
            )
        for index, (frame, extra) in enumerate(zip(frames, frame_diagnostics, strict=True)):
            _merge_diagnostics(
                frame,
                extra,
                _CAPTURE_FRAME_FIELDS,
                path,
                where=f"frames[{index}]",
            )
    _write_json(path, document)
    return document


_VIDEO_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "film",
        "geometry",
        "playone_build",
        "cpu_profile",
        "capture_start_frame",
        "film_start_frame",
        "end",
        "log",
        "palettes",
    }
)
_CAPTURE_ENDS = ("hold", "capped")
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

    def video_index(self, frame: int) -> int | None:
        """Index of capture *frame* relative to recording start, or ``None`` before it.

        The result is not checked against the recording's length.
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

    def _validate_log(self, path: Path | None) -> None:
        log = self.log
        rows = len(log.frame)
        if len(log.film_tick) != rows or len(log.global_tick) != rows:
            raise _video_error(
                f"log columns differ in length: frame {rows}, film_tick {len(log.film_tick)}, "
                f"global_tick {len(log.global_tick)}",
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
        ),
        palettes=PaletteLog(
            initial=_rgb_entries(palettes.get("initial"), path, "palettes.initial"),
            changes=changes,
        ),
    )


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
    return {
        "schema_version": capture.schema_version,
        "kind": capture.kind,
        "film": film,
        "geometry": _geometry_document(capture.geometry),
        "playone_build": capture.playone_build,
        "cpu_profile": capture.cpu_profile,
        "capture_start_frame": capture.capture_start_frame,
        "film_start_frame": capture.film_start_frame,
        "end": capture.end,
        "log": {
            "frame": list(capture.log.frame),
            "film_tick": list(capture.log.film_tick),
            "global_tick": list(capture.log.global_tick),
        },
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


def read_capture_palette(path: Path) -> tuple[tuple[int, int, int], ...]:
    """The 256 RGB triples of a capture's ``palettes_%04d.json``."""
    return _capture_palette_object(_read_json(path), path)


def read_report(path: Path) -> Report:
    """Read a ``report.json``, including reports written before recent optional fields."""
    return _report_object(_read_json(path), path)


def write_report(path: Path, report: Report) -> None:
    """Validate and write a ``report.json`` through a temporary file and rename."""
    report.validate(path)
    _write_json(path, _report_document(report))
