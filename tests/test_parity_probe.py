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


def test_world_shift_finds_how_far_the_capture_scene_is_moved() -> None:
    width, rows = 16, 12
    ours = bytes((x * 7 + y * 13) % 251 for y in range(rows) for x in range(width))
    # The capture holds the same scene two columns right and four rows down.
    capture = bytes(((x - 2) * 7 + (y - 4) * 13) % 251 for y in range(rows) for x in range(width))
    dx, dy, agree = parity_probe.world_shift(ours, capture, [], width, rows, reach=6)
    assert (dx, dy, agree) == (2, 4, 1.0)


def test_world_shift_ignores_actor_pixels() -> None:
    width, rows = 8, 6
    ours = bytearray(range(width * rows))
    capture = bytes(ours)
    actor = [0, 1, 2]
    for pixel in actor:
        ours[pixel] = 255  # an actor the capture does not hold
    assert parity_probe.world_shift(bytes(ours), capture, actor, width, rows, reach=2) == (
        0,
        0,
        1.0,
    )


def test_shift_summary_reports_the_actor_relative_to_the_world() -> None:
    line = parity_probe.shift_summary([(2, -4, 0, 0), (4, -2, 2, 2), (2, -4, 0, 0)])
    assert line == (
        "frames 3: median actor dx 2 dy -4; world dx 0 dy 0; actor minus world dx 2 dy -4"
    )
    assert parity_probe.shift_summary([]) == "no frame had enough actor pixels"


def test_world_shift_keeps_zero_for_an_odd_reach_and_prefers_the_smaller_tie() -> None:
    width, rows = 8, 6
    flat = bytes([3] * (width * rows))  # every offset agrees fully
    assert parity_probe.world_shift(flat, flat, [], width, rows, reach=1) == (0, 0, 1.0)
    assert parity_probe.world_shift(flat, flat, [], width, rows, reach=4) == (0, 0, 1.0)


def test_world_shift_is_not_pulled_by_the_captures_actor() -> None:
    width, rows = 16, 12
    scene = bytes((x * 7 + y * 13) % 251 for y in range(rows) for x in range(width))
    capture = bytearray(scene)
    # The capture's aircraft sits four columns right of where ours is drawn.
    ours_actor = [y * width + x for y in range(3, 6) for x in range(2, 6)]
    capture_actor = [p + 4 for p in ours_actor]
    for p in capture_actor:
        capture[p] = 250
    result = parity_probe.world_shift(
        scene, bytes(capture), ours_actor, width, rows, reach=6, capture_actor=capture_actor
    )
    assert result == (0, 0, 1.0)


def test_shifted_pixels_moves_the_silhouette_and_drops_what_leaves_the_frame() -> None:
    width, rows = 4, 3
    # (0, 0), (3, 0) and (1, 2), moved one column right and one row down.
    assert parity_probe.shifted_pixels([0, 3, 9], 1, 1, width, rows) == [5]
    assert parity_probe.shifted_pixels([5], -1, -1, width, rows) == [0]


def test_world_shift_skips_offsets_as_large_as_the_frame() -> None:
    width, rows = 8, 6
    flat = bytes([3] * (width * rows))
    assert parity_probe.world_shift(flat, flat, [], width, rows, reach=8) == (0, 0, 1.0)


def test_a_wider_capture_aircraft_does_not_move_the_world() -> None:
    width, rows = 24, 12
    sky = 230  # a CTRY background index, so never an object
    ours = bytearray([sky] * (width * rows))
    capture = bytearray(ours)
    silhouette = [y * width + x for y in range(4, 7) for x in range(8, 12)]
    for p in silhouette:
        ours[p] = 40
    # The capture's aircraft is two columns wider on the right.
    for p in [y * width + x for y in range(4, 7) for x in range(8, 14)]:
        capture[p] = 40
    capture_actor = parity_probe.capture_actor_pixels(bytes(capture), silhouette, width, rows)
    assert set(capture_actor) == {y * width + x for y in range(4, 7) for x in range(8, 14)}
    result = parity_probe.world_shift(
        bytes(ours), bytes(capture), silhouette, width, rows, reach=4, capture_actor=capture_actor
    )
    assert result == (0, 0, 1.0)


def test_scenery_between_two_separated_actors_stays_in_the_world_match() -> None:
    width, rows = 60, 10
    sky = 230
    capture = bytearray([sky] * (width * rows))
    left = [y * width + x for y in range(4, 6) for x in range(2, 4)]
    right = [y * width + x for y in range(4, 6) for x in range(56, 58)]
    tree = [y * width + x for y in range(3, 7) for x in range(29, 31)]
    for p in left + right + tree:
        capture[p] = 40
    masked = set(parity_probe.capture_actor_pixels(bytes(capture), left + right, width, rows))
    assert set(left + right) <= masked
    assert not masked & set(tree)
