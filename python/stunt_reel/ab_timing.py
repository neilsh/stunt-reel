"""Interleaved A/B timing of a headless render: the schedule, one run, the CSV and the summary.

``mise run ab`` (``python/scripts/ab.py``) times *variants* of one headless ``stuntreel`` render:
two binaries, or one binary under named environment variables. Variants alternate inside each
round so a machine's drift lands on every variant alike, and each run's row records what a
reviewer needs to recompute a figure: the loop and wall time, the four store hashes and the
adapter ``render.json`` names. The CSV is the raw data (committed beside the journal entry that
cites it); :func:`summarize` reads rows, so a committed CSV can be summarised again.

The loop time is ``--report-timing``'s ``loop`` line
(``docs/howto/time-a-headless-render.md``); the wall time is this module's stopwatch around the
whole process. Nothing here prints or chooses an exit code (ADR 0010).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shlex
import statistics
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from stunt_reel import dataroot, process_tree
from stunt_reel.hashing import file_sha256
from stunt_reel.parity_artifacts import RENDER_DOCUMENT
from stunt_reel.parity_pipeline import RENDER_FLAGS, SIDATA

__all__ = [
    "BINARY_KEY",
    "COLUMNS",
    "MODES",
    "PLANES",
    "BusyError",
    "Cell",
    "Row",
    "RunError",
    "Variant",
    "busy_processes",
    "environment_for",
    "parse_loop_ms",
    "parse_variant",
    "read_csv",
    "render_argv",
    "round_order",
    "run_once",
    "summarize",
    "write_csv",
]

#: The word in a ``--variant`` that names the variant's own binary, not an environment variable.
BINARY_KEY = "binary"
#: How a round's order moves: ``alternate`` runs the variants forward in even rounds and reversed
#: in odd ones; ``rotate`` starts each round one variant later. They agree for two variants.
MODES = ("alternate", "rotate")
#: The store planes hashed per run, as the CSV's ``<plane>_sha256`` columns.
PLANES = ("frames", "layers", "palettes", "shapes")
COLUMNS = (
    "cell",
    "round",
    "position",
    "variant",
    "loop_ms",
    "wall_ms",
    *(f"{plane}_sha256" for plane in PLANES),
    "adapter",
    "adapter_class",
)
#: What counts as a competing process, by image name without ``.exe``, case-blind.
_BUSY = frozenset({"stuntreel", "cargo", "rustc"})
_LOOP_LINE = re.compile(r"^\[stuntreel\] timing loop (\d+(?:\.\d+)?) ms\s*$", re.MULTILINE)
#: Wall-clock seconds one render may take before its process tree is ended.
RUN_TIMEOUT_S = 3600.0


class BusyError(RuntimeError):
    """A competing process runs; the message names it."""


class RunError(RuntimeError):
    """A render that failed, printed no loop time, or landed on another adapter than asked."""


@dataclass(frozen=True)
class Variant:
    """One side of the comparison: a name, its own binary (or the default), its environment."""

    name: str
    binary: Path | None = None
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Cell:
    """One measured cell: a tick span on one adapter, run for every variant in every round."""

    span: str
    adapter: str

    @property
    def name(self) -> str:
        """``<adapter>-<first>-<last>``, the CSV's ``cell`` value."""
        first, _, last = self.span.partition("..=")
        return f"{self.adapter}-{first}-{last}"


@dataclass(frozen=True)
class Row:
    """One run, as one CSV row."""

    cell: str
    round: int
    position: int
    variant: str
    loop_ms: float
    wall_ms: float
    sha256: Mapping[str, str]
    adapter: str
    adapter_class: str

    def fields(self) -> list[str]:
        """The row's values in :data:`COLUMNS` order."""
        return [
            self.cell,
            str(self.round),
            str(self.position),
            self.variant,
            f"{self.loop_ms:.3f}",
            f"{self.wall_ms:.3f}",
            *(self.sha256[plane] for plane in PLANES),
            self.adapter,
            self.adapter_class,
        ]


