"""The Haiku judge's blind composites carry no key, and its answers are scored from the seed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from stunt_reel.bench.faults import ALL_FAULTS
from stunt_reel.bench.judge import answer_key, make_composites, score_answers
from stunt_reel.parity_artifacts import FrameReport, I6Gate, Report, write_report

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def inputs(tmp_path: Path, bench_fixture: Path) -> tuple[Path, Path, Path]:
    report = tmp_path / "report.json"
    frames = tuple(FrameReport(film_tick=t, ssim=0.9, iou=0.0, scored=True) for t in (10, 20))
    write_report(
        report,
        Report(
            per_frame=frames,
            reference_frames=2,
            frames=2,
            mean_ssim_scored=0.9,
            mean_iou_scored=0.0,
            i6_gate=I6Gate(),
            scored_frames=2,
        ),
    )
    return bench_fixture / "capture", bench_fixture / "render", report


def test_composites_carry_no_key(tmp_path: Path, inputs: tuple[Path, Path, Path]) -> None:
    out = tmp_path / "out"
    count = make_composites(*inputs, out, seed=3, frames_per_fault=1)
    files = sorted(p.name for p in out.iterdir())
    assert all(n == "ids.txt" or n.endswith(".png") for n in files)
    ids = (out / "ids.txt").read_text(encoding="utf-8").split()
    assert len(ids) == count
    assert sorted(f"{i}.png" for i in ids) == [n for n in files if n != "ids.txt"]
    with Image.open(out / f"{ids[0]}.png") as image:
        assert image.size == (976, 240)


def test_the_key_is_recomputed_from_the_seed(inputs: tuple[Path, Path, Path]) -> None:
    first = answer_key(*inputs, seed=3, frames_per_fault=1)
    assert first == answer_key(*inputs, seed=3, frames_per_fault=1)
    assert set(first) != set(answer_key(*inputs, seed=4, frames_per_fault=1))


def test_each_pair_appears_in_both_orders(inputs: tuple[Path, Path, Path]) -> None:
    key = answer_key(*inputs, seed=3, frames_per_fault=1)
    faults = {f.key for f in ALL_FAULTS if f.name not in ("none", "grey")}
    for fault in faults:
        answers = sorted(a for f, a in key.values() if f == fault)
        assert answers in ([], ["A", "B"]) or len(answers) % 2 == 0
        assert answers.count("A") == answers.count("B")
    assert any(f == "shift_x:4" for f, _ in key.values())
    assert [a for f, a in key.values() if f == "control"] == ["either"]


def test_bad_answer_lines_count_as_unanswered(tmp_path: Path) -> None:
    key = {
        "a": ("shift_x:4", "A"),
        "b": ("shift_x:4", "B"),
        "c": ("shift_x:4", "A"),
        "d": ("shift_x:4", "B"),
        "m": ("shift_x:4", "A"),
        "e": ("control", "either"),
    }
    path = tmp_path / "answers.txt"
    # a answered; c twice; zzz not in the key; d has no answer token; b answers Q; m is missing.
    path.write_text("a A fine\nc A x\nc B y\nzzz A z\nd\nb Q\ne A tie\n", encoding="utf-8")
    result = score_answers(path, key)
    assert result["unanswered"] == 5
    assert result["shift_x:4"]["answered"] == 1
    assert result["shift_x:4"]["accuracy"] == 1.0
    assert result["control_a_share"] == 1.0


def test_accuracy_counts_both_orders(tmp_path: Path) -> None:
    key = {
        "a": ("shift_x:4", "A"),
        "b": ("shift_x:4", "B"),
        "c": ("flicker:3", "A"),
        "d": ("flicker:3", "B"),
    }
    path = tmp_path / "answers.txt"
    path.write_text("a A r\nb A r\nc A r\nd B r\n", encoding="utf-8")
    result = score_answers(path, key)
    assert result["shift_x:4"]["accuracy"] == 0.5
    assert result["shift_x:4"]["a_share"] == 1.0
    assert result["shift_x:4"]["passes"] is False
    assert result["flicker:3"]["accuracy"] == 1.0
    assert result["flicker:3"]["passes"] is True
    assert result["unanswered"] == 0
