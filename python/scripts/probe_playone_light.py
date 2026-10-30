"""Probe PLAYONE.EXE's per-shot lighting and shade arrays through the DOSBox-X TAC harness.

The terrain shade path (see research/playone-exe/terrain-shade.md) reads a light vector
from work:0x8072/0x8074/0x8076 and turns per-vertex normals into an 8.8 palette-index
ramp. This probe drives one film through the harness and, at chosen film clocks, prints the
light vector, the sun-billboard vector, the sun-position words and the first shade-array
entries, so the per-shot input can be pinned down without breakpoints.

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

from stunt_reel import dataroot
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.tac import playone
from stunt_reel.tac.emulator import EmulatorUnavailable
from stunt_reel.tac.session import Page, Session, SessionError, run_session

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
        "--stage",
        type=Path,
        default=Path("tools/dosbox/dosbox-parity.conf"),
        help="DOSBox-X config",
    )
    parser.add_argument(
        "--dump-all-segments",
        action="store_true",
        help="also dump all 16 real-mode segments at each sample (60 KiB each)",
    )
    return parser.parse_args()


def resolve(path: Path) -> Path:
    """Resolve a path against the repository root."""
    return path if path.is_absolute() else dataroot.REPO_ROOT / path


def signed_words(page: Page, segment: int, offset: int, count: int) -> list[int]:
    """Reads count little-endian signed 16-bit words from segment:offset."""
    data = page.read_memory(segment, offset, 2 * count)
    if len(data) < 2 * count:
        raise RuntimeError(f"short read at {segment:04X}:{offset:04X}")
    return list(struct.unpack("<" + "h" * count, data[: 2 * count]))


def magnitude(values: list[int]) -> float:
    """Returns the Euclidean length of a work-segment vector."""
    total = sum(v * v for v in values)
    return float(round(total**0.5, 1))


def sample(page: Page, tick: int, work: int, out: Path, *, dump_all: bool = False) -> None:
    """Prints and dumps one sample of the lighting state."""
    light = signed_words(page, work, LIGHT_OFFSET, 3)
    billboard = signed_words(page, work, SUN_BILLBOARD_OFFSET, 3)
    sun_position = signed_words(page, playone.DGROUP_RUNTIME_SEG, SUN_POSITION_OFFSET, 6)
    shades = signed_words(page, work, SHADE_ARRAY_OFFSET, SHADE_WORDS)
    print(
        f"[shot] tick {tick:5d} workseg {work:04X} L {light} |L| {magnitude(light)} "
        f"sun_billboard {billboard} sun_position {sun_position} shade {shades}",
        flush=True,
    )
    (out / f"work_t{tick}.bin").write_bytes(page.read_memory(work, 0, SEGMENT_BYTES))
    (out / f"ds_t{tick}.bin").write_bytes(
        page.read_memory(playone.DGROUP_RUNTIME_SEG, 0, SEGMENT_BYTES)
    )
    if dump_all:
        for segment in range(0x10):
            (out / f"seg_{segment:04X}.bin").write_bytes(
                page.read_memory(segment, 0, SEGMENT_BYTES)
            )


def sample_ticks(session: Session, ticks: list[int], out: Path, *, dump_all: bool) -> None:
    """Steps one frame at a time until every requested film clock has been sampled."""
    out.mkdir(parents=True, exist_ok=True)
    pending = list(ticks)
    while pending:
        page = session.next_frame()
        tick, _global = page.film_clock
        if tick < pending[0]:
            continue
        pending.pop(0)
        work = int.from_bytes(
            page.read_memory(playone.DGROUP_RUNTIME_SEG, WORK_SEGMENT_POINTER, 2), "little"
        )
        sample(page, tick, work, out, dump_all=dump_all)


def run(args: argparse.Namespace) -> int:
    """Drive one emulator session and sample the lighting state."""
    film = resolve(args.film)
    out = resolve(args.out)
    conf = resolve(args.stage)
    ticks = [int(part) for part in args.ticks.split(",")]

    try:
        run_session(
            film,
            sample=lambda session: sample_ticks(
                session, ticks, out, dump_all=args.dump_all_segments
            ),
            conf=conf,
        )
    except EmulatorUnavailable as exc:
        print(f"[probe] {exc}; run via mise exec", file=sys.stderr)
        return 1
    except (SessionError, RuntimeError, TimeoutError, ConnectionError) as exc:
        print(f"[probe] {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    """Run the probe and terminate the emulator."""
    if not ensure_links_or_report("probe_playone_light"):
        return 2
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
