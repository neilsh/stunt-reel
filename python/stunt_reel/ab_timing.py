"""Interleaved A/B timing of a headless render: the schedule, one run, the CSV and the summary.

``mise run ab`` (``python/scripts/ab.py``) times *variants* of one headless ``stuntreel`` render:
two binaries, or one binary under named environment variables. Variants alternate inside each
round so a machine's drift lands on every variant alike, and each run's row records what a
reviewer needs to recompute a figure: the loop and wall time, the four store hashes, the
adapter ``render.json`` names, and the share of the machine's CPUs other processes used meanwhile
(:class:`OtherLoad`), since that load slows a lavapipe render (#1018). The CSV is the raw data (committed beside the journal entry that
cites it); :func:`summarize` reads rows, so a committed CSV can be summarised again.

The loop time is ``--report-timing``'s ``loop`` line
(``docs/howto/time-a-headless-render.md``); the wall time is this module's stopwatch around the
whole process. Nothing here prints or chooses an exit code (ADR 0010).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import shlex
import statistics
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Self

import psutil

from stunt_reel import dataroot, process_tree
from stunt_reel.hashing import file_sha256
from stunt_reel.parity_artifacts import RENDER_DOCUMENT
from stunt_reel.parity_pipeline import RENDER_FLAGS, SIDATA

__all__ = [
    "BINARY_KEY",
    "COLUMNS",
    "MAX_LOAD",
    "MODES",
    "PLANES",
    "BusyError",
    "Cell",
    "CpuSample",
    "OtherLoad",
    "Row",
    "RunError",
    "Timing",
    "Variant",
    "busy_processes",
    "environment_for",
    "machine_load",
    "other_share",
    "parse_loop_ms",
    "parse_variant",
    "read_csv",
    "render_argv",
    "round_order",
    "run_once",
    "summarize",
    "wait_for_quiet",
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
    "other_load",
)
#: The columns of a CSV written before ``other_load`` was recorded, read as an unknown load.
_COLUMNS_BEFORE_LOAD = COLUMNS[:-1]
#: The default largest share of all logical CPUs other processes may use before and during a run.
MAX_LOAD = 0.10
#: Seconds over which :func:`machine_load` measures the machine before each run.
QUIET_WINDOW_S = 2.0
#: Seconds a run waits for the machine to fall to the load bar before the timing stops.
QUIET_WAIT_S = 600.0
#: Seconds between the samples :class:`OtherLoad` takes while a render runs.
SAMPLE_S = 0.25
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
    #: The share of all logical CPUs other processes used during the run; NaN when unknown.
    other_load: float = math.nan

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
            f"{self.other_load:.3f}",
        ]


class Timing(NamedTuple):
    """What one render measured: :func:`run_once`'s result."""

    loop_ms: float
    wall_ms: float
    sha256: dict[str, str]
    adapter: str
    adapter_class: str
    other_load: float


class CpuSample(NamedTuple):
    """CPU seconds summed over every logical CPU at one moment: busy, in all, and the render's."""

    busy: float
    total: float
    own: float


def other_share(first: CpuSample, last: CpuSample) -> float:
    """The share of all logical CPUs that processes other than the render used between samples.

    NaN when no time passed between them; never below 0.
    """
    total = last.total - first.total
    if total <= 0:
        return math.nan
    return max(0.0, (last.busy - first.busy - (last.own - first.own)) / total)


class OtherLoad:
    """While its ``with`` block runs, samples the machine and process *pid* every :data:`SAMPLE_S`.

    :attr:`share` is :func:`other_share` from entry to the last sample taken while *pid* lived.
    Raises ``psutil.Error`` when *pid* is already gone.
    """

    def __init__(self, pid: int) -> None:
        self._process = psutil.Process(pid)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._first: CpuSample | None = None
        self._last: CpuSample | None = None

    def _sample(self) -> CpuSample | None:
        times = psutil.cpu_times()
        try:
            own = self._process.cpu_times()
        except psutil.Error:
            return None
        total = sum(times)
        return CpuSample(total - times.idle, total, own.user + own.system)

    def _loop(self) -> None:
        while not self._stop.wait(SAMPLE_S):
            if (sample := self._sample()) is not None:
                self._last = sample

    def __enter__(self) -> Self:
        self._first = self._sample()
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join()

    @property
    def share(self) -> float:
        """Other processes' share of all logical CPUs; NaN with fewer than two samples."""
        if self._first is None or self._last is None:
            return math.nan
        return other_share(self._first, self._last)


