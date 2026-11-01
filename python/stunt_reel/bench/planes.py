"""Load the planes the bench scores: a capture's index planes and a render store's planes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np

from stunt_reel.parity_artifacts import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    ArtifactError,
    RenderStore,
    StoredFrame,
    read_capture,
    read_capture_palette,
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


class BenchError(RuntimeError):
    """A bench input is missing or malformed."""


@dataclass(frozen=True)
class RenderPlanes:
    """One rendered tick: its picture, and its index and layer planes."""

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
    """A render directory's store: ``render.json`` and its zstd chunks (ADR 0027).

    The store is opened on first use and keeps its last two decoded chunks, so walking the
    ticks in order decodes each film second once; a tick's picture is ``palette[idx]``.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._store: RenderStore | None = None

    @property
    def store(self) -> RenderStore:
        """The opened store; ``BenchError`` when the directory is not a readable one."""
        if self._store is None:
            try:
                self._store = RenderStore(self.root)
            except ArtifactError as err:
                raise BenchError(str(err)) from err
        return self._store

    def ticks(self) -> list[int]:
        """The ticks in ``render.json``, ascending."""
        return self.store.ticks()

    def stored(self, tick: int) -> StoredFrame:
        """One tick as stored: its planes and palette."""
        try:
            return self.store.frame(tick)
        except ArtifactError as err:
            raise BenchError(str(err)) from err

    def load(self, tick: int) -> RenderPlanes:
        """Decode a tick into arrays."""
        frame = self.stored(tick)
        idx = np.frombuffer(frame.indices, dtype=np.uint8)
        layer = np.frombuffer(frame.layers, dtype="<u2")
        if idx.size != CAPTURE_HEIGHT * CAPTURE_WIDTH:
            raise BenchError(f"{self.root} is not {CAPTURE_WIDTH}x{CAPTURE_HEIGHT}; re-render it")
        palette = np.frombuffer(frame.palette, dtype=np.uint8).reshape(256, 3)
        return RenderPlanes(
            rgb=palette[idx].reshape((*SHAPE, 3)),
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
