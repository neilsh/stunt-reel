"""Regenerate the synthetic bench fixture beside this file.

Two film ticks (10 and 20) of 320x200 content: a sky, a checkered terrain, an actor and a
button bar. ``capture/`` is the reference, ``render/`` a slightly dimmer render of it (a render
store, ADR 0027), and ``render_before/`` the same render with the terrain checker phase flipped
at tick 20.

Run it from the repository root with ``mise exec -- uv run python <this file>``. ``golden.json``
is not written here: it holds the Rust scorer's SSIM, produced by the command in
``tests/fixtures/README.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from stunt_reel.parity_artifacts import (
    CameraPose,
    CapturedFrame,
    CaptureSet,
    FilmId,
    Geometry,
    RenderPalette,
    RenderTick,
    StoredFrame,
    write_capture,
    write_render_store,
)

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 320, 200
TICKS = (10, 20)
LAYER_TERRAIN = 2
LAYER_ACTOR = 16
CURSOR_X, CURSOR_Y = 200, 40
ACTOR_X, ACTOR_Y, ACTOR_W, ACTOR_H = 100, 120, 20, 16
FILM = FilmId(name="BENCH.FLM", flm_bytes=1)
GEOMETRY = Geometry(width=WIDTH, height=HEIGHT)


def palette() -> np.ndarray:
    """The capture palette: entry i is (i, 255 - i, i // 2)."""
    entries = np.arange(256)
    return np.stack([entries, 255 - entries, entries // 2], axis=1).astype(np.uint8)


def planes(
    *, actor_shift: int, checker_flip: bool, cursor: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """The index and layer planes of one frame."""
    idx = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    layer = np.zeros((HEIGHT, WIDTH), dtype=np.uint16)
    rows = np.arange(HEIGHT)[:, None]
    cols = np.arange(WIDTH)[None, :]
    idx[:60, :] = (227 + rows[:60] % 12).astype(np.uint8)
    phase = (rows // 8 + cols // 8 + int(checker_flip)) % 2
    terrain = np.where(phase == 0, 40, 41).astype(np.uint8)
    idx[60:185, :] = terrain[60:185, :]
    layer[60:185, :] = LAYER_TERRAIN
    x0 = ACTOR_X + actor_shift
    idx[ACTOR_Y : ACTOR_Y + ACTOR_H, x0 : x0 + ACTOR_W] = 16
    layer[ACTOR_Y : ACTOR_Y + ACTOR_H, x0 : x0 + ACTOR_W] = LAYER_ACTOR
    idx[185:, :] = 250
    if cursor:
        idx[CURSOR_Y : CURSOR_Y + 3, CURSOR_X : CURSOR_X + 3] = 255
    return idx, layer


def write_text(path: Path, text: str) -> None:
    """Write *text* with LF line endings on every platform."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_capture_dir(directory: Path) -> None:
    """Write the reference capture."""
    directory.mkdir(parents=True, exist_ok=True)
    frames = []
    for ordinal, tick in enumerate(TICKS, start=1):
        idx, _ = planes(actor_shift=0 if tick == 10 else 4, checker_flip=False, cursor=tick == 10)
        (directory / f"tick_{ordinal:04d}.idx").write_bytes(idx.tobytes())
        write_text(
            directory / f"palettes_{ordinal:04d}.json",
            json.dumps(palette().tolist()) + "\n",
        )
        frames.append(
            CapturedFrame(
                ordinal=ordinal,
                film_tick=tick,
                frame_file=f"tick_{ordinal:04d}.idx",
                palette_file=f"palettes_{ordinal:04d}.json",
            )
        )
    write_capture(
        directory,
        CaptureSet(schema_version=1, film=FILM, geometry=GEOMETRY, frames=tuple(frames)),
    )


def write_render_dir(directory: Path, *, flip_tick_20: bool) -> None:
    """Write a render store whose palette is the capture palette scaled by 0.9."""
    directory.mkdir(parents=True, exist_ok=True)
    scaled = np.rint(palette().astype(np.float64) * 0.9).astype(np.uint8)
    pose = CameraPose(
        eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, 0.0), fov_degrees=45.0, roll_radians=0.0
    )
    frames = []
    for tick in TICKS:
        idx, layer = planes(actor_shift=0, checker_flip=flip_tick_20 and tick == 20)
        entry = RenderTick(
            tick=tick,
            palette=RenderPalette(sky=0, brightness=0x8000, saturation=0x8000),
            camera=pose,
            palette_index=0,
        )
        stored = StoredFrame(
            indices=idx.tobytes(),
            layers=layer.astype("<u2").tobytes(),
            palette=scaled.tobytes(),
        )
        frames.append((entry, stored))
    write_render_store(directory, FILM, GEOMETRY, frames)


def main() -> None:
    """Write all three directories."""
    write_capture_dir(HERE / "capture")
    write_render_dir(HERE / "render", flip_tick_20=False)
    write_render_dir(HERE / "render_before", flip_tick_20=True)


if __name__ == "__main__":
    main()
