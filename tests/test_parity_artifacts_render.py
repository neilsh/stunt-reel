"""Offline tests for the render record in the Python parity artifact adapter (synthetic documents only)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from artifact_helpers import (
    raw_record,
    sample_geometry,
    sample_record,
    sample_tick,
    store_record,
    write_json,
)
from stunt_reel.parity_artifacts import (
    FILM_FIELDS,
    RENDER_SCHEMA_VERSION,
    ArtifactError,
    FilmCheck,
    FilmId,
    Geometry,
    RenderAdapter,
    RenderRecord,
    open_render,
    read_render,
    tick_range_for_captured_ticks,
    write_render,
)


def test_a_render_record_round_trips_through_json(tmp_path: Path) -> None:
    path = tmp_path / "render.json"
    record = sample_record()
    write_render(path, record)
    assert read_render(path) == record
    assert b"\r" not in path.read_bytes(), "render.json is written with LF line endings"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == RENDER_SCHEMA_VERSION
    assert document["film"] == {"name": "CTRY.FLM", "flm_bytes": 100}
    assert document["geometry"] == {"width": 320, "height": 200, "viewport_rows": 185}
    assert [entry["tick"] for entry in document["ticks"]] == [10, 12]
    assert document["ticks"][0]["palette"]["sky"] == 0x2000
    assert document["ticks"][0]["camera"]["eye"] == [0.0, 10.0, 50.0]
    assert document["ticks"][0]["palette_index"] == 0
    assert document["ticks"][0]["credits"] is False
    assert document["palette_count"] == 1
    assert document["chunks"] == [
        {
            "second": 0,
            "ticks": 2,
            "index": {"offset": 0, "length": 10},
            "layer": {"offset": 0, "length": 10},
        }
    ]


def test_a_document_written_by_the_rust_side_loads_and_extra_keys_are_ignored(
    tmp_path: Path,
) -> None:
    record = read_render(write_json(tmp_path / "render.json", raw_record()))
    assert record.schema_version == RENDER_SCHEMA_VERSION
    assert record.film == FilmId(name="CTRY.FLM", flm_bytes=100)
    assert record.geometry == sample_geometry()
    assert record.ticks == (replace(sample_tick(10), credits=True),)
    extra = raw_record()
    extra["future_top"] = {"kept": True}
    assert read_render(write_json(tmp_path / "extra.json", extra)) == record


def test_a_render_records_its_adapter(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "parity" / "v3" / "render"
    record = read_render(fixture / "render.json")
    assert record.adapter == RenderAdapter("Test GPU", "hardware")
    path = tmp_path / "render.json"
    write_render(path, record)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["adapter"] == {"name": "Test GPU", "class": "hardware"}


def test_a_render_without_an_adapter_reads_none(tmp_path: Path) -> None:
    raw = raw_record()
    assert "adapter" not in raw
    record = read_render(write_json(tmp_path / "absent.json", raw))
    assert record.adapter is None
    raw["adapter"] = None
    assert read_render(write_json(tmp_path / "null.json", raw)) == record
    path = tmp_path / "render.json"
    write_render(path, record)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert "adapter" not in document, "render.json leaves an unknown adapter out"


def test_an_unknown_adapter_class_is_refused(tmp_path: Path) -> None:
    raw = raw_record()
    raw["adapter"] = {"name": "Test GPU", "class": "quantum"}
    with pytest.raises(ArtifactError, match=r"adapter\.class") as refusal:
        read_render(write_json(tmp_path / "render.json", raw))
    assert refusal.value.kind == "wrong_type"


def test_a_tick_without_its_credits_flag_is_refused(tmp_path: Path) -> None:
    raw = raw_record()
    del raw["ticks"][0]["credits"]
    with pytest.raises(ArtifactError, match=r"ticks\[0\]\.credits") as refusal:
        read_render(write_json(tmp_path / "render.json", raw))
    assert refusal.value.kind == "wrong_type"


def test_an_unsupported_version_is_rejected_and_names_the_directory(tmp_path: Path) -> None:
    write_json(tmp_path / "render.json", raw_record(9))
    with pytest.raises(ArtifactError, match="schema version 9") as refusal:
        read_render(tmp_path / "render.json")
    assert refusal.value.kind == "unsupported_version"
    with pytest.raises(ArtifactError) as from_directory:
        open_render(tmp_path)
    assert from_directory.value.kind == "unsupported_version"
    assert from_directory.value.path == tmp_path / "render.json"


@pytest.mark.parametrize(
    ("geometry", "message"),
    [
        (Geometry(width=0, height=200), "width and height must be positive"),
        (
            Geometry(width=320, height=200, viewport_rows=201),
            "viewport_rows must be between 1 and height",
        ),
    ],
)
def test_geometry_is_validated_before_anything_is_read(
    tmp_path: Path, geometry: Geometry, message: str
) -> None:
    record = RenderRecord(RENDER_SCHEMA_VERSION, FilmId(), geometry, (), 0, ())
    with pytest.raises(ArtifactError, match=message) as refusal:
        write_render(tmp_path / "render.json", record)
    assert refusal.value.kind == "geometry"


def test_tick_ordering_is_checked(tmp_path: Path) -> None:
    duplicate = replace(store_record((10,)), ticks=(sample_tick(10), sample_tick(10)))
    with pytest.raises(ArtifactError, match="duplicate tick at index 1") as repeat:
        duplicate.validate(tmp_path / "render.json")
    assert repeat.value.kind == "ordering"
    unordered = replace(store_record((10,)), ticks=(sample_tick(12), sample_tick(10)))
    with pytest.raises(ArtifactError, match="not strictly ascending at index 1"):
        unordered.validate()


def test_film_conflicts_need_both_sides() -> None:
    full = FilmId(name="CTRY.FLM", flm_bytes=100, flm_sha256="aa", all_sha256="bb")
    assert full.conflicts(FilmId()) == ()
    other = FilmId(name="intro.flm", flm_bytes=101, flm_sha256="cc", all_sha256="dd")
    assert full.conflicts(other) == FILM_FIELDS


_FILM_CASES = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "parity" / "film_identity.json").read_text(
        encoding="utf-8"
    )
)["cases"]


@pytest.mark.parametrize("case", _FILM_CASES, ids=[case["case"] for case in _FILM_CASES])
def test_every_shared_film_case_has_its_outcome(case: dict[str, Any]) -> None:
    capture, render = FilmId(**case["capture"]), FilmId(**case["render"])
    check = render.check(capture, waive_archive=case["waive_archive"])
    assert check == FilmCheck(case["outcome"], tuple(case.get("fields", ())))


def test_open_render_reads_the_record(tmp_path: Path) -> None:
    write_render(tmp_path / "render.json", sample_record())
    controls = open_render(tmp_path)
    assert controls.geometry == sample_geometry()
    assert controls.film == FilmId(name="CTRY.FLM", flm_bytes=100)
    assert controls.controls[10].sky == 0x2000
    assert controls.record == sample_record()


def test_open_render_refuses_a_version_2_render_with_the_re_render_action(
    tmp_path: Path,
) -> None:
    write_json(tmp_path / "render.json", raw_record(2))
    with pytest.raises(ArtifactError, match="re-render") as refusal:
        open_render(tmp_path)
    assert refusal.value.kind == "unsupported_version"


def test_open_render_refuses_a_directory_with_neither_document(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="re-render") as refusal:
        open_render(tmp_path)
    assert refusal.value.kind == "missing"
    assert refusal.value.path == tmp_path


def test_tick_range_for_captured_ticks_is_the_captures_own_inclusive_ticks() -> None:
    # 0-based and inclusive: no offset between a capture's film tick and the range
    assert tick_range_for_captured_ticks([769, 3640, 1000]) == "769..=3640"
    assert tick_range_for_captured_ticks([10]) == "10..=10"
    assert tick_range_for_captured_ticks([0, 1342]) == "0..=1342"


def test_tick_range_for_captured_ticks_needs_a_capture() -> None:
    with pytest.raises(ArtifactError, match="no --tick-range"):
        tick_range_for_captured_ticks([])


def test_a_tick_credits_flag_round_trips_and_is_always_written(tmp_path: Path) -> None:
    """``credits`` is required from schema 3, so it is written for every tick."""
    path = tmp_path / "render.json"
    record = sample_record()
    flagged = replace(record, ticks=(replace(record.ticks[0], credits=True), record.ticks[1]))
    write_render(path, flagged)
    assert read_render(path) == flagged
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["ticks"][0]["credits"] is True
    assert document["ticks"][1]["credits"] is False
    document["ticks"][0]["credits"] = 1
    write_json(path, document)
    with pytest.raises(ArtifactError, match=r"ticks\[0\]\.credits"):
        read_render(path)
