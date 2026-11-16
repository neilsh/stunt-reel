"""Count corpus films with a drawn, shadowed slot more than 100 m up (#512 journal).

Walks every distinct `.FLM` (by SHA-256) under a corpus root and reports, per film, the slices
where a slot's last create has `SIF_EXISTS`, `SIF_DRAW` and `SIF_SHADOW` and its last stream `y`
is below the threshold (y-down metres, so -100 is 100 m up). A film `walk_film` rejects counts as
having none. Prints the films with hits, most first, and the totals; nothing is written.

Usage, from the repository root:
`mise exec -- uv run python work/2026-11/512_altitude-cutoff/high_shadow_census.py <corpus dir> [-100]`
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "python"))

from stunt_reel.flm_walk import SLICE_HEADER_SIZE, FlmWalkError, walk_film

SHADOWED = 0x07  # SIF_EXISTS | SIF_DRAW | SIF_SHADOW


def high_slices(data: bytes, threshold: float) -> list[tuple[int, int, float]]:
    """Return `(tick, slot, y)` for each slice end where a shadowed slot is above the threshold."""
    tick = 0
    flags: dict[int, int] = {}
    pos3: dict[int, tuple[int, int, int]] = {}
    out: list[tuple[int, int, float]] = []
    for view in walk_film(data):
        p = view.start + SLICE_HEADER_SIZE
        moves, rotates, animates = view.moves, view.rotates, view.animates
        while p < view.end:
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
                    p += 2 if f & 0x02 else 0
                    if not f & 0x08:
                        pos3[slot] = struct.unpack_from("<iii", data, p)
                        p += 12
                    p += 0 if f & 0x10 else 6
            elif group == 1:
                if moves & bit:
                    pos3[slot] = struct.unpack_from("<iii", data, p)
                    p += 12
                p += 6 if rotates & bit else 0
                p += 2 if animates & bit else 0
            elif tag < 0x90 or tag >= 0xA0:
                p += 2
            elif tag == 0x99:
                p = data.index(b"\0", data.index(b"\0", p) + 1) + 1
            elif tag == 0x9B:
                p += 1
            elif tag == 0x9C:
                p += 3
        for slot, f in flags.items():
            if f & SHADOWED == SHADOWED and slot in pos3:
                y = pos3[slot][1] / 65536
                if y < threshold:
                    out.append((tick, slot, y))
        tick += data[view.start + 2]
    return out


def main(argv: list[str]) -> int:
    """Print the census for the corpus root in `argv[0]`."""
    root = Path(argv[0])
    threshold = float(argv[1]) if len(argv) > 1 else -100.0
    seen: set[str] = set()
    rows: list[tuple[int, float, str]] = []
    for path in sorted(root.rglob("*.FLM")):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        try:
            hits = high_slices(data, threshold)
        except (FlmWalkError, IndexError, ValueError, struct.error):
            continue
        if hits:
            rows.append((len(hits), min(h[2] for h in hits), str(path.relative_to(root))))
    for count, lowest, name in sorted(rows, reverse=True):
        print(f"{count:6d} {lowest:10.1f} {name}")
    print(f"{len(rows)} films of {len(seen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
