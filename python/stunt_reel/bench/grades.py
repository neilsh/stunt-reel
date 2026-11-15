"""The grading brief a vision model reads, and the grade lines it writes.

:func:`render_brief` is one run's whole instruction; :func:`parse_grades` turns the grader's
lines into a :class:`SheetGrades` per sheet id; :func:`planes_digest` digests the planes the
sheets show, so scoring can tell it graded the pictures it wrote.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stunt_reel.bench.planes import BenchError, RenderTree

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from stunt_reel.bench.taxonomy import Taxonomy

__all__ = [
    "CLEAN",
    "CLEAR",
    "SheetGrades",
    "parse_grades",
    "planes_digest",
    "render_brief",
]


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
