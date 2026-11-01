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
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stunt_reel.bench.faults import ALL_FAULTS
from stunt_reel.bench.planes import BenchError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "Category",
    "FilmWindow",
    "Taxonomy",
    "add_example",
    "load_categories",
]


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
