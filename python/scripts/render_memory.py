"""Render a reference film headless and report each run's peak and steady memory.

Usage::

    mise run render-memory -- --film location [--ticks 12..=120] [--binary [LABEL=]PATH ...]
        [--runs N] [--software-only] [--no-build]

Each run is one ``stuntreel`` process with the parity pipeline's command
(:func:`stunt_reel.parity_pipeline.render_film`), rendering into
``build/scratch/render-memory/<film>/<label>_<n>/store`` with its output in ``log.txt`` beside
it. Peak is the process's high-water resident set: ``ru_maxrss`` from ``wait4`` where the
platform has it (Linux, macOS), else the peak working set, with peak private bytes beside it
(Windows). Steady is the median resident set, sampled every 0.1 s, over the last four fifths
of the run, past start-up and the world's upload. Each line also gives the SHA-256 prefixes of
the run's ``frames.zst``, ``layers.zst`` and ``palettes.zst``, and the last line says whether
every run's stores are identical.

Without ``--binary`` it measures the release binary, built first unless ``--no-build``. With
several, runs alternate (A, B, A, B, ...) so drift on the machine falls on both; a binary from
``mise run build-at`` is the usual "before".
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from stunt_reel import dataroot, parity_pipeline, process_tree, references
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.link import binary_path

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: Where each run's store and log go, relative to the checkout.
MEMORY_DIR = Path("build") / "scratch" / "render-memory"
#: The render-store files whose digests show whether two runs drew the same pixels.
STORE_FILES = ("frames.zst", "layers.zst", "palettes.zst")
#: The share of a run, from its start, left out of the steady figure.
WARM_UP = 0.2
#: Bytes of output kept for an error message.
_TAIL_BYTES = 4000
_MIB = 1 << 20


@dataclass(frozen=True)
class Memory:
    """One run's memory, in bytes, and its wall time in seconds."""

    peak: int
    #: Peak private bytes, where the platform reports them (Windows); else ``None``.
    peak_private: int | None
    steady: int
    wall: float


@dataclass(frozen=True)
class Row:
    """One run: its binary's label, its number among that binary's runs, memory and digests."""

    label: str
    n: int
    memory: Memory
    digests: tuple[str, ...]


def parse_ticks(text: str) -> list[int]:
    """The film ticks of ``A..=B``, both ends included."""
    start, sep, end = text.partition("..=")
    try:
        first, last = int(start), int(end)
    except ValueError:
        first = last = -1
    if not sep or first < 0 or last < first:
        raise ValueError(f"--ticks wants A..=B with 0 <= A <= B, got {text!r}")
    return list(range(first, last + 1))


def parse_binary(text: str) -> tuple[str, Path]:
    """``LABEL=PATH``, or a bare path labelled by its file name."""
    label, sep, path = text.partition("=")
    if sep and label and "/" not in label and "\\" not in label:
        return label, Path(path)
    return Path(text).name, Path(text)


def plan_runs(binaries: Sequence[tuple[str, Path]], runs: int) -> list[tuple[str, Path, int]]:
    """Each run's label, binary and number, the binaries alternating within each round."""
    labels = [label for label, _ in binaries]
    if len(set(labels)) != len(labels):
        raise ValueError(f"two binaries share a label: {labels}")
    return [(label, path, n) for n in range(1, runs + 1) for label, path in binaries]


def steady_bytes(samples: Sequence[tuple[float, int]], wall: float) -> int:
    """The median sampled resident set after the first :data:`WARM_UP` of ``wall``; 0 if none."""
    later = [rss for at, rss in samples if at > wall * WARM_UP]
    return int(statistics.median(later)) if later else 0


def store_digests(store: Path) -> tuple[str, ...]:
    """SHA-256 of each of :data:`STORE_FILES` in ``store``, ``missing`` for one it lacks."""
    return tuple(
        hashlib.sha256((store / name).read_bytes()).hexdigest()
        if (store / name).is_file()
        else "missing"
        for name in STORE_FILES
    )


def _short(digests: tuple[str, ...]) -> str:
    return " ".join(digest[:8] for digest in digests)


def format_line(row: Row) -> str:
    """One run's line: peak (and peak private), steady, wall time and digest prefixes."""
    memory = row.memory
    peak = f"peak {memory.peak // _MIB} MiB"
    if memory.peak_private is not None:
        peak += f" (private {memory.peak_private // _MIB} MiB)"
    return (
        f"{row.label} #{row.n}: {peak}, steady {memory.steady // _MIB} MiB, "
        f"{memory.wall:.1f} s; stores {_short(row.digests)}"
    )


def verdict(rows: Sequence[Row]) -> str:
    """Whether every run's stores are identical, naming each run's digests when they differ."""
    groups: dict[tuple[str, ...], list[str]] = {}
    for row in rows:
        groups.setdefault(row.digests, []).append(f"{row.label} #{row.n}")
    if len(rows) == 1:
        return "one run, so no stores to compare"
    if len(groups) == 1:
        return f"stores identical over all {len(rows)} runs"
    return "stores DIFFER: " + "; ".join(
        f"{_short(digests)} in {', '.join(names)}" for digests, names in groups.items()
    )


def _sample(pid: int) -> tuple[int, int, int] | None:
    """The process's resident set, peak working set and peak private bytes, 0 where unknown."""
    import psutil  # type: ignore[import-untyped]  # noqa: PLC0415  # no stubs; dev tools only

    try:
        info: object = psutil.Process(pid).memory_info()
    except psutil.Error:
        return None
    return (
        int(getattr(info, "rss", 0)),
        int(getattr(info, "peak_wset", 0)),
        int(getattr(info, "peak_pagefile", 0)),
    )


