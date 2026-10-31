"""Generate the Lua a dosbox-automation run executes.

dosbox-automation cannot pause or step the guest, so a capture is a *plan*: one script boots
the film, then records per frame what the plan asks for ([`capture-dosbox-automation.md`]
§§ 4 and 6). Pass 1 is a trace (film clock, global clock, page-changed flag, plus any extra
words); Python picks frames from it; pass 2 repeats the trace and also dumps the page, the
working palette and any memory ranges at exactly those frames.

Lua runs on the emulation thread under an instruction limit, so nothing here loops per byte
over a page: hex encoding is ``raw:gsub(".", H)``, pages are compared as strings and diffed
offline, and every string output starts with a letter because ``dosbox.output`` coerces a
numeric-looking string into a number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stunt_reel.tac.playone import (
    AUTOMATION_DS,
    FILM_CLOCK_OFFSET,
    GLOBAL_TICK_OFFSET,
    WORKING_PALETTE_OFFSET,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "KEY_GAP",
    "KEY_HOLD",
    "MAX_DUMPS",
    "MAX_READ",
    "START_FRAME",
    "MemRange",
    "boot_end",
    "keys_script",
    "script",
]

#: Emulated frame at which the file dialog is up and keys can be sent.
START_FRAME: int = 1200
#: Frames between key presses, and frames a key stays down.
KEY_GAP: int = 20
KEY_HOLD: int = 5
#: One page sample is 128 KB of hex, and the output store holds about 15 MB.
MAX_DUMPS: int = 90
#: ``dosbox.mem_read`` returns at most one 64 KB segment.
MAX_READ: int = 65535
_PAGE_BYTES: int = 64000
_PALETTE_BYTES: int = 768
_KEY_NAME = re.compile(r"KBD_[a-z0-9_]+")


@dataclass(frozen=True)
class MemRange:
    """A guest memory range to dump at each dump frame."""

    segment: int
    offset: int
    length: int

    def __post_init__(self) -> None:
        if not 0 < self.length <= MAX_READ:
            raise ValueError(f"a range reads 1 to {MAX_READ} bytes, got {self.length}")


def boot_end(key_count: int) -> int:
    """The first frame at which the boot keys have all been released."""
    return START_FRAME + key_count * (KEY_GAP + KEY_HOLD)


def _keys_lua(keys: Sequence[str]) -> str:
    for key in keys:
        if not _KEY_NAME.fullmatch(key):
            raise ValueError(f"key name {key!r} is not a KBD_ name")
    names = ", ".join(f'"{key}"' for key in keys)
    return (
        f"wait_until({START_FRAME})\n"
        f"for _, k in ipairs({{{names}}}) do\n"
        f"  dosbox.wait_frames({KEY_GAP}); dosbox.key(k, true); "
        f"dosbox.wait_frames({KEY_HOLD}); dosbox.key(k, false)\n"
        "end\n"
    )


def keys_script(keys: Sequence[str]) -> str:
    """A script that only boots and presses *keys*, then ends (the caller watches the screen)."""
    return (
        "local out = dosbox.output\n"
        "local function wait_until(f) while dosbox.frame() < f do dosbox.wait_frames(1) end end\n"
        + _keys_lua(keys)
        + "out.done = true\n"
    )


def _check_frames(
    keys: Sequence[str],
    first: int,
    last: int,
    dump_frames: Sequence[int],
) -> None:
    if first < boot_end(len(keys)):
        raise ValueError(
            f"the trace starts at {first}, before the boot keys end at {boot_end(len(keys))}"
        )
    if last < first:
        raise ValueError(f"the trace window {first}..{last} is empty")
    if len(dump_frames) > MAX_DUMPS:
        raise ValueError(f"at most {MAX_DUMPS} dump frames per run, got {len(dump_frames)}")
    if list(dump_frames) != sorted(set(dump_frames)):
        raise ValueError("dump frames must ascend without repeats")
    if dump_frames and not (first <= dump_frames[0] and dump_frames[-1] <= last):
        raise ValueError(f"dump frames must lie inside the trace window {first}..{last}")


def script(
    *,
    keys: Sequence[str],
    first: int,
    last: int,
    dump_frames: Sequence[int] = (),
    ranges: Sequence[MemRange] = (),
    words: Sequence[tuple[int, int]] = (),
    end_hold: int | None = None,
) -> str:
    """The Lua for one run: boot with *keys*, trace frames *first* to *last*, dump *dump_frames*.

    The trace entry for frame *f* is ``film_tick:global_tick[:word...]:changed`` (``changed``
    is 1 when the A000 page differs from frame *f* - 1's). Dumps are ``p<f>`` (page),
    ``c<f>`` (the DS working palette, 6-bit units) and ``m<f>_<n>`` per range, all hex.

    With *end_hold* the trace also stops once the film clock (above zero) has not moved for that
    many frames, so *last* is only a cap on a film of unknown length.
    """
    if end_hold is not None and end_hold < 1:
        raise ValueError(f"end_hold must be at least 1, got {end_hold}")
    _check_frames(keys, first, last, dump_frames)
    extra = "".join(
        f' .. ":" .. dosbox.mem_read_word(0x{seg:04X}, 0x{off:04X})' for seg, off in words
    )
    dump_block = ""
    if dump_frames:
        reads = [
            '    out["p" .. f] = "x" .. pg:gsub(".", H)',
            (
                f'    out["c" .. f] = "x" .. dosbox.mem_read(DS, 0x{WORKING_PALETTE_OFFSET:X}, '
                f'{_PALETTE_BYTES}):gsub(".", H)'
            ),
        ]
        reads += [
            (
                f'    out["m" .. f .. "_{n}"] = "x" .. dosbox.mem_read(0x{r.segment:04X}, '
                f'0x{r.offset:X}, {r.length}):gsub(".", H)'
            )
            for n, r in enumerate(ranges, start=1)
        ]
        dump_block = "  if dumps[di] == f then\n" + "\n".join(reads) + "\n    di = di + 1\n  end\n"
    hold_block = (
        f"  if t > 0 and hold >= {end_hold} then break end\n" if end_hold is not None else ""
    )
    frames = ", ".join(str(f) for f in dump_frames)
    return (
        f"local DS = 0x{AUTOMATION_DS:04X}\n"
        "local out = dosbox.output\n"
        "local function wait_until(f) while dosbox.frame() < f do dosbox.wait_frames(1) end end\n"
        "local H = {}\n"
        'for i = 0, 255 do H[string.char(i)] = string.format("%02x", i) end\n'
        + _keys_lua(keys)
        + f"local dumps = {{{frames}}}\n"
        "local di = 1\n"
        "local tr = {}\n"
        "local lt, hold = -1, 0\n"
        f"local prev = dosbox.mem_read(0xA000, 0, {_PAGE_BYTES})\n"
        f"for f = {first}, {last} do\n"
        "  wait_until(f)\n"
        f"  local t = dosbox.mem_read_word(DS, 0x{FILM_CLOCK_OFFSET:04X})\n"
        f"  local g = dosbox.mem_read_word(DS, 0x{GLOBAL_TICK_OFFSET:04X})\n"
        f"  local pg = dosbox.mem_read(0xA000, 0, {_PAGE_BYTES})\n"
        "  if t == lt then hold = hold + 1 else hold = 0; lt = t end\n"
        f'  tr[#tr + 1] = t .. ":" .. g{extra} .. ":" .. ((pg ~= prev) and "1" or "0")\n'
        "  prev = pg\n" + dump_block + hold_block + "end\n"
        'out.trace = "x" .. table.concat(tr, ",")\n'
        "out.done = true\n"
    )
