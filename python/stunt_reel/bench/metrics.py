"""Candidate parity metrics, and the differential score of a before/after pair.

Every metric scores one render against one capture. Regions and the grey level come from the
*control* render of the tick (:class:`Regions`), never from the render under test, so a fault that
removes the actors still has actor windows to be judged on. The overlay always comes from the
capture's index plane.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from stunt_reel.bench.planes import BenchError
from stunt_reel.bench.ssim import (
    STRIDE,
    UI_BAR_FIRST_ROW,
    WINDOW,
    capture_luma,
    frame_ssim,
    overlay_mask,
    render_luma,
    stretch,
    window_grid,
    window_ssim,
)

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from stunt_reel.bench.planes import CapturePlanes, RenderPlanes

__all__ = ["METRICS", "Differential", "Metric", "Regions", "differential"]

OCEAN_LAYER = 1
TERRAIN_LAYER = 2
PROPS_LAYER = 3
ACTOR_LAYER = 16
#: A window is structured when its capture luma spans more than this.
STRUCTURE_SPAN = 3.0
#: Sobel ``|gx| + |gy|`` at or above this is an edge.
EDGE_THRESHOLD = 64.0
PIXELS = 200 * 320


@dataclass(frozen=True)
class Regions:
    """What the control render says about a tick: its layer plane and its mean luma."""

    layer: NDArray[np.uint16]
    control_mean_luma: float


Metric = Callable[["CapturePlanes", "RenderPlanes", Regions], "float | None"]


def _allowed(capture: CapturePlanes) -> NDArray[np.bool_]:
    return window_grid(stretch(overlay_mask(capture.idx)))


def _mean(values: NDArray[np.float64], keep: NDArray[np.bool_]) -> float | None:
    return float(values[keep].mean()) if keep.any() else None


def _any_in_window(plane240: NDArray[np.bool_]) -> NDArray[np.bool_]:
    windows = sliding_window_view(plane240, (WINDOW, WINDOW))[::STRIDE, ::STRIDE]
    return np.asarray(windows.any(axis=(2, 3)))


def ssim(capture: CapturePlanes, render: RenderPlanes, regions: Regions) -> float | None:
    """The scorer's frame SSIM."""
    del regions
    return frame_ssim(capture, render.rgb)


def ssim_structured(capture: CapturePlanes, render: RenderPlanes, regions: Regions) -> float | None:
    """Mean window SSIM over clear windows where the capture is not flat."""
    del regions
    reference = stretch(capture_luma(capture))
    windows = sliding_window_view(reference, (WINDOW, WINDOW))[::STRIDE, ::STRIDE]
    span = windows.max(axis=(2, 3)) - windows.min(axis=(2, 3))
    scores = window_ssim(reference, stretch(render_luma(render.rgb)))
    return _mean(scores, _allowed(capture) & (span > STRUCTURE_SPAN))


def grey_skill(capture: CapturePlanes, render: RenderPlanes, regions: Regions) -> float | None:
    """How far the render is from the flat grey frame, as a share of the way to perfect."""
    level = np.uint8(round(regions.control_mean_luma))
    floor = frame_ssim(capture, np.full(render.rgb.shape, level, dtype=np.uint8))
    if floor >= 1.0:
        return None
    return (frame_ssim(capture, render.rgb) - floor) / (1.0 - floor)


def _index_metric(low: int, *, exact: bool) -> Metric:
    def metric(capture: CapturePlanes, render: RenderPlanes, regions: Regions) -> float | None:
        if render.idx is None:
            return None
        layer = regions.layer
        region = (layer == low) if exact else (layer >= low)
        region = region & ~overlay_mask(capture.idx)
        count = int(region.sum())
        if count == 0:
            return None
        return float((capture.idx[region] == render.idx[region]).sum()) / count

    return metric


def _edges(luma: NDArray[np.float64]) -> NDArray[np.bool_]:
    """Sobel edges of rows 0 to 184, over pixels with a full 3x3 neighbourhood."""
    p = luma[:UI_BAR_FIRST_ROW]
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.asarray(np.abs(gx) + np.abs(gy) >= EDGE_THRESHOLD)


