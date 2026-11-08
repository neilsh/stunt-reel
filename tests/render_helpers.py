"""Synthetic render stores for the Python tests (ADR 0027).

Each tick's planes differ by tick, so a test can tell which source tick a frame came from.
"""

from __future__ import annotations

import json
import struct
from typing import TYPE_CHECKING

from stunt_reel import parity_layout, parity_pipeline, references
from stunt_reel.parity_artifacts import (
    PALETTE_BYTES,
    RENDER_SCHEMA_VERSION,
    CameraPose,
    FilmId,
    Geometry,
    RenderAdapter,
    RenderPalette,
    RenderRecord,
    RenderStore,
    RenderTick,
    StoredFrame,
    write_render,
    write_render_store,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

#: The geometry of a store written without one: 4x3 with a 2-row viewport.
TINY = Geometry(width=4, height=3, viewport_rows=2)


def frame_for(tick: int, geometry: Geometry = TINY) -> StoredFrame:
    """Planes and a palette that are distinct for every tick."""
    pixels = geometry.width * geometry.height
    indices = bytes((tick + pixel) % 256 for pixel in range(pixels))
    layers = struct.pack(f"<{pixels}H", *((tick * 7 + pixel) % 65536 for pixel in range(pixels)))
    palette = bytes((entry + tick % 2) % 256 for entry in range(PALETTE_BYTES))
    return StoredFrame(indices=indices, layers=layers, palette=palette)


def tick_entry(tick: int, *, sky: int = 45, brightness: int = 32768) -> RenderTick:
    """A render.json entry for *tick*; the store assigns its palette index."""
    return RenderTick(
        tick=tick,
        palette=RenderPalette(sky=sky, brightness=brightness, saturation=32768),
        camera=CameraPose(
            eye=(float(tick), 0.0, 0.0), target=(0.0, 0.0, 0.0), fov_degrees=45.0, roll_radians=0.0
        ),
        palette_index=0,
    )


def write_store(
    directory: Path,
    ticks: Iterable[int],
    *,
    geometry: Geometry = TINY,
    film: FilmId | None = None,
    adapter: RenderAdapter | None = None,
) -> RenderRecord:
    """Write a render store holding *ticks*; with none, an empty ``render.json`` only."""
    directory.mkdir(parents=True, exist_ok=True)
    film = film if film is not None else FilmId()
    ticks = list(ticks)
    if not ticks:
        record = RenderRecord(
            schema_version=RENDER_SCHEMA_VERSION,
            film=film,
            geometry=geometry,
            ticks=(),
            palette_count=0,
            chunks=(),
            adapter=adapter,
        )
        write_render(directory / "render.json", record)
        return record
    frames = ((tick_entry(tick), frame_for(tick, geometry)) for tick in ticks)
    return write_render_store(directory, film, geometry, frames, adapter=adapter)


def rewrite_store(
    source: Path, out: Path, change: Callable[[int, StoredFrame], StoredFrame]
) -> RenderRecord:
    """Write *out* as *source*'s store with every tick passed through *change*."""
    store = RenderStore(source)
    record = store.record
    out.mkdir(parents=True, exist_ok=True)
    frames = ((entry, change(entry.tick, store.frame(entry.tick))) for entry in record.ticks)
    return write_render_store(out, record.film, record.geometry, frames)


def flip_byte(data: bytes, at: int = 0) -> bytes:
    """*data* with the lowest bit of byte *at* flipped."""
    changed = bytearray(data)
    changed[at] ^= 1
    return bytes(changed)


def pin_reference(root: Path, film: str, frames: list[dict[str, int]]) -> Path:
    """Write a capture of *film* under *root* and name it in the root's references.toml."""
    reference = root / parity_layout.frames_path(f"vault-{film}")
    reference.mkdir(parents=True, exist_ok=True)
    (reference / "meta.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")
    pointers = root / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True, exist_ok=True)
    digest = references.capture_digest(reference)
    with pointers.open("a", encoding="utf-8") as handle:
        handle.write(
            f'[{film}]\nfilm = "vault-{film}"\nsha256 = "{digest}"\n'
            'makeone = "patch3"\nplayone = "patch3"\n'
        )
    return reference


def reference_tree(
    root: Path, ticks: list[int], films: tuple[str, ...] = ("ctry", "intro")
) -> Path:
    """A data root holding each film's ``.FLM``, ``.ALL`` and SIDATA, and its pinned capture."""
    vault = root / "corpus" / "stisldem" / "VAULT"
    vault.mkdir(parents=True, exist_ok=True)
    (root / "corpus" / parity_pipeline.SIDATA).mkdir(parents=True, exist_ok=True)
    for name in films:
        (vault / f"{name.upper()}.FLM").write_bytes(
            name.encode()
        )  # distinct films: equal bytes are one film
        (vault / f"{name.upper()}.ALL").write_bytes(b"")
        pin_reference(root, name, [{"film_tick": tick} for tick in ticks])
    return root
