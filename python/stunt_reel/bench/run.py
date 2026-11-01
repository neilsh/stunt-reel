"""Plant every fault on every scored frame and score each candidate metric against recapture noise.

A metric earns its place only if the damage it is meant to see moves it by more than two
captures of the same film move it apart. That yardstick is sigma: the sample standard deviation,
over the scored ticks both captures hold, of ``metric(reference) - metric(recapture)`` against
the same control render. A fault is *detected* when it lowers the metric by at least
:data:`DETECT_SIGMAS` sigma on average.
"""

from __future__ import annotations

import shutil
import statistics
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from stunt_reel.bench.faults import ALL_FAULTS, Fault, plant
from stunt_reel.bench.metrics import METRICS, Regions, differential
from stunt_reel.bench.planes import (
    BenchError,
    CapturePlanes,
    RenderPlanes,
    RenderSource,
    RenderTree,
    load_capture,
)
from stunt_reel.bench.ssim import frame_ssim, render_luma
from stunt_reel.parity_artifacts import read_report, render_plane_paths, tick_stem

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DETECT_SIGMAS",
    "FIDELITY_TOLERANCE",
    "MIN_PAIRED_TICKS",
    "bench",
    "check_fidelity",
    "plant_tree",
    "recapture_sigma",
    "run_bench",
]

#: Fewest ticks two captures must share, scored, for sigma to mean anything.
MIN_PAIRED_TICKS = 20
#: A fault is detected when it lowers a metric by this many sigma.
DETECT_SIGMAS = 3.0
#: Largest allowed gap between the numpy SSIM and the Rust scorer's.
FIDELITY_TOLERANCE = 1e-4
#: The seed ``plant_tree`` plants ``wrong_tick`` with.
PLANT_SEED = 1


def _regions(control: RenderPlanes) -> Regions:
    return Regions(layer=control.layer, control_mean_luma=float(render_luma(control.rgb).mean()))


def check_fidelity(report: Path, captures: dict[int, CapturePlanes], tree: RenderTree) -> None:
    """Refuse a ``report.json`` the numpy SSIM does not reproduce, naming the first tick."""
    rendered = set(tree.ticks())
    for frame in read_report(report).per_frame:
        capture = captures.get(frame.film_tick)
        if capture is None or frame.film_tick not in rendered:
            continue
        ours = frame_ssim(capture, tree.load(frame.film_tick).rgb)
        if abs(ours - frame.ssim) > FIDELITY_TOLERANCE:
            raise BenchError(
                f"tick {frame.film_tick}: numpy ssim {ours:.6f} but {report} says "
                f"{frame.ssim:.6f}; the report is stale or the render changed since it was scored"
            )


def _paired_ticks(
    a: dict[int, CapturePlanes],
    b: dict[int, CapturePlanes],
    source: RenderSource,
    ticks: list[int],
) -> list[int]:
    rendered = set(source.ticks())
    return [t for t in ticks if t in a and t in b and t in rendered]


def recapture_sigma(
    metric: str,
    a: dict[int, CapturePlanes],
    b: dict[int, CapturePlanes],
    source: RenderSource,
    ticks: list[int],
) -> float:
    """Sigma of *metric*: how far two captures of one film disagree about the same control."""
    fn = METRICS[metric]
    paired = _paired_ticks(a, b, source, ticks)
    if len(paired) < MIN_PAIRED_TICKS:
        raise BenchError(
            f"only {len(paired)} scored ticks are in both captures; sigma needs {MIN_PAIRED_TICKS}"
        )
    deltas: list[float] = []
    for tick in paired:
        control = source.load(tick)
        regions = _regions(control)
        first = fn(a[tick], control, regions)
        second = fn(b[tick], control, regions)
        if first is not None and second is not None:
            deltas.append(first - second)
    if len(deltas) < 2:
        # A metric n/a on (nearly) every frame has no noise to measure; its faults then
        # have no frames either, so it fails the bench without stopping the others.
        return 0.0
    return float(statistics.stdev(deltas))


def _build_floor(source: RenderSource, floor: RenderSource) -> dict[str, Any]:
    counts: list[int] = []
    other = set(floor.ticks())
    for tick in source.ticks():
        if tick not in other:
            continue
        ours, theirs = source.load(tick), floor.load(tick)
        changed = render_luma(ours.rgb) != render_luma(theirs.rgb)
        if ours.idx is not None and theirs.idx is not None:
            changed = changed | (ours.idx != theirs.idx)
        counts.append(int(changed.sum()))
    if not counts:
        raise BenchError("the floor render shares no tick with the render")
    return {
        "max_changed_pixels": max(counts),
        "mean_changed_pixels": float(sum(counts)) / len(counts),
    }


