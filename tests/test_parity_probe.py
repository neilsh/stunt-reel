"""Offline tests for the retime helpers of `python/scripts/parity_probe.py` (synthetic data only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_probe  # noqa: E402

from stunt_reel import parity_artifacts  # noqa: E402
from stunt_reel.parity_artifacts import (  # noqa: E402
    SCHEMA_VERSION,
    CameraPose,
    FilmId,
    Geometry,
    RenderPalette,
    RenderRecord,
    RenderTick,
    read_render,
)


def _capture(tmp_path: Path, ticks: list[int]) -> Path:
    """A capture directory whose `meta.json` tags `ticks` as the film clock."""
    reference = tmp_path / "ref"
    reference.mkdir()
    frames = [{"ordinal": index + 1, "film_tick": tick} for index, tick in enumerate(ticks)]
    (reference / "meta.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")
    return reference


def _record(ticks: list[int]) -> RenderRecord:
    return RenderRecord(
        schema_version=SCHEMA_VERSION,
        film=FilmId(name="CTRY.FLM", flm_bytes=100),
        geometry=Geometry(width=320, height=200, viewport_rows=185),
        ticks=tuple(
            RenderTick(
                tick=tick,
                palette=RenderPalette(sky=45, brightness=32768, saturation=32768),
                camera=CameraPose(
                    eye=(0.0, 0.0, 0.0),
                    target=(0.0, 0.0, 0.0),
                    fov_degrees=45.0,
                    roll_radians=0.0,
                ),
            )
            for tick in ticks
        ),
    )


def _sidecar(ticks: list[int]) -> dict[str, Any]:
    return {
        "film": "CTRY.FLM",
        "flm_bytes": 100,
        "ticks": [
            {
                "tick": tick,
                "camera": {"eye": [tick, 0, 0]},
                "brightness": 32768,
                "saturation": 32768,
                "sky": 45,
            }
            for tick in ticks
        ],
    }


def _render(
    tmp_path: Path, name: str, ticks: list[int], *, sidecar: bool = True, record: bool = True
) -> Path:
    """A render directory with the three per-tick files and, optionally, its documents."""
    render = tmp_path / name
    render.mkdir()
    for tick in ticks:
        for ext in parity_artifacts.RENDER_SUFFIXES:
            (render / f"tick_{tick:05d}{ext}").write_bytes(f"{tick}{ext}".encode())
    if record:
        parity_artifacts.write_render(render / parity_artifacts.RENDER_DOCUMENT, _record(ticks))
    if sidecar:
        (render / parity_artifacts.LEGACY_SIDECAR).write_text(
            json.dumps(_sidecar(ticks)), encoding="utf-8"
        )
    return render


def test_plan_retime_maps_each_distinct_tick_in_both_directions() -> None:
    assert parity_probe.plan_retime([12, 10, 12], 1) == [(10, 11), (12, 13)]
    assert parity_probe.plan_retime([10, 12], -1) == [(10, 9), (12, 11)]
    assert parity_probe.plan_retime([7], 0) == [(7, 7)]


def test_retime_copies_planes_under_target_names_and_rewrites_both_documents(
    tmp_path: Path,
) -> None:
    reference = _capture(tmp_path, [10, 11, 12])
    render = _render(tmp_path, "ours", [10, 11, 12])
    out = tmp_path / "retimed"
    result = parity_probe.retime_render(render, reference, out, 0)
    assert result.copied == 3
    assert result.missing == []
    assert result.palette_written is True
    assert result.record_written is True
    for tick in (10, 11, 12):
        for ext in parity_artifacts.RENDER_SUFFIXES:
            assert (out / f"tick_{tick:05d}{ext}").read_bytes() == f"{tick}{ext}".encode()
    palette = json.loads((out / parity_artifacts.LEGACY_SIDECAR).read_text(encoding="utf-8"))
    assert [entry["tick"] for entry in palette["ticks"]] == [10, 11, 12]
    assert palette["film"] == "CTRY.FLM"
    record = read_render(out / parity_artifacts.RENDER_DOCUMENT)
    assert [tick.tick for tick in record.ticks] == [10, 11, 12]
    assert record.ticks[0].palette == _record([10]).ticks[0].palette


def test_retime_positive_offset_takes_the_next_ticks_frames(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10, 11])
    render = _render(tmp_path, "ours", [11, 12], sidecar=False)
    out = tmp_path / "retimed"
    result = parity_probe.retime_render(render, reference, out, 1)
    assert result.copied == 2
    assert result.missing == []
    assert result.palette_written is False
    assert result.record_written is True
    assert (out / "tick_00010.png").read_bytes() == b"11.png"
    assert (out / "tick_00011.png").read_bytes() == b"12.png"
    assert not (out / parity_artifacts.LEGACY_SIDECAR).exists()
    record = read_render(out / parity_artifacts.RENDER_DOCUMENT)
    assert [tick.tick for tick in record.ticks] == [10, 11]


def test_retime_negative_offset_names_the_first_missing_tick(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10, 11])
    render = _render(tmp_path, "ours", [10])
    with pytest.raises(parity_probe.RetimeError, match="first 10"):
        parity_probe.retime_render(render, reference, tmp_path / "out", -1)
    result = parity_probe.retime_render(render, reference, tmp_path / "out", -1, allow_missing=True)
    assert result.copied == 1
    assert result.missing == [10]
    assert (tmp_path / "out" / "tick_00011.png").is_file()
    assert not (tmp_path / "out" / "tick_00010.png").exists()


def test_retime_refuses_a_non_empty_output_unless_forced(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10])
    render = _render(tmp_path, "ours", [10])
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("x", encoding="utf-8")
    with pytest.raises(parity_probe.RetimeError, match="not empty"):
        parity_probe.retime_render(render, reference, out, 0)
    result = parity_probe.retime_render(render, reference, out, 0, force=True)
    assert result.copied == 1


def test_retime_without_documents_copies_frames_only(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10])
    render = _render(tmp_path, "ours", [10], sidecar=False, record=False)
    out = tmp_path / "out"
    result = parity_probe.retime_render(render, reference, out, 0)
    assert result.palette_written is False
    assert result.record_written is False
    assert not (out / parity_artifacts.LEGACY_SIDECAR).exists()
    assert not (out / parity_artifacts.RENDER_DOCUMENT).exists()


def test_retime_keeps_the_legacy_sidecar_in_sync_while_it_exists(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10])
    render = _render(tmp_path, "ours", [10], record=False)
    out = tmp_path / "out"
    result = parity_probe.retime_render(render, reference, out, 0)
    assert result.palette_written is True
    assert result.record_written is False
    assert (out / parity_artifacts.LEGACY_SIDECAR).is_file()
    assert not (out / parity_artifacts.RENDER_DOCUMENT).exists()


def test_retime_preserves_unknown_document_keys(tmp_path: Path) -> None:
    reference = _capture(tmp_path, [10])
    render = _render(tmp_path, "ours", [10])
    record_path = render / parity_artifacts.RENDER_DOCUMENT
    record_document: dict[str, Any] = json.loads(record_path.read_text(encoding="utf-8"))
    record_document["future_top"] = {"kept": True}
    record_document["ticks"][0]["future_entry"] = [1, 2]
    record_path.write_text(json.dumps(record_document), encoding="utf-8")
    sidecar_path = render / parity_artifacts.LEGACY_SIDECAR
    sidecar_document: dict[str, Any] = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar_document["future_top"] = True
    sidecar_path.write_text(json.dumps(sidecar_document), encoding="utf-8")

    out = tmp_path / "out"
    parity_probe.retime_render(render, reference, out, 0)

    shifted: dict[str, Any] = json.loads(
        (out / parity_artifacts.RENDER_DOCUMENT).read_text(encoding="utf-8")
    )
    assert shifted["future_top"] == {"kept": True}
    assert shifted["ticks"][0]["future_entry"] == [1, 2]
    shifted_sidecar: dict[str, Any] = json.loads(
        (out / parity_artifacts.LEGACY_SIDECAR).read_text(encoding="utf-8")
    )
    assert shifted_sidecar["future_top"] is True


def _report(per_frame: tuple[parity_artifacts.FrameReport, ...]) -> parity_artifacts.Report:
    """A report whose totals agree with the frames given, so ``validate`` accepts it."""
    scored = [frame for frame in per_frame if frame.scored is True]
    return parity_artifacts.Report(
        per_frame=per_frame,
        reference_frames=len(per_frame),
        frames=len(per_frame),
        scored_frames=len(scored),
        excluded_frames=len(per_frame) - len(scored),
        mean_ssim_scored=sum(frame.ssim for frame in scored) / len(scored) if scored else None,
        mean_iou_scored=sum(frame.iou for frame in scored) / len(scored) if scored else None,
        mean_loss_by_class_scored={"props": 0.02, "terrain": 0.01},
    )


def test_summary_prints_the_headline_the_worst_frames_and_the_log_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    frames = (
        parity_artifacts.FrameReport(film_tick=10, ssim=0.50, iou=0.90, ordinal=1, scored=True),
        parity_artifacts.FrameReport(film_tick=11, ssim=0.90, iou=0.95, ordinal=2, scored=True),
        parity_artifacts.FrameReport(film_tick=12, ssim=0.00, iou=0.00, ordinal=3, scored=False),
    )
    path = tmp_path / "ctry" / "report.json"
    path.parent.mkdir()
    parity_artifacts.write_report(path, _report(frames))

    parity_probe.cmd_summary(argparse.Namespace(report=path, worst=1))

    out = capsys.readouterr().out
    assert "ssim 0.7000" in out
    assert "iou 0.9250" in out
    assert "loss by class: props 0.0200  terrain 0.0100" in out
    assert "worst scored frames: tick 10 0.500" in out
    assert "| 2/3 | 0.700 | 0.925 |" in out
