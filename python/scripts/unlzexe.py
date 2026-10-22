"""Minimal LZEXE 0.91 unpacker for `PLAYONE.EXE` analysis.

Writes the unpacked load image (no MZ header) to ``out`` and ``out.json`` holding the entry
registers, image size and relocation linear offsets. Reads a proprietary executable from the
local, gitignored ``target_bin/``; nothing it produces is committed (see ``AGENTS.md``).

Usage: ``python python/scripts/unlzexe.py target_bin/PLAYONE.EXE build/re/playone.img``
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def _relocations(d: bytes, loader: int) -> list[int]:
    """Decode the compressed relocation table (0.91 layout: loader + 0x158)."""
    p = loader + 0x158
    relocs: list[int] = []
    rel_off = rel_seg = 0
    while True:
        span = d[p]
        p += 1
        if span == 0:
            span = struct.unpack_from("<H", d, p)[0]
            p += 2
            if span == 0:
                rel_seg += 0x0FFF
                continue
            if span == 1:
                break
        rel_off += span
        rel_seg += (rel_off & ~0x0F) >> 4
        rel_off &= 0x0F
        relocs.append(rel_seg * 16 + rel_off)
    return relocs


def _decompress(d: bytes, start: int) -> bytearray:
    """Run the LZ91 bit stream that begins at ``start``."""
    p = start
    buf: int = struct.unpack_from("<H", d, p)[0]
    p += 2
    count = 16

    def bit() -> int:
        nonlocal buf, count, p
        b: int = buf & 1
        count -= 1
        if count == 0:
            buf = struct.unpack_from("<H", d, p)[0]
            p += 2
            count = 16
        else:
            buf >>= 1
        return b

    o = bytearray()
    while True:
        if bit():
            o.append(d[p])
            p += 1
            continue
        if not bit():
            length = ((bit() << 1) | bit()) + 2
            span = d[p] - 256
            p += 1
        else:
            lo, hi = d[p], d[p + 1]
            p += 2
            span = (lo | ((hi & ~0x07) << 5) | 0xE000) - 0x10000
            length = (hi & 0x07) + 2
            if length == 2:
                length = d[p]
                p += 1
                if length == 0:
                    break
                if length == 1:
                    continue
                length += 1
        for _ in range(length):
            o.append(o[len(o) + span])
    return o


def unpack(d: bytes) -> tuple[bytearray, dict[str, object]]:
    """Return the unpacked image and its metadata."""
    h = struct.unpack_from("<14H", d, 0)
    hdr_par, cs = h[4], h[11]
    if d[0x1C:0x20] != b"LZ91":
        raise ValueError("not an LZEXE 0.91 executable")
    loader = (hdr_par + cs) * 16
    ip, entry_cs, sp, ss = struct.unpack_from("<4H", d, loader)
    image = _decompress(d, hdr_par * 16)
    meta: dict[str, object] = {
        "entry": {"ip": ip, "cs": entry_cs, "sp": sp, "ss": ss},
        "size": len(image),
        "relocs": _relocations(d, loader),
    }
    return image, meta


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    image, meta = unpack(Path(argv[1]).read_bytes())
    out = Path(argv[2])
    out.write_bytes(image)
    Path(f"{out}.json").write_text(json.dumps(meta), encoding="utf-8")
    print(len(image), meta["entry"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
