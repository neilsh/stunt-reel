"""Offline tests for the pure parts of `python/scripts/parity_sweep.py` (synthetic data only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from render_helpers import reference_tree, tick_entry

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_probe  # noqa: E402
import parity_sweep  # noqa: E402
from parity_sweep import Variant  # noqa: E402

from stunt_reel import parity_artifacts, parity_layout, parity_pipeline  # noqa: E402
from stunt_reel.parity_artifacts import FilmId, Geometry, StoredFrame  # noqa: E402
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
    layer = bytearray(2 * width * geometry.height)
    capture = bytearray([233]) * (width * rows)  # sky is never an object pixel
    for y in range(50, 60):
        for x in range(100, 110):
            layer[2 * (y * width + x)] = parity_artifacts.LAYER_FIRST_ACTOR
            if y < 55:
                capture[y * width + x] = 10
    frame = StoredFrame(
        indices=bytes(width * geometry.height), layers=bytes(layer), palette=bytes(768)
    )
    parity_artifacts.write_render_store(
        tmp_path, FilmId(), geometry, [(tick_entry(7), frame)], adapter=None
    )
    (tmp_path / "tick_0001.idx").write_bytes(bytes(capture))
    (tmp_path / "meta.json").write_text(
        json.dumps({"film": "CTRY.FLM", "frames": [{"film_tick": 7}, {"film_tick": 9}]}),
        encoding="utf-8",
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


def _sweep_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt_on: str | None = None
) -> Path:
    """Patch ``parity_sweep`` so ``main`` runs offline: fake renders scored by ``DBG_X``."""
    root = reference_tree(tmp_path / "data", [7])
    repo = tmp_path / "repo"
    scores = {"a": 0.5, "b": 0.5, "c": 0.4}

    def fake_run_film(
        job: parity_pipeline.FilmJob,
        workdir: Path,
        *,
        env: dict[str, str] | None = None,
        retime: int | None = None,  # noqa: ARG001 - run_film's signature
    ) -> parity_pipeline.FilmScore:
        value = (env or {})["DBG_X"]
        if value == interrupt_on:
            raise KeyboardInterrupt
        out = workdir / job.name
        out.mkdir(parents=True, exist_ok=True)
        score = parity_pipeline.Score(scores[value], scores[value])
        return parity_pipeline.FilmScore(job.name, out, workdir / f"{job.name}_report", score)

    monkeypatch.setattr(parity_sweep, "REPO_ROOT", repo)
    monkeypatch.setattr(parity_sweep, "run_film", fake_run_film)
    monkeypatch.setattr(parity_sweep, "preflight", lambda *_a, **_k: [])
    monkeypatch.setattr(parity_sweep, "write_crops", lambda *_a, **_k: [])
    return root


@pytest.mark.parametrize("jobs", ["1", "4"])
def test_sweep_keeps_the_same_best_at_any_jobs(
    jobs: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    argv = ["--var", "DBG_X=a,b,c", "--keep-best", "--no-build", "--data-root", str(root)]
    assert parity_sweep.main([*argv, "--jobs", jobs]) == 0
    sweep = tmp_path / "repo" / parity_layout.sweep_root()
    assert sorted(path.name for path in sweep.iterdir()) == ["v001"]


def test_sweep_prints_the_same_table_at_any_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sweep_env(tmp_path, monkeypatch)
    argv = ["--var", "DBG_X=c,a,b", "--no-build", "--data-root", str(root)]
    assert parity_sweep.main([*argv, "--jobs", "1"]) == 0
    sequential = capsys.readouterr().out
    assert parity_sweep.main([*argv, "--jobs", "4"]) == 0
    assert capsys.readouterr().out == sequential


@pytest.mark.parametrize("jobs", ["1", "2"])
def test_sweep_interrupt_leaves_no_work_directories(
    jobs: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sweep_env(tmp_path, monkeypatch, interrupt_on="b")
    argv = ["--var", "DBG_X=a,b,c", "--no-build", "--data-root", str(root), "--jobs", jobs]
    with pytest.raises(KeyboardInterrupt):
        parity_sweep.main(argv)
    sweep = tmp_path / "repo" / parity_layout.sweep_root()
    assert not sweep.exists() or not any(sweep.glob("v*"))
