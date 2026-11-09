"""Plant every fault on every scored frame and score each candidate metric against recapture noise.

A metric earns its place only if the damage it is meant to see moves it by more than two
captures of the same film move it apart. That yardstick is sigma: the sample standard deviation,
over the scored ticks both captures hold, of ``metric(reference) - metric(recapture)`` against
the same control render. A fault is *detected* when it lowers the metric by at least
:data:`DETECT_SIGMAS` sigma on average.
"""

from __future__ import annotations

import statistics
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import numpy as np

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
from stunt_reel.parity_artifacts import StoredFrame, read_report, write_render_store

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

__all__ = [
    "DETECT_SIGMAS",
    "FIDELITY_TOLERANCE",
    "MIN_PAIRED_TICKS",
    "bench",
    "check_fidelity",
    "plant_tree",
    "recapture_noise",
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
    return Regions(
        layer=control.layer,
        control_mean_luma=float(render_luma(control.rgb).mean()),
        credits_drawn=control.credits,
    )


def check_fidelity(report: Path, captures: dict[int, CapturePlanes], tree: RenderTree) -> None:
    """Refuse a ``report.json`` the numpy SSIM does not reproduce, naming the first tick."""
    rendered = set(tree.ticks())
    for frame in read_report(report).per_frame:
        capture = captures.get(frame.film_tick)
        if capture is None or frame.film_tick not in rendered:
            continue
        render = tree.load(frame.film_tick)
        ours = frame_ssim(capture, render.rgb, credits_drawn=render.credits)
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


def _recapture_deltas(
    metrics: list[str],
    a: dict[int, CapturePlanes],
    b: dict[int, CapturePlanes],
    source: RenderSource,
    ticks: list[int],
) -> tuple[list[int], dict[str, list[float]]]:
    """The paired ticks, and each metric's ``a - b`` on them, loading each control render once."""
    paired = _paired_ticks(a, b, source, ticks)
    if len(paired) < MIN_PAIRED_TICKS:
        raise BenchError(
            f"only {len(paired)} scored ticks are in both captures; sigma needs {MIN_PAIRED_TICKS}"
        )
    deltas: dict[str, list[float]] = {name: [] for name in metrics}
    for tick in paired:
        control = source.load(tick)
        regions = _regions(control)
        for name in metrics:
            fn = METRICS[name]
            first = fn(a[tick], control, regions)
            second = fn(b[tick], control, regions)
            if first is not None and second is not None:
                deltas[name].append(first - second)
    return paired, deltas


def _sigmas(deltas: dict[str, list[float]]) -> dict[str, float | None]:
    # A metric n/a on (nearly) every frame has no noise to measure: None, so nothing it
    # scores can be called detected.
    return {
        name: float(statistics.stdev(values)) if len(values) >= 2 else None
        for name, values in deltas.items()
    }


def recapture_noise(
    a: dict[int, CapturePlanes],
    b: dict[int, CapturePlanes],
    paired: list[int],
    ssim_deltas: list[float],
) -> dict[str, Any]:
    """The whole-frame ``ssim`` noise of two captures over *paired* ticks (method.md § 2.2.1).

    ``identical_pages`` counts paired ticks whose index planes match pixel for pixel;
    ``sigma`` is the sample standard deviation of *ssim_deltas*, and ``median``, ``p90``,
    ``p95`` and ``max`` are of their absolute values, each ``None`` without enough deltas.
    """
    spread = np.abs(np.asarray(ssim_deltas, dtype=np.float64))
    identical = sum(1 for tick in paired if np.array_equal(a[tick].idx, b[tick].idx))

    def quantile(q: float) -> float | None:
        return float(np.percentile(spread, q)) if spread.size else None

    return {
        "paired": len(paired),
        "identical_pages": identical,
        "sigma": float(statistics.stdev(ssim_deltas)) if len(ssim_deltas) >= 2 else None,
        "median": quantile(50),
        "p90": quantile(90),
        "p95": quantile(95),
        "max": float(spread.max()) if spread.size else None,
    }


def recapture_sigma(
    metric: str,
    a: dict[int, CapturePlanes],
    b: dict[int, CapturePlanes],
    source: RenderSource,
    ticks: list[int],
) -> float | None:
    """Sample standard deviation of *metric* differences between captures of the same control.

    Raises ``BenchError`` if fewer than :data:`MIN_PAIRED_TICKS` ticks are shared; returns
    ``None`` if fewer than two paired ticks produce a value for the metric.
    """
    return _sigmas(_recapture_deltas([metric], a, b, source, ticks)[1])[metric]


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


def _entry(values: list[float], sigma: float | None) -> dict[str, Any]:
    if not values:
        return {"mean_change": None, "sigmas": None, "detected": False, "frames": 0}
    mean = float(np.mean(values))
    if sigma is None:
        return {"mean_change": mean, "sigmas": None, "detected": False, "frames": len(values)}
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
    paired, noise_deltas = _recapture_deltas(
        list(METRICS), reference, recapture, source, scored_ticks
    )
    sigma = _sigmas(noise_deltas)
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
            # A fault that substitutes another tick (advance, wrong_tick) keeps this tick's
            # credits flag, so the differential masks the same windows as the control.
            planted = replace(planted, credits=control.credits)
            # Planted, control and the recapture sigma all take the control's mask: a fault
            # that loses the credits is scored on the ink, and one that gains them cannot
            # unmask the cursor, which the sigma never saw.
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
        "noise": recapture_noise(reference, recapture, paired, noise_deltas.get("ssim", [])),
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
    """Write *out* as *render*'s store with each fault's ticks replaced by the frame it makes.

    Ticks absent from the source and faults without a frame are skipped. A planted frame is
    stored as its index plane under a palette reproducing its picture (so ``flicker`` shifts
    that tick's palette). Raises ``BenchError`` for the ``grey`` fault, which has no index
    plane, and for a picture no palette over its index plane can carry; file errors propagate.
    """
    for fault, _ in plants:
        if fault.name == "grey":
            raise BenchError("grey has no index plane, so it cannot be written into a render tree")
    source = RenderTree(render)
    held = set(source.ticks())
    planted: dict[int, StoredFrame] = {}
    for fault, ticks in plants:
        for tick in ticks:
            if tick not in held:
                continue
            planes = plant(fault, tick, source, PLANT_SEED)
            if planes is None or planes.idx is None:
                continue
            planted[tick] = _stored(fault, tick, planes, planes.idx, source.stored(tick).palette)
    out.mkdir(parents=True, exist_ok=True)
    record = source.store.record
    write_render_store(
        out,
        record.film,
        record.geometry,
        ((entry, planted.get(entry.tick) or source.stored(entry.tick)) for entry in record.ticks),
        adapter=record.adapter,
    )


def _stored(
    fault: Fault, tick: int, planes: RenderPlanes, idx: NDArray[np.uint8], base: bytes
) -> StoredFrame:
    """*planes* as a stored frame: *base* with each index it shows recoloured to its picture."""
    idx = idx.reshape(-1)
    rgb = planes.rgb.reshape(-1, 3)
    palette = np.frombuffer(base, dtype=np.uint8).reshape(256, 3).copy()
    shown, first = np.unique(idx, return_index=True)
    palette[shown] = rgb[first]
    if not np.array_equal(palette[idx], rgb):
        raise BenchError(
            f"{fault.key} at tick {tick} gives one index two colours, so no palette over its "
            "index plane can carry it into a render tree"
        )
    return StoredFrame(
        indices=idx.astype(np.uint8).tobytes(),
        layers=planes.layer.astype("<u2").tobytes(),
        palette=palette.tobytes(),
    )
