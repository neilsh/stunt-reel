"""Probe PLAYONE.EXE's per-shot lighting and shade arrays through the DOSBox-X TAC harness.

The terrain shade path (see `research/playone-exe/terrain-shade.md`) reads a light vector
from `work:0x8072/0x8074/0x8076` and turns per-vertex normals into an 8.8 palette-index
ramp. This probe drives one film through the harness and, at chosen film clocks, prints the
light vector, the sun-billboard vector, the sun-position words and the first shade-array
entries, so the per-shot input can be pinned down without breakpoints.

Writes `work_tNNN.bin` and `ds_tNNN.bin` (60 KiB each, the work and DGROUP segments) into
`--out`, plus one line per sample on stdout. Reads a proprietary executable from the local,
gitignored `corpus/`; nothing it produces is committed.

Usage: ``mise exec -- uv run python python/scripts/probe_playone_light.py
[--film corpus/stisldem/VAULT/CTRY.FLM] [--ticks 10,150,273,448] [--out build/scratch/round5]``
"""

from __future__ import annotations

import argparse
import logging
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from stunt_reel.tac import playone
from stunt_reel.tac.client import TacClient
from stunt_reel.tac.framebuffer import _wait_until_static, read_ticks
from stunt_reel.tac.transport import ListenTransport

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
CONTROL_PORT: int = 58991
LAUNCH_TIMEOUT_SECONDS: float = 30.0
EMULATOR_STOP_SECONDS: float = 10.0
FRAME_CAP: int = 2000
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
        "--stage", type=Path, default=Path("dosbox-parity.conf"), help="DOSBox-X config"
    )
    return parser.parse_args()


def signed_words(client: TacClient, segment: int, offset: int, count: int) -> list[int]:
    """Reads `count` little-endian signed 16-bit words from `segment:offset`."""
    data = client.read_memory(f"{segment:04X}:{offset:04X}", 2 * count)
    if len(data) < 2 * count:
        raise RuntimeError(f"short read at {segment:04X}:{offset:04X}")
    return list(struct.unpack("<" + "h" * count, data[: 2 * count]))


def magnitude(values: list[int]) -> float:
    """Returns the Euclidean length of a work-segment vector."""
    total = sum(v * v for v in values)
    return float(round(total**0.5, 1))


def sample(client: TacClient, tick: int, work: int, out: Path) -> None:
    """Prints and dumps one sample of the lighting state."""
    light = signed_words(client, work, LIGHT_OFFSET, 3)
    billboard = signed_words(client, work, SUN_BILLBOARD_OFFSET, 3)
    sun_position = signed_words(client, playone.DGROUP_RUNTIME_SEG, SUN_POSITION_OFFSET, 6)
    shades = signed_words(client, work, SHADE_ARRAY_OFFSET, SHADE_WORDS)
    print(
        f"[shot] tick {tick:5d} workseg {work:04X} L {light} |L| {magnitude(light)} "
        f"sun_billboard {billboard} sun_position {sun_position} shade {shades}",
        flush=True,
    )
    (out / f"work_t{tick}.bin").write_bytes(client.read_memory(f"{work:04X}:0000", SEGMENT_BYTES))
    (out / f"ds_t{tick}.bin").write_bytes(
        client.read_memory(f"{playone.DGROUP_RUNTIME_SEG:04X}:0000", SEGMENT_BYTES)
    )


def run(args: argparse.Namespace) -> int:
    """Launches one emulator session and samples the lighting state."""
    film = args.film if args.film.is_absolute() else REPO_ROOT / args.film
    out = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    conf = args.stage if args.stage.is_absolute() else REPO_ROOT / args.stage
    ticks = [int(part) for part in args.ticks.split(",")]
    _stage, staged_conf = stage_film(film, conf)
    out.mkdir(parents=True, exist_ok=True)

    transport = ListenTransport(port=CONTROL_PORT)
    transport.listen()
    client = TacClient(transport)
    emulator: subprocess.Popen[bytes] | None = None
    try:
        exe = shutil.which("dosbox-x")
        if exe is None:
            print("[probe] dosbox-x is not on PATH; run via mise exec", file=sys.stderr)
            return 1
        emulator = subprocess.Popen([exe, "-conf", str(staged_conf)], cwd=str(REPO_ROOT))  # noqa: S603
        transport.accept(timeout=LAUNCH_TIMEOUT_SECONDS)
        if not client.ping():
            print("[probe] debugger did not answer PING", file=sys.stderr)
            return 1
        _wait_until_static(client, out / "_scratch.idx")
        playone.confirm_film(client, film.name[0].lower())
        playone.arm_frame_trap(client)
        pending = list(ticks)
        work = 0
        for _frame in range(FRAME_CAP):
            playone.next_frame(client)
            tick, _global = read_ticks(client, playone.DGROUP_RUNTIME_SEG)
            if not pending or tick < pending[0]:
                continue
            pending.pop(0)
            work = client.read_u16(f"{playone.DGROUP_RUNTIME_SEG:04X}:{WORK_SEGMENT_POINTER:04X}")
            sample(client, tick, work, out)
        return 0
    finally:
        client.close()
        if emulator is not None and emulator.poll() is None:
            emulator.terminate()
            try:
                emulator.wait(timeout=EMULATOR_STOP_SECONDS)
            except subprocess.TimeoutExpired:
                emulator.kill()


def stage_film(film: Path, conf: Path) -> tuple[Path, Path]:
    """Stages `film` alone in a fresh mount and returns `(stage, staged_conf)`."""
    from capture_playone_reference import stage_film as stage

    return stage(film, conf)


def main() -> int:
    """Run the probe and terminate the emulator."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
