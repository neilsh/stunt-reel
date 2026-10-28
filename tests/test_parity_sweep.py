"""Offline tests for the pure parts of `python/scripts/parity_sweep.py` (synthetic data only)."""

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
from parity_sweep import Variant  # noqa: E402

from stunt_reel import parity_artifacts  # noqa: E402
from stunt_reel.parity_artifacts import FilmId, Geometry, RenderRecord  # noqa: E402
from stunt_reel.parity_pipeline import Score  # noqa: E402


def _geometry() -> Geometry:
    return Geometry(width=320, height=200, viewport_rows=185)


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
    geometry = _geometry()
    width, rows = geometry.width, geometry.plane_rows()
    pixels = [10 * width + 5, 20 * width + 30]  # (5, 10) and (30, 20)
    assert parity_sweep.padded_box(pixels, 25, geometry) == (0, 0, 55, 45)
    far = [(rows - 1) * width + width - 1]
    assert parity_sweep.padded_box(far, 25, geometry) == (width - 26, rows - 26, width, rows)
    assert parity_sweep.padded_box([], 25, geometry) == (0, 0, width, rows)


def test_actor_iou_on_synthetic_planes(tmp_path: Path) -> None:
    """The refactored probe: ours is a 10x10 square, the capture shows an overlapping 10x5."""
    geometry = _geometry()
    width, rows = geometry.width, geometry.plane_rows()
    layer = bytearray(2 * width * rows)
    capture = bytearray([233]) * (width * rows)  # sky is never an object pixel
    for y in range(50, 60):
        for x in range(100, 110):
            layer[2 * (y * width + x)] = parity_artifacts.LAYER_FIRST_ACTOR
            if y < 55:
                capture[y * width + x] = 10
    (tmp_path / "tick_00007.layer").write_bytes(bytes(layer))
    (tmp_path / "tick_0001.idx").write_bytes(bytes(capture))
    (tmp_path / "meta.json").write_text(
        json.dumps({"film": "CTRY.FLM", "frames": [{"film_tick": 7}, {"film_tick": 9}]}),
        encoding="utf-8",
    )
    parity_artifacts.write_render(
        tmp_path / "render.json",
        RenderRecord(schema_version=1, film=FilmId(), geometry=geometry, ticks=()),
    )
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "per_frame": [
                    {"film_tick": 7, "ordinal": 1, "ssim": 0.7, "iou": 0.9, "scored": True},
                    {"film_tick": 9, "ordinal": 2, "ssim": 0.7, "iou": 0.9, "scored": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    value, count = parity_probe.actor_iou(report, tmp_path, tmp_path, every=1)
    assert count == 1
    assert value == pytest.approx(0.5)


def test_identical_variants_are_flagged_to_four_decimals() -> None:
    first = _variant(1, "0", 0.771234, 0.676234)
    second = _variant(2, "1", 0.771236, 0.676236)
    third = _variant(3, "-1", 0.7723, 0.6773)
    pairs = parity_sweep.identical_variant_pairs([first, third, second])
    assert [(left.index, right.index) for left, right in pairs] == [(1, 2)]


def test_identical_variants_accepts_a_legitimate_tie() -> None:
    pairs = parity_sweep.identical_variant_pairs([_variant(1, "0", 0.77, 0.67)] * 2)
    assert len(pairs) == 1  # a warning, never a failure
    assert parity_sweep.identical_variant_pairs([_variant(1, "0", 0.77, 0.67)]) == []


def test_noise_note_appears_only_inside_the_adoption_floor() -> None:
    assert "within noise" in parity_sweep.noise_note(0.0019)
    assert parity_sweep.noise_note(0.002) == ""
    assert parity_sweep.noise_note(0.01) == ""


def test_validate_selector_requires_var_or_reuse() -> None:
    parity_sweep.validate_selector(None, ["DBG_X=0,1"])
    parity_sweep.validate_selector(Path("dir"), [])
    with pytest.raises(ValueError, match="--var cannot be combined"):
        parity_sweep.validate_selector(Path("dir"), ["DBG_X=0,1"])
    with pytest.raises(ValueError, match="--var is required"):
        parity_sweep.validate_selector(None, [])
