"""Map offsets between two builds of an LZEXE program by pairing their functions.

Unpacks both executables (``unlzexe.py``), pairs their code segments, functions and
instructions with an iced-x86 decode (``build_pairing.py`` beside this script), and prints what each
requested data offset or code address became. Defaults to the unpatched and Patch #3
``PLAYONE.EXE`` that ``mise run game-builds`` writes under ``<data root>/builds/``; the method and
the resulting map are in ``research/playone-exe/patch3.md`` section 4 and
``research/playone-exe/memory-map.md`` section 1.1. Nothing it reads or prints is committed.

Usage::

    mise run pair-builds                          # segment and function summary, DGROUP shift runs
    mise run pair-builds -- --ds 0x0542,0x49EC    # DGROUP offsets (the entry segment's DS)
    mise run pair-builds -- --ds 0x8072@0x824     # DS offsets as segment 0x824's code reads them
    mise run pair-builds -- --ds 0x8078@0:es      # ES-relative offsets read by segment 0
    mise run pair-builds -- --code 0x196C,0x9100  # load-image code addresses
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

import unlzexe
from build_pairing import (
    DISPLACEMENT,
    FAR_CALL,
    IMMEDIATE,
    REFERENCED,
    LoadImage,
    Pairing,
    dispatch_slots,
    map_code,
    map_data,
    pair_images,
    pair_slots,
    shift_runs,
    signed,
)

from stunt_reel import dataroot, game_builds

#: What each kind of direct evidence counts.
NOUNS: dict[str, str] = {
    REFERENCED: "memory operands",
    DISPLACEMENT: "displacements",
    IMMEDIATE: "immediates",
}
#: The bytes compared at a mapped DGROUP offset to corroborate it.
CONTENT_BYTES: int = 16


def load(path: Path) -> LoadImage:
    """Unpack an LZEXE 0.91 executable into a load image."""
    image, meta = unlzexe.unpack(path.read_bytes())
    entry = cast("dict[str, int]", meta["entry"])
    relocs = cast("list[int]", meta["relocs"])
    return LoadImage(bytes(image), frozenset(relocs), entry["cs"], entry["ip"], entry["ss"])


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    builds = dataroot.data_root() / game_builds.BUILDS_DIR
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--left", type=Path, default=builds / "unpatched" / "PLAYONE.EXE")
    parser.add_argument("--right", type=Path, default=builds / "patched" / "PLAYONE.EXE")
    parser.add_argument(
        "--ds", default="", help="comma-separated data offsets, each OFF[@SEGMENT][:OVERRIDE]"
    )
    parser.add_argument("--code", default="", help="comma-separated load-image code addresses")
    parser.add_argument("--unpaired", action="store_true", help="list unpaired functions")
    parser.add_argument(
        "--slots",
        type=lambda text: int(text, 16),
        metavar="SEGMENT",
        help="pair the display-list dispatch slots at the start of this left code segment",
    )
    args = parser.parse_args(argv)
    # Check every hex value here, so a typo exits 2 with a usage message before the builds load.
    for spec in filter(None, args.ds.split(",")):
        off_text, _, seg_text = spec.partition(":")[0].partition("@")
        _hex_or_exit(parser, "--ds", off_text, seg_text)
    _hex_or_exit(parser, "--code", *filter(None, args.code.split(",")))
    return args


def _hex_or_exit(parser: argparse.ArgumentParser, flag: str, *values: str) -> None:
    """Exit through *parser* when a non-empty value among *values* is not hexadecimal."""
    for value in filter(None, values):
        try:
            int(value, 16)
        except ValueError:
            parser.error(f"{flag}: {value!r} is not a hexadecimal number")


def _content(pairing: Pairing, offset: int, mapped: int) -> str:
    """How many bytes at the two DGROUP offsets agree, or where the left bytes occur."""
    lbase, rbase = pairing.left.dgroup() * 16, pairing.right.dgroup() * 16
    left = pairing.left.data[lbase + offset : lbase + offset + CONTENT_BYTES]
    right = pairing.right.data[rbase + mapped : rbase + mapped + CONTENT_BYTES]
    same = next((i for i, (a, b) in enumerate(zip(left, right, strict=False)) if a != b), None)
    compared = min(len(left), len(right))  # shorter near the end of an image
    return f"{compared if same is None else same}/{CONTENT_BYTES} bytes equal"


def _search(pairing: Pairing, offset: int) -> str:
    """Where the left DGROUP bytes at *offset* occur in the right DGROUP, if once."""
    lbase, rbase = pairing.left.dgroup() * 16, pairing.right.dgroup() * 16
    needle = pairing.left.data[lbase + offset : lbase + offset + CONTENT_BYTES]
    if len(set(needle)) < 3:
        return "bytes too uniform to search"
    hay = pairing.right.data[rbase : rbase + 0x10000]
    first = hay.find(needle)
    if first < 0:
        return "bytes not found"
    if hay.find(needle, first + 1) >= 0:
        return "bytes occur more than once"
    return f"bytes occur once, at {first:#06x}"


def report_data(pairing: Pairing, spec: str) -> None:
    """Print one ``OFF[@SEGMENT][:OVERRIDE]`` query; SEGMENT defaults to the entry segment."""
    head, _, override = spec.partition(":")
    off_text, _, seg_text = head.partition("@")
    offset = int(off_text, 16)
    paragraph = int(seg_text, 16) if seg_text else pairing.left.entry_cs
    found = map_data(pairing, offset, paragraph, override)
    dgroup = paragraph == pairing.left.entry_cs and not override
    line = f"{override or 'ds'}:{offset:#06x} (segment {paragraph:#06x} code)"
    if found.mapped is None:
        line += " unmapped"
    else:
        line += f" -> {found.mapped:#06x}  shift {signed(found.mapped - offset):+#x}, {found.how}"
    if found.how in NOUNS:
        noun = NOUNS[found.how]
        line += f" ({found.agreeing} of {found.references} {noun})"
    else:
        near = ", ".join(
            f"{n:#06x}->{map_data(pairing, n, paragraph, override).mapped or 0:#06x}"
            for n in (found.below, found.above)
            if n is not None
        )
        line += f"; neighbours {near}"
    if dgroup:
        line += "; " + (
            _content(pairing, offset, found.mapped)
            if found.mapped is not None
            else _search(pairing, offset)
        )
    print(line)


def report_code(pairing: Pairing, addr: int) -> None:
    """Print one code-address query."""
    found = map_code(pairing, addr)
    if found.mapped is None:
        print(f"code {addr:#07x} unmapped (in no paired function, and no paired far call)")
        return
    pair = pairing.function_at(addr)
    detail = (
        f"{found.agreeing} of {found.references} paired far calls"
        if found.how == FAR_CALL
        else f"function {pair[0].start:#07x} -> {pair[1].start:#07x}, similarity {pair[2]:.2f}"
        if pair
        else ""
    )
    print(f"code {addr:#07x} -> {found.mapped:#07x}  {found.how}; {detail}")


def report_summary(pairing: Pairing, unpaired: bool) -> None:
    """Print the segment pairing and the DGROUP shift runs."""
    print(f"DGROUP {pairing.left.dgroup():#06x} -> {pairing.right.dgroup():#06x}")
    for s in pairing.stats:
        print(
            f"segment {s.left:#06x} -> {s.right:#06x}: functions {s.left_functions}/"
            f"{s.right_functions}, {s.exact} identical, {s.paired} paired, "
            f"{s.aligned} instructions aligned"
        )
        if unpaired:
            print("  unpaired left:", " ".join(f"{a:#07x}" for a in s.unpaired_left))
            print("  unpaired right:", " ".join(f"{a:#07x}" for a in s.unpaired_right))
    print("DGROUP offsets referenced by segment-0 code, in runs of one shift:")
    for run in shift_runs(pairing, pairing.left.entry_cs):
        print(f"  {run.first:#06x}..{run.last:#06x} {run.shift:+#07x} ({run.offsets} offsets)")


def report_slots(pairing: Pairing, paragraph: int) -> None:
    """Print how the left dispatch slots pair with the right ones, in runs of one index shift."""
    right = len(dispatch_slots(pairing.right, pairing.segments[paragraph]))
    pairs = pair_slots(pairing, paragraph)
    print(f"dispatch slots: {len(pairs)} left, {right} right (opcode = index x 9)")
    runs: list[tuple[int, int, int | None]] = []
    for k, j in pairs:
        shift = None if j is None else j - k
        if runs and runs[-1][2] == shift and runs[-1][1] == k - 1:
            runs[-1] = (runs[-1][0], k, shift)
        else:
            runs.append((k, k, shift))
    for first, last, shift in runs:
        what = "no right slot pairs" if shift is None else f"right index {shift:+d}"
        print(f"  left slots {first}..{last} (opcodes {9 * first:#06x}..{9 * last:#06x}): {what}")


def main(argv: list[str]) -> int:
    """Pair the two builds and print the summary or the requested mappings."""
    args = parse_args(argv)
    try:
        pairing = pair_images(load(args.left), load(args.right))
    except (OSError, ValueError) as err:  # no build there, not LZEXE, or unpairable code
        print(f"pair-builds: {err}", file=sys.stderr)
        return 2
    if not args.ds and not args.code and args.slots is None:
        report_summary(pairing, args.unpaired)
    if args.slots is not None:
        report_slots(pairing, args.slots)
    for spec in filter(None, args.ds.split(",")):
        report_data(pairing, spec)
    for addr in filter(None, args.code.split(",")):
        report_code(pairing, int(addr, 16))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
