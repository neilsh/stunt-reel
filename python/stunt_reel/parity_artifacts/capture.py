"""The capture document: a capture directory's ``meta.json`` and its palette files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from stunt_reel.parity_artifacts._fields import (
    CAPTURE_META,
    PALETTE_ENTRIES,
    SCHEMA_VERSION,
    _as_array,
    _as_object,
    _as_unsigned,
    _error,
    _optional_string,
    _read_json,
    _write_json,
    _wrong_type,
)
from stunt_reel.parity_artifacts.render import FilmId, Geometry, _film_fields

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


#: Width of the Mode 13h raster a capture without a width was made at.
CAPTURE_WIDTH = 320
#: Height of the Mode 13h raster a capture without a height was made at.
CAPTURE_HEIGHT = 200
#: Zero-padding of a capture ordinal in its default raster file names.
CAPTURE_ORDINAL_WIDTH = 4
#: The one subdirectory of a capture a frame or palette file name may point into (ADR 0024).
CAPTURE_FRAMES_DIR = "frames"


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
        if self.geometry.viewport_rows is not None:
            # meta.json has no viewport field: a capture is the whole screen.
            raise _error("geometry", "invalid geometry: a capture has no viewport_rows", path)
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


def read_capture_palette(path: Path) -> tuple[tuple[int, int, int], ...]:
    """The 256 RGB triples of a capture's ``palettes_%04d.json``."""
    return _capture_palette_object(_read_json(path), path)
