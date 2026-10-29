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

``render.json`` is the typed render record (ADR 0005). ``palette_controls.json``
is the legacy sidecar, still read as a fallback until renders made before the
record age out. Reports keep serde-defaulted optional fields, so a report written
before a field existed still loads.

Errors are ``ArtifactError`` (a ``ValueError`, so the parity scripts' existing
handlers keep working), naming the file and the field.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

__all__ = [
    "CAPTURE_HEIGHT",
    "CAPTURE_META",
    "CAPTURE_WIDTH",
    "LAYER_FIRST_ACTOR",
    "LEGACY_SIDECAR",
    "PALETTE_ENTRIES",
    "RENDER_DOCUMENT",
    "RENDER_SUFFIXES",
    "SCHEMA_VERSION",
    "ArtifactError",
    "CameraPose",
    "CaptureSet",
    "CapturedFrame",
    "FilmId",
    "FrameReport",
    "Geometry",
    "I6Gate",
    "Page",
    "RenderControls",
    "RenderPalette",
    "RenderRecord",
    "RenderTick",
    "Report",
    "RetimedDocuments",
    "frames_for_captured_ticks",
    "open_render",
    "read_capture",
    "read_capture_palette",
    "read_page",
    "read_render",
    "read_report",
    "render_plane_paths",
    "retime_document",
    "tick_stem",
    "write_capture",
    "write_render",
    "write_report",
    "write_retimed_documents",
]

#: Version carried by ``render.json`` and a capture's ``meta.json`` (port constant).
SCHEMA_VERSION = 1
#: Document written beside a render directory's frames, last.
RENDER_DOCUMENT = "render.json"
#: Capture directory description written by ``mise run capture-ref``.
CAPTURE_META = "meta.json"
#: Width of the Mode 13h raster a capture without a width was made at.
CAPTURE_WIDTH = 320
#: Height of the Mode 13h raster a capture without a height was made at.
CAPTURE_HEIGHT = 200
#: Legacy render sidecar, read until renders made before the record age out.
LEGACY_SIDECAR = "palette_controls.json"
#: Files a render writes per whole tick, beside the tick's stem.
RENDER_SUFFIXES = (".png", ".idx", ".layer")
#: Entries in a capture's ``palettes_%04d.json``; Mode 13h has a 256-entry palette.
PALETTE_ENTRIES = 256
#: First layer id an actor draw writes (mirrors ``stunt_render::LAYER_FIRST_ACTOR``).
LAYER_FIRST_ACTOR = 16
#: Zero-padding of the film clock in ``tick_%05d`` frame names.
RENDER_TICK_WIDTH = 5
#: Zero-padding of a capture ordinal in its default raster file names.
CAPTURE_ORDINAL_WIDTH = 4


class ArtifactError(ValueError):
    """A parity artifact that is absent, malformed or does not satisfy its schema.

    ``kind`` names the failure so a caller can act on it without parsing the
    message: ``missing``, ``wrong_type``, ``unsupported_version``,
    ``ordering``, ``conflict``, ``geometry``, ``frame``,
    ``report_inconsistent`` or ``io``.

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
    """One rendered tick: the film clock its files are named for."""

    tick: int
    palette: RenderPalette
    camera: CameraPose


@dataclass(frozen=True)
class RenderRecord:
    """Document written beside a render directory's frames, last."""

    schema_version: int
    film: FilmId
    geometry: Geometry
    ticks: tuple[RenderTick, ...]

    def validate(self, path: Path | None = None) -> None:
        """Check the schema version, geometry and strict tick ordering."""
        if self.schema_version != SCHEMA_VERSION:
            raise _error(
                "unsupported_version",
                f"unsupported schema version {self.schema_version}; expected {SCHEMA_VERSION}",
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
                if "/" in name or "\\" in name:
                    raise _error(
                        "frame",
                        f"frame {frame.ordinal}: {field_name} must be a basename",
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
    """Palette controls and film identity of a render directory, whichever document exists."""

    film: FilmId
    geometry: Geometry | None
    controls: dict[int, RenderPalette]
    record: RenderRecord | None
    legacy: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RetimedDocuments:
    """Which of a retimed render's documents were written."""

    record_written: bool
    sidecar_written: bool


def _film_fields(document: Mapping[str, Any], path: Path | None) -> FilmId:
    """A film identity from top-level ``film``, ``flm_bytes`` and ``flm_sha256``."""
    return FilmId(
        name=_optional_string(document.get("film"), path, "film"),
        flm_bytes=_optional_int(document.get("flm_bytes"), path, "flm_bytes"),
        flm_sha256=_optional_string(document.get("flm_sha256"), path, "flm_sha256"),
    )


def _film_object(document: Mapping[str, Any], path: Path | None) -> FilmId:
    """A film identity from the nested ``film`` object of a ``render.json``."""
    film = _as_object(document.get("film"), path, "film")
    return FilmId(
        name=_optional_string(film.get("name"), path, "film.name"),
        flm_bytes=_optional_int(film.get("flm_bytes"), path, "film.flm_bytes"),
        flm_sha256=_optional_string(film.get("flm_sha256"), path, "film.flm_sha256"),
    )


def _geometry_document(geometry: Geometry) -> dict[str, Any]:
    document: dict[str, Any] = {"width": geometry.width, "height": geometry.height}
    if geometry.viewport_rows is not None:
        document["viewport_rows"] = geometry.viewport_rows
    return document


def _geometry_object(document: Mapping[str, Any], path: Path | None) -> Geometry:
    geometry = Geometry(
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
    return geometry


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
        }
        for tick in record.ticks
    ]
    return {
        "schema_version": record.schema_version,
        "film": film,
        "geometry": _geometry_document(record.geometry),
        "ticks": ticks,
    }


def _legacy_controls(document: Any, path: Path | None) -> tuple[FilmId, dict[int, RenderPalette]]:
    """Parse the legacy sidecar's film identity and palette controls."""
    raw = _as_object(document, path, "the sidecar")
    film = _film_fields(raw, path)
    controls: dict[int, RenderPalette] = {}
    ticks = raw.get("ticks")
    if ticks is None:
        return film, controls
    for index, value in enumerate(_as_array(ticks, path, "ticks")):
        where = f"ticks[{index}]"
        entry = _as_object(value, path, where)
        tick = _as_unsigned(entry.get("tick"), path, f"{where}.tick", 0xFFFFFFFF)
        controls[tick] = RenderPalette(
            sky=_as_unsigned(entry.get("sky"), path, f"{where}.sky", 0xFFFF),
            brightness=_as_unsigned(entry.get("brightness"), path, f"{where}.brightness", 0xFFFF),
            saturation=_as_unsigned(entry.get("saturation"), path, f"{where}.saturation", 0xFFFF),
        )
    return film, controls


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


def tick_stem(tick: int) -> str:
    """The file-name stem a render writes for film-clock *tick*."""
    return f"tick_{tick:0{RENDER_TICK_WIDTH}d}"


def render_plane_paths(directory: Path, tick: int) -> tuple[Path, Path]:
    """The index and layer plane paths a render writes for *tick*."""
    stem = tick_stem(tick)
    return directory / f"{stem}.idx", directory / f"{stem}.layer"


def _read_plane(path: Path, kind: str, expected: int, geometry: Geometry) -> bytes:
    """Reads one plane file, naming it when it is unreadable or the wrong size."""
    try:
        data = path.read_bytes()
    except OSError as err:
        raise _error("missing", f"the file must be readable ({err})", path) from err
    if len(data) != expected:
        raise _error(
            "geometry",
            f"holds {len(data)} {kind}, expected {expected} for {geometry.width}x{geometry.height}",
            path,
        )
    return data


def read_page(directory: Path, tick: int, geometry: Geometry) -> Page:
    """Reads one render page's planes, sizing them from the record's full raster.

    The files span width * height pixels even when viewport_rows narrows the drawn
    scene, exactly as the Rust plane_codec writes them; only Page.actor_pixels
    narrows its scan to the viewport.
    """
    index_path, layer_path = render_plane_paths(directory, tick)
    pixels = geometry.width * geometry.height
    indices = _read_plane(index_path, "palette indices", pixels, geometry)
    layer_bytes = _read_plane(layer_path, "layer bytes", 2 * pixels, geometry)
    layers = tuple(
        int.from_bytes(layer_bytes[offset : offset + 2], "little")
        for offset in range(0, len(layer_bytes), 2)
    )
    return Page(indices=indices, layers=layers, geometry=geometry)


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
    """Read a render directory's controls, preferring ``render.json`` to the sidecar.

    A directory with neither document is incomplete: ADR 0005 makes the record
    required, so the error carries the re-render action. A legacy sidecar-only
    directory still loads, with no geometry; callers fall back to the capture's.
    """
    record_path = directory / RENDER_DOCUMENT
    if record_path.is_file():
        record = read_render(record_path)
        return RenderControls(
            film=record.film,
            geometry=record.geometry,
            controls={tick.tick: tick.palette for tick in record.ticks},
            record=record,
            legacy=False,
            warnings=(),
        )
    sidecar_path = directory / LEGACY_SIDECAR
    if not sidecar_path.is_file():
        raise _error(
            "missing",
            f"missing field {RENDER_DOCUMENT} or {LEGACY_SIDECAR} "
            "(re-render the directory with stuntreel --headless --out-dir)",
            directory,
        )
    film, controls = _legacy_controls(_read_json(sidecar_path), sidecar_path)
    return RenderControls(
        film=film,
        geometry=None,
        controls=controls,
        record=None,
        legacy=True,
        warnings=(
            f"has no {RENDER_DOCUMENT}; reading the legacy {LEGACY_SIDECAR} "
            "(re-render the directory to replace it)",
        ),
    )


#: Top-level fields the capture document owns; a diagnostic may not overwrite one.
_CAPTURE_FIELDS = frozenset(
    {"schema_version", "film", "flm_bytes", "flm_sha256", "frames", "width", "height"}
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


def retime_document(
    document: Mapping[str, Any], pairs: Iterable[tuple[int, int]]
) -> dict[str, Any]:
    """Re-label each source tick entry onto its target tick, preserving unknown keys.

    Works for both ``render.json`` and the legacy sidecar: only the ``tick`` field of
    each copied ``ticks[]`` entry changes, and entries whose source tick is absent
    are dropped. Nothing is invented, so a retime cannot introduce a frame.
    """
    entries = document.get("ticks")
    by_tick: dict[int, dict[str, Any]] = {}
    if entries is not None:
        for index, value in enumerate(_as_array(entries, None, "ticks")):
            entry = _as_object(value, None, f"ticks[{index}]")
            tick = _as_unsigned(entry.get("tick"), None, f"ticks[{index}].tick", 0xFFFFFFFF)
            by_tick[tick] = entry
    ticks: list[dict[str, Any]] = []
    for target, source in pairs:
        source_entry = by_tick.get(source)
        if source_entry is None:
            continue
        shifted = dict(source_entry)
        shifted["tick"] = target
        ticks.append(shifted)
    rebuilt: dict[str, Any] = {key: value for key, value in document.items() if key != "ticks"}
    rebuilt["ticks"] = ticks
    return rebuilt


def write_retimed_documents(
    source: Path, out: Path, pairs: Sequence[tuple[int, int]]
) -> RetimedDocuments:
    """Write *source*'s documents into *out*, relabelling ticks by *pairs*.

    *pairs* are ``(target, source)`` pairs, as ``plan_retime`` produces. The legacy
    sidecar is rewritten while it exists and ``render.json`` is written last, as the
    render journal does. Unknown keys survive the rewrite, and the shifted record is
    re-validated before it is written so it still loads in Rust.
    """
    out.mkdir(parents=True, exist_ok=True)
    sidecar_written = False
    sidecar_path = source / LEGACY_SIDECAR
    if sidecar_path.is_file():
        sidecar = _as_object(_read_json(sidecar_path), sidecar_path, "the sidecar")
        _legacy_controls(sidecar, sidecar_path)
        _write_json(out / LEGACY_SIDECAR, retime_document(sidecar, pairs))
        sidecar_written = True
    record_written = False
    record_path = source / RENDER_DOCUMENT
    if record_path.is_file():
        document = _as_object(_read_json(record_path), record_path, "the render record")
        _render_record(document, record_path).validate(record_path)
        shifted = retime_document(document, pairs)
        _render_record(shifted, record_path).validate(record_path)
        _write_json(out / RENDER_DOCUMENT, shifted)
        record_written = True
    return RetimedDocuments(record_written=record_written, sidecar_written=sidecar_written)
