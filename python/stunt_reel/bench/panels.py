"""The difference panels of readout sheets and parity strips, and their key.

The **composite** is grey where capture and render agree in luma, magenta where the capture is
brighter and green where the render is, so a shifted feature shows as a magenta fringe on one side
and a green one on the other (the green side is where the render put a feature brighter than its
surroundings, the magenta side one darker). Two colours of equal
luma look alike in it; the **index map** catches those: the capture dimmed, with every
mismatched pixel painted by the layer the render drew there (:data:`LAYER_KEY`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from stunt_reel.bench.ssim import render_luma
from stunt_reel.parity_artifacts import (
    LAYER_FIRST_ACTOR,
    LAYER_NONE,
    LAYER_OCEAN,
    LAYER_OVERLAY,
    LAYER_PROP,
    LAYER_TERRAIN,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from numpy.typing import NDArray
    from PIL import ImageDraw, ImageFont

__all__ = [
    "COMPOSITE_TITLE",
    "INDEX_MAP_TITLE",
    "LAYER_KEY",
    "MASKED",
    "KeyEntry",
    "composite",
    "draw_key",
    "index_map",
]

#: What masked pixels (the button bar, the HUD timer, the cursor) show in a difference panel.
MASKED = 128
#: How much the composite amplifies a luma difference, as the old grey difference panel did.
GAIN = 3
#: The index map's base: capture luma scaled by this, so painted pixels stand out.
DIM = 0.55
COMPOSITE_TITLE = "OVERLAY: magenta = brighter in capture, green = brighter in render"
INDEX_MAP_TITLE = "INDEX MISMATCH, coloured by what the render drew there"


@dataclass(frozen=True)
class KeyEntry:
    """One colour of the index map: the render layers ``lo`` to ``hi`` inclusive."""

    name: str
    colour: tuple[int, int, int]
    lo: int
    hi: int


#: The index map's colours, none of them the composite's magenta or green.
LAYER_KEY = (
    KeyEntry("uncovered", (255, 220, 0), LAYER_NONE, LAYER_NONE),
    KeyEntry("ocean", (0, 110, 255), LAYER_OCEAN, LAYER_OCEAN),
    KeyEntry("terrain", (255, 120, 0), LAYER_TERRAIN, LAYER_TERRAIN),
    KeyEntry("prop", (255, 255, 255), LAYER_PROP, LAYER_PROP),
    KeyEntry("credits", (0, 230, 230), LAYER_OVERLAY, LAYER_OVERLAY),
    KeyEntry("actor or its shadow", (230, 0, 0), LAYER_FIRST_ACTOR, 0xFFFF),
    KeyEntry("unknown layer", (150, 90, 40), LAYER_OVERLAY + 1, LAYER_FIRST_ACTOR - 1),
)


def composite(
    capture_rgb: NDArray[np.uint8], render_rgb: NDArray[np.uint8], mask: NDArray[np.bool_]
) -> NDArray[np.uint8]:
    """Their mean luma, with the capture's excess times :data:`GAIN` in red and blue and the
    render's in green; *mask* pixels :data:`MASKED`.
    """
    capture = render_luma(capture_rgb)
    render = render_luma(render_rgb)
    mean = (capture + render) / 2
    excess = (capture - render) * GAIN / 2
    planes = np.stack([mean + excess, mean - excess, mean + excess], axis=-1)
    out = planes.round().clip(0, 255).astype(np.uint8)
    out[mask] = MASKED
    return out


def index_map(
    capture_rgb: NDArray[np.uint8],
    mismatch: NDArray[np.bool_],
    layer: NDArray[np.uint16],
    mask: NDArray[np.bool_],
) -> tuple[NDArray[np.uint8], dict[str, int]]:
    """The dimmed capture with each unmasked *mismatch* pixel painted by its *layer*'s entry.

    Returns the picture and each :data:`LAYER_KEY` entry's painted pixel count.
    """
    base = (render_luma(capture_rgb) * DIM).round().clip(0, 255).astype(np.uint8)
    out = np.repeat(base[..., None], 3, axis=-1)
    shown = mismatch & ~mask
    counts: dict[str, int] = {}
    for entry in LAYER_KEY:
        painted = shown & (layer >= entry.lo) & (layer <= entry.hi)
        out[painted] = entry.colour
        counts[entry.name] = int(np.count_nonzero(painted))
    out[mask] = MASKED
    return out, counts


def draw_key(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    columns: Sequence[Mapping[str, int]],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    line: int,
) -> int:
    """Draw a swatch, name and each column's pixel count per key entry; returns the lines drawn.

    The unknown-layer entry is drawn only when some column counts a pixel on it.
    """
    x, y = origin
    drawn = 0
    for entry in LAYER_KEY:
        counts = [column.get(entry.name, 0) for column in columns]
        if entry is LAYER_KEY[-1] and not any(counts):
            continue
        top = y + drawn * line
        side = max(line - 6, 4)
        draw.rectangle([x, top + 2, x + side, top + 2 + side], fill=entry.colour, outline="black")
        text = f"{entry.name}: " + " | ".join(str(c) for c in counts)
        draw.text((x + side + 6, top), text, fill="black", font=font)
        drawn += 1
    return drawn
