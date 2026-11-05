"""Synthetic load images and pairings for the offline `dbx` tests."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from build_pairing import MEM, Function, Insn, LoadImage, Pairing, VoteKey

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


def image(
    size: int = 0xA000, *, slots_at: int = 0x8240, slots: int = 108, relocs: Iterable[int] = ()
) -> LoadImage:
    """*size* zero bytes with *slots* dispatch slots (`26 C7 44 FE imm16 E9 rel16`) at *slots_at*."""
    data = bytearray(size)
    for i in range(slots):
        at = slots_at + 9 * i
        data[at : at + 6] = bytes.fromhex("26c744fe") + (0x1000 + i).to_bytes(2, "little")
        data[at + 6 : at + 9] = b"\xe9" + (0x0100).to_bytes(2, "little")
    return LoadImage(bytes(data), frozenset(relocs), 0, 0, 0)


def put(img: LoadImage, offset: int, data: bytes) -> LoadImage:
    """A copy of *img* with *data* written at *offset*."""
    buf = bytearray(img.data)
    buf[offset : offset + len(data)] = data
    return LoadImage(bytes(buf), img.relocs, img.entry_cs, img.entry_ip, img.stack_paragraph)


def _function(start: int, end: int) -> Function:
    return Function(0, start, (Insn(start, (), (), ""), Insn(end, (), (), "")))


def pairing(
    *,
    code: Mapping[int, int] | None = None,
    functions: Sequence[tuple[int, int, float]] = (),
    data: Mapping[int, int] | None = None,
) -> Pairing:
    """A pairing that knows only *code*, *functions* `(start, end, ratio)` and *data* offsets."""
    votes: dict[VoteKey, Counter[int]] = {
        (0, MEM, "", left): Counter({right: 3}) for left, right in (data or {}).items()
    }
    return Pairing(
        left=image(),
        right=image(),
        segments={},
        stats=[],
        functions=[(_function(s, e), _function(s, e), r) for s, e, r in functions],
        code=dict(code or {}),
        votes=votes,
        sites={},
    )
