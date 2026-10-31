"""Probe PLAYONE.EXE's per-shot lighting and shade arrays on dosbox-automation.

The terrain shade path (see research/playone-exe/terrain-shade.md) reads a light vector
from work:0x8072/0x8074/0x8076 and turns per-vertex normals into an 8.8 palette-index
ramp. This probe runs one film as a plan: the trace reads the work-segment pointer, and the
dump passes read the work and DGROUP segments at the first frame of each chosen film clock, so
the light vector, the sun-billboard vector, the sun-position words and the first shade-array
entries can be pinned down without breakpoints.

Writes work_tNNN.bin and ds_tNNN.bin (60 KiB each, the work and DGROUP segments) into
--out, plus one line per sample on stdout. Reads a proprietary executable from the local,
gitignored corpus/; nothing it produces is committed.

Usage: mise exec -- uv run python python/scripts/probe_playone_light.py
[--film corpus/stisldem/VAULT/CTRY.FLM] [--ticks 10,150,273,448] [--out build/scratch/round5]
"""

from __future__ import annotations

import argparse
import logging
import struct
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import dataroot
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.tac import automation, luagen, plan, playone, staging
from stunt_reel.tac.emulator import EmulatorUnavailable

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from stunt_reel.tac.automation import ScriptRunner

DEFAULT_FILM: Path = Path("corpus/stisldem/VAULT/CTRY.FLM")
DEFAULT_TICKS: tuple[int, ...] = (10, 150, 273, 448, 700, 900, 1100)
#: DS offset of the far pointer to the display-list work segment (written by the VM setup).
WORK_SEGMENT_POINTER: int = 0x0542
#: Work-segment offsets: light vector, sun-billboard vector, shade array (terrain-shade.md).
LIGHT_OFFSET: int = 0x8072
SUN_BILLBOARD_OFFSET: int = 0x8078
SHADE_ARRAY_OFFSET: int = 0x7468
#: DGROUP offset of the sun-position vector.
SUN_POSITION_OFFSET: int = 0x49EC
SEGMENT_BYTES: int = 0xF000
SHADE_WORDS: int = 8
#: A trace window well past the longest film (70.087 emulated frames per second).
MAX_TRACE_FRAMES: int = 12000


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--film", type=Path, default=DEFAULT_FILM, help="film to play")
    parser.add_argument(
        "--ticks",
        default=",".join(str(t) for t in DEFAULT_TICKS),
        help="comma-separated film clocks to sample at",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("build/scratch/round5"), help="dump directory"
    )
    parser.add_argument(
        "--dump-all-segments",
        action="store_true",
        help="also dump all 16 real-mode segments at each sample (60 KiB each; mind the 15 MB output cap)",
    )
    return parser.parse_args()


def resolve(path: Path) -> Path:
    """Resolve a path against the repository root."""
    return path if path.is_absolute() else dataroot.REPO_ROOT / path


def signed_words(data: bytes, offset: int, count: int) -> list[int]:
    """Reads count little-endian signed 16-bit words from *data* at *offset*."""
    chunk = data[offset : offset + 2 * count]
    if len(chunk) < 2 * count:
        raise RuntimeError(f"short read at offset {offset:04X}")
    return list(struct.unpack("<" + "h" * count, chunk))


def magnitude(values: list[int]) -> float:
    """Returns the Euclidean length of a work-segment vector."""
    total = sum(v * v for v in values)
    return float(round(total**0.5, 1))


