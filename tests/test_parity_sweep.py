"""Offline tests for the pure parts of ``python/scripts/parity_sweep.py`` (synthetic data only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_probe  # noqa: E402
import parity_sweep  # noqa: E402
from parity_sweep import Score, Variant  # noqa: E402


def test_parse_var_splits_values() -> None:
    assert parity_sweep.parse_var("DBG_PITCH=0, -0.5") == ("DBG_PITCH", ["0", "-0.5"])


@pytest.mark.parametrize("spec", ["PITCH=1", "DBG_X", "dbg_x=1", "DBG_X=1,,2", "DBG_X="])
def test_parse_var_rejects_malformed(spec: str) -> None:
    with pytest.raises(ValueError, match="--var"):
        parity_sweep.parse_var(spec)


def test_expand_variants_is_cartesian_last_fastest() -> None:
    combos = parity_sweep.expand_variants(["A", "B"], [["0", "1"], ["x", "y", "z"]])
    assert len(combos) == 6
    assert combos[:3] == [("0", "x"), ("0", "y"), ("0", "z")]
    assert combos[-1] == ("1", "z")


def test_expand_variants_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="twice"):
        parity_sweep.expand_variants(["A", "A"], [["0"], ["1"]])


def test_render_range_covers_captured_ticks() -> None:
    # frame n renders tick n - 1, and the range is half-open
    assert parity_sweep.render_range([769, 3640, 1000]) == "770..3642"


def test_parse_report_prefers_scored_means() -> None:
    data = {"mean_ssim_scored": 0.7, "mean_iou_scored": 0.8, "mean_ssim": 0.5, "mean_iou": 0.6}
    assert parity_sweep.parse_report(data) == (0.7, 0.8)


def test_parse_report_falls_back_to_all_frames() -> None:
    data = {"mean_ssim_scored": None, "mean_iou_scored": None, "mean_ssim": 0.5, "mean_iou": 0.6}
    assert parity_sweep.parse_report(data) == (0.5, 0.6)


def test_parse_report_rejects_empty() -> None:
    with pytest.raises(ValueError, match="no mean"):
        parity_sweep.parse_report({})


def _variant(index: int, value: str, ctry: float | None, intro: float | None) -> Variant:
    def score(ssim: float | None) -> Score | None:
        return None if ssim is None else Score(ssim, 0.8, 0.25)

    return Variant(index, (value,), {"ctry": score(ctry), "intro": score(intro)})


def test_rank_orders_by_mean_ssim_and_puts_failures_last() -> None:
    low = _variant(1, "0", 0.771, 0.676)  # mean 0.7235
    ctry_only_gain = _variant(2, "-0.3", 0.784, 0.660)  # mean 0.722: the regression shows
    best = _variant(3, "-0.1", 0.780, 0.676)  # mean 0.728
    failed = _variant(4, "bad", 0.9, None)
    assert [v.index for v in parity_sweep.rank([low, failed, ctry_only_gain, best])] == [3, 1, 2, 4]


def test_format_table_aligns_columns_and_marks_failures() -> None:
    ordered = parity_sweep.rank([_variant(1, "0", 0.771, 0.676), _variant(2, "-0.3", 0.784, None)])
    table = parity_sweep.format_table(["DBG_DY"], ["ctry", "intro"], ordered, "film").splitlines()
    assert table[0].split("  ")[-1] == "mean SSIM"
    assert table[1].split() == ["0", "0.7710", "0.8000", "0.6760", "0.8000", "0.7235"]
    assert table[2].split() == ["-0.3", "0.7840", "0.8000", "-", "-", "-"]
    assert len({len(line) for line in table}) == 1  # right-aligned, so equal width


def test_format_table_iou_probe_adds_actor_column() -> None:
    table = parity_sweep.format_table(["DBG_DY"], ["ctry"], [_variant(1, "0", 0.771, None)], "iou")
    header, row = table.splitlines()
    assert "ctry actor" in header
    assert "mean SSIM" not in header  # one film: the mean is the film's own SSIM
    assert row.split() == ["0", "0.7710", "0.8000", "0.2500"]


def test_winner_line_names_values_or_reports_failure() -> None:
    ordered = parity_sweep.rank([_variant(1, "0", 0.771, 0.676), _variant(2, "-1", 0.8, 0.7)])
    assert parity_sweep.winner_line(["DBG_DY"], ordered) == "winner: DBG_DY=-1 (mean SSIM 0.7500)"
    failed = parity_sweep.rank([_variant(1, "0", None, None)])
    assert parity_sweep.winner_line(["DBG_DY"], failed).startswith("winner: none")


def test_padded_box_clamps_to_viewport() -> None:
    width = parity_probe.WIDTH
    pixels = [10 * width + 5, 20 * width + 30]  # (5, 10) and (30, 20)
    assert parity_sweep.padded_box(pixels, 25) == (0, 0, 55, 45)
    far = [(parity_probe.ROWS - 1) * width + width - 1]
    assert parity_sweep.padded_box(far, 25) == (
        width - 26,
        parity_probe.ROWS - 26,
        width,
        parity_probe.ROWS,
    )
    assert parity_sweep.padded_box([], 25) == (0, 0, width, parity_probe.ROWS)


def test_actor_iou_on_synthetic_planes(tmp_path: Path) -> None:
    """The refactored probe: ours is a 10x10 square, the capture shows an overlapping 10x5."""
    width, rows = parity_probe.WIDTH, parity_probe.ROWS
    layer = bytearray(2 * width * rows)
    capture = bytearray([233]) * (width * rows)  # sky is never an object pixel
    for y in range(50, 60):
        for x in range(100, 110):
            layer[2 * (y * width + x)] = parity_probe.ACTOR_LAYER_MIN
            if y < 55:
                capture[y * width + x] = 10
    (tmp_path / "tick_00007.layer").write_bytes(bytes(layer))
    (tmp_path / "tick_0001.idx").write_bytes(bytes(capture))
    report = tmp_path / "report.json"
    report.write_text(
        '{"per_frame": [{"film_tick": 7, "ordinal": 1, "scored": true},'
        ' {"film_tick": 9, "ordinal": 2, "scored": false}]}',
        encoding="utf-8",
    )
    value, count = parity_probe.actor_iou(report, tmp_path, tmp_path, every=1)
    assert count == 1
    assert value == pytest.approx(0.5)


def _render_tree(tmp_path: Path, film: str, flm_bytes: int, ticks: list[int]) -> tuple[Path, Path]:
    """A capture of CTRY.FLM (100 bytes) at ticks 7 and 9, and a render with planes at ``ticks``."""
    reference, render = tmp_path / "ref", tmp_path / "ours"
    reference.mkdir()
    render.mkdir()
    frames = [{"film_tick": 7}, {"film_tick": 9}]
    meta = {"film": "CTRY.FLM", "flm_bytes": 100, "frames": frames}
    (reference / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    sidecar = {"film": film, "flm_bytes": flm_bytes, "ticks": []}
    (render / parity_sweep.RENDER_SIDECAR).write_text(json.dumps(sidecar), encoding="utf-8")
    for tick in ticks:
        (render / f"tick_{tick:05d}.idx").write_bytes(b"")
        (render / f"tick_{tick:05d}.layer").write_bytes(b"")
    return reference, render


def test_check_render_accepts_a_matching_render_with_planes(tmp_path: Path) -> None:
    reference, render = _render_tree(tmp_path, "ctry.flm", 100, [7, 9])
    parity_sweep.check_render(reference, render, [7, 9])


@pytest.mark.parametrize(
    ("film", "flm_bytes", "message"),
    [("INTRO.FLM", 100, "render is of INTRO.FLM"), ("CTRY.FLM", 101, "render's is 101$")],
)
def test_check_render_refuses_another_film(
    tmp_path: Path, film: str, flm_bytes: int, message: str
) -> None:
    reference, render = _render_tree(tmp_path, film, flm_bytes, [7, 9])
    with pytest.raises(ValueError, match=message):
        parity_sweep.check_render(reference, render, [7, 9])


def test_check_render_refuses_a_render_without_planes(tmp_path: Path) -> None:
    reference, render = _render_tree(tmp_path, "CTRY.FLM", 100, [7])
    (render / "tick_00007.layer").unlink()
    with pytest.raises(ValueError, match="no render planes for 2 captured tick"):
        parity_sweep.check_render(reference, render, [7, 9])