def _reap(proc: subprocess.Popen[bytes]) -> tuple[int | None, int | None]:
    """The exit code and ``wait4`` peak resident bytes once ``proc`` has exited, else Nones."""
    if sys.platform == "win32":
        code, maxrss = proc.poll(), None
    else:
        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
        if pid == 0:
            code, maxrss = None, None
        else:
            code = proc.returncode = os.waitstatus_to_exitcode(status)
            # Linux reports ru_maxrss in KiB, macOS in bytes.
            maxrss = usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    return code, maxrss


class MemoryProbe:
    """A :data:`parity_pipeline.Run` adapter that also measures the process's memory.

    After a call, :attr:`memory` holds the run's figures; output goes to ``log``.
    """

    def __init__(self, log: Path, interval: float = 0.1) -> None:
        self.log = log
        self.interval = interval
        self.memory = Memory(0, None, 0, 0.0)

    def __call__(
        self, argv: list[str], env: dict[str, str] | None, timeout: float | None
    ) -> tuple[int, str]:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        samples: list[tuple[float, int]] = []
        peak_wset = peak_private = 0
        start = time.monotonic()
        with self.log.open("wb") as sink:
            proc = subprocess.Popen(  # noqa: S603  # argv is the parity pipeline's own command
                argv, cwd=REPO_ROOT, env=env, stdout=sink, stderr=subprocess.STDOUT
            )
            while True:
                if (sample := _sample(proc.pid)) is not None:
                    samples.append((time.monotonic() - start, sample[0]))
                    peak_wset = max(peak_wset, sample[1])
                    peak_private = max(peak_private, sample[2])
                code, maxrss = _reap(proc)
                if code is not None:
                    break
                if timeout is not None and time.monotonic() - start > timeout:
                    proc.kill()
                    proc.wait()
                    return process_tree.TIMEOUT_EXIT, f"timeout after {timeout:g}s"
                time.sleep(self.interval)
        wall = time.monotonic() - start
        peak = maxrss or peak_wset or max((rss for _, rss in samples), default=0)
        self.memory = Memory(peak, peak_private or None, steady_bytes(samples, wall), wall)
        tail = self.log.read_bytes()[-_TAIL_BYTES:].decode(errors="replace")
        return code, tail


class Probe(Protocol):
    """What :func:`measure` needs of a probe: a run adapter that leaves its figures behind."""

    @property
    def memory(self) -> Memory: ...

    def __call__(
        self, argv: list[str], env: dict[str, str] | None, timeout: float | None, /
    ) -> tuple[int, str]: ...


def measure(
    job: parity_pipeline.FilmJob,
    plan: Sequence[tuple[str, Path, int]],
    *,
    out: Path,
    ticks: Sequence[int] | None,
    software_only: bool = False,
    probe: Callable[[Path], Probe] = MemoryProbe,
) -> list[Row]:
    """Renders ``job`` once per planned run into ``out/<label>_<n>``; each run's row, in order.

    ``ticks`` ``None`` renders the ticks the job's capture holds. A run's earlier store is
    replaced. A failing render raises :class:`parity_pipeline.CommandError`.
    """
    rows: list[Row] = []
    for label, binary, n in plan:
        run_dir = out / f"{label}_{n}"
        shutil.rmtree(run_dir, ignore_errors=True)
        adapter = probe(run_dir / "log.txt")
        parity_pipeline.render_film(
            job,
            run_dir / "store",
            ticks=ticks,
            software_only=software_only,
            binary=binary,
            run=adapter,
        )
        rows.append(Row(label, n, adapter.memory, store_digests(run_dir / "store")))
    return rows


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--film", required=True, choices=references.reference_films(REPO_ROOT))
    parser.add_argument("--ticks", default=None, help="A..=B (default: the captured ticks)")
    parser.add_argument(
        "--binary",
        action="append",
        default=[],
        help="[LABEL=]PATH of a stuntreel build; repeat to compare (default: the release binary)",
    )
    parser.add_argument("--runs", type=int, default=1, help="runs of each binary (default 1)")
    parser.add_argument("--no-build", action="store_true", help="reuse the release binary")
    parser.add_argument(
        "--software-only",
        action="store_true",
        help="render on the software adapter (lavapipe, WARP), even when a GPU is available",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.runs < 1:
        print(f"render_memory: --runs wants 1 or more, got {args.runs}", file=sys.stderr)
        return 2
    try:
        ticks = parse_ticks(args.ticks) if args.ticks else None
        binaries = [parse_binary(text) for text in args.binary] or [("release", binary_path())]
        plan = plan_runs(binaries, args.runs)
    except ValueError as err:
        print(f"render_memory: {err}", file=sys.stderr)
        return 2
    build = not args.binary and not args.no_build
    missing = [str(path) for _, path in binaries if not build and not path.is_file()]
    root = dataroot.data_root()
    problems = parity_pipeline.preflight(root, [args.film], build_required=build)
    problems += [f"missing binary {path}" for path in missing]
    if problems:
        print("render_memory: " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if build:
        parity_pipeline.build_release()
    out = REPO_ROOT / MEMORY_DIR / args.film
    try:
        with parity_pipeline.reference_job(root, args.film) as job:
            rows = measure(job, plan, out=out, ticks=ticks, software_only=args.software_only)
    except parity_pipeline.CommandError as err:
        print(f"render_memory: {err}", file=sys.stderr)
        return 1
    for row in rows:
        print(format_line(row))
    print(verdict(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
