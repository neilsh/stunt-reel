"""Candidate parity metrics and the differential score, on the synthetic bench fixture."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

from pytest_helpers import MemorySource
from stunt_reel.bench.faults import Fault, plant
from stunt_reel.bench.metrics import METRICS, Regions, differential
from stunt_reel.bench.planes import BenchError, RenderPlanes, RenderTree, load_capture
from stunt_reel.bench.ssim import frame_ssim, render_luma

if TYPE_CHECKING:
    from pathlib import Path

INDEX_KEYS = ("index_ocean", "index_terrain", "index_props", "index_actors")


def regions_of(planes: RenderPlanes) -> Regions:
    return Regions(layer=planes.layer, control_mean_luma=float(render_luma(planes.rgb).mean()))


def test_every_metric_is_at_its_best_on_a_perfect_render(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[10]
    perfect = RenderTree(bench_fixture / "render").load(10)
    perfect = RenderPlanes(
        rgb=capture.palette[capture.idx], idx=capture.idx.copy(), layer=perfect.layer
    )
    regions = regions_of(perfect)
    for key in ("ssim", "ssim_structured", "edge_f", "ssim_actors"):
        value = METRICS[key](capture, perfect, regions)
        assert value is not None
        assert abs(value - 1.0) < 1e-9, key
    for key in INDEX_KEYS:
        value = METRICS[key](capture, perfect, regions)
        assert value is None or value == 1.0, key


def test_grey_skill_is_zero_for_the_grey_frame_itself(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[10]
    base = RenderTree(bench_fixture / "render").load(10)
    regions = regions_of(base)
    level = np.uint8(round(regions.control_mean_luma))
    grey = RenderPlanes(rgb=np.full_like(base.rgb, level), idx=None, layer=base.layer)
    skill = METRICS["grey_skill"](capture, grey, regions)
    assert skill is not None
    assert abs(skill) < 1e-9


def test_index_metrics_are_na_without_an_index_plane(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[10]
    base = RenderTree(bench_fixture / "render").load(10)
    no_idx = RenderPlanes(rgb=base.rgb, idx=None, layer=base.layer)
    for key in INDEX_KEYS:
        assert METRICS[key](capture, no_idx, regions_of(base)) is None


def test_regions_come_from_the_control_render(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[10]
    control = RenderTree(bench_fixture / "render").load(10)
    removed = plant(Fault("actors_removed", None), 10, MemorySource({10: control}), 0)
    assert removed is not None
    assert (control.layer >= 16).any()
    assert METRICS["ssim_actors"](capture, removed, regions_of(control)) is not None
    assert METRICS["ssim_actors"](capture, removed, regions_of(removed)) is None


def test_differential_of_identical_renders_has_no_delta(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[20]
    planes = RenderTree(bench_fixture / "render").load(20)
    result = differential(capture, planes, planes)
    assert result.changed_idx == 0.0
    assert result.changed_luma == 0.0
    assert result.delta is None
    assert set(result.changed_by_layer) == {"ocean", "terrain", "props", "actors", "none"}
    assert all(value == 0.0 for value in result.changed_by_layer.values())


def test_differential_needs_index_planes(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[20]
    planes = RenderTree(bench_fixture / "render").load(20)
    grey = RenderPlanes(rgb=planes.rgb, idx=None, layer=planes.layer)
    with pytest.raises(BenchError):
        differential(capture, planes, grey)
    with pytest.raises(BenchError):
        differential(capture, grey, planes)


def test_differential_matches_its_golden(bench_fixture: Path) -> None:
    golden = json.loads((bench_fixture / "golden.json").read_text(encoding="utf-8"))
    want = golden["differential"]["20"]
    capture = load_capture(bench_fixture / "capture")[20]
    before = RenderTree(bench_fixture / "render_before").load(20)
    after = RenderTree(bench_fixture / "render").load(20)
    got = differential(capture, before, after)
    assert abs(got.changed_idx - want["changed_idx"]) < 1e-9
    assert abs(got.changed_luma - want["changed_luma"]) < 1e-9
    assert set(got.changed_by_layer) == set(want["changed_by_layer"])
    for key, value in want["changed_by_layer"].items():
        assert abs(got.changed_by_layer[key] - value) < 1e-9
    if want["delta"] is None:
        assert got.delta is None
    else:
        assert got.delta is not None
        assert abs(got.delta - want["delta"]) < 1e-9


def test_ssim_metric_is_frame_ssim(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[20]
    planes = RenderTree(bench_fixture / "render").load(20)
    assert METRICS["ssim"](capture, planes, regions_of(planes)) == frame_ssim(capture, planes.rgb)
