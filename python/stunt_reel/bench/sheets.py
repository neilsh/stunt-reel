"""The comparison sheets a readout grades, and the PIL images that carry them.

A sheet is the capture beside the render at 2x, their composite and index map
(:mod:`stunt_reel.bench.panels`), and an actor close-up beside the map's key.
Its file name carries no key: :func:`plan_sheets` recomputes the key from the run's seed.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from stunt_reel.bench.faults import ACTOR_LAYER
from stunt_reel.bench.mismatch import (
    colour_mismatch,
    index_mismatch,
    mismatch_fraction,
    readout_mask,
)
from stunt_reel.bench.panels import COMPOSITE_TITLE, INDEX_MAP_TITLE, composite, draw_key, index_map
from stunt_reel.bench.ssim import stretch
from stunt_reel.parity_artifacts import LAYER_PROP
lazy from stunt_reel.bench.planes import RenderSource

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from numpy.typing import NDArray

    from stunt_reel.bench.planes import CapturePlanes
    from stunt_reel.bench.taxonomy import FilmWindow, Taxonomy
    from stunt_reel.parity_artifacts import Report

__all__ = [
    "Sheet",
    "build_sheet",
    "pick_ticks",
    "plan_sheets",
    "sheet_id",
]


#: Frames a readout grades per film.
SHEET_TICKS = 12
#: Frames each planted fault is drawn on in a calibrating run.
FAULT_FRAMES = 6
#: Actor pixels, summed over every actor, a frame must hold to carry an actors-removed sheet: an 8x8
#: block of the 320x200 frame, a convention inside the untested gap between the sheets graders
#: missed (1 and 33) and caught (852 or more) (research/parity/metric-bench.md, calibration rules).
MIN_ACTOR_PIXELS = 64
#: Frames whose fade level is below this are not picked: the screen is fading in or out.
MIN_FADE_LEVEL = 0.95
#: The prop layer, framed by the close-up when no actor is on screen.
PROP_LAYER = LAYER_PROP


Kind = Literal["real", "control", "planted"]


@dataclass(frozen=True)
class Sheet:
    """One graded image: a real frame, a control (recapture as render), or a planted fault."""

    id: str
    kind: Kind
    tick: int
    fault: str | None


def pick_ticks(
    report: Report, held: Collection[int], window: FilmWindow, n: int = SHEET_TICKS
) -> list[int]:
    """*n* scored, unfaded ticks in *window* and *held*, spread evenly; all of them if fewer."""
    ticks = sorted(
        frame.film_tick
        for frame in report.per_frame
        if frame.scored is True
        and (frame.fade_level is None or frame.fade_level >= MIN_FADE_LEVEL)
        and window.holds(frame.film_tick)
        and frame.film_tick in held
    )
    if len(ticks) <= n:
        return ticks
    return [ticks[round(i * (len(ticks) - 1) / (n - 1))] for i in range(n)]


def sheet_id(seed: int, kind: str, fault: str | None, tick: int) -> str:
    """A sheet's file name: 12 hex characters that say nothing of what it shows."""
    return hashlib.sha256(f"{seed}:{kind}:{fault}:{tick}".encode()).hexdigest()[:12]


def plan_sheets(
    ticks: Sequence[int], tree: RenderSource, taxonomy: Taxonomy, seed: int, calibrate: bool
) -> list[Sheet]:
    """Every sheet a run holds: the key, recomputed from the seed whenever it is needed."""
    sheets = [Sheet(sheet_id(seed, "real", None, t), "real", t, None) for t in ticks]
    if not calibrate:
        return sheets
    sheets += [Sheet(sheet_id(seed, "control", None, t), "control", t, None) for t in ticks]
    rng = random.Random(seed)  # noqa: S311 - not security
    for key in taxonomy.faults:
        if key == "actors_removed":
            with_actors = [
                t
                for t in ticks
                if np.count_nonzero(tree.load(t).layer >= ACTOR_LAYER) >= MIN_ACTOR_PIXELS
            ]
            chosen = with_actors[:FAULT_FRAMES]
        else:
            chosen = rng.sample(list(ticks), min(FAULT_FRAMES, len(ticks)))
        sheets += [Sheet(sheet_id(seed, "planted", key, t), "planted", t, key) for t in chosen]
    return sheets


SCALE = 2
GAP = 8
LABEL = 26
#: First row of the button bar (row 185 of 200) once stretched to 240.
BAR = 222
PAD = 32
PANEL_WIDTH = 320 * SCALE
CLOSE_UP_HEIGHT = 240 * SCALE
GREY = 128
#: Height of one line of the key panel.
KEY_LINE = 30


def _font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=20)


def _enlarge(rgb: NDArray[np.uint8], k: int) -> NDArray[np.uint8]:
    return np.repeat(np.repeat(rgb, k, axis=0), k, axis=1)


def _labelled(image: Image.Image, title: str) -> Image.Image:
    out = Image.new("RGB", (image.width, image.height + LABEL), "white")
    out.paste(image, (0, LABEL))
    ImageDraw.Draw(out).text((4, 2), title, fill="black", font=_font())
    return out