def sample(
    work_bytes: bytes,
    ds_bytes: bytes,
    tick: int,
    work: int,
    out: Path,
    *,
    segments: Sequence[bytes] = (),
) -> None:
    """Prints and dumps one sample of the lighting state."""
    light = signed_words(work_bytes, LIGHT_OFFSET, 3)
    billboard = signed_words(work_bytes, SUN_BILLBOARD_OFFSET, 3)
    sun_position = signed_words(ds_bytes, SUN_POSITION_OFFSET, 6)
    shades = signed_words(work_bytes, SHADE_ARRAY_OFFSET, SHADE_WORDS)
    print(
        f"[shot] tick {tick:5d} workseg {work:04X} L {light} |L| {magnitude(light)} "
        f"sun_billboard {billboard} sun_position {sun_position} shade {shades}",
        flush=True,
    )
    (out / f"work_t{tick}.bin").write_bytes(work_bytes)
    (out / f"ds_t{tick}.bin").write_bytes(ds_bytes)
    for segment, data in enumerate(segments):
        (out / f"seg_{segment:04X}_t{tick}.bin").write_bytes(data)


def probe(
    open_runner: Callable[[], AbstractContextManager[ScriptRunner]],
    keys: list[str],
    ticks: list[int],
    out: Path,
    *,
    dump_all: bool,
) -> None:
    """Run the plan and print and dump a sample at each requested film clock."""
    out.mkdir(parents=True, exist_ok=True)
    first = luagen.boot_end(len(keys))
    pointer = (playone.AUTOMATION_DS, WORK_SEGMENT_POINTER)
    planned: list[int] = []

    def ranges(trace: plan.Trace, frames: Sequence[int]) -> list[luagen.MemRange]:
        if not frames:
            raise RuntimeError(f"the film never reached any of the ticks {ticks}")
        works = {trace.entry(f).words[0] for f in frames}
        if len(works) != 1:
            raise RuntimeError(
                "the work segment moved between samples: "
                + ", ".join(f"{w:04X}" for w in sorted(works))
            )
        planned.append(works.pop())
        found = [
            luagen.MemRange(planned[0], 0, SEGMENT_BYTES),
            luagen.MemRange(playone.AUTOMATION_DS, 0, SEGMENT_BYTES),
        ]
        if dump_all:
            found += [luagen.MemRange(segment, 0, SEGMENT_BYTES) for segment in range(0x10)]
        return found

    result = plan.run_plan(
        open_runner,
        keys=keys,
        first=first,
        last=first + MAX_TRACE_FRAMES,
        pick=lambda trace: plan.pick_ticks(trace, ticks),
        ranges=ranges,
        words=[pointer],
        end_hold=30,
        progress=lambda line: print(f"[probe] {line}", flush=True),
    )
    # The ranges were planned at the trace pass's segment, so a dump pass that read another
    # pointer dumped bytes that are not its work segment.
    for frame, dump in result.dumps.items():
        if planned and dump.entry.words[0] != planned[0]:
            raise RuntimeError(
                f"dump pass at frame {frame} read work segment {dump.entry.words[0]:04X}, "
                f"but the trace pass read {planned[0]:04X}"
            )
    for frame in sorted(result.dumps):
        entry = result.dumps[frame].entry
        work_bytes, ds_bytes, *segments = result.dumps[frame].ranges
        sample(work_bytes, ds_bytes, entry.film_tick, entry.words[0], out, segments=segments)


def run(args: argparse.Namespace) -> int:
    """Stage one film, run the plan and sample the lighting state."""
    film = resolve(args.film)
    out = resolve(args.out)
    ticks = [int(part) for part in args.ticks.split(",")]
    try:
        staged = staging.stage_film(film)
    except OSError as exc:
        print(f"[probe] {exc}", file=sys.stderr)
        return 1
    try:
        probe(
            lambda: automation.launched(staged.write_conf),
            playone.film_selection_names(film.stem),
            ticks,
            out,
            dump_all=args.dump_all_segments,
        )
    except EmulatorUnavailable as exc:
        print(f"[probe] {exc}; run via mise exec", file=sys.stderr)
        return 1
    except (automation.ScriptError, plan.PlanError, RuntimeError, TimeoutError, OSError) as exc:
        print(f"[probe] {exc}", file=sys.stderr)
        return 1
    finally:
        staging.unstage(staged)
    return 0


def main() -> int:
    """Run the probe and terminate the emulator."""
    if not ensure_links_or_report("probe_playone_light"):
        return 2
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
