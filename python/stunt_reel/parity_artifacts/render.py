"""The render record: ``render.json``, its typed records and the ``--tick-range`` mapping.

The film identity and raster geometry live here too, because the capture and video documents
carry them in the same shape.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from itertools import accumulate
from typing import TYPE_CHECKING, Any, Literal

from stunt_reel.parity_artifacts._fields import (
    ArtifactError,
    _as_array,
    _as_bool,
    _as_float,
    _as_object,
    _as_string,
    _as_unsigned,
    _error,
    _optional_int,
    _optional_string,
    _read_json,
    _vector3,
    _write_json,
    _wrong_type,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path


#: Version carried by ``render.json`` (port constant).
RENDER_SCHEMA_VERSION = 3
#: Document written beside a render directory's frames, last.
RENDER_DOCUMENT = "render.json"
#: Film ticks per render chunk: one film second of the authored 50 Hz clock [I4].
RENDER_CHUNK_TICKS = 50
#: Largest byte offset a render's chunk table may reach: a u64, as in the Rust record.
_MAX_OFFSET = 2**64 - 1
#: First layer id an actor draw writes (mirrors ``stunt_render::LAYER_FIRST_ACTOR``).
LAYER_FIRST_ACTOR = 16

#: What kind of adapter drew a render: a GPU, or a CPU implementation such as lavapipe or WARP.
AdapterClass = Literal["hardware", "cpu"]
_ADAPTER_CLASSES: tuple[AdapterClass, ...] = ("hardware", "cpu")


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
    #: The film shows credits at this tick; required in ``render.json`` from version 3.
    credits: bool = False


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
class RenderAdapter:
    """The graphics adapter a render was drawn on."""

    #: Adapter name as its driver reports it.
    name: str
    #: Whether the adapter is a GPU or a CPU implementation; the document's ``class``.
    adapter_class: AdapterClass


@dataclass(frozen=True)
class RenderRecord:
    """Document written beside a render directory's plane files, last."""

    schema_version: int
    film: FilmId
    geometry: Geometry
    ticks: tuple[RenderTick, ...]
    palette_count: int
    chunks: tuple[RenderChunk, ...]
    #: Adapter the frames were drawn on; ``None`` in renders written before it was recorded.
    adapter: RenderAdapter | None = None

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
            if max(ends) > _MAX_OFFSET:
                raise at("lengths run past the largest file offset")
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
        row = bisect.bisect_left(self.ticks, tick, key=lambda entry: entry.tick)
        if row == len(self.ticks) or self.ticks[row].tick != tick:
            return None
        ends = list(accumulate(chunk.ticks for chunk in self.chunks))
        number = bisect.bisect_right(ends, row)
        if number == len(self.chunks):
            return None
        return number, row - (ends[number] - self.chunks[number].ticks)


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
        credits=_as_bool(raw.get("credits"), path, f"{field_name}.credits"),
    )


def _adapter_object(value: Any, path: Path | None) -> RenderAdapter | None:
    """The top-level ``adapter`` of a ``render.json`` or ``report.json``; absent or null is None."""
    if value is None:
        return None
    raw = _as_object(value, path, "adapter")
    name = _as_string(raw.get("name"), path, "adapter.name")
    for adapter_class in _ADAPTER_CLASSES:
        if raw.get("class") == adapter_class:
            return RenderAdapter(name=name, adapter_class=adapter_class)
    raise _wrong_type(path, "adapter.class", '"hardware" or "cpu"')


def _adapter_document(adapter: RenderAdapter) -> dict[str, Any]:
    return {"name": adapter.name, "class": adapter.adapter_class}


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
        adapter=_adapter_object(raw.get("adapter"), path),
    )


def _tick_document(tick: RenderTick) -> dict[str, Any]:
    document: dict[str, Any] = {
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
        "credits": tick.credits,
    }
    return document


def _render_document(record: RenderRecord) -> dict[str, Any]:
    film: dict[str, Any] = {}
    if record.film.name is not None:
        film["name"] = record.film.name
    if record.film.flm_bytes is not None:
        film["flm_bytes"] = record.film.flm_bytes
    if record.film.flm_sha256 is not None:
        film["flm_sha256"] = record.film.flm_sha256
    if record.film.all_sha256 is not None:
        film["all_sha256"] = record.film.all_sha256
    ticks = [_tick_document(tick) for tick in record.ticks]
    chunks = [
        {
            "second": chunk.second,
            "ticks": chunk.ticks,
            "index": {"offset": chunk.index.offset, "length": chunk.index.length},
            "layer": {"offset": chunk.layer.offset, "length": chunk.layer.length},
        }
        for chunk in record.chunks
    ]
    document: dict[str, Any] = {
        "schema_version": record.schema_version,
        "film": film,
        "geometry": _geometry_document(record.geometry),
        "ticks": ticks,
        "palette_count": record.palette_count,
        "chunks": chunks,
    }
    if record.adapter is not None:
        document["adapter"] = _adapter_document(record.adapter)
    return document


def _store_span(value: Any, path: Path | None, field_name: str) -> StoreSpan:
    raw = _as_object(value, path, field_name)
    return StoreSpan(
        offset=_as_unsigned(raw.get("offset"), path, f"{field_name}.offset", _MAX_OFFSET),
        length=_as_unsigned(raw.get("length"), path, f"{field_name}.length", _MAX_OFFSET),
    )


def _chunk_object(value: Any, path: Path | None, field_name: str) -> RenderChunk:
    raw = _as_object(value, path, field_name)
    return RenderChunk(
        second=_as_unsigned(raw.get("second"), path, f"{field_name}.second", 0xFFFFFFFF),
        ticks=_as_unsigned(raw.get("ticks"), path, f"{field_name}.ticks", 0xFFFFFFFF),
        index=_store_span(raw.get("index"), path, f"{field_name}.index"),
        layer=_store_span(raw.get("layer"), path, f"{field_name}.layer"),
    )


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


def tick_range_for_captured_ticks(ticks: Iterable[int]) -> str:
    """The ``--tick-range`` covering the captured film ticks.

    The range is 0-based and inclusive, so it is the capture's own ticks:
    ``min..=max``.
    """
    values = list(ticks)
    if not values:
        raise _error("missing", "a capture with no frames has no --tick-range")
    return f"{min(values)}..={max(values)}"


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
