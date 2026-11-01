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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from stunt_reel.tac.playone import PlayoneLayout

__all__ = [
    "KEY_GAP",
    "KEY_HOLD",
    "MAX_DUMPS",
    "MAX_READ",
    "PALETTE_BANDS",
    "START_FRAME",
    "TRACE_CHANGED",
    "TRACE_COMPOSED",
    "TRACE_PALETTE",
    "TRACE_TORN",
    "MemRange",
    "boot_end",
    "keys_script",
    "script",
    "video_script",
]

#: Emulated frame at which the file dialog is up and keys can be sent.
START_FRAME: int = 1200
#: Frames between key presses, and frames a key stays down.
KEY_GAP: int = 20
KEY_HOLD: int = 5
#: One page sample is 128 KB of hex; 90 samples ran out of Lua memory (live, 2026-10-30), 40 fit.
MAX_DUMPS: int = 40
#: ``dosbox.mem_read`` returns at most one 64 KB segment.
MAX_READ: int = 65535
_PAGE_BYTES: int = 64000
_PALETTE_BYTES: int = 768
#: Bits of a trace entry's last field: the page changed, the page is torn between the two
#: composed pages, the working palette changed since the previous frame, and rows 0..191 equal
#: one composed page. The last is a check on the layout: a page that never equals either
#: composed page means the offsets are wrong, which would otherwise read as a film with no tears.
TRACE_CHANGED: int = 1
TRACE_TORN: int = 2
TRACE_PALETTE: int = 4
TRACE_COMPOSED: int = 8
#: Rows 0..191 of the page, the part copied from a composed page (192..199 are the button bar,
#: drawn on A000 directly), compared in bands of 8 rows: 192 row compares per frame exceeded
#: the instruction limit, 24 bands fit a whole film (tear-palette investigation § 1.1).
_COMPOSED_BYTES: int = 192 * 320
_BAND_BYTES: int = 8 * 320
#: The video script logs palette writes in this many equal bands (32 entries, 96 bytes each).
PALETTE_BANDS: int = 8
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


