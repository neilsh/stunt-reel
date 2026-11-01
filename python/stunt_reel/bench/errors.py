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
import json
import random
import re
import tomllib
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from stunt_reel.bench.faults import ACTOR_LAYER, ALL_FAULTS, plant
from stunt_reel.bench.planes import BenchError, RenderTree, load_capture
from stunt_reel.bench.ssim import render_luma, stretch
from stunt_reel.parity_artifacts import read_report

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from pathlib import Path

    from numpy.typing import NDArray

    from stunt_reel.parity_artifacts import Report

__all__ = [
    "Calibration",
    "Category",
    "CategoryReadout",
    "Change",
    "FilmWindow",
    "Readout",
    "Sheet",
    "SheetGrades",
    "Taxonomy",
    "add_example",
    "build_sheet",
    "calibrate",
    "compare",
    "load_categories",
    "make_run",
    "parse_grades",
    "pick_ticks",
    "plan_sheets",
    "planes_digest",
    "readout",
    "render_brief",
    "score_run",
    "sheet_id",
    "write_example",
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
panels may match the capture closely; grade what you see, not what you expect. Where the
DIFFERENCE panel is black the two panels are identical: grade every category 0.

Folder: `{sheet_dir}/`. `{ids_name}` lists {count} image ids; each image is `<id>.png` in that folder.
Read only `{ids_name}` and those images, in the listed order. Do not read any other file and do not
dispatch subagents.

## Categories

| Category | Definition |
|---|---|
{table}

## Grades

0 = absent; 1 = minor, seen only on a close look; 2 = clear; 3 = dominates the frame.

## Output

One line per image, in `{ids_name}` order, every category present, then `| other:` and either `none` or
a few words on any error no category covers:

`<id> {example} | other: none`

Write the lines, and nothing else, to `{sheet_dir}/{grades_name}`.
Your final message is only the number of lines written.
"""


def render_brief(
    taxonomy: Taxonomy,
    sheet_dir: Path,
    count: int,
    ids_name: str = "ids.txt",
    grades_name: str = "grades.txt",
) -> str:
    """The grader's whole instruction for the *count* sheets listed in *ids_name*."""
    return _BRIEF.format(
        sheet_dir=sheet_dir.as_posix(),
        count=count,
        ids_name=ids_name,
        grades_name=grades_name,
        table="\n".join(f"| `{c.id}` | {c.definition} |" for c in taxonomy.categories),
        example=" ".join(f"{i}=0" for i in taxonomy.ids),
    )


def planes_digest(render: Path, ticks: Sequence[int]) -> str:
    """SHA-256 over everything a sheet shows at *ticks*, so scoring sees the pictures graded.

    Per tick in order: the tick (u32 little-endian), its palette, its index plane and its
    layer plane, decoded from the store (ADR 0027). The picture is ``palette[index]``, so
    this covers it, and the digest does not change with the zstd version or level.
    """
    tree = RenderTree(render)
    digest = hashlib.sha256()
    for tick in sorted(ticks):
        frame = tree.stored(tick)
        digest.update(tick.to_bytes(4, "little"))
        digest.update(frame.palette)
        digest.update(frame.indices)
        digest.update(frame.layers)
    return digest.hexdigest()


#: A grade at or above this counts a frame as showing the error.
CLEAR = 2
#: A control is clean when every grade is at most this.
CLEAN = 1
_GRADE = re.compile(r"^(?P<name>[^=\s]+)=(?P<value>\S*)$")


@dataclass(frozen=True)
class SheetGrades:
    """One grade line: a grade or ``None`` (ungraded) per category, unknown names, the note."""

    grades: dict[str, int | None]
    unknown: dict[str, int]
    other: str


def parse_grades(text: str, taxonomy: Taxonomy) -> dict[str, SheetGrades]:
    """Grade lines per sheet id; tolerates code fences, backticks, CRLF and blank lines.

    Missing categories remain ungraded and unknown categories are retained. Raises
    ``BenchError`` for duplicate sheet ids, missing ids, or invalid grade tokens.
    """
    parsed: dict[str, SheetGrades] = {}
    for raw in text.splitlines():
        line = raw.strip().replace("`", "")
        if not line or raw.strip().startswith("```"):
            continue
        cells, _, other = line.partition("| other:")
        tokens = cells.replace("|", " ").split()
        if not tokens or "=" in tokens[0]:
            raise BenchError(f"grade line has no sheet id: {raw.strip()!r}")
        sheet, values = tokens[0].removesuffix(":").removesuffix(".png"), tokens[1:]
        if sheet in parsed:
            raise BenchError(f"sheet {sheet} is graded twice")
        grades: dict[str, int | None] = dict.fromkeys(taxonomy.ids)
        unknown: dict[str, int] = {}
        for token in values:
            match = _GRADE.match(token)
            if match is None or match["value"] not in ("0", "1", "2", "3"):
                raise BenchError(f"{token!r} is not <category>=<0-3> in {raw.strip()!r}")
            name, value = match["name"], int(match["value"])
            if name in grades:
                grades[name] = value
            else:
                unknown[name] = value
        parsed[sheet] = SheetGrades(grades, unknown, other.strip())
    return parsed


def _note(grades: SheetGrades | None) -> str:
    """The ``other`` note, or empty when it says nothing."""
    if grades is None or grades.other.lower() in ("", "none"):
        return ""
    return grades.other


@dataclass(frozen=True)
class CategoryReadout:
    """One category over a run's real frames."""

    category: str
    ticks_2plus: tuple[int, ...]
    mean: float | None
    ungraded: int


@dataclass(frozen=True)
class Readout:
    """What the grader saw on a run's real frames, and which render and categories it graded."""

    film: str
    ticks: tuple[int, ...]
    categories_digest: str
    render_digest: str
    categories: tuple[CategoryReadout, ...]
    other: dict[int, str]
    missing: int
    unknown: tuple[str, ...]
    #: Sheets the two passes disagreed on, scored from the tie-break (0 for a single pass).
    disputed: int = 0

    def to_json(self) -> dict[str, Any]:
        """The ``readout.json`` document."""
        document = asdict(self)
        document["other"] = {str(tick): note for tick, note in self.other.items()}
        return document

    @classmethod
    def from_json(cls, doc: dict[str, Any]) -> Readout:
        """Read a ``readout.json`` document."""
        try:
            return cls(
                film=str(doc["film"]),
                ticks=tuple(int(t) for t in doc["ticks"]),
                categories_digest=str(doc["categories_digest"]),
                render_digest=str(doc["render_digest"]),
                categories=tuple(
                    CategoryReadout(
                        category=str(c["category"]),
                        ticks_2plus=tuple(int(t) for t in c["ticks_2plus"]),
                        mean=None if c["mean"] is None else float(c["mean"]),
                        ungraded=int(c["ungraded"]),
                    )
                    for c in doc["categories"]
                ),
                other={int(tick): str(note) for tick, note in doc["other"].items()},
                missing=int(doc["missing"]),
                unknown=tuple(str(u) for u in doc["unknown"]),
                disputed=int(doc.get("disputed", 0)),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise BenchError(f"not a readout document: {err}") from err


def readout(
    grades: dict[str, SheetGrades],
    sheets: Sequence[Sheet],
    ids: Sequence[str],
    film: str,
    categories_digest: str,
    render_digest: str,
) -> Readout:
    """Per category, the real frames graded 2 or more and the mean grade."""
    real = sorted((s for s in sheets if s.kind == "real"), key=lambda s: s.tick)
    graded = [(s.tick, grades[s.id]) for s in real if s.id in grades]
    categories = []
    for name in ids:
        values = [(tick, g.grades.get(name)) for tick, g in graded]
        known = [v for _, v in values if v is not None]
        categories.append(
            CategoryReadout(
                category=name,
                ticks_2plus=tuple(t for t, v in values if v is not None and v >= CLEAR),
                mean=sum(known) / len(known) if known else None,
                ungraded=sum(1 for _, v in values if v is None),
            )
        )
    return Readout(
        film=film,
        ticks=tuple(s.tick for s in real),
        categories_digest=categories_digest,
        render_digest=render_digest,
        categories=tuple(categories),
        other={tick: _note(g) for tick, g in graded if _note(g)},
        missing=len(real) - len(graded),
        unknown=tuple(sorted({name for _, g in graded for name in g.unknown})),
    )


@dataclass(frozen=True)
class Change:
    """A category whose count of frames graded 2+ moved between two readouts."""

    category: str
    before: int
    after: int
    added: tuple[int, ...]
    removed: tuple[int, ...]


def compare(before: Readout, after: Readout, min_change: int) -> list[Change]:
    """Categories whose 2+ count moved by at least *min_change*.

    Raises ``BenchError`` if category digests or ticks differ, or either readout has missing sheets.
    """
    if before.categories_digest != after.categories_digest:
        raise BenchError(
            f"readouts graded different categories ({before.categories_digest} before, "
            f"{after.categories_digest} now); calibrate and start a new series"
        )
    if before.ticks != after.ticks:
        only_before = sorted(set(before.ticks) - set(after.ticks))
        only_after = sorted(set(after.ticks) - set(before.ticks))
        raise BenchError(
            f"readouts graded different ticks (only before: {only_before}, only now: {only_after})"
        )
    if before.missing or after.missing:
        raise BenchError(
            f"a readout is missing sheets ({before.missing} before, {after.missing} now); "
            "grade the missing sheets before comparing"
        )
    earlier = {c.category: set(c.ticks_2plus) for c in before.categories}
    changes = []
    for category in after.categories:
        was, now = earlier.get(category.category, set()), set(category.ticks_2plus)
        if abs(len(now) - len(was)) >= min_change:
            changes.append(
                Change(
                    category.category,
                    len(was),
                    len(now),
                    tuple(sorted(now - was)),
                    tuple(sorted(was - now)),
                )
            )
    return changes


@dataclass(frozen=True)
class Calibration:
    """Controls graded clean, and per fault key (detected, sheets)."""

    controls_clean: int
    controls: int
    faults: dict[str, tuple[int, int]]
    passes: bool
    #: No ``actors_removed`` sheet was planted, so the bar tested nothing; ``passes`` is False.
    inconclusive: bool = False


def _at_least(share: tuple[int, int], count: int) -> int:
    """``ceil(share * count)``, in integers: the probe's bars scaled to *count* sheets."""
    numerator, denominator = share
    return -(-numerator * count // denominator)


#: Pass bar from the probe: actors removed caught on 5 of 6. Controls are reported but not gated:
#: a recapture is pixel-identical to the reference, so a control sheet's difference panel is black,
#: which no real sheet's is, and Haiku's misreads there say little about real frames.
ACTORS_BAR = (5, 6)


def _detected(planted: SheetGrades | None, real: SheetGrades | None, named: Sequence[str]) -> bool:
    if planted is None or real is None:
        return False
    for name in named:
        value, base = planted.grades.get(name), None if real is None else real.grades.get(name)
        if value is not None and base is not None and value > base:
            return True
    note = _note(planted)
    return bool(note) and note != _note(real)


def calibrate(
    grades: dict[str, SheetGrades], sheets: Sequence[Sheet], taxonomy: Taxonomy
) -> Calibration:
    """Controls graded clean (reported) and planted faults caught (gated by ``ACTORS_BAR``)."""
    real = {s.tick: grades.get(s.id) for s in sheets if s.kind == "real"}
    controls = [s for s in sheets if s.kind == "control"]
    clean = 0
    for sheet in controls:
        graded = grades.get(sheet.id)
        values = [] if graded is None else [graded.grades.get(n) for n in taxonomy.ids]
        if graded is not None and all(v is not None and v <= CLEAN for v in values):
            clean += 1
    faults: dict[str, tuple[int, int]] = {}
    for key, named in taxonomy.faults.items():
        planted = [s for s in sheets if s.kind == "planted" and s.fault == key]
        detected = sum(_detected(grades.get(s.id), real.get(s.tick), named) for s in planted)
        faults[key] = (detected, len(planted))
    actors, actor_sheets = faults.get("actors_removed", (0, 0))
    inconclusive = actor_sheets == 0
    passes = not inconclusive and actors >= _at_least(ACTORS_BAR, actor_sheets)
    return Calibration(clean, len(controls), faults, passes, inconclusive)


RUN_FILE = "run.json"
GRADES_FILE = "grades.txt"
SECOND_FILE = "grades-2.txt"
TIEBREAK_IDS = "ids-tiebreak.txt"
TIEBREAK_FILE = "grades-tiebreak.txt"
READOUT_FILE = "readout.json"


def disputed(
    first: dict[str, SheetGrades], second: dict[str, SheetGrades], ids: Sequence[str]
) -> list[str]:
    """The *ids*, in order, that one pass lacks or on which the two passes disagree whether
    some category is clear (graded :data:`CLEAR` or more)."""
    out = []
    for sheet in ids:
        a, b = first.get(sheet), second.get(sheet)
        if (
            a is None
            or b is None
            or any(
                ((a.grades.get(n) or 0) >= CLEAR) != ((b.grades.get(n) or 0) >= CLEAR)
                for n in a.grades.keys() | b.grades.keys()
            )
        ):
            out.append(sheet)
    return out


def merge_grades(
    first: dict[str, SheetGrades],
    second: dict[str, SheetGrades],
    tiebreak: dict[str, SheetGrades],
    ids: Sequence[str],
) -> dict[str, SheetGrades]:
    """The first pass, with each disputed sheet graded by *tiebreak*."""
    merged = dict(first)
    for sheet in disputed(first, second, ids):
        if sheet not in tiebreak:
            raise BenchError(f"no tie-break grade for {sheet}")
        merged[sheet] = tiebreak[sheet]
    return merged


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def make_run(
    film: str,
    capture: Path,
    recapture: Path | None,
    render: Path,
    report: Path,
    out: Path,
    taxonomy_path: Path,
    seed: int,
    revision: str,
) -> int:
    """Write the sheets, ``ids.txt``, ``brief.md`` and ``run.json``; returns the sheets written.

    A *recapture* makes it a calibrating run: controls show the recapture in the render's place,
    and each fault in ``[faults]`` is planted on up to :data:`FAULT_FRAMES` frames.
    Existing PNG sheets, grades, tie-break files and readout in *out* are removed first.
    Raises ``BenchError`` if no eligible tick is available; input and file errors propagate.
    """
    taxonomy = load_categories(taxonomy_path)
    # A film with no [films] entry is graded over its whole length.
    window = taxonomy.films.get(film, FilmWindow(0, None))
    captured = load_capture(capture)
    recaptured = load_capture(recapture) if recapture is not None else None
    tree = RenderTree(render)
    held = set(captured) & set(tree.ticks())
    if recaptured is not None:
        held &= set(recaptured)
    ticks = pick_ticks(read_report(report), held, window)
    if not ticks:
        end = "the end" if window.end is None else window.end
        raise BenchError(
            f"no scored, unfaded tick of {film} from {window.start} to {end} is both captured "
            "and rendered"
        )
    sheets = plan_sheets(ticks, tree, taxonomy, seed, calibrate=recaptured is not None)
    out.mkdir(parents=True, exist_ok=True)
    stale_files = [GRADES_FILE, SECOND_FILE, TIEBREAK_IDS, TIEBREAK_FILE, READOUT_FILE]
    for stale in [*out.glob("*.png"), *(out / name for name in stale_files)]:
        stale.unlink(missing_ok=True)
    faults = {fault.key: fault for fault in ALL_FAULTS}
    written: list[str] = []
    for sheet in sheets:
        planes = tree.load(sheet.tick)
        frame = captured[sheet.tick]
        if sheet.kind == "control" and recaptured is not None:
            other = recaptured[sheet.tick]
            shown = other.palette[other.idx]
        elif sheet.kind == "planted" and sheet.fault is not None:
            planted = plant(faults[sheet.fault], sheet.tick, tree, seed)
            if planted is None:
                continue
            shown = planted.rgb
        else:
            shown = planes.rgb
        build_sheet(frame.palette[frame.idx], shown, planes.layer).save(out / f"{sheet.id}.png")
        written.append(sheet.id)
    random.Random(seed).shuffle(written)  # noqa: S311 - not security
    _write_text(out / "ids.txt", "".join(f"{i}\n" for i in written))
    _write_text(out / "brief.md", render_brief(taxonomy, out.resolve(), len(written)))
    _write_text(
        out / "brief-2.md",
        render_brief(taxonomy, out.resolve(), len(written), grades_name=SECOND_FILE),
    )
    run = {
        "film": film,
        "ticks": ticks,
        "seed": seed,
        "calibrate": recaptured is not None,
        "revision": revision,
        "categories_digest": taxonomy.digest,
        "render_digest": planes_digest(render, ticks),
    }
    _write_text(out / RUN_FILE, json.dumps(run, indent=2) + "\n")
    return len(written)


def _read_grades(path: Path, taxonomy: Taxonomy, sheets: Sequence[Sheet]) -> dict[str, SheetGrades]:
    grades = parse_grades(path.read_text(encoding="utf-8"), taxonomy)
    stray = sorted(set(grades) - {s.id for s in sheets})
    if stray:
        raise BenchError(f"{path} grades sheets this run does not hold: {stray}")
    return grades


def write_disputes(out: Path, taxonomy_path: Path) -> int:
    """Write ``ids-tiebreak.txt`` and ``brief-tiebreak.md`` for the sheets the two passes in *out*
    disagree on; returns how many (with 0, scoring needs no tie-break)."""
    taxonomy = load_categories(taxonomy_path)
    try:
        ids = (out / "ids.txt").read_text(encoding="utf-8").split()
        first = parse_grades((out / GRADES_FILE).read_text(encoding="utf-8"), taxonomy)
        second = parse_grades((out / SECOND_FILE).read_text(encoding="utf-8"), taxonomy)
    except FileNotFoundError as err:
        raise BenchError(f"{err.filename} is missing; grade both passes first") from err
    disputes = disputed(first, second, ids)
    (out / TIEBREAK_FILE).unlink(missing_ok=True)
    _write_text(out / TIEBREAK_IDS, "".join(f"{i}\n" for i in disputes))
    brief = render_brief(taxonomy, out.resolve(), len(disputes), TIEBREAK_IDS, TIEBREAK_FILE)
    _write_text(out / "brief-tiebreak.md", brief)
    return len(disputes)


def score_run(
    out: Path, render: Path, taxonomy_path: Path, against: Path | None
) -> tuple[Readout, list[Change] | None, Calibration | None]:
    """Score ``grades.txt`` in *out* and write ``readout.json``.

    With a second pass (``grades-2.txt``), each sheet the passes disagree on is scored from
    ``grades-tiebreak.txt`` (see :func:`write_disputes`) and the rest from the first pass.
    Returns the readout, optional comparison, and optional calibration. Raises ``BenchError``
    for changed categories or render, invalid grades, missing tie-breaks, or incompatible
    comparisons. The readout is written before the optional comparison is checked.
    """
    try:
        run = json.loads((out / RUN_FILE).read_text(encoding="utf-8"))
        (out / GRADES_FILE).stat()
    except FileNotFoundError as err:
        raise BenchError(f"{err.filename} is missing; run errors-make and grade first") from err
    taxonomy = load_categories(taxonomy_path)
    if run["categories_digest"] != taxonomy.digest:
        raise BenchError(
            f"{taxonomy_path} changed since errors-make (categories {run['categories_digest']} "
            f"then, {taxonomy.digest} now); run errors-make again"
        )
    ticks = [int(t) for t in run["ticks"]]
    render_digest = planes_digest(render, ticks)
    if run["render_digest"] != render_digest:
        raise BenchError(
            f"{render} changed since errors-make (render {run['render_digest']} then, "
            f"{render_digest} now); run errors-make again"
        )
    planned = plan_sheets(ticks, RenderTree(render), taxonomy, int(run["seed"]), run["calibrate"])
    # make_run skips a planted sheet plant() declines; only the sheets in ids.txt were graded.
    written = set((out / "ids.txt").read_text(encoding="utf-8").split())
    sheets = [s for s in planned if s.id in written]
    grades = _read_grades(out / GRADES_FILE, taxonomy, sheets)
    disputes = 0
    if (out / SECOND_FILE).is_file():
        second = _read_grades(out / SECOND_FILE, taxonomy, sheets)
        ids = (out / "ids.txt").read_text(encoding="utf-8").split()
        disputes = len(disputed(grades, second, ids))
        tiebreak: dict[str, SheetGrades] = {}
        if disputes:
            if not (out / TIEBREAK_FILE).is_file():
                raise BenchError(
                    f"the two passes disagree on {disputes} sheets; run errors-disputes and "
                    "grade brief-tiebreak.md"
                )
            tiebreak = _read_grades(out / TIEBREAK_FILE, taxonomy, sheets)
        grades = merge_grades(grades, second, tiebreak, ids)
    earlier = None
    if against is not None:
        if against.resolve() == (out / READOUT_FILE).resolve():
            raise BenchError(
                f"--against {against} is this run's own readout.json; copy the previous readout "
                "aside before errors-make and compare with the copy"
            )
        try:
            document = json.loads(against.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            raise BenchError(f"{against} is not a readout document: {err}") from err
        earlier = Readout.from_json(document)
    result = readout(grades, sheets, taxonomy.ids, str(run["film"]), taxonomy.digest, render_digest)
    result = replace(result, disputed=disputes)
    _write_text(out / READOUT_FILE, json.dumps(result.to_json(), indent=2) + "\n")
    changes = None if earlier is None else compare(earlier, result, taxonomy.min_change)
    calibration = calibrate(grades, sheets, taxonomy) if run["calibrate"] else None
    return result, changes, calibration


def write_example(
    film: str, tick: int, category: str, capture: Path, render: Path, taxonomy_path: Path
) -> Path:
    """Write *tick*'s sheet into ``error-examples/`` unless it is there, and name it in *category*."""
    taxonomy = load_categories(taxonomy_path)
    if category not in taxonomy.ids:
        raise BenchError(f"{taxonomy_path}: no category {category!r}")
    name = f"{film}-{tick:04d}"
    path = taxonomy_path.parent / "error-examples" / f"{name}.png"
    if not path.is_file():
        frame = load_capture(capture).get(tick)
        if frame is None:
            raise BenchError(f"{capture} holds no frame at tick {tick}")
        planes = RenderTree(render).load(tick)
        path.parent.mkdir(parents=True, exist_ok=True)
        build_sheet(frame.palette[frame.idx], planes.rgb, planes.layer).save(path)
    add_example(taxonomy_path, category, name)
    return path