def _dilate(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    padded = np.pad(mask, 1)
    out = np.zeros_like(mask)
    for dy in range(3):
        for dx in range(3):
            out |= padded[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
    return out


def edge_f(capture: CapturePlanes, render: RenderPlanes, regions: Regions) -> float | None:
    """F-measure of the render's Sobel edges against the capture's, within one pixel.

    Edges are taken only at pixels with a full 3x3 neighbourhood in rows 0 to 184, and not on
    the overlay's cursor.
    """
    del regions
    clear = ~overlay_mask(capture.idx)[1 : UI_BAR_FIRST_ROW - 1, 1:-1]
    a = _edges(capture_luma(capture)) & clear
    b = _edges(render_luma(render.rgb)) & clear
    if not a.any() and not b.any():
        return 1.0
    if not a.any() or not b.any():
        return 0.0
    precision = float((b & _dilate(a)).sum()) / float(b.sum())
    recall = float((a & _dilate(b)).sum()) / float(a.sum())
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def ssim_actors(capture: CapturePlanes, render: RenderPlanes, regions: Regions) -> float | None:
    """Mean window SSIM over clear windows that hold an actor pixel of the control render."""
    actors = _any_in_window(stretch(regions.layer >= ACTOR_LAYER))
    scores = window_ssim(stretch(capture_luma(capture)), stretch(render_luma(render.rgb)))
    return _mean(scores, _allowed(capture) & actors)


METRICS: dict[str, Metric] = {
    "ssim": ssim,
    "ssim_structured": ssim_structured,
    "grey_skill": grey_skill,
    "index_ocean": _index_metric(OCEAN_LAYER, exact=True),
    "index_terrain": _index_metric(TERRAIN_LAYER, exact=True),
    "index_props": _index_metric(PROPS_LAYER, exact=True),
    "index_actors": _index_metric(ACTOR_LAYER, exact=False),
    "edge_f": edge_f,
    "ssim_actors": ssim_actors,
}


@dataclass(frozen=True)
class Differential:
    """What a change did: how much of the frame it touched, and whether it got closer."""

    changed_idx: float
    changed_luma: float
    changed_by_layer: dict[str, float]
    delta: float | None


def _layer_key(layer: int) -> str:
    if layer == OCEAN_LAYER:
        return "ocean"
    if layer == TERRAIN_LAYER:
        return "terrain"
    if layer == PROPS_LAYER:
        return "props"
    if layer >= ACTOR_LAYER:
        return "actors"
    return "none"


def differential(capture: CapturePlanes, before: RenderPlanes, after: RenderPlanes) -> Differential:
    """Score *after* against *before* on the pixels and windows the change touched."""
    if before.idx is None or after.idx is None:
        raise BenchError("differential needs both renders to carry an index plane")
    idx_changed = before.idx != after.idx
    before_luma = render_luma(before.rgb)
    after_luma = render_luma(after.rgb)
    luma_changed = before_luma != after_luma
    changed = idx_changed | luma_changed
    by_layer = dict.fromkeys(("ocean", "terrain", "props", "actors", "none"), 0.0)
    layers, counts = np.unique(after.layer[changed], return_counts=True)
    for layer, count in zip(layers.tolist(), counts.tolist(), strict=True):
        by_layer[_layer_key(layer)] += count / PIXELS
    windows = _any_in_window(stretch(changed)) & _allowed(capture)
    delta: float | None = None
    if windows.any():
        reference = stretch(capture_luma(capture))
        after_scores = window_ssim(reference, stretch(after_luma))
        before_scores = window_ssim(reference, stretch(before_luma))
        delta = float(after_scores[windows].mean()) - float(before_scores[windows].mean())
    return Differential(
        changed_idx=float(idx_changed.sum()) / PIXELS,
        changed_luma=float(luma_changed.sum()) / PIXELS,
        changed_by_layer=by_layer,
        delta=delta,
    )