def machine_load(seconds: float) -> float:
    """The share of all logical CPUs busy over the next *seconds*, every process included."""
    return psutil.cpu_percent(interval=seconds) / 100.0


def wait_for_quiet(
    max_load: float,
    *,
    timeout: float = QUIET_WAIT_S,
    measure: Callable[[float], float] | None = None,
    window: float = QUIET_WINDOW_S,
) -> float:
    """Measure the machine in *window*-second spans until it is at most *max_load* busy.

    *measure* defaults to :func:`machine_load`. Returns the last load measured, above *max_load*
    once *timeout* seconds of spans have passed.
    """
    measure = measure or machine_load
    waited = 0.0
    while True:
        load = measure(window)
        waited += window
        if load <= max_load or waited >= timeout:
            return load


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


#: Runs a render from argv, env and timeout: ``(exit code, output, other processes' load)``.
Runner = Callable[[Sequence[str], Mapping[str, str], float], tuple[int, str, float]]


def _process_runner(
    argv: Sequence[str], env: Mapping[str, str], timeout: float
) -> tuple[int, str, float]:
    with process_tree.spawn(argv, cwd=dataroot.REPO_ROOT, env=env) as proc:
        try:
            meter = OtherLoad(proc.pid)
        except psutil.Error:
            return (*process_tree.wait(proc, timeout), math.nan)
        with meter:
            code, output = process_tree.wait(proc, timeout)
        return code, output, meter.share


def run_once(
    argv: Sequence[str],
    env: Mapping[str, str],
    out_dir: Path,
    *,
    expect_class: str,
    run: Runner = _process_runner,
    clock: Callable[[], float] = time.perf_counter,
) -> Timing:
    """One render's :class:`Timing`.

    *expect_class* is ``cpu`` or ``hardware``. Raises :class:`RunError` for a non-zero exit, a
    missing loop line or store plane, or an adapter of another class than asked for.
    """
    started = clock()
    code, output, other_load = run(argv, env, RUN_TIMEOUT_S)
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
    return Timing(loop_ms, wall_ms, sha256, adapter_name, adapter_class, other_load)


def write_csv(rows: Iterable[Row]) -> str:
    """*rows* as the CSV text, a header line first."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(row.fields() for row in rows)
    return out.getvalue()


def read_csv(text: str) -> list[Row]:
    """The rows of a CSV that :func:`write_csv` wrote, an older one without ``other_load`` too.

    Raises ``ValueError`` for another header.
    """
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) not in (COLUMNS, _COLUMNS_BEFORE_LOAD):
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
            other_load=float(line.get("other_load", "nan")),
        )
        for line in reader
    ]


def _fmt(value: float) -> str:
    return f"{value:.1f}".removesuffix(".0")


def _load(runs: Sequence[Row]) -> str:
    """The largest other-process load of *runs* as a percentage; ``-`` when none was recorded."""
    known = [r.other_load for r in runs if not math.isnan(r.other_load)]
    return f"{max(known) * 100:.0f}%" if known else "-"


def _change(base: float, other: float) -> float:
    return (other - base) / base * 100.0


def summarize(rows: Sequence[Row]) -> str:
    """A Markdown summary per cell: each variant's loop median, minimum and range, its change
    against the cell's first variant, the rounds it was faster in, and the largest share of the
    CPUs other processes used during any of its runs.

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
            (
                "| Variant | Loop ms by round | Median | Min | Range | Change | Faster "
                "| Wall median | Other load | Stores |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|",
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
                f"| {_fmt(wall)} | {_load(runs)} | {_stores(runs, base)} |"
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