def parse_variant(text: str) -> Variant:
    """``NAME [binary=PATH] [VAR=VALUE ...]``: a variant's name, binary and environment.

    Raises ``ValueError`` for an empty text, a word that is neither the name (the first) nor a
    ``KEY=VALUE``, or a repeated key.
    """
    words = shlex.split(text, posix=False)
    if not words or "=" in words[0]:
        raise ValueError(f"{text!r} does not start with a variant name")
    binary: Path | None = None
    env: dict[str, str] = {}
    for word in words[1:]:
        key, equals, value = word.partition("=")
        if not equals or not key or not value:
            raise ValueError(f"{word!r} in {text!r} is not KEY=VALUE")
        value = value.strip("\"'")
        if key == BINARY_KEY:
            if binary is not None:
                raise ValueError(f"{BINARY_KEY} is given twice in {text!r}")
            binary = Path(value)
        elif key in env:
            raise ValueError(f"{key} is given twice in {text!r}")
        else:
            env[key] = value
    return Variant(words[0], binary, env)


def round_order(count: int, index: int, mode: str) -> list[int]:
    """The variants' positions (0-based) in round *index* of a run over *count* variants.

    ``alternate``: forward in even rounds, reversed in odd. ``rotate``: forward, starting
    ``index`` places later (modulo *count*). Raises ``ValueError`` for another mode.
    """
    forward = list(range(count))
    if mode == "alternate":
        return forward if index % 2 == 0 else forward[::-1]
    if mode == "rotate":
        shift = index % count if count else 0
        return forward[shift:] + forward[:shift]
    raise ValueError(f"unknown order {mode!r}; one of {', '.join(MODES)}")


def busy_processes(names: Iterable[str]) -> list[str]:
    """The competing processes among the image *names*: ``stuntreel``, ``cargo``, ``rustc``."""
    return sorted({n for n in names if n.lower().removesuffix(".exe") in _BUSY})


def parse_loop_ms(output: str) -> float:
    """The loop time of a ``--report-timing`` run's output, in ms.

    Raises ``ValueError`` when the output has no ``loop`` line, or several.
    """
    found = _LOOP_LINE.findall(output)
    if len(found) != 1:
        raise ValueError(f"expected one 'timing loop' line, found {len(found)}")
    return float(found[0])


def render_argv(
    binary: Path, film: Path, archive: Path, root: Path, cell: Cell, out_dir: Path
) -> list[str]:
    """The headless render command for *cell*: ``parity_pipeline``'s flags, ``--report-timing``."""
    first, _, last = cell.span.partition("..=")
    argv = [
        str(binary),
        "--headless",
        str(film),
        "--all",
        str(archive),
        "--tick-range",
        f"{first}..={last}",
        "--sidata",
        str(dataroot.corpus_of(root) / SIDATA),
        "--out-dir",
        str(out_dir),
        *RENDER_FLAGS,
        "--report-timing",
    ]
    if cell.adapter == "lavapipe":
        argv.append("--software-only")
    return argv


Runner = Callable[[Sequence[str], Mapping[str, str], float], tuple[int, str]]


def _process_runner(argv: Sequence[str], env: Mapping[str, str], timeout: float) -> tuple[int, str]:
    return process_tree.run(argv, timeout, cwd=dataroot.REPO_ROOT, env=env)


