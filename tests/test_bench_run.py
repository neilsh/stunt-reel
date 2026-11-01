"""The bench plants every fault on every scored frame and scores metrics against recapture noise."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import stunt_reel.bench.run as run_module
from stunt_reel.bench.faults import ALL_FAULTS, Fault
from stunt_reel.bench.metrics import METRICS
from stunt_reel.bench.planes import (
    BenchError,
    CapturePlanes,
    RenderPlanes,
    RenderTree,
    load_capture,
)
from stunt_reel.bench.run import (
    MIN_PAIRED_TICKS,
    bench,
    check_fidelity,
    plant_tree,
    recapture_sigma,
)
from stunt_reel.parity_artifacts import FrameReport, I6Gate, RenderStore, Report, write_report

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_bench  # noqa: E402

H, W = 200, 320
TICKS = 300
CAPTURE_TICKS = list(range(0, TICKS, 14))
#: Capture ticks the bench is told are not scored.
UNSCORED = [42]
TEXTURE = np.random.default_rng(7).integers(30, 120, size=(H, W), dtype=np.uint8)
PALETTE = np.stack([np.arange(256), 255 - np.arange(256), np.arange(256) // 2], axis=1).astype(
    np.uint8
)


class LazySource:
    """A moving-actor film generated on demand: 300 ticks without holding them all."""

    def __init__(self, *, terrain: bool = True) -> None:
        self.terrain = terrain

    def ticks(self) -> list[int]:
        return list(range(TICKS))

    def idx(self, tick: int) -> np.ndarray:
        idx = TEXTURE.copy()
        idx[:60] = 230
        idx[150:170, 250:270] = 90
        x = 20 + tick
        idx[100:130, x : x + 24] = 200
        return idx

    def load(self, tick: int) -> RenderPlanes:
        idx = self.idx(tick)
        layer = np.zeros((H, W), dtype=np.uint16)
        layer[:60] = 1
        if self.terrain:
            layer[60:] = 2
        layer[150:170, 250:270] = 3
        layer[100:130, 20 + tick : 44 + tick] = 16
        return RenderPlanes(rgb=PALETTE[idx], idx=idx, layer=layer)


def captures(source: LazySource, *, noise: int) -> dict[int, CapturePlanes]:
    """Captures of the source at every 10th tick; *noise* seeds a per-tick speckle patch."""
    frames: dict[int, CapturePlanes] = {}
    for tick in CAPTURE_TICKS:
        idx = source.idx(tick)
        if noise:
            rng = np.random.default_rng(noise * 1000 + tick)
            y, x = (int(v) for v in rng.integers(70, 150, 2))
            idx[y : y + 20, x : x + 20] = rng.integers(30, 120, size=(20, 20), dtype=np.uint8)
        frames[tick] = CapturePlanes(idx=idx, palette=PALETTE)
    return frames


NUDGED_PIXELS = 4


class NudgedSource(LazySource):
    """The film with four pixels of row 0 one level brighter on even ticks."""

    def load(self, tick: int) -> RenderPlanes:
        planes = super().load(tick)
        rgb = planes.rgb.copy()
        if tick % 2 == 0:
            rgb[0, :NUDGED_PIXELS] += 1
        return RenderPlanes(rgb=rgb, idx=planes.idx, layer=planes.layer)


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    source = LazySource()
    scored = [t for t in CAPTURE_TICKS if t not in UNSCORED]
    floor = NudgedSource()
    return bench(captures(source, noise=0), captures(source, noise=1), source, scored, 1, floor)


@pytest.fixture(scope="module")
def terrainless() -> dict[str, Any]:
    """The bench on a render with no terrain, over ssim alone to keep the test fast."""
    source = LazySource(terrain=False)
    patch = pytest.MonkeyPatch()
    patch.setattr(run_module, "METRICS", {"ssim": METRICS["ssim"]})
    try:
        return bench(
            captures(source, noise=0), captures(source, noise=1), source, CAPTURE_TICKS, 1, None
        )
    finally:
        patch.undo()


def write_fixture_report(path: Path, bench_fixture: Path, *, ssim20_offset: float = 0.0) -> None:
    golden = json.loads((bench_fixture / "golden.json").read_text(encoding="utf-8"))["ssim"]
    frames = tuple(
        FrameReport(
            film_tick=int(tick),
            ssim=value + (ssim20_offset if tick == "20" else 0.0),
            iou=0.0,
            scored=True,
        )
        for tick, value in golden.items()
    )
    write_report(
        path,
        Report(
            per_frame=frames,
            reference_frames=2,
            frames=2,
            mean_ssim_scored=0.99,
            mean_iou_scored=0.0,
            i6_gate=I6Gate(),
            scored_frames=2,
        ),
    )


def test_fixture_report_passes_the_fidelity_check(tmp_path: Path, bench_fixture: Path) -> None:
    report = tmp_path / "report.json"
    write_fixture_report(report, bench_fixture)
    check_fidelity(
        report, load_capture(bench_fixture / "capture"), RenderTree(bench_fixture / "render")
    )


def test_a_stale_report_names_the_tick(tmp_path: Path, bench_fixture: Path) -> None:
    report = tmp_path / "report.json"
    write_fixture_report(report, bench_fixture, ssim20_offset=-0.01)
    with pytest.raises(BenchError, match=r"tick 20.*numpy ssim 0\.99\d+ but .*0\.98\d+"):
        check_fidelity(
            report, load_capture(bench_fixture / "capture"), RenderTree(bench_fixture / "render")
        )


def test_too_few_paired_ticks_stops_with_the_count() -> None:
    source = LazySource()
    ref, rec = captures(source, noise=0), captures(source, noise=1)
    with pytest.raises(BenchError, match=f"only 19 .* needs {MIN_PAIRED_TICKS}"):
        recapture_sigma("ssim", ref, rec, source, CAPTURE_TICKS[:19])


def test_plant_tree_changes_only_the_planted_ticks(tmp_path: Path, bench_fixture: Path) -> None:
    out = tmp_path / "planted"
    plant_tree(bench_fixture / "render", out, [(Fault("shift_x", 4), range(20, 21))])
    source, planted = RenderStore(bench_fixture / "render"), RenderStore(out)
    assert planted.record.ticks == source.record.ticks
    assert planted.frame(10) == source.frame(10)
    assert planted.frame(20).indices != source.frame(20).indices
    assert planted.frame(20).palette == source.frame(20).palette


def test_a_colour_fault_is_planted_as_a_shifted_palette(
    tmp_path: Path, bench_fixture: Path
) -> None:
    out = tmp_path / "planted"
    plant_tree(bench_fixture / "render", out, [(Fault("flicker", 10), range(20, 21))])
    source, planted = RenderTree(bench_fixture / "render"), RenderTree(out)
    before, after = source.load(20), planted.load(20)
    assert before.idx is not None
    assert after.idx is not None
    assert np.array_equal(after.idx, before.idx)
    shifted = np.clip(before.rgb.astype(np.int16) + 10, 0, 255).astype(np.uint8)
    assert np.array_equal(after.rgb, shifted)


def test_plant_tree_refuses_grey(tmp_path: Path, bench_fixture: Path) -> None:
    with pytest.raises(BenchError, match="grey"):
        plant_tree(
            bench_fixture / "render", tmp_path / "out", [(Fault("grey", None), range(10, 21))]
        )
    assert not (tmp_path / "out").exists()


def test_a_fault_that_does_nothing_is_not_detected(terrainless: dict[str, Any]) -> None:
    entry = terrainless["results"]["ssim"]["flat_terrain"]
    assert entry["mean_change"] == 0.0
    assert entry["detected"] is False
    assert terrainless["passes"]["ssim"] is False


def test_a_large_shift_is_detected_by_ssim_structured(document: dict[str, Any]) -> None:
    entry = document["results"]["ssim_structured"]["shift_x:8"]
    assert entry["mean_change"] < 0
    assert entry["detected"] is True
    assert document["detectable"]["ssim_structured"]["shift_x"] is not None


def test_bench_json_has_every_metric_and_fault(document: dict[str, Any]) -> None:
    json.dumps(document)
    keys = {fault.key for fault in ALL_FAULTS}
    assert set(document["sigma"]) == set(METRICS)
    assert set(document["passes"]) == set(METRICS)
    for name in METRICS:
        assert set(document["results"][name]) == keys
        assert set(document["detectable"][name]) == {"shift_x", "shift_y", "advance", "flicker"}
        assert document["results"][name]["none"]["mean_change"] == 0.0
        assert document["results"][name]["none"]["detected"] is False
    assert set(document["differential"]) == keys - {"none", "grey"}
    assert document["build_floor"] is not None


def test_unscored_frames_are_left_out(document: dict[str, Any]) -> None:
    assert not set(UNSCORED) & set(document["film_ticks"])
    assert document["film_ticks"] == [t for t in CAPTURE_TICKS if t not in UNSCORED]
    assert document["results"]["ssim"]["shift_x:1"]["frames"] == len(document["film_ticks"])


def test_build_floor_counts_changed_pixels(document: dict[str, Any]) -> None:
    floor = document["build_floor"]
    assert floor["max_changed_pixels"] == NUDGED_PIXELS
    assert 0 < floor["mean_changed_pixels"] <= NUDGED_PIXELS


def test_plant_tree_leaves_the_source_alone(tmp_path: Path, bench_fixture: Path) -> None:
    source = tmp_path / "src"
    shutil.copytree(bench_fixture / "render", source)
    before = {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}
    plant_tree(source, tmp_path / "out", [(Fault("shift_x", 4), range(10, 21))])
    after = {path.name: path.read_bytes() for path in source.iterdir() if path.is_file()}
    assert after == before


class NoOceanSource(LazySource):
    """A film whose layer plane never holds the ocean, so ``index_ocean`` is n/a everywhere."""

    def load(self, tick: int) -> RenderPlanes:
        planes = super().load(tick)
        return RenderPlanes(
            rgb=planes.rgb,
            idx=planes.idx,
            layer=np.where(planes.layer == 1, 2, planes.layer).astype(np.uint16),
        )


def test_an_unmeasurable_sigma_is_none_and_never_detects() -> None:
    source = NoOceanSource()
    ref, rec = captures(source, noise=0), captures(source, noise=1)
    assert recapture_sigma("index_ocean", ref, rec, source, CAPTURE_TICKS) is None
    entry = run_module._entry([-0.5, -0.4], None)
    assert entry["detected"] is False
    assert entry["sigmas"] is None
    assert entry["frames"] == 2


def test_a_zero_sigma_detects_any_negative_mean() -> None:
    assert run_module._entry([-0.01], 0.0)["detected"] is True
    assert run_module._entry([0.01], 0.0)["detected"] is False


def test_sigmas_are_positive_when_the_metric_fell_and_detect_from_exactly_three() -> None:
    sigma = 0.5  # binary fractions, so 1.5 / 0.5 is exactly DETECT_SIGMAS
    at_the_line = run_module._entry([-1.5], sigma)
    assert at_the_line["sigmas"] == run_module.DETECT_SIGMAS == 3.0
    assert at_the_line["detected"] is True
    assert at_the_line["mean_change"] == -1.5

    just_short = run_module._entry([-1.49], sigma)
    assert 2.9 < just_short["sigmas"] < 3.0
    assert just_short["detected"] is False


def test_a_rising_metric_has_negative_sigmas_and_is_not_detected() -> None:
    entry = run_module._entry([1.5], 0.5)
    assert entry["sigmas"] == -3.0
    assert entry["detected"] is False
    assert entry["mean_change"] == 1.5


def test_a_reversed_plant_range_is_an_argument_error() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parity_bench.parse_plant("shift_x:4@600-500")
    fault, ticks = parity_bench.parse_plant("shift_x:4@500-599")
    assert fault.key == "shift_x:4"
    assert ticks == range(500, 600)


def test_plant_accepts_repeated_fault_flags() -> None:
    args = parity_bench.parse_args(
        [
            "plant",
            "--render",
            "R",
            "--out",
            "O",
            "--fault",
            "actors_removed@250-349",
            "--fault",
            "shift_x:4@500-599",
            "--fault",
            "advance:5@750-849",
        ]
    )
    assert [fault.key for fault, _ in args.fault] == [
        "actors_removed",
        "shift_x:4",
        "advance:5",
    ]
    assert [ticks for _, ticks in args.fault] == [range(250, 350), range(500, 600), range(750, 850)]


def test_rows_print_an_unmeasured_sigma_as_na(capsys: pytest.CaptureFixture[str]) -> None:
    entry = {"mean_change": None, "sigmas": None, "detected": False, "frames": 0}
    document = {
        "sigma": {"ssim": 0.001, "index_ocean": None},
        "passes": {"ssim": False, "index_ocean": False},
        "results": {
            name: {fault.key: entry for fault in ALL_FAULTS} for name in ("ssim", "index_ocean")
        },
    }
    parity_bench._print_rows(document)
    lines = capsys.readouterr().out.splitlines()
    assert "sigma n/a" in lines[1]
    assert "sigma 0.00100" in lines[0]
