"""Errors, JSON file access and field readers shared by every parity artifact document."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


#: Version carried by a capture's ``meta.json``, frame or video (port constant).
SCHEMA_VERSION = 1
#: Capture directory description written by ``mise run capture-ref``.
CAPTURE_META = "meta.json"
#: Entries in a capture's ``palettes_%04d.json``; Mode 13h has a 256-entry palette.
PALETTE_ENTRIES = 256


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
    return _parse_json(text, path)


def _parse_json(text: str | bytes, path: Path) -> Any:
    """Parse *text* read from *path*, reporting malformed JSON as an artifact error."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise _error("wrong_type", "the file must be valid JSON", path) from err


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    """Write *document* through a temporary file and rename, so readers never see half."""
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        # LF on every platform, as the Rust adapter writes and the repository stores (.editorconfig).
        temporary.write_text(text, encoding="utf-8", newline="\n")
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
