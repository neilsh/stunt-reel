"""Replay a film slot through ``PLAYONE.EXE``'s scenery draw walk at one tick.

Prints each slot's DOS-axes position, shape and extent (``(bounding_size >> scale_index) + 1``),
and the eye and look target, from ``stuntreel film-slots``. With ``--slot N`` it also walks the
image's scene tree with the eye and that slot's entry as ``scene_tree.walk_slot`` does and prints
the leaf the entry reaches, the planes on its path, the ``SP_1NODE`` gates it passed and the draw
order around it. Evidence: ``research/playone-exe/scene-walk-actors.md`` sections 2 and 4.

Reads proprietary files from the data root and the gitignored ``build/``; it prints positions,
ids and node offsets only (see ``NOTICE.md``).

Usage: mise run scene-walk -- corpus/stisldem/VAULT/CTRY.FLM --tick 871 [--slot 11]
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import unlzexe
import xref

from stunt_reel import link, scene_tree
from stunt_reel.all_archive import ArchiveError, archive_chunks
from stunt_reel.dataroot import REPO_ROOT, data_path_arg, read_data_file_or_report

#: Neighbours of the slot in the draw order that ``--context`` shows by default.
DEFAULT_CONTEXT = 3
#: The ``.SOD`` header: ``OP_ID``, ``bounding_size`` (word at 2), ``ground_y_offset``, ``scale_index`` (byte at 6).
SOD_HEADER = 7

#: Where ``mise run superset-all`` writes the stock shapes, from the repository root.
SUPERSET_ALL = Path("target/linked/superset/SUPERSET.ALL")

#: Runs ``stuntreel film-slots`` for a film and a tick, returning its JSON text.
Sampler = Callable[[Path, float], str]


@dataclass(frozen=True)
class Slot:
    """One drawn slot at the sampled tick, in DOS axes."""

    slot: int
    shape: int
    position: tuple[float, float, float]
    view: bool
    shadow: bool
    extent: int | None  # ``None`` when no archive holds the shape


@dataclass(frozen=True)
class Frame:
    """The film at one tick: the camera and the drawn slots."""

    tick: int
    eye: tuple[float, float, float]
    target: tuple[float, float, float]
    slots: list[Slot]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("flm", type=data_path_arg, help="the film to sample")
    parser.add_argument("--tick", type=float, required=True, help="the 50 Hz tick to sample")
    parser.add_argument("--slot", type=int, help="walk this slot's entry through the scene tree")
    parser.add_argument(
        "--image",
        type=data_path_arg,
        default=None,
        help="MZ, LZEXE 0.91 or load-image PLAYONE.EXE (default: the data root's, unpacked)",
    )
    parser.add_argument(
        "--archive",
        type=data_path_arg,
        action="append",
        default=[],
        help="an .ALL holding the shapes, searched in order (default: the film's own, then "
        "target/linked/superset/SUPERSET.ALL)",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=DEFAULT_CONTEXT,
        help="draw-order steps shown on each side of the slot (default %(default)s)",
    )
    return parser.parse_args(argv)


def sod_extent(sod: bytes) -> int:
    """``(bounding_size >> scale_index) + 1`` of a ``.SOD`` shape, as ``0x1AF3..0x1AFF`` compute it."""
    if len(sod) < SOD_HEADER:
        raise ValueError(f"a .SOD of {len(sod)} bytes has no header")
    bounding: int = struct.unpack_from("<H", sod, 2)[0]
    return (bounding >> sod[6]) + 1


def shape_extents(archives: list[bytes]) -> dict[int, int]:
    """Every shape the archives hold with its extent; an earlier archive wins a shared id."""
    extents: dict[int, int] = {}
    for data in archives:
        for chunk_id, payload in archive_chunks(data):
            if payload[:2] == b"\x0c\x00":  # a .SOD opens with OP_ID, 0x000C
                try:
                    extents.setdefault(chunk_id, sod_extent(payload))
                except ValueError:
                    continue
    return extents


def parse_frame(text: str, extents: dict[int, int]) -> Frame:
    """The ``film-slots`` JSON as a :class:`Frame`; extents come from ``extents``."""
    raw = json.loads(text)
    slots = [
        Slot(
            slot=s["slot"],
            shape=s["shape"],
            position=(s["position"][0], s["position"][1], s["position"][2]),
            view=s["view"],
            shadow=s["shadow"],
            extent=extents.get(s["shape"]),
        )
        for s in raw["slots"]
    ]
    eye, target = raw["eye"], raw["target"]
    return Frame(raw["tick"], (eye[0], eye[1], eye[2]), (target[0], target[1], target[2]), slots)


def _vec(v: tuple[float, float, float]) -> str:
    return f"({v[0]:.2f}, {v[1]:.2f}, {v[2]:.2f})"


def frame_lines(frame: Frame) -> list[str]:
    """The tick, the camera and one line per slot."""
    lines = [f"tick {frame.tick}", f"eye {_vec(frame.eye)}  target {_vec(frame.target)}"]
    for s in frame.slots:
        extent = "?" if s.extent is None else str(s.extent)
        flags = "".join([" view" if s.view else "", " shadow" if s.shadow else ""])
        lines.append(
            f"slot {s.slot:2d} shape 0x{s.shape:04X} at {_vec(s.position)} extent {extent}{flags}"
        )
    return lines


def _step_line(step: scene_tree.DrawStep) -> str:
    where = f"({step.x}, {step.y}, {step.z})"
    if step.kind == "slot":
        return f"slot at {where}, leaf 0x{step.node:04X}"
    return f"object 0x{step.obj:04X} at {where}, leaf 0x{step.node:04X}"


def walk_lines(result: scene_tree.SlotWalk, context: int) -> list[str]:
    """The leaf, the planes, the gates and the draw order around the slot."""
    names = {
        scene_tree.SP_XPLANE: "SP_XPLANE",
        scene_tree.SP_ZPLANE: "SP_ZPLANE",
        scene_tree.SP_HSLOPE: "SP_HSLOPE",
        scene_tree.SP_VSLOPE: "SP_VSLOPE",
    }
    if result.leaf is None:
        lines = ["the entry reached no SP_LEAF: a node dropped it"]
    else:
        lines = [f"the entry reaches leaf 0x{result.leaf:04X}"]
    for plane in result.planes:
        at = "" if plane.coord is None else f" at {plane.coord}"
        lines.append(
            f"  {names[plane.kind]} 0x{plane.node:04X}{at}: {plane.side} side ({plane.why})"
        )
    for node, obj, x, y, z in result.gates:
        lines.append(
            f"  SP_1NODE 0x{node:04X}: object 0x{obj:04X} at ({x}, {y}, {z}), taken as near"
        )
    index = result.slot_index
    if index is not None:
        lines.append(f"draw order, {len(result.order)} steps; the slot is step {index}:")
        lo, hi = max(0, index - context), min(len(result.order), index + context + 1)
        lines += [
            f"  {n:5d}{'>' if n == index else ' '} {_step_line(result.order[n])}"
            for n in range(lo, hi)
        ]
    return lines


def default_archives(flm: Path) -> list[Path]:
    """The film's own ``.ALL`` beside it, then the superset of stock shapes, where they exist."""
    candidates = [flm.with_suffix(".ALL"), REPO_ROOT / SUPERSET_ALL]
    return [path for path in candidates if path.is_file()]


