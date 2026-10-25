"""Validated loaders for the JSON the Rust binaries hand the parity tooling.

``stuntreel --headless`` writes the render palette sidecar, ``stuntreel parity`` writes
the report, and ``mise run capture-ref`` writes a capture's ``meta.json`` and
``palettes_%04d.json``. None of those files carries a schema or a version, so a shape
change would otherwise surface as a ``KeyError`` in the middle of a sweep, after the
renders have been paid for. Each loader checks the fields its callers read and raises
``ParityInputError`` naming the file and the field.

The data keeps its own shape: ``retime`` rewrites the sidecar and must preserve keys
this tool does not know, so the loader validates without reformatting what it reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

__all__ = [
    "PALETTE_ENTRIES",
    "ParityInputError",
    "capture_ticks",
    "load_palette",
    "load_sidecar",
    "scored_frames",
]

#: Entries in a capture's ``palettes_%04d.json``; Mode 13h has a 256-entry palette.
PALETTE_ENTRIES = 256


class ParityInputError(ValueError):
    """A JSON artifact is missing a field the tool needs, or has one of the wrong type."""

    def __init__(self, path: Path, field: str, expected: str) -> None:
        super().__init__(f"{path}: {field} must be {expected}")
        self.path = path
        self.field = field


def _read_json(path: Path) -> Any:
    """Parse *path*, reporting an unreadable or malformed file the same way as a bad field."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise ParityInputError(path, "the file", f"readable ({err})") from err
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        raise ParityInputError(path, "the file", "valid JSON") from err


def _as_object(value: Any, path: Path, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ParityInputError(path, field, "an object")
    return cast("dict[str, Any]", value)


def _as_array(value: Any, path: Path, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ParityInputError(path, field, "an array")
    return value


def _as_int(value: Any, path: Path, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParityInputError(path, field, "an integer")
    return value


def _as_bool(value: Any, path: Path, field: str) -> bool:
    if not isinstance(value, bool):
        raise ParityInputError(path, field, "true or false")
    return value


def scored_frames(report: Path) -> list[dict[str, Any]]:
    """The entries of a ``stuntreel parity`` report's ``per_frame`` array that were scored."""
    data = _as_object(_read_json(report), report, "the report")
    frames = _as_array(data.get("per_frame"), report, "per_frame")
    scored: list[dict[str, Any]] = []
    for index, raw in enumerate(frames):
        where = f"per_frame[{index}]"
        frame = _as_object(raw, report, where)
        if not _as_bool(frame.get("scored"), report, f"{where}.scored"):
            continue
        _as_int(frame.get("film_tick"), report, f"{where}.film_tick")
        _as_int(frame.get("ordinal"), report, f"{where}.ordinal")
        scored.append(frame)
    return scored


def capture_ticks(reference: Path) -> list[int]:
    """The film clock of every captured frame in a capture directory's ``meta.json``."""
    meta_path = reference / "meta.json"
    meta = _as_object(_read_json(meta_path), meta_path, "the capture metadata")
    frames = _as_array(meta.get("frames"), meta_path, "frames")
    ticks: list[int] = []
    for index, raw in enumerate(frames):
        where = f"frames[{index}]"
        frame = _as_object(raw, meta_path, where)
        ticks.append(_as_int(frame.get("film_tick"), meta_path, f"{where}.film_tick"))
    return ticks


def load_sidecar(sidecar: Path) -> dict[str, Any]:
    """A render's ``palette_controls.json``, with every ``ticks[]`` entry naming its tick.

    A sidecar without ``ticks`` is returned as-is: older renders may have none, and the
    retime that consumes it reports the missing palette entries itself.
    """
    data = _as_object(_read_json(sidecar), sidecar, "the sidecar")
    raw_ticks = data.get("ticks")
    if raw_ticks is None:
        return data
    for index, raw in enumerate(_as_array(raw_ticks, sidecar, "ticks")):
        where = f"ticks[{index}]"
        entry = _as_object(raw, sidecar, where)
        _as_int(entry.get("tick"), sidecar, f"{where}.tick")
    return data


def load_palette(path: Path) -> list[list[int]]:
    """The 256 RGB triples of a capture's ``palettes_%04d.json``."""
    entries = _as_array(_read_json(path), path, "the palette")
    if len(entries) != PALETTE_ENTRIES:
        raise ParityInputError(
            path, "the palette", f"{PALETTE_ENTRIES} RGB triples, got {len(entries)}"
        )
    palette: list[list[int]] = []
    for index, raw in enumerate(entries):
        entry = _as_array(raw, path, f"[{index}]")
        if len(entry) < 3:
            raise ParityInputError(path, f"[{index}]", "at least 3 channel values")
        palette.append(
            [
                _as_int(value, path, f"[{index}][{channel}]")
                for channel, value in enumerate(entry[:3])
            ]
        )
    return palette