#: A relative mouse move far enough left and down to clamp the cursor to the bottom-left corner.
_PARK_DX: int = -2000
_PARK_DY: int = 2000


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
        # The cursor is drawn on the page; past the bottom-left edge it sits over the button bar,
        # below the 3D view (live 2026-10-31). No wait, so boot_end still holds.
        f"dosbox.mouse_move({_PARK_DX}, {_PARK_DY})\n"
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
    layout: PlayoneLayout,
) -> str:
    """The Lua for one run: boot with *keys*, trace frames *first* to *last*, dump *dump_frames*.

    The trace entry for frame *f* is ``film_tick:global_tick[:word...]:mask``, the mask the sum
    of :data:`TRACE_CHANGED` (the A000 page differs from frame *f* - 1's), :data:`TRACE_TORN`
    (rows 0..191 match neither composed page, and some bands match only one and others only
    the other), :data:`TRACE_PALETTE` (the working palette differs from frame *f* - 1's) and
    :data:`TRACE_COMPOSED` (rows 0..191 equal one composed page).
    Dumps are ``p<f>`` (page),
    ``c<f>`` (the DS working palette, 6-bit units) and ``m<f>_<n>`` per range, all hex.

    With *end_hold* the trace also stops once the film clock (above zero) has not moved for that
    many frames, so *last* is only a cap on a film of unknown length. *layout* says where the
    PLAYONE.EXE build being run keeps the clocks and the palette.
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
                f'    out["c" .. f] = "x" .. dosbox.mem_read(DS, 0x{layout.working_palette:X}, '
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
    page_a, page_b = layout.composed_pages
    palette_read = f"dosbox.mem_read(DS, 0x{layout.working_palette:X}, {_PALETTE_BYTES})"
    tear_lua = (
        f"local ROWS, BAND = {_COMPOSED_BYTES}, {_BAND_BYTES}\n"
        "local function split(pg)\n"
        f"  local a = dosbox.mem_read(dosbox.mem_read_word(DS, 0x{page_a:04X}), 0, ROWS)\n"
        f"  local b = dosbox.mem_read(dosbox.mem_read_word(DS, 0x{page_b:04X}), 0, ROWS)\n"
        "  local top = pg:sub(1, ROWS)\n"
        f"  if top == a or top == b then return {TRACE_COMPOSED} end\n"
        "  local onlyA, onlyB = false, false\n"
        "  for o = 1, ROWS, BAND do\n"
        "    local s = top:sub(o, o + BAND - 1)\n"
        "    local ea, eb = s == a:sub(o, o + BAND - 1), s == b:sub(o, o + BAND - 1)\n"
        "    if ea and not eb then onlyA = true elseif eb and not ea then onlyB = true end\n"
        "  end\n"
        f"  return (onlyA and onlyB) and {TRACE_TORN} or 0\n"
        "end\n"
    )
    mask = (
        f"((pg ~= prev) and {TRACE_CHANGED} or 0) + split(pg)"
        f" + ((pal ~= ppal) and {TRACE_PALETTE} or 0)"
    )
    return (
        f"local DS = 0x{layout.ds:04X}\n"
        "local out = dosbox.output\n"
        "local function wait_until(f) while dosbox.frame() < f do dosbox.wait_frames(1) end end\n"
        "local H = {}\n"
        'for i = 0, 255 do H[string.char(i)] = string.format("%02x", i) end\n'
        + _keys_lua(keys)
        + tear_lua
        + f"local dumps = {{{frames}}}\n"
        "local di = 1\n"
        "local tr = {}\n"
        "local lt, hold = -1, 0\n"
        f"local prev = dosbox.mem_read(0xA000, 0, {_PAGE_BYTES})\n"
        f"local ppal = {palette_read}\n"
        f"for f = {first}, {last} do\n"
        "  wait_until(f)\n"
        f"  local t = dosbox.mem_read_word(DS, 0x{layout.film_clock:04X})\n"
        f"  local g = dosbox.mem_read_word(DS, 0x{layout.global_tick:04X})\n"
        f"  local pg = dosbox.mem_read(0xA000, 0, {_PAGE_BYTES})\n"
        f"  local pal = {palette_read}\n"
        "  if t == lt then hold = hold + 1 else hold = 0; lt = t end\n"
        f'  tr[#tr + 1] = t .. ":" .. g{extra} .. ":" .. ({mask})\n'
        "  prev = pg\n"
        "  ppal = pal\n" + dump_block + hold_block + "end\n"
        'out.trace = "x" .. table.concat(tr, ",")\n'
        "out.done = true\n"
    )


def video_script(
    *,
    keys: Sequence[str],
    cap: int,
    end_hold: int,
    layout: PlayoneLayout,
) -> str:
    """The Lua for a video capture: boot with *keys*, record the screen, log clocks and palette.

    ``dosbox.capture_start()`` begins the AVI once the boot keys are done; then, one emulated
    frame at a time for at most *cap* frames, the script logs ``frame:film_tick:global_tick``
    and, when the working palette changed, ``frame:band:hex`` for each of the
    :data:`PALETTE_BANDS` bands that differ (whole-palette compares per frame, never per byte).
    The loop ends when the film clock (above zero) has held for *end_hold* frames. Outputs:
    ``cs`` (the frame recording began), ``pal0`` (the palette then), ``log``, ``pal`` and
    ``end`` (``hold`` or ``capped``), every string behind an ``x`` so it stays a string.
    """
    if cap < 1:
        raise ValueError(f"cap must be at least 1, got {cap}")
    if end_hold < 1:
        raise ValueError(f"end_hold must be at least 1, got {end_hold}")
    palette_read = f"dosbox.mem_read(DS, 0x{layout.working_palette:X}, {_PALETTE_BYTES})"
    band = _PALETTE_BYTES // PALETTE_BANDS
    return (
        f"local DS = 0x{layout.ds:04X}\n"
        "local out = dosbox.output\n"
        "local function wait_until(f) while dosbox.frame() < f do dosbox.wait_frames(1) end end\n"
        "local H = {}\n"
        'for i = 0, 255 do H[string.char(i)] = string.format("%02x", i) end\n'
        + _keys_lua(keys)
        + "dosbox.capture_start()\n"
        'out.cs = "x" .. dosbox.frame()\n'
        f'out.pal0 = "x" .. {palette_read}:gsub(".", H)\n'
        f"local tr, pl, lt, hold, ppal = {{}}, {{}}, -1, 0, {palette_read}\n"
        'out["end"] = "xcapped"\n'
        f"for i = 1, {cap} do\n"
        "  dosbox.wait_frames(1)\n"
        "  local f = dosbox.frame()\n"
        f"  local t = dosbox.mem_read_word(DS, 0x{layout.film_clock:04X}); "
        f"local g = dosbox.mem_read_word(DS, 0x{layout.global_tick:04X})\n"
        '  tr[#tr + 1] = f .. ":" .. t .. ":" .. g\n'
        f"  local pal = {palette_read}\n"
        "  if pal ~= ppal then\n"
        f"    for b = 0, {PALETTE_BANDS - 1} do\n"
        f"      local s = pal:sub(b * {band} + 1, b * {band} + {band})\n"
        f"      if s ~= ppal:sub(b * {band} + 1, b * {band} + {band}) then "
        'pl[#pl + 1] = f .. ":" .. b .. ":" .. s:gsub(".", H) end\n'
        "    end\n"
        "    ppal = pal\n"
        "  end\n"
        "  if t == lt then hold = hold + 1 else hold = 0; lt = t end\n"
        f'  if t > 0 and hold >= {end_hold} then out["end"] = "xhold"; break end\n'
        "end\n"
        "dosbox.capture_stop()\n"
        'out.log = "x" .. table.concat(tr, ",")\n'
        'out.pal = "x" .. table.concat(pl, ",")\n'
        "out.done = true\n"
    )
