"""Dump the film-level events of an `.FLM` film, one line per event with its tick.

Lists slot creates, variable sets (tags `0x80`-`0x8F`), "before" sets (`0xA0`+), the
`0x90`-`0x98` ops, credits, max-object and sound opcodes (sounds only with `--sounds`).
Ticks are the running sum of the slice durations *before* the event's slice, as quoted in
``research/playone-exe/palette-fade.md`` section 5.1; by the slice-end convention in
section 5 the engine applies the event one slice duration later.

Reads a film from the local, gitignored ``corpus/``; nothing it prints is committed
(see ``AGENTS.md``).

Usage: ``python python/scripts/flm_events.py corpus/.../CTRY.FLM [--sounds]``
"""

from __future__ import annotations

import sys
from pathlib import Path

from stunt_reel.flm_walk import (
    SIF_ANIMATES,
    SIF_DRAW,
    SIF_EXISTS,
    SIF_MOVES,
    SIF_ROTATES,
    SLICE_HEADER_SIZE,
    walk_film,
)


def _u16(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 2], "little")


def film_events(data: bytes, *, sounds: bool = False) -> tuple[int, list[tuple[int, str]]]:
    """Return the film's total ticks and its ``(tick, description)`` events."""
    tick = 0
    events: list[tuple[int, str]] = []
    for view in walk_film(data):
        duration = data[view.start + 2]
        pos = view.start + SLICE_HEADER_SIZE
        moves, rotates, animates = view.moves, view.rotates, view.animates
        while pos < view.end:
            tag = data[pos]
            pos += 1
            if tag == 0xFF:
                break
            group, slot = tag >> 6, tag & 0x3F
            bit = 1 << slot
            if group == 0:
                flags = data[pos]
                pos += 1
                moves = moves | bit if flags & SIF_MOVES else moves & ~bit
                rotates = rotates | bit if flags & SIF_ROTATES else rotates & ~bit
                animates = animates | bit if flags & SIF_ANIMATES else animates & ~bit
                if flags & SIF_EXISTS:
                    pos += 2 if flags & SIF_DRAW else 0
                    pos += 0 if flags & SIF_MOVES else 12
                    pos += 0 if flags & SIF_ROTATES else 6
                events.append((tick, f"create slot {slot} flags {flags:#04x}"))
            elif group == 1:
                pos += 12 if moves & bit else 0
                pos += 6 if rotates & bit else 0
                pos += 2 if animates & bit else 0
            elif tag < 0x90:
                events.append((tick, f"var_set {tag & 15} = {_u16(data, pos)}"))
                pos += 2
            elif tag <= 0x98:
                events.append((tick, f"op {tag:#04x}"))
            elif tag == 0x99:
                end = data.index(b"\0", pos)
                end2 = data.index(b"\0", end + 1)
                events.append((tick, f"credits {data[pos:end]!r} {data[end + 1 : end2]!r}"))
                pos = end2 + 1
            elif tag == 0x9B:
                events.append((tick, f"max_obj {data[pos]}"))
                pos += 1
            elif tag == 0x9C:
                if sounds:
                    events.append((tick, f"sound {data[pos]} {_u16(data, pos + 1):#06x}"))
                pos += 3
            elif tag >= 0xA0:
                events.append((tick, f"before {tag & 31} = {_u16(data, pos)}"))
                pos += 2
        tick += duration
    return tick, events


def main(argv: list[str]) -> int:
    paths = [arg for arg in argv[1:] if not arg.startswith("--")]
    if len(paths) != 1:
        print(__doc__)
        return 2
    total, events = film_events(Path(paths[0]).read_bytes(), sounds="--sounds" in argv)
    print("total ticks", total)
    for tick, description in events:
        print(tick, description)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