def _entry(values: list[float], sigma: float) -> dict[str, Any]:
    if not values:
        return {"mean_change": None, "sigmas": None, "detected": False, "frames": 0}
    mean = float(np.mean(values))
    if sigma == 0.0:
        return {"mean_change": mean, "sigmas": None, "detected": mean < 0, "frames": len(values)}
    drop = -mean / sigma
    return {
        "mean_change": mean,
        "sigmas": drop,
        "detected": drop >= DETECT_SIGMAS,
        "frames": len(values),
    }


def bench(
    reference: dict[int, CapturePlanes],
    recapture: dict[int, CapturePlanes],
    source: RenderSource,
    scored_ticks: list[int],
    seed: int,
    floor: RenderSource | None,
) -> dict[str, Any]:
    """The ``bench.json`` document for one film."""
    rendered = set(source.ticks())
    film_ticks = [t for t in scored_ticks if t in reference and t in rendered]
    sigma = {
        name: recapture_sigma(name, reference, recapture, source, scored_ticks) for name in METRICS
    }
    changes: dict[str, dict[str, list[float]]] = {
        name: {fault.key: [] for fault in ALL_FAULTS} for name in METRICS
    }
    deltas: dict[str, list[float]] = {fault.key: [] for fault in ALL_FAULTS}
    for tick in film_ticks:
        capture = reference[tick]
        control = source.load(tick)
        regions = _regions(control)
        base = {name: fn(capture, control, regions) for name, fn in METRICS.items()}
        for fault in ALL_FAULTS:
            planted = plant(fault, tick, source, seed)
            if planted is None:
                continue
            for name, fn in METRICS.items():
                value = fn(capture, planted, regions)
                before = base[name]
                if value is not None and before is not None:
                    changes[name][fault.key].append(value - before)
            if fault.name not in ("none", "grey"):
                delta = differential(capture, control, planted).delta
                if delta is not None:
                    deltas[fault.key].append(delta)

    results: dict[str, dict[str, Any]] = {}
    detectable: dict[str, dict[str, int | None]] = {}
    passes: dict[str, bool] = {}
    for name in METRICS:
        results[name] = {f.key: _entry(changes[name][f.key], sigma[name]) for f in ALL_FAULTS}
        detectable[name] = {}
        for fault in ALL_FAULTS:
            if fault.magnitude is None:
                continue
            current = detectable[name].setdefault(fault.name, None)
            if results[name][fault.key]["detected"] and (
                current is None or fault.magnitude < current
            ):
                detectable[name][fault.name] = fault.magnitude
        passes[name] = all(
            results[name][fault.key]["detected"] for fault in ALL_FAULTS if fault.name != "none"
        )

    diff: dict[str, dict[str, Any]] = {}
    for fault in ALL_FAULTS:
        if fault.name in ("none", "grey"):
            continue
        values = deltas[fault.key]
        mean_delta = float(np.mean(values)) if values else None
        diff[fault.key] = {
            "mean_delta": mean_delta,
            "negative": mean_delta is not None and mean_delta < 0,
        }
    return {
        "film_ticks": film_ticks,
        "sigma": sigma,
        "results": results,
        "detectable": detectable,
        "passes": passes,
        "differential": diff,
        "build_floor": None if floor is None else _build_floor(source, floor),
    }


def run_bench(
    reference: Path,
    recapture: Path,
    render: Path,
    report: Path,
    seed: int,
    floor_render: Path | None,
) -> dict[str, Any]:
    """Load the directories, check the report against the numpy SSIM, and :func:`bench`."""
    captured = load_capture(reference)
    tree = RenderTree(render)
    check_fidelity(report, captured, tree)
    scored = sorted(f.film_tick for f in read_report(report).per_frame if f.scored is True)
    return bench(
        captured,
        load_capture(recapture),
        tree,
        scored,
        seed,
        None if floor_render is None else RenderTree(floor_render),
    )


def plant_tree(render: Path, out: Path, plants: list[tuple[Fault, range]]) -> None:
    """Copy *render* to *out*, overwriting each fault's ticks with the frame the fault makes."""
    for fault, _ in plants:
        if fault.name == "grey":
            raise BenchError("grey has no index plane, so it cannot be written into a render tree")
    shutil.copytree(render, out)
    source = RenderTree(render)
    held = set(source.ticks())
    for fault, ticks in plants:
        for tick in ticks:
            if tick not in held:
                continue
            planted = plant(fault, tick, source, PLANT_SEED)
            if planted is None or planted.idx is None:
                continue
            idx_path, layer_path = render_plane_paths(out, tick)
            Image.fromarray(planted.rgb).save(out / f"{tick_stem(tick)}.png")
            idx_path.write_bytes(planted.idx.tobytes())
            layer_path.write_bytes(planted.layer.astype("<u2").tobytes())
