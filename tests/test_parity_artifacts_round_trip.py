"""Offline tests that every optional field of every parity artifact document survives a round trip."""

from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass, replace
from typing import TYPE_CHECKING, Any
lazy from pathlib import Path

import pytest

from artifact_helpers import (
    sample_capture,
    sample_record,
    sample_report,
    sample_video,
)
from stunt_reel.parity_artifacts import (
    FilmId,
    Geometry,
    RenderAdapter,
    load_video_capture,
    read_capture,
    read_render,
    read_report,
    write_capture,
    write_render,
    write_report,
    write_video_capture,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _unset_optional_fields(value: object) -> set[str]:
    """Optional (default ``None``) dataclass fields that no node in *value*'s tree populates."""
    declared: set[str] = set()
    populated: set[str] = set()

    def walk(node: object) -> None:
        if is_dataclass(node) and not isinstance(node, type):
            for field in fields(node):
                name = f"{type(node).__name__}.{field.name}"
                child = getattr(node, field.name)
                if field.default is None and field.default_factory is MISSING:
                    declared.add(name)
                    if child is not None:
                        populated.add(name)
                walk(child)
        elif isinstance(node, (tuple, list)):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)

    walk(value)
    return declared - populated


_FULL_FILM = FilmId(name="CTRY.FLM", flm_bytes=100, flm_sha256="abc", all_sha256="def")
_CPU_ADAPTER = RenderAdapter("llvmpipe (LLVM 19.1.7, 256 bits)", "cpu")


def _round_trip_capture(directory: Path, capture: Any) -> Any:
    write_capture(directory, capture)
    return read_capture(directory)


def _round_trip_video(directory: Path, capture: Any) -> Any:
    write_video_capture(directory, capture, diagnostics={})
    return load_video_capture(directory)


def _round_trip_render(directory: Path, record: Any) -> Any:
    write_render(directory / "render.json", record)
    return read_render(directory / "render.json")


def _round_trip_report(directory: Path, report: Any) -> Any:
    write_report(directory / "report.json", report)
    return read_report(directory / "report.json")


@pytest.mark.parametrize(
    ("round_trip", "make", "exempt"),
    [
        # A still capture has no viewport: CaptureSet.validate refuses one.
        (
            _round_trip_capture,
            lambda: replace(sample_capture(), film=_FULL_FILM),
            {"Geometry.viewport_rows"},
        ),
        (
            _round_trip_video,
            lambda: replace(
                sample_video(), film=_FULL_FILM, geometry=Geometry(4, 2, 2), playone_sha256="22"
            ),
            set(),
        ),
        (
            _round_trip_render,
            lambda: replace(sample_record(), film=_FULL_FILM, adapter=_CPU_ADAPTER),
            set(),
        ),
        (
            _round_trip_report,
            lambda: replace(
                sample_report(), adapter=_CPU_ADAPTER, archive_conflict_waived=True, crates="f" * 40
            ),
            set(),
        ),
    ],
    ids=["capture", "video", "render", "report"],
)
def test_every_optional_field_survives_a_round_trip(
    tmp_path: Path,
    round_trip: Callable[[Path, Any], Any],
    make: Callable[[], Any],
    exempt: set[str],
) -> None:
    value = make()
    # A writer emits an optional field only when it is set, so a field the fixture leaves unset
    # is one a dropped write would not show; set each one so the equality below covers it.
    unset = _unset_optional_fields(value) - exempt
    assert not unset, f"set these fields in the fixture: {sorted(unset)}"
    assert round_trip(tmp_path, value) == value
