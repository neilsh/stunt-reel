"""Inter-slice state for `.FLM` files, which a Kaitai schema cannot express.

An `.FLM` film is a chain of time slices; each 3-byte slice header carries the
byte distance back to the previous header. Opcode payload widths inside a slice
depend on the slot flags bound by the most recent `create` for that slot, so no
stateless schema can walk the chain. `research/formats/flm_slice.ksy` parses one
slice given the three slot masks; `walk_film` supplies them.

The rules mirror `FlmParser::parse_slice` in `crates/stunt-core/src/flm/parser.rs`,
which stays authoritative for engine behaviour; this walker only produces slice
bounds and masks.
"""

from __future__ import annotations

from dataclasses import dataclass

FILM_MAGIC: bytes = b"FILM"
SLICE_HEADER_SIZE: int = 3
SIF_EXISTS: int = 0x01
SIF_DRAW: int = 0x02
SIF_MOVES: int = 0x08
SIF_ROTATES: int = 0x10
SIF_ANIMATES: int = 0x20


class FlmWalkError(Exception):
    """Raised when a film does not follow the documented opcode grammar."""


@dataclass(frozen=True)
class SliceView:
    """One time slice, plus the slot masks in force when its header was read."""

    index: int
    start: int
    end: int  # exclusive; positioned just past the 0xFF terminator
    moves: int  # bit i set when slot i carries SIF_MOVES at slice start
    rotates: int
    animates: int


def _take(pos: int, count: int, size: int, tag: int, offset: int) -> int:
    """Advance `count` bytes, rejecting a stream that ends mid-opcode."""
    if pos + count > size:
        raise FlmWalkError(f"truncated opcode {tag:#04x} at {offset}")
    return pos + count


def _byte(data: bytes, pos: int, tag: int, offset: int) -> int:
    """Read one payload byte, rejecting a stream that ends mid-opcode."""
    if pos >= len(data):
        raise FlmWalkError(f"truncated opcode {tag:#04x} at {offset}")
    return data[pos]


def _skip_strz(data: bytes, pos: int, tag: int, offset: int) -> int:
    """Skip one NUL-terminated ASCII string, returning the position after it."""
    end = data.find(b"\x00", pos)
    if end < 0:
        raise FlmWalkError(f"truncated opcode {tag:#04x} at {offset}")
    return end + 1


def walk_film(data: bytes) -> list[SliceView]:
    """Walk one film and return its slices, or raise FlmWalkError."""
    if data[:4] != FILM_MAGIC:
        raise FlmWalkError(f"missing FILM magic: {data[:4]!r}")
    size = len(data)
    pos = len(FILM_MAGIC)
    moves = rotates = animates = 0
    index = 0
    previous_start: int | None = None
    views: list[SliceView] = []
    while True:
        header_start = pos
        if size - pos < SLICE_HEADER_SIZE:
            raise FlmWalkError(f"truncated slice header at {pos}")
        prev_slice_len = int.from_bytes(data[pos : pos + 2], "little")
        pos += SLICE_HEADER_SIZE
        if previous_start is not None and prev_slice_len != header_start - previous_start:
            raise FlmWalkError(
                f"slice {index} prev_slice_len {prev_slice_len} != {header_start - previous_start}"
            )
        if pos == size:
            # Header-only trailer: `tick_duration` is not validated (it is 0x00
            # in MAMMOTH.FLM and MAMMOTH2.FLM) and the group is not a slice.
            return views
        # Masks are recorded here, at header time: the schema sizes the first
        # opcode of the slice with them, and `create` mutates them from there.
        start_moves, start_rotates, start_animates = moves, rotates, animates
        terminated = False
        while pos < size:
            offset = pos
            tag = data[pos]
            pos += 1
            if tag == 0xFF:
                terminated = True
                break
            group = tag >> 6
            slot = tag & 0x3F
            bit = 1 << slot
            if group == 0:
                flags = _byte(data, pos, tag, offset)
                pos += 1
                # A slot may be re-created with a flag cleared, which is why the
                # mask is rewritten rather than only accumulated.
                if flags & SIF_MOVES:
                    moves |= bit
                else:
                    moves &= ~bit
                if flags & SIF_ROTATES:
                    rotates |= bit
                else:
                    rotates &= ~bit
                if flags & SIF_ANIMATES:
                    animates |= bit
                else:
                    animates &= ~bit
                if flags & SIF_EXISTS:
                    if flags & SIF_DRAW:
                        pos = _take(pos, 2, size, tag, offset)
                    if (flags & SIF_MOVES) == 0:
                        pos = _take(pos, 12, size, tag, offset)
                    if (flags & SIF_ROTATES) == 0:
                        pos = _take(pos, 6, size, tag, offset)
            elif group == 1:
                if (moves >> slot) & 1:
                    pos = _take(pos, 12, size, tag, offset)
                if (rotates >> slot) & 1:
                    pos = _take(pos, 6, size, tag, offset)
                if (animates >> slot) & 1:
                    pos = _take(pos, 2, size, tag, offset)
            elif group == 2:
                if tag < 0x90:
                    pos = _take(pos, 2, size, tag, offset)
                elif tag <= 0x98:
                    pass
                elif tag == 0x99:
                    pos = _skip_strz(data, pos, tag, offset)
                    pos = _skip_strz(data, pos, tag, offset)
                elif tag == 0x9B:
                    pos = _take(pos, 1, size, tag, offset)
                elif tag == 0x9C:
                    pos = _take(pos, 3, size, tag, offset)
                elif tag >= 0xA0:
                    pos = _take(pos, 2, size, tag, offset)
                else:
                    raise FlmWalkError(f"unsupported opcode {tag:#04x} at {offset}")
            else:
                raise FlmWalkError(f"unsupported opcode {tag:#04x} at {offset}")
        if not terminated:
            # The stream ran out on an opcode boundary without a 0xFF
            # terminator (AFS, BATHROOM, BATTLE, COLLISN, and UFO end in filler).
            # Only payload-aligned EOF reaches here, so the complete slices are
            # yielded and the truncated final group is dropped.
            return views
        views.append(
            SliceView(
                index=index,
                start=header_start,
                end=pos,
                moves=start_moves,
                rotates=start_rotates,
                animates=start_animates,
            )
        )
        previous_start = header_start
        index += 1
