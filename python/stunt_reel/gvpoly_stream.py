"""`GVPOLY` records of PLAYONE's live, slot-patched display list.

A `GVPOLY` handler (op `0x168` at image `0x995C`, op `0x2BE` `GVPOLY16` at `0x9A24`) is entered with `ES:SI`
on the record's first word, because the dispatch slot has already consumed the opcode word at
`SI-2` and patched it into the handler's VM-space IP (`research/playone-exe/world-scene.md`
section 4). A record is `count`, `count` vertex-register offsets (read by the edge builder
`0xC9D4`), the ramp word `(base << 8) | count`, one shade offset per vertex, then the next IP
(`research/playone-exe/sod-vm.md` section 8.5). `base` is the palette index the Gouraud ramp
starts from.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Polygon:
    """One `GVPOLY` record: where its first word sits, its handler and its words."""

    linear: int
    handler: int  # the handler's image offset
    base: int  # ramp base palette index
    count: int
    regs: tuple[int, ...]  # vertex-register byte offsets
    shades: tuple[int, ...]
    next_ip: int

    @property
    def size(self) -> int:
        """Bytes from the first word to the end of the next-IP word."""
        return 6 + 2 * len(self.regs) + 2 * len(self.shades)


def decode_record(data: bytes, linear: int, handler: int) -> Polygon | None:
    """The record at the start of *data*, or None when *data* is too short to hold it."""
    if len(data) < 2:
        return None
    (count,) = struct.unpack_from("<H", data)
    ramp_at = 2 + 2 * count
    if len(data) < ramp_at + 2:
        return None
    regs = struct.unpack_from(f"<{count}H", data, 2)
    (ramp,) = struct.unpack_from("<H", data, ramp_at)
    # The Gouraud loop counts shades with `dec cl` over the ramp word's whole low byte
    # (`0x9ACF`); only the skip tail masks it to `& 0x0F` (`0x9A38`).
    shade_count = ramp & 0xFF
    if len(data) < ramp_at + 4 + 2 * shade_count:
        return None
    words = struct.unpack_from(f"<{shade_count + 1}H", data, ramp_at + 2)
    return Polygon(
        linear, handler, ramp >> 8, count, regs, tuple(words[:shade_count]), words[shade_count]
    )
