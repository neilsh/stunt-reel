"""Offline tests for `python/scripts/parity_probe.py`'s report summary (synthetic data only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_probe  # noqa: E402

from stunt_reel import parity_artifacts  # noqa: E402

if TYPE_CHECKING:
    import pytest


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