def _panel(rgb240: NDArray[np.uint8], title: str) -> Image.Image:
    return _labelled(Image.fromarray(_enlarge(rgb240, SCALE)), title)


def _close_up_box(
    layer: NDArray[np.uint16],
) -> tuple[tuple[int, int, int, int], str] | None:
    """Rows and columns framing the actors, else the props, padded; and what they frame."""
    for mask, name in ((layer >= ACTOR_LAYER, "aircraft/actors"), (layer == PROP_LAYER, "props")):
        ys, xs = np.nonzero(mask)
        if len(ys):
            y0, y1 = max(int(ys.min()) - PAD, 0), min(int(ys.max()) + PAD + 1, BAR)
            x0, x1 = max(int(xs.min()) - PAD, 0), min(int(xs.max()) + PAD + 1, 320)
            return (y0, y1, x0, x1), name
    return None


def _close_up(
    capture: NDArray[np.uint8], render: NDArray[np.uint8], layer: NDArray[np.uint16]
) -> Image.Image:
    out = Image.new("RGB", (PANEL_WIDTH, CLOSE_UP_HEIGHT + LABEL), "white")
    draw = ImageDraw.Draw(out)
    framed = _close_up_box(layer)
    if framed is None:
        draw.text((4, 2), "CLOSE-UP: no aircraft or props in frame", fill="black", font=_font())
        return out
    (y0, y1, x0, x1), name = framed
    k = max(1, min((PANEL_WIDTH // 2 - GAP) // (x1 - x0), CLOSE_UP_HEIGHT // (y1 - y0)))
    for i, source in enumerate((capture, render)):
        crop = Image.fromarray(_enlarge(source[y0:y1, x0:x1], k))
        out.paste(crop, (i * (PANEL_WIDTH // 2 + GAP // 2), LABEL))
    title = f"CLOSE-UP of {name}: CAPTURE (left) | RENDER (right), {k}x"
    draw.text((4, 2), title, fill="black", font=_font())
    return out


def _key_panel(counts: dict[str, int], fraction: float) -> Image.Image:
    out = Image.new("RGB", (PANEL_WIDTH, CLOSE_UP_HEIGHT + LABEL), "white")
    draw = ImageDraw.Draw(out)
    draw.text(
        (4, 2),
        "KEY to the INDEX MISMATCH panel: pixels per colour, of 320x200",
        fill="black",
        font=_font(),
    )
    lines = draw_key(draw, (8, LABEL + 12), [counts], _font(), KEY_LINE)
    summary = f"{100 * fraction:.1f}% of the unmasked pixels mismatch"
    draw.text((8, LABEL + 24 + lines * KEY_LINE), summary, fill="black", font=_font())
    return out


def build_sheet(
    capture: CapturePlanes,
    render_rgb: NDArray[np.uint8],
    render_idx: NDArray[np.uint8] | None,
    layer: NDArray[np.uint16],
    *,
    credits_drawn: bool = False,
) -> Image.Image:
    """Three rows at 2x: capture and render, their composite and index map, a close-up and key.

    With no *render_idx*, a pixel mismatches when its colour differs.
    The button bar and HUD timer are grey in every panel; the difference panels mask the cursor
    too, unless *credits_drawn* (``overlay_mask``).
    """
    capture_rgb = capture.palette[capture.idx]
    if render_idx is None:
        mismatch = colour_mismatch(capture_rgb, render_rgb)
    else:
        mismatch = index_mismatch(capture.idx, render_idx)
    hud = stretch(readout_mask(capture.idx, credits_drawn=True))
    masked = readout_mask(capture.idx, credits_drawn=credits_drawn)
    fraction = mismatch_fraction(mismatch, masked)
    capture240 = np.array(stretch(capture_rgb), dtype=np.uint8)
    render240 = np.array(stretch(render_rgb), dtype=np.uint8)
    layer240 = stretch(layer)
    masked240 = stretch(masked)
    mismatch_map, counts = index_map(capture_rgb, mismatch, layer, masked)  # counts on 320x200
    mismatch_map = np.array(stretch(mismatch_map), dtype=np.uint8)
    overlay = composite(capture240, render240, masked240)
    capture240[hud] = GREY  # the game's button bar and timer are not part of the 3D view
    render240[hud] = GREY
    rows = (
        (
            _panel(capture240, "CAPTURE (the original game)"),
            _panel(render240, "RENDER (our reimplementation)"),
        ),
        (_panel(overlay, COMPOSITE_TITLE), _panel(mismatch_map, INDEX_MAP_TITLE)),
        (_close_up(capture240, render240, layer240), _key_panel(counts, fraction)),
    )
    height = rows[0][0].height
    out = Image.new("RGB", (2 * PANEL_WIDTH + GAP, 3 * height + 2 * GAP), "white")
    for row, (left, right) in enumerate(rows):
        y = row * (height + GAP)
        out.paste(left, (0, y))
        out.paste(right, (PANEL_WIDTH + GAP, y))
    return out
