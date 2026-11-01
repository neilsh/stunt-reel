"""Load the planes the bench scores: a capture's index planes and a render's PNG and planes."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np
from PIL import Image

from stunt_reel.parity_artifacts import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    read_capture,
    read_capture_palette,
    read_render,
    render_plane_paths,
    tick_stem,
)

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

__all__ = [
    "BenchError",
    "CapturePlanes",
    "RenderPlanes",
    "RenderSource",
    "RenderTree",
    "load_capture",
]

SHAPE = (CAPTURE_HEIGHT, CAPTURE_WIDTH)
#: Ticks a tree keeps decoded; a whole tree is about 500 MB in memory.
CACHE_TICKS = 64


class BenchError(RuntimeError):
    """A bench input is missing or malformed."""


@dataclass(frozen=True)
class RenderPlanes:
    """One rendered tick: the PNG, and the index and layer planes beside it."""

    rgb: NDArray[np.uint8]  # (200, 320, 3)
    idx: NDArray[np.uint8] | None  # (200, 320)
    layer: NDArray[np.uint16]  # (200, 320)


@dataclass(frozen=True)
class CapturePlanes:
    """One captured frame: its index plane and its 8-bit palette."""

    idx: NDArray[np.uint8]  # (200, 320)
    palette: NDArray[np.uint8]  # (256, 3), 8-bit


class RenderSource(Protocol):
    """Where faults, metrics and the bench get rendered ticks from."""

    def ticks(self) -> list[int]:
        """The film ticks this source can load, ascending."""
        ...

    def load(self, tick: int) -> RenderPlanes:
        """The planes of one tick."""
        ...


class RenderTree:
    """A render directory: ``render.json`` plus ``tick_NNNNN.{png,idx,layer}``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: OrderedDict[int, RenderPlanes] = OrderedDict()

    def ticks(self) -> list[int]:
        """The ticks in ``render.json``, ascending."""
        return [entry.tick for entry in read_render(self.root / "render.json").ticks]

    def load(self, tick: int) -> RenderPlanes:
        """Decode a tick, keeping the :data:`CACHE_TICKS` most recent."""
        cached = self._cache.get(tick)
        if cached is not None:
            self._cache.move_to_end(tick)
            return cached
        planes = self._decode(tick)
        self._cache[tick] = planes
        while len(self._cache) > CACHE_TICKS:
            self._cache.popitem(last=False)
        return planes

    def _decode(self, tick: int) -> RenderPlanes:
        png = self.root / f"{tick_stem(tick)}.png"
        idx_path, layer_path = render_plane_paths(self.root, tick)
        for path in (png, idx_path, layer_path):
            if not path.is_file():
                raise BenchError(f"{path} is missing; re-render {self.root} to write its planes")
        with Image.open(png) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
        if rgb.shape != (*SHAPE, 3):
            raise BenchError(f"{png} is {rgb.shape}, expected {(*SHAPE, 3)}")
        idx = np.frombuffer(idx_path.read_bytes(), dtype=np.uint8)
        layer = np.frombuffer(layer_path.read_bytes(), dtype="<u2")
        if idx.size != CAPTURE_HEIGHT * CAPTURE_WIDTH or layer.size != idx.size:
            raise BenchError(f"{idx_path} or {layer_path} is the wrong size; re-render {self.root}")
        return RenderPlanes(
            rgb=rgb,
            idx=idx.reshape(SHAPE),
            layer=layer.astype(np.uint16).reshape(SHAPE),
        )


def load_capture(directory: Path) -> dict[int, CapturePlanes]:
    """Every captured frame of *directory*, keyed by film tick."""
    capture = read_capture(directory)
    frames: dict[int, CapturePlanes] = {}
    for frame in capture.frames:
        idx = np.frombuffer((directory / frame.frame_file).read_bytes(), dtype=np.uint8)
        if idx.size != CAPTURE_HEIGHT * CAPTURE_WIDTH:
            raise BenchError(f"{directory / frame.frame_file} holds {idx.size} bytes")
        palette = read_capture_palette(directory / frame.palette_file)
        frames[frame.film_tick] = CapturePlanes(
            idx=idx.reshape(SHAPE),
            palette=np.array(palette, dtype=np.uint8),
        )
    return frames