def run_once(
    argv: Sequence[str],
    env: Mapping[str, str],
    out_dir: Path,
    *,
    expect_class: str,
    run: Runner = _process_runner,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[float, float, dict[str, str], str, str]:
    """One render: ``(loop ms, wall ms, plane hashes, adapter name, adapter class)``.

    *expect_class* is ``cpu`` or ``hardware``. Raises :class:`RunError` for a non-zero exit, a
    missing loop line or store plane, or an adapter of another class than asked for.
    """
    started = clock()
    code, output = run(argv, env, RUN_TIMEOUT_S)
    wall_ms = (clock() - started) * 1000.0
    name = Path(argv[0]).name
    if code != 0:
        tail = "\n".join(output.strip().splitlines()[-6:])
        raise RunError(f"{name} exited {code}: {tail}")
    try:
        loop_ms = parse_loop_ms(output)
        record = json.loads((out_dir / RENDER_DOCUMENT).read_text(encoding="utf-8"))
        adapter = record["adapter"]
        sha256 = {plane: file_sha256(out_dir / f"{plane}.zst") for plane in PLANES}
        adapter_name, adapter_class = str(adapter["name"]), str(adapter["class"]).lower()
    except (ValueError, OSError, KeyError, TypeError) as err:
        raise RunError(f"{name} left no usable record in {out_dir}: {err}") from err
    if adapter_class != expect_class:
        raise RunError(f"asked for a {expect_class} adapter, the render used {adapter_name!r}")
    return loop_ms, wall_ms, sha256, adapter_name, adapter_class


def write_csv(rows: Iterable[Row]) -> str:
    """*rows* as the CSV text, a header line first."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(row.fields() for row in rows)
    return out.getvalue()


def read_csv(text: str) -> list[Row]:
    """The rows of a CSV that :func:`write_csv` wrote. Raises ``ValueError`` for another header."""
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError(f"not an ab CSV: header is {reader.fieldnames}, want {list(COLUMNS)}")
    return [
        Row(
            cell=line["cell"],
            round=int(line["round"]),
            position=int(line["position"]),
            variant=line["variant"],
            loop_ms=float(line["loop_ms"]),
            wall_ms=float(line["wall_ms"]),
            sha256={plane: line[f"{plane}_sha256"] for plane in PLANES},
            adapter=line["adapter"],
            adapter_class=line["adapter_class"],
        )
        for line in reader
    ]


def _fmt(value: float) -> str:
    return f"{value:.1f}".removesuffix(".0")


def _change(base: float, other: float) -> float:
    return (other - base) / base * 100.0


def summarize(rows: Sequence[Row]) -> str:
    """A Markdown summary per cell: each variant's loop median, minimum and range, its change
    against the cell's first variant, and the rounds it was faster in.

    "Faster" is a strictly smaller loop time than the first variant's in the same round. The
    ``stores`` column says which planes hash like the first variant's, and ``varies`` when a
    variant's own runs hash differently from each other.
    """
    cells = list(dict.fromkeys(row.cell for row in rows))
    parts: list[str] = []
    for cell in cells:
        mine = [row for row in rows if row.cell == cell]
        variants = list(dict.fromkeys(row.variant for row in mine))
        by_variant = {
            v: sorted((r for r in mine if r.variant == v), key=lambda r: r.round) for v in variants
        }
        base = by_variant[variants[0]]
        base_loop = {r.round: r.loop_ms for r in base}
        base_median = statistics.median(base_loop.values())
        parts += [
            f"### {cell}",
            "",
            (
                f"Adapter: {', '.join(sorted({r.adapter for r in mine}))}. "
                f"Rounds: {len({r.round for r in mine})}. Baseline: `{variants[0]}`."
            ),
            "",
            "| Variant | Loop ms by round | Median | Min | Range | Change | Faster | Wall median | Stores |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for name in variants:
            runs = by_variant[name]
            loops = [r.loop_ms for r in runs]
            median = statistics.median(loops)
            wall = statistics.median(r.wall_ms for r in runs)
            if runs is base:
                change, faster = "baseline", "-"
            else:
                paired = [r for r in runs if r.round in base_loop]
                wins = sum(r.loop_ms < base_loop[r.round] for r in paired)
                change = f"{_change(base_median, median):+.1f}%"
                faster = f"{wins} of {len(paired)}"
            parts.append(
                f"| {name} | {', '.join(_fmt(x) for x in loops)} | {_fmt(median)} | {_fmt(min(loops))} "
                f"| {_fmt(min(loops))}..{_fmt(max(loops))} | {change} | {faster} "
                f"| {_fmt(wall)} | {_stores(runs, base)} |"
            )
        parts.append("")
    return "\n".join(parts)


def _stores(runs: Sequence[Row], base: Sequence[Row]) -> str:
    """``same`` when every plane hashes like the baseline's; else the planes that differ."""
    if any(len({r.sha256[p] for r in runs}) > 1 for p in PLANES):
        return "varies"
    differing = [p for p in PLANES if runs[0].sha256[p] != base[0].sha256[p]]
    if any(len({r.sha256[p] for r in base}) > 1 for p in PLANES):
        return "baseline varies"
    return "same" if not differing else "differ: " + ", ".join(differing)


def environment_for(variant: Variant, adapter: str, icd: Path | None) -> dict[str, str]:
    """The environment of a run: this process's, the adapter's driver file, the variant's."""
    env = dict(os.environ)
    env.pop("VK_DRIVER_FILES", None)
    if adapter == "lavapipe":
        if icd is None:
            raise ValueError("a lavapipe cell needs --icd (the ICD manifest of a Mesa build)")
        env["VK_DRIVER_FILES"] = str(icd)
    env.update(variant.env)
    return env
