"""List corpus films whose view slot can queue its own shadow (#510 journal).

Walks every distinct `.FLM` (by SHA-256) under a corpus root. Per film it counts the ticks whose
view slot (`view_obj`, opcodes `0x90..0x97`) has `SIF_EXISTS`, `SIF_DRAW` and `SIF_SHADOW` and a
nonzero shape, the view slot's lowest and median stream height over those ticks (metres up), and
the slots that are drawn and shadowed but lack `SIF_MOVES` (#499 item 2). A film `walk_film`
rejects is skipped. Prints one line per film with view-slot shadow ticks, lowest median height
first; nothing is written.

Given one `.FLM` instead of a directory, prints each such slice's tick, view slot, flags, shape
and height.

Usage, from the repository root:
`mise exec -- uv run python work/2026-11/510_view-slot-shadow/view_shadow_census.py <corpus dir>`
"""

from __future__ import annotations

import hashlib
import statistics
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "python"))

from stunt_reel.flm_walk import SLICE_HEADER_SIZE, FlmWalkError, walk_film

SHADOWED = 0x07  # SIF_EXISTS | SIF_DRAW | SIF_SHADOW


def view_shadow(
    data: bytes, spans: list[tuple[int, int, int, int, float]] | None = None
) -> tuple[int, list[float], set[int], set[int], int]:
    """Return view-slot shadow ticks, their heights, the view slots, static shadow slots, length.

    With `spans`, also append `(tick, view slot, flags, shape, height)` for each such slice.
    """
    tick = 0
    view = -1
    flags: dict[int, int] = {}
    shape: dict[int, int] = {}
    ypos: dict[int, float] = {}
    ticks = 0
    heights: list[float] = []
    views: set[int] = set()
    static: set[int] = set()
    for sv in walk_film(data):
        p = sv.start + SLICE_HEADER_SIZE
        moves, rotates, animates = sv.moves, sv.rotates, sv.animates
        while p < sv.end:
            tag = data[p]
            p += 1
            if tag == 0xFF:
                break
            group, slot = tag >> 6, tag & 0x3F
            bit = 1 << slot
            if group == 0:
                f = data[p]
                p += 1
                flags[slot] = f
                moves = moves | bit if f & 0x08 else moves & ~bit
                rotates = rotates | bit if f & 0x10 else rotates & ~bit
                animates = animates | bit if f & 0x20 else animates & ~bit
                if f & 0x01:
                    if f & 0x02:
                        shape[slot] = struct.unpack_from("<H", data, p)[0]
                        p += 2
                    if not f & 0x08:
                        ypos[slot] = -struct.unpack_from("<i", data, p + 4)[0] / 65536
                        p += 12
                    p += 0 if f & 0x10 else 6
                if f & 0x0F == SHADOWED and shape.get(slot):
                    static.add(slot)
            elif group == 1:
                if moves & bit:
                    ypos[slot] = -struct.unpack_from("<i", data, p + 4)[0] / 65536
                    p += 12
                p += 6 if rotates & bit else 0
                p += 2 if animates & bit else 0
            elif 0x90 <= tag <= 0x97:
                view = tag - 0x90
            elif tag < 0x90 or tag >= 0xA0:
                p += 2
            elif tag == 0x99:
                p = data.index(b"\0", data.index(b"\0", p) + 1) + 1
            elif tag == 0x9B:
                p += 1
            elif tag == 0x9C:
                p += 3
        step = data[sv.start + 2]
        if step != 0xFF and flags.get(view, 0) & SHADOWED == SHADOWED and shape.get(view):
            ticks += step
            views.add(view)
            if view in ypos:
                heights.append(ypos[view])
            if spans is not None:
                spans.append((tick, view, flags[view], shape[view], ypos.get(view, float("nan"))))
        tick += step if step != 0xFF else 0
    return ticks, heights, views, static, tick


def main(argv: list[str]) -> int:
    """Print the census for the corpus root in `argv[0]`."""
    root = Path(argv[0])
    if root.is_file():
        spans: list[tuple[int, int, int, int, float]] = []
        view_shadow(root.read_bytes(), spans)
        for tick, view, f, shp, y in spans:
            print(f"tick {tick:6d} view {view} flags {f:#04x} shape {shp:#06x} up {y:8.2f}")
        return 0
    seen: set[str] = set()
    rows: list[tuple[float, str]] = []
    for path in sorted(root.rglob("*.FLM")):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        try:
            ticks, heights, views, static, length = view_shadow(data)
        except (FlmWalkError, IndexError, ValueError, struct.error):
            continue
        if not ticks:
            continue
        med = statistics.median(heights) if heights else float("nan")
        low = min(heights) if heights else float("nan")
        rows.append(
            (
                med,
                f"{ticks:6d}/{length:<6d} low {low:8.2f} med {med:8.2f} views {sorted(views)} "
                f"static {sorted(static)} {path.relative_to(root)}",
            )
        )
    for _, line in sorted(rows):
        print(line)
    print(f"{len(rows)} films of {len(seen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