def sample_with_binary(flm: Path, tick: float) -> str:
    """Run ``stuntreel film-slots`` (building the release binary first) and return its stdout."""
    binary = link.ensure_binary()
    done = subprocess.run(  # noqa: S603 - argv built here: the release binary
        [str(binary), "film-slots", "--flm", str(flm), "--tick", str(tick)],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode:
        raise RuntimeError(f"stuntreel film-slots failed: {done.stderr.strip()}")
    return done.stdout


def run(args: argparse.Namespace, sample: Sampler = sample_with_binary) -> int:
    """Print the frame and, with ``--slot``, the walk; 0 on success."""
    archive_paths = args.archive or default_archives(args.flm)
    blobs = []
    for path in archive_paths:
        data = read_data_file_or_report("scene_walk", path)
        if data is None:
            return 2
        blobs.append(data)
    try:
        frame = parse_frame(sample(args.flm, args.tick), shape_extents(blobs))
    except (ArchiveError, RuntimeError, ValueError, KeyError) as exc:
        print(f"[scene-walk] {exc}", file=sys.stderr)
        return 1
    print("\n".join(frame_lines(frame)))
    if args.slot is None:
        return 0
    chosen = next((s for s in frame.slots if s.slot == args.slot), None)
    if chosen is None:
        print(f"[scene-walk] slot {args.slot} is not drawn at tick {frame.tick}", file=sys.stderr)
        return 1
    if chosen.extent is None:
        print(f"[scene-walk] no archive holds shape 0x{chosen.shape:04X}", file=sys.stderr)
        return 1
    exe = read_data_file_or_report("scene_walk", args.image or unlzexe.default_exe())
    if exe is None:
        return 2
    try:
        tree = scene_tree.tree_segment(xref.load(exe).data)
        entry = scene_tree.SlotEntry(*chosen.position, chosen.extent)
        walked = scene_tree.walk_slot(tree, frame.eye, frame.target, entry)
    except ValueError as exc:
        print(f"[scene-walk] {exc}", file=sys.stderr)
        return 1
    print("\n".join(walk_lines(walked, args.context)))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
