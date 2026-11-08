"""Offline tests for the report document in the Python parity artifact adapter (synthetic documents only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from artifact_helpers import (
    sample_report,
    write_json,
)
from stunt_reel.parity_artifacts import (
    ArtifactError,
    FrameReport,
    I6Gate,
    RenderAdapter,
    Report,
    read_report,
    write_report,
)


def test_a_report_round_trips_through_json(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    report = sample_report()
    write_report(path, report)
    assert read_report(path) == report
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["mean_ssim_scored"] == 0.7
    assert document["i6_gate"] == {"initial": False, "sign_off": False}
    assert document["per_frame"][0]["scored"] is True


def test_an_old_report_without_optional_fields_still_loads(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "report.json",
        {"per_frame": [{"film_tick": 9, "ssim": 0.7, "iou": 0.9}]},
    )
    report = read_report(path)
    assert report.per_frame == (FrameReport(film_tick=9, ssim=0.7, iou=0.9),)
    assert report.scored_frames == 0
    assert report.credits_missing_frames == 0
    assert report.i6_gate == I6Gate()
    assert report.headline() == (0.0, 0.0)


def test_a_report_records_its_adapter(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "parity" / "v1" / "report.json"
    report = read_report(fixture)
    assert report.adapter == RenderAdapter("Test GPU", "hardware")
    path = tmp_path / "report.json"
    write_report(path, report)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["adapter"] == {"name": "Test GPU", "class": "hardware"}


@pytest.mark.parametrize("adapter", [{}, {"adapter": None}], ids=["absent", "null"])
def test_a_report_without_an_adapter_reads_none(tmp_path: Path, adapter: dict[str, Any]) -> None:
    path = write_json(tmp_path / "report.json", {"per_frame": [], **adapter})
    report = read_report(path)
    assert report.adapter is None
    write_report(path, report)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["adapter"] is None, "report.json writes an unknown adapter as null"


def test_an_unknown_adapter_class_is_refused(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "report.json",
        {"per_frame": [], "adapter": {"name": "Test GPU", "class": "quantum"}},
    )
    with pytest.raises(ArtifactError, match=r"adapter\.class") as refusal:
        read_report(path)
    assert refusal.value.kind == "wrong_type"


def test_headline_prefers_the_scored_means() -> None:
    assert sample_report().headline() == (0.7, 0.9)
    all_frames = Report(
        per_frame=(),
        mean_ssim=0.5,
        mean_iou=0.6,
        mean_ssim_scored=None,
        mean_iou_scored=None,
    )
    assert all_frames.headline() == (0.5, 0.6)


def test_write_report_checks_the_identities() -> None:
    broken = Report(per_frame=(), reference_frames=1)
    with pytest.raises(ArtifactError, match="reference_frames must equal"):
        write_report(Path("unused.json"), broken)
    for count in (1, -1):
        bad = Report(per_frame=(), credits_missing_frames=count)
        with pytest.raises(ArtifactError, match="credits_missing_frames must be from 0"):
            write_report(Path("unused.json"), bad)
