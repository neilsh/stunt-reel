"""Instruction counts of a headless lavapipe render under Cachegrind, for a perf ticket's gate.

``mise run icount`` (``python/scripts/icount.py``) counts one tick span on two or more builds,
several repeats each, with the setup of ``research/parity/lavapipe-instruction-counts.md`` § 1.
It reads each Cachegrind output file for the whole-run count, the count outside glibc's allocator
(:data:`ALLOCATOR_FILES`, whose path varies between repeats) and the count per function, and
:func:`summarize` reads each variant's change against the baseline's median and its multiple of
the baseline's repeat range. Nothing here prints or chooses an exit code (ADR 0010).
"""

from __future__ import annotations

import csv
import io
import json
import re
import statistics
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
lazy from pathlib import Path

from stunt_reel import ab_timing, dataroot
from stunt_reel.hashing import file_sha256
from stunt_reel.parity_artifacts import RENDER_DOCUMENT

__all__ = [
    "ALLOCATOR_FILES",
    "COLUMNS",
    "Count",
    "RunError",
    "cachegrind_argv",
    "count_once",
    "environment",
    "parse_cachegrind",
    "summarize",
    "write_csv",
]

#: Source files whose instructions the "outside the allocator" count leaves out.
ALLOCATOR_FILES = ("/malloc/malloc.c", "memmove-vec-unaligned-erms.S")
#: Valgrind's options for a count: no cache model, and JIT-compiled shader code is checked for
#: self-modification.
VALGRIND_OPTIONS = ("--tool=cachegrind", "--cache-sim=no", "--smc-check=all-non-file")
#: Environment that makes one run's count independent of the last: Mesa's shader cache off, one
#: lavapipe thread.
COUNT_ENVIRONMENT = {"MESA_SHADER_CACHE_DISABLE": "true", "LP_NUM_THREADS": "1"}
COLUMNS = (
    "span",
    "variant",
    "repeat",
    "ir_total",
    "ir_outside_allocator",
    *(f"{plane}_sha256" for plane in ab_timing.PLANES),
)
#: Seconds one counted render may take (about 50 times a native run of a short span).
RUN_TIMEOUT_S = 7200.0
_I_REFS = re.compile(r"I\s+refs:\s+([\d,]+)")


class RunError(RuntimeError):
    """A counted render that failed or left no usable Cachegrind file or store."""


@dataclass(frozen=True)
class Count:
    """One counted run: its instructions in total, outside the allocator and per function."""

    span: str
    variant: str
    repeat: int
    total: int
    outside: int
    sha256: Mapping[str, str]
    functions: Mapping[str, int] = field(default_factory=dict, repr=False)


#: Runs argv under env: ``(exit code, combined output)``.
Runner = Callable[[Sequence[str], Mapping[str, str], float], tuple[int, str]]


