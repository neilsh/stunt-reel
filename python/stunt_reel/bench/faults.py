"""Plant render faults in memory: known-wrong frames the metric bench must tell from right ones."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from stunt_reel.bench.planes import RenderPlanes
from stunt_reel.bench.ssim import render_luma

if TYPE_CHECKING:
    from typing import Any

    from numpy.typing import NDArray

    from stunt_reel.bench.planes import RenderSource

__all__ = ["ALL_FAULTS", "WRONG_TICK_DRAWS", "Fault", "plant"]

#: Layers at or above this are actors; below it, terrain and scenery.
ACTOR_LAYER = 16
#: The layer holding terrain.
TERRAIN_LAYER = 2
#: Ticks a ``wrong_tick`` candidate must be from the frame's own.
WRONG_TICK_MIN_DISTANCE = 100
#: Share of index pixels a ``wrong_tick`` frame must differ in.
WRONG_TICK_MIN_DIFFERENCE = 0.10
#: Candidates ``wrong_tick`` loads before giving up; testing all would read the whole tree per frame.
WRONG_TICK_DRAWS = 50


@dataclass(frozen=True)
class Fault:
    """A kind of damage, with its size where it has one."""

    name: str
    magnitude: int | None

    @property
    def key(self) -> str:
        """``name``, or ``name:magnitude``."""
        return self.name if self.magnitude is None else f"{self.name}:{self.magnitude}"


ALL_FAULTS: tuple[Fault, ...] = (
    Fault("none", None),
    Fault("actors_removed", None),
    *(Fault("shift_x", k) for k in (1, 2, 4, 8)),
    *(Fault("shift_y", k) for k in (1, 2, 4)),
    *(Fault("advance", k) for k in (1, 3, 5)),
    Fault("flat_terrain", None),
    *(Fault("flicker", a) for a in (3, 10)),
    Fault("wrong_tick", None),
    Fault("grey", None),
)


def _map_planes(planes: RenderPlanes, fn: Any) -> RenderPlanes:
    return RenderPlanes(
        rgb=fn(planes.rgb),
        idx=None if planes.idx is None else fn(planes.idx),
        layer=fn(planes.layer),
    )


def _actors_removed(planes: RenderPlanes) -> RenderPlanes:
    height, width = planes.layer.shape
    columns = np.arange(width)[None, :]
    keep = planes.layer < ACTOR_LAYER
    source = np.maximum.accumulate(np.where(keep, columns, -1), axis=1)
    source = np.where(source < 0, columns, source)
    rows = np.arange(height)[:, None]
    return _map_planes(planes, lambda plane: plane[rows, source])


def _shift_x(plane: NDArray[Any], k: int) -> NDArray[Any]:
    out = np.empty_like(plane)
    out[:, k:] = plane[:, : plane.shape[1] - k]
    out[:, :k] = plane[:, :1]
    return out


def _shift_y(plane: NDArray[Any], k: int) -> NDArray[Any]:
    out = np.empty_like(plane)
    out[k:] = plane[: plane.shape[0] - k]
    out[:k] = plane[:1]
    return out


def _flat_terrain(planes: RenderPlanes) -> RenderPlanes:
    mask = planes.layer == TERRAIN_LAYER
    if not mask.any():
        return planes
    rgb = planes.rgb.copy()
    flat = np.rint(planes.rgb[mask].mean(axis=0)).astype(np.uint8)
    rgb[mask] = flat
    idx = planes.idx
    if idx is not None:
        idx = idx.copy()
        idx[mask] = _flat_index(planes.idx, mask, planes.rgb, flat)  # type: ignore[arg-type]
    return RenderPlanes(rgb=rgb, idx=idx, layer=planes.layer.copy())


def _flat_index(
    idx: NDArray[np.uint8], mask: NDArray[np.bool_], rgb: NDArray[np.uint8], flat: NDArray[np.uint8]
) -> int:
    """The index flat terrain takes: its most common one that no other layer shows.

    A render store keeps one colour per index, so an index shared with another layer would have
    to show both the flat colour and its own. Failing a terrain-only index, an index the frame
    does not use; then one whose other pixels already show the flat colour; failing all three,
    the most common terrain index.
    """
    terrain = np.bincount(idx[mask], minlength=256)
    own = np.where(np.bincount(idx[~mask], minlength=256) > 0, 0, terrain)
    if own.any():
        return int(own.argmax())
    free = np.flatnonzero(np.bincount(idx.reshape(-1), minlength=256) == 0)
    if free.size:
        return int(free[0])
    outside, colours = idx[~mask], rgb[~mask]
    for index in np.unique(outside):
        if (colours[outside == index] == flat).all():
            return int(index)
    return int(terrain.argmax())


def _flicker(planes: RenderPlanes, tick: int, amount: int) -> RenderPlanes:
    signed = amount if tick % 2 == 0 else -amount
    rgb = np.clip(planes.rgb.astype(np.int16) + signed, 0, 255).astype(np.uint8)
    return RenderPlanes(rgb=rgb, idx=planes.idx, layer=planes.layer)


def _wrong_tick(tick: int, source: RenderSource, rng_seed: int) -> RenderPlanes | None:
    own = source.load(tick).idx
    if own is None:
        return None
    candidates = [t for t in source.ticks() if abs(t - tick) >= WRONG_TICK_MIN_DISTANCE]
    random.Random(rng_seed * 1_000_003 + tick).shuffle(candidates)  # noqa: S311 - not security
    for candidate in candidates[:WRONG_TICK_DRAWS]:
        planes = source.load(candidate)
        if planes.idx is None:
            continue
        if (planes.idx != own).mean() >= WRONG_TICK_MIN_DIFFERENCE:
            return planes
    return None


def _grey(planes: RenderPlanes) -> RenderPlanes:
    level = np.uint8(round(float(render_luma(planes.rgb).mean())))
    return RenderPlanes(rgb=np.full_like(planes.rgb, level), idx=None, layer=planes.layer)


def plant(fault: Fault, tick: int, source: RenderSource, rng_seed: int) -> RenderPlanes | None:
    """The frame *fault* makes of *tick*; ``None`` when the fault has no frame there.

    Some faults reuse the source's arrays; callers must not mutate the returned planes.
    Raises ``ValueError`` for an unknown fault name.
    """
    planes = source.load(tick)
    magnitude = fault.magnitude or 0
    match fault.name:
        case "none":
            return planes
        case "actors_removed":
            return _actors_removed(planes)
        case "shift_x":
            return _map_planes(planes, lambda plane: _shift_x(plane, magnitude))
        case "shift_y":
            return _map_planes(planes, lambda plane: _shift_y(plane, magnitude))
        case "advance":
            target = tick + magnitude
            return source.load(target) if target in source.ticks() else None
        case "flat_terrain":
            return _flat_terrain(planes)
        case "flicker":
            return _flicker(planes, tick, magnitude)
        case "wrong_tick":
            return _wrong_tick(tick, source, rng_seed)
        case "grey":
            return _grey(planes)
    raise ValueError(f"unknown fault {fault.name!r}")
