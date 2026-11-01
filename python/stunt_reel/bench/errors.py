"""The error readout: a vision model grades each kind of render error per frame.

``research/parity/error-categories.toml`` lists the categories, the faults each should catch, the
films' tick windows and the readout's noise floor. A run picks frames from a film's window, draws
one comparison sheet per frame (capture beside render, their difference, an actor close-up) and a
grading brief; a Haiku subagent writes one grade line per sheet; the scorer turns the lines into a
readout, compares it with an earlier one, and on a calibrating run checks controls and planted
faults. The sheets carry no key: it is recomputed from the seed when scoring.
"""

from __future__ import annotations

import hashlib
import random
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from stunt_reel.bench.faults import ACTOR_LAYER, ALL_FAULTS
from stunt_reel.bench.planes import BenchError
from stunt_reel.bench.ssim import render_luma, stretch
from stunt_reel.parity_artifacts import tick_stem

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from pathlib import Path

    from numpy.typing import NDArray

    from stunt_reel.bench.planes import RenderTree
    from stunt_reel.parity_artifacts import Report

__all__ = [
    "Category",
    "FilmWindow",
    "Sheet",
    "Taxonomy",
    "add_example",
    "build_sheet",
    "idx_digest",
    "load_categories",
    "pick_ticks",
    "plan_sheets",
    "render_brief",
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


@dataclass(frozen=True)
class Category:
    """One kind of render error, as graders are shown it."""

    id: str
    definition: str
    examples: tuple[str, ...]


@dataclass(frozen=True)
class FilmWindow:
    """The film ticks a readout picks frames from; ``end`` is exclusive, ``None`` the film's end."""

    start: int
    end: int | None

    def holds(self, tick: int) -> bool:
        """Whether *tick* is in the window."""
        return tick >= self.start and (self.end is None or tick < self.end)


@dataclass(frozen=True)
class Taxonomy:
    """The categories file: categories in order, faults, film windows and ``min_change``."""

    categories: tuple[Category, ...]
    faults: dict[str, tuple[str, ...]]
    films: dict[str, FilmWindow]
    min_change: int
    #: SHA-256 of the ids and definitions graders see; examples and comments leave it unchanged.
    digest: str

    @property
    def ids(self) -> tuple[str, ...]:
        """The category ids, in file order."""
        return tuple(category.id for category in self.categories)


def load_categories(path: Path, examples_dir: Path | None = None) -> Taxonomy:
    """Read and check the categories file; examples must exist in *examples_dir*."""
    examples_dir = examples_dir or path.parent / "error-examples"
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as err:
        raise BenchError(f"{path}: {err}") from err
    categories: list[Category] = []
    for block in document.get("category", []):
        category = Category(
            id=str(block["id"]),
            definition=str(block["definition"]),
            examples=tuple(str(e) for e in block.get("examples", [])),
        )
        if category.id in {c.id for c in categories}:
            raise BenchError(f"{path}: category {category.id!r} is listed twice")
        for example in category.examples:
            if not (examples_dir / f"{example}.png").is_file():
                raise BenchError(
                    f"{path}: example {example!r} of {category.id!r} has no "
                    f"{examples_dir / f'{example}.png'}"
                )
        categories.append(category)
    ids = {c.id for c in categories}
    known_faults = {fault.key for fault in ALL_FAULTS}
    faults: dict[str, tuple[str, ...]] = {}
    for key, named in document.get("faults", {}).items():
        if key not in known_faults:
            raise BenchError(f"{path}: [faults] key {key!r} is not a fault in faults.py")
        for category_id in named:
            if category_id not in ids:
                raise BenchError(f"{path}: fault {key!r} names unknown category {category_id!r}")
        faults[key] = tuple(named)
    films = {
        name: FilmWindow(int(window["start"]), window.get("end"))
        for name, window in document.get("films", {}).items()
    }
    digest = hashlib.sha256(
        "\n".join(f"{c.id}\t{c.definition}" for c in categories).encode()
    ).hexdigest()
    return Taxonomy(
        categories=tuple(categories),
        faults=faults,
        films=films,
        min_change=int(document.get("readout", {}).get("min_change", 2)),
        digest=digest,
    )


_EXAMPLES_LINE = re.compile(r"^examples = \[(?P<names>.*)\]$")


def add_example(path: Path, category: str, name: str) -> None:
    """Add *name* to *category*'s ``examples`` by editing that one line; comments survive."""
    lines = path.read_text(encoding="utf-8").split("\n")
    start = next((i for i, line in enumerate(lines) if line == f'id = "{category}"'), None)
    if start is None:
        raise BenchError(f"{path}: no category {category!r}")
    for i in range(start + 1, len(lines)):
        if lines[i] == "[[category]]":
            break
        match = _EXAMPLES_LINE.match(lines[i])
        if match is None:
            continue
        names = [n.strip().strip('"') for n in match["names"].split(",") if n.strip()]
        if name in names:
            return
        names.append(name)
        lines[i] = "examples = [" + ", ".join(f'"{n}"' for n in names) + "]"
        path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        return
    raise BenchError(f"{path}: category {category!r} has no examples line")


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


_BRIEF = """\
# Brief: grade the render errors

You are comparing frames from *Stunt Island* (1992), a DOS game that replays filmed aircraft stunts. Each
image is one moment of a film shown two ways: **CAPTURE** (top left) is the original game's screen, and
**RENDER** (top right) is a reimplementation that should match it exactly. Below them: a **DIFFERENCE**
image (brighter = more different) and a **CLOSE-UP** of the aircraft area, capture left, render right.
The grey band at the bottom of each panel is the game's button bar, masked out: ignore it. Some RENDER
panels may match the capture closely; grade what you see, not what you expect.

Folder: `{sheet_dir}/`. `ids.txt` lists {count} image ids; each image is `<id>.png` in that folder.
Read only `ids.txt` and those images, in the listed order. Do not read any other file and do not
dispatch subagents.

## Categories

| Category | Definition |
|---|---|
{table}

## Grades

0 = absent; 1 = minor, seen only on a close look; 2 = clear; 3 = dominates the frame.

## Output

One line per image, in `ids.txt` order, every category present, then `| other:` and either `none` or
a few words on any error no category covers:

`<id> {example} | other: none`

Write the lines, and nothing else, to `{sheet_dir}/grades.txt`.
Your final message is only the number of lines written.
"""


def render_brief(taxonomy: Taxonomy, sheet_dir: Path, count: int) -> str:
    """The grader's whole instruction for the *count* sheets in *sheet_dir*."""
    return _BRIEF.format(
        sheet_dir=sheet_dir.as_posix(),
        count=count,
        table="\n".join(f"| `{c.id}` | {c.definition} |" for c in taxonomy.categories),
        example=" ".join(f"{i}=0" for i in taxonomy.ids),
    )


def idx_digest(render: Path, ticks: Sequence[int]) -> str:
    """SHA-256 over the render's index planes at *ticks*, so scoring sees the pictures graded."""
    digest = hashlib.sha256()
    for tick in sorted(ticks):
        digest.update((render / f"{tick_stem(tick)}.idx").read_bytes())
    return digest.hexdigest()