def _process_runner(argv: Sequence[str], env: Mapping[str, str], timeout: float) -> tuple[int, str]:
    done = subprocess.run(  # noqa: S603
        list(argv),
        env=dict(env),
        cwd=dataroot.REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return done.returncode, done.stdout


def parse_cachegrind(text: str) -> tuple[int, int, dict[str, int]]:
    """``(total, outside the allocator, per function)`` instructions of a Cachegrind file.

    A line's file is the last ``fl=`` one; the outside count leaves out lines in
    :data:`ALLOCATOR_FILES`. Functions are keyed by name, summed over files.
    """
    total = allocator = 0
    in_allocator = False
    function = ""
    functions: dict[str, int] = {}
    for line in text.splitlines():
        if line.startswith("fl="):
            in_allocator = any(name in line for name in ALLOCATOR_FILES)
        elif line.startswith("fn="):
            function = line[3:]
        elif line[:1].isdigit():
            parts = line.split()
            if len(parts) > 1:
                count = int(parts[1])
                total += count
                functions[function] = functions.get(function, 0) + count
                if in_allocator:
                    allocator += count
    return total, total - allocator, functions


def environment(variant: ab_timing.Variant, icd: Path) -> dict[str, str]:
    """The run's environment: ab's lavapipe one, both ICD variables, then :data:`COUNT_ENVIRONMENT`."""
    env = ab_timing.environment_for(variant, "lavapipe", icd)
    env["VK_ICD_FILENAMES"] = str(icd)
    env.update(COUNT_ENVIRONMENT)
    env.update(variant.env)
    return env


def cachegrind_argv(render: Sequence[str], cg_out: Path, machine: str) -> list[str]:
    """*render* under ``setarch <machine> -R valgrind --tool=cachegrind``, writing *cg_out*."""
    return [
        "setarch",
        machine,
        "-R",
        "valgrind",
        *VALGRIND_OPTIONS,
        f"--cachegrind-out-file={cg_out}",
        *render,
    ]


def count_once(
    argv: Sequence[str],
    env: Mapping[str, str],
    cg_out: Path,
    out_dir: Path,
    identity: tuple[str, str, int],
    *,
    run: Runner = _process_runner,
) -> Count:
    """One counted render of ``(span, variant, repeat)``; raises :class:`RunError` on failure."""
    span, variant, repeat = identity
    code, output = run(argv, env, RUN_TIMEOUT_S)
    if code != 0:
        tail = "\n".join(output.strip().splitlines()[-6:])
        raise RunError(f"exited {code}: {tail}")
    try:
        total, outside, functions = parse_cachegrind(cg_out.read_text(encoding="utf-8"))
        json.loads((out_dir / RENDER_DOCUMENT).read_text(encoding="utf-8"))
        sha256 = {p: file_sha256(out_dir / f"{p}.zst") for p in ab_timing.PLANES}
    except (OSError, ValueError) as err:
        raise RunError(f"left no usable Cachegrind file or store: {err}") from err
    if (found := _I_REFS.search(output)) and int(found[1].replace(",", "")) != total:
        raise RunError(f"Cachegrind printed I refs {found[1]}, its file sums to {total:,}")
    if total == 0:
        raise RunError("Cachegrind counted no instructions")
    return Count(span, variant, repeat, total, outside, sha256, functions)


def write_csv(counts: Sequence[Count]) -> str:
    """The runs as CSV, one row each, in :data:`COLUMNS`."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for c in counts:
        writer.writerow(
            [c.span, c.variant, c.repeat, c.total, c.outside]
            + [c.sha256[p] for p in ab_timing.PLANES]
        )
    return out.getvalue()


def stores_match(runs: Sequence[Count], base: Sequence[Count]) -> bool:
    """Whether every run of *runs* hashes every plane like the first run of *base*."""
    return all(r.sha256 == base[0].sha256 for r in [*runs, *base])


def change_line(runs: Sequence[int], base: Sequence[int]) -> str:
    """The median change against the baseline's, and its multiple of the baseline's range."""
    median, base_median = statistics.median(runs), statistics.median(base)
    spread = max(base) - min(base)
    change = median - base_median
    percent = f"{change / base_median * 100:+.4f}%" if base_median else "n/a"
    if spread:
        multiple = f"{abs(change) / spread:.1f}x the baseline's range"
    else:
        multiple = "baseline repeats identical, no range"
    return f"{median:,.0f} ({change:+,.0f}, {percent}), {multiple}"


def top_differences(base: Mapping[str, int], other: Mapping[str, int], limit: int) -> list[str]:
    """The *limit* functions whose count differs most, as ``name: base -> other (diff)`` lines."""
    names = set(base) | set(other)
    diffs = sorted(names, key=lambda n: -abs(other.get(n, 0) - base.get(n, 0)))
    return [
        f"{n}: {base.get(n, 0):,} -> {other.get(n, 0):,} ({other.get(n, 0) - base.get(n, 0):+,})"
        for n in diffs[:limit]
        if other.get(n, 0) != base.get(n, 0)
    ]


def summarize(counts: Sequence[Count], variants: Sequence[str], top: int = 10) -> str:
    """The summary, per span: each variant against the first, the stores and the top functions."""
    lines = ["# Instruction counts", ""]
    for span in dict.fromkeys(c.span for c in counts):
        by = {v: [c for c in counts if c.span == span and c.variant == v] for v in variants}
        base = by[variants[0]]
        lines += [f"## {span}", ""]
        lines.append(
            f"Baseline `{variants[0]}`, {len(base)} repeats: whole-run range "
            f"{max(c.total for c in base) - min(c.total for c in base):,}, outside the allocator "
            f"{max(c.outside for c in base) - min(c.outside for c in base):,}."
        )
        lines.append("")
        for name in variants:
            runs = by[name]
            lines.append(f"* `{name}` ({len(runs)} repeats), median, change, multiple of range:")
            lines.append(
                f"  * whole run: {change_line([c.total for c in runs], [c.total for c in base])}"
            )
            lines.append(
                "  * outside glibc's `malloc.c` and `memmove`: "
                f"{change_line([c.outside for c in runs], [c.outside for c in base])}"
            )
            if name != variants[0]:
                same = "same" if stores_match(runs, base) else "DIFFER from the baseline's"
                lines.append(f"  * stores: {same}")
                lines.append("  * top function differences, repeat 0 against the baseline's:")
                lines += [
                    f"    * {d}" for d in top_differences(base[0].functions, runs[0].functions, top)
                ]
        lines += [""]
    lines.append(
        "One span's repeat range does not bound another's: the allocator's noise differs by film "
        "and span, and a difference of two spans adds both spans' noise."
    )
    return "\n".join(lines) + "\n"
