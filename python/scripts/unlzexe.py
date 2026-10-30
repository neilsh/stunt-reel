"""Minimal LZEXE 0.91 unpacker for `PLAYONE.EXE` analysis.

LZEXE 0.91 is by Fabrice Bellard; this is a minimal Python unpacker written for
analysis, not a copy or distribution of LZEXE.

Writes the unpacked load image (no MZ header) to ``out`` and ``out.json`` holding the entry
registers, image size and relocation linear offsets. Reads a proprietary executable from the
local, gitignored ``corpus/stuntisl/``; nothing it produces is committed (see ``AGENTS.md``).

Usage: ``python python/scripts/unlzexe.py corpus/stuntisl/PLAYONE.EXE build/re/playone.img``

With ``--mz`` the output is instead a complete unpacked MZ executable (header plus image), for
tools such as Ghidra that load MZ files:
``python python/scripts/unlzexe.py --mz corpus/stuntisl/PLAYONE.EXE build/re/playone_unpacked.exe``
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path
from typing import cast

from stunt_reel.dataroot import REPO_ROOT, ensure_links_or_report


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


def to_mz(image: bytes | bytearray, meta: dict[str, object]) -> bytes:
    """Wrap the image in an MZ header with a plain relocation table, for Ghidra's ``MzLoader``.

    The header is padded to 512 bytes, which for `PLAYONE.EXE` gives the 1,024-byte header and
    201,548-byte file recorded in ``research/playone-exe/startup.md``.
    """
    entry = cast("dict[str, int]", meta["entry"])
    relocs = cast("list[int]", meta["relocs"])
    hdr_len = -(-(0x1C + 4 * len(relocs)) // 512) * 512
    total = hdr_len + len(image)
    stack_top = entry["ss"] * 16 + entry["sp"]
    min_alloc = max(0, -(-(stack_top - len(image)) // 16))
    hdr = bytearray(hdr_len)
    struct.pack_into(
        "<2s13H",
        hdr,
        0,
        b"MZ",
        total % 512,
        -(-total // 512),
        len(relocs),
        hdr_len // 16,
        min_alloc,
        0xFFFF,
        entry["ss"],
        entry["sp"],
        0,
        entry["ip"],
        entry["cs"],
        0x1C,
        0,
    )
    for i, lin in enumerate(relocs):
        struct.pack_into("<2H", hdr, 0x1C + 4 * i, lin & 0x0F, lin >> 4)
    return bytes(hdr) + bytes(image)


def main(argv: list[str]) -> int:
    mz = "--mz" in argv
    argv = [a for a in argv if a != "--mz"]
    if len(argv) != 3:
        print(__doc__)
        return 2
    # Only a corpus input needs the data root linked; any other file reads as it is.
    reads_corpus = Path(os.path.abspath(argv[1])).is_relative_to(REPO_ROOT / "corpus")
    if reads_corpus and not ensure_links_or_report("unlzexe"):
        return 2
    image, meta = unpack(Path(argv[1]).read_bytes())
    out = Path(argv[2])
    out.write_bytes(to_mz(image, meta) if mz else image)
    Path(f"{out}.json").write_text(json.dumps(meta), encoding="utf-8")
    print(len(image), meta["entry"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
