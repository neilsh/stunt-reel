"""The comparison sheets a readout grades, and the PIL images that carry them.

A sheet is the capture beside the render at 2x, their luma difference, and an actor close-up.
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
from stunt_reel.bench.ssim import render_luma, stretch
lazy from stunt_reel.bench.planes import RenderTree

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from numpy.typing import NDArray

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
#: Frames whose fade level is below this are not picked: the screen is fading in or out.
MIN_FADE_LEVEL = 0.95
#: The prop layer, framed by the close-up when no actor is on screen.
PROP_LAYER = 3


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
    ticks: Sequence[int], tree: RenderTree, taxonomy: Taxonomy, seed: int, calibrate: bool
) -> list[Sheet]:
    """Every sheet a run holds: the key, recomputed from the seed whenever it is needed."""
    sheets = [Sheet(sheet_id(seed, "real", None, t), "real", t, None) for t in ticks]
    if not calibrate:
        return sheets
    sheets += [Sheet(sheet_id(seed, "control", None, t), "control", t, None) for t in ticks]
    rng = random.Random(seed)  # noqa: S311 - not security
    for key in taxonomy.faults:
        if key == "actors_removed":
            with_actors = [t for t in ticks if (tree.load(t).layer >= ACTOR_LAYER).any()]
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


def build_sheet(
    capture_rgb: NDArray[np.uint8], render_rgb: NDArray[np.uint8], layer: NDArray[np.uint16]
) -> Image.Image:
    """Capture and render side by side at 2x, their luma difference, and an actor close-up."""
    capture = np.array(stretch(capture_rgb), dtype=np.uint8)
    render = np.array(stretch(render_rgb), dtype=np.uint8)
    layer240 = stretch(layer)
    capture[BAR:] = GREY  # the game's button bar is not part of the 3D view
    render[BAR:] = GREY
    diff = np.clip(np.abs(render_luma(capture) - render_luma(render)) * 3, 0, 255)
    diff_rgb = np.repeat(diff.astype(np.uint8)[..., None], 3, axis=2)
    top = (
        _panel(capture, "CAPTURE (the original game)"),
        _panel(render, "RENDER (our reimplementation)"),
    )
    bottom = (
        _panel(
            diff_rgb,
            "DIFFERENCE |capture - render| (brighter = more different; grey band = UI bar, ignore)",
        ),
        _close_up(capture, render, layer240),
    )
    out = Image.new("RGB", (2 * PANEL_WIDTH + GAP, 2 * top[0].height + GAP), "white")
    for row, (left, right) in enumerate((top, bottom)):
        y = row * (top[0].height + GAP)
        out.paste(left, (0, y))
        out.paste(right, (PANEL_WIDTH + GAP, y))
    return out
