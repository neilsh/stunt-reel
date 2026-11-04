"""`GVPOLY` records of PLAYONE's live, slot-patched display list.

A `GVPOLY` handler (op `0x168` at image `0x995C`, op `0x2BE` `GVPOLY16` at `0x9A24`) is entered with `ES:SI`
on the record's first word, because the dispatch slot has already consumed the opcode word at
`SI-2` and patched it into the handler's VM-space IP (`research/playone-exe/world-scene.md`
sections 4 and 4.1). A record is `w0 = (colour << 8) | (count & 0x0F)`, `count` shade-index words,
then the next IP; the stream is threaded, so the next record's first word follows that IP.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class Polygon:
    """One `GVPOLY` record: where its first word sits, its handler and its words."""

    linear: int
    handler: int  # the handler's image offset
    colour: int
    count: int
    shades: tuple[int, ...]
    next_ip: int

    @property
    def size(self) -> int:
        """Bytes from the first word to the end of the next-IP word."""
        return 4 + 2 * self.count


def decode_record(data: bytes, linear: int, handler: int) -> Polygon | None:
    """The record at the start of *data*, or None when *data* is too short to hold it."""
    if len(data) < 2:
        return None
    (w0,) = struct.unpack_from("<H", data)
    count = w0 & 0x0F
    if len(data) < 4 + 2 * count:
        return None
    words = struct.unpack_from(f"<{count + 1}H", data, 2)
    return Polygon(linear, handler, w0 >> 8, count, tuple(words[:count]), words[count])


def follow(poly: Polygon, dump: bytes, base: int, handler_ips: Mapping[int, int]) -> list[Polygon]:
    """The records that follow *poly* in *dump* (linear start *base*) while each next IP is a
    `GVPOLY` handler's; stops at another op or at the end of the dump."""
    chain: list[Polygon] = []
    while poly.next_ip in handler_ips:
        linear = poly.linear + poly.size
        offset = linear - base
        if offset < 0:
            break
        nxt = decode_record(dump[offset:], linear, handler_ips[poly.next_ip])
        if nxt is None:
            break
        chain.append(nxt)
        poly = nxt
    return chain
