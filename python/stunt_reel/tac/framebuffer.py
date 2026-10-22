"""VGA Mode 13h framebuffer and DAC palette capture for visual parity.

Extracts the page that ``PLAYONE.EXE`` is actually scanning out. Sampling rides on
the documented post-retrace trap at ``0D51:0C5E`` (``# [MEM-VSYNC-03DA]``): an
execution breakpoint plus ``RUN`` stops the guest once per render-loop frame, so
every dump is a whole frame rather than a tear. ``VRT`` cannot be used here - this
DOSBox-X build dies with ``0xC0000409`` when it single-steps a Mode 13h guest.

The loop records a page only when it differs from the previous page and carries
enough palette indices to be film content, which skips the modal dialog, palette
fades, and the DOS text screen that surround playback, per Invariant [I4]. Every
recorded page is tagged with the film clock (``DS:0x4896``, ``# [MEM-FLM-TICK]``) read
while the guest is halted at the trap, so parity compares it against the render of the
same 50 Hz tick instead of relying on capture order.

Reference rasters are evidence only: the caller writes them under ``build/``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from stunt_reel.tac import playone
from stunt_reel.tac.client import TacClient
from stunt_reel.tac.palette import MODE_13H_PALETTE

__all__ = [
    "BOOT_PAGES",
    "FILM_MIN_COLORS",
    "FRAME_BYTES",
    "FRAME_HEIGHT",
    "FRAME_WIDTH",
    "MAX_DIALOG_DUMPS",
    "MAX_IDLE_HITS",
    "MIN_FRAME_COLORS",
    "PAGE_OFFSET",
    "PALETTE_ENTRIES",
    "SETTLED_DUMPS",
    "VGA_SEG",
    "capture",
    "dump_frame",
    "read_palette",
    "read_ticks",
]

_LOGGER = logging.getLogger(__name__)

#: Real-mode segment of the VGA linear framebuffer window.
VGA_SEG: str = "A000"
#: Mode 13h page size in bytes (320x200, one byte per pixel).
FRAME_BYTES: int = 320 * 200
FRAME_WIDTH: int = 320
FRAME_HEIGHT: int = 200
PALETTE_ENTRIES: int = 256

#: Pages with fewer distinct indices are palette fades or blank frames, not pictures.
MIN_FRAME_COLORS: int = 4
#: Distinct indices that mark film content; the modal dialog only ever uses six.
FILM_MIN_COLORS: int = 20
#: Byte offset of the page ``PLAYONE.EXE`` scans out during playback.
PAGE_OFFSET: int = 0
#: Trap hits allowed without a new frame before the capture gives up.
MAX_IDLE_HITS: int = 2000
#: Dumps allowed while waiting for the modal dialog to finish drawing.
MAX_DIALOG_DUMPS: int = 600
#: Consecutive identical dumps that count as a settled page.
SETTLED_DUMPS: int = 5
#: Distinct pages DOSBox-X and the game draw before the dialog appears.
BOOT_PAGES: int = 3

_DAC_ENTRY_RE = re.compile(r"[0-9A-Fa-f]{6}")


def _scale_6bit(value: int) -> int:
    """Scale a 6-bit VGA DAC channel (0..=63) to the 8-bit range (0..=255)."""
    return (value * 255 + 31) // 63


def read_palette(client: TacClient) -> tuple[list[tuple[int, int, int]], str]:
    """Read the live DAC palette as 8-bit RGB triples.

    Returns the palette and its provenance: ``"dacpal"`` for the ``VGA DACPAL``
    listing, ``"fallback"`` for the SDK table when the emulator does not report one.
    DAC registers are 6 bits per channel and are scaled to ``0..=255`` so reference
    pixels are comparable to rendered palette-index pixels.
    """
    lines = client.execute("VGA DACPAL")
    palette: list[tuple[int, int, int]] = []
    for line in lines:
        if ":" not in line:
            continue
        for entry in _DAC_ENTRY_RE.findall(line.split(":", 1)[1]):
            palette.append(
                (
                    _scale_6bit(int(entry[0:2], 16)),
                    _scale_6bit(int(entry[2:4], 16)),
                    _scale_6bit(int(entry[4:6], 16)),
                )
            )
        if len(palette) >= PALETTE_ENTRIES:
            break

    if len(palette) == PALETTE_ENTRIES:
        return palette, "dacpal"

    fallback = [MODE_13H_PALETTE[i] for i in range(PALETTE_ENTRIES)]
    return [(int(r), int(g), int(b)) for r, g, b in fallback], "fallback"


def dump_frame(client: TacClient, host_path: Path, page_offset: int = PAGE_OFFSET) -> None:
    """Dump the 64000-byte Mode 13h page at ``page_offset`` into ``host_path``.

    ``MEMDUMPBIN`` takes its length in hex and resolves the filename through the
    host filesystem; an absolute path with forward slashes and no quoting works,
    and a path relative to the emulator working directory is the fallback.
    """
    offset = page_offset
    absolute = host_path.resolve().as_posix()
    candidates = [absolute]
    try:
        relative = Path(host_path.resolve()).relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        relative = None
    if relative is not None and relative != absolute:
        candidates.append(relative)

    last_body: list[str] = []
    for name in candidates:
        last_body = client.execute(f"MEMDUMPBIN {VGA_SEG}:{offset:04X} {FRAME_BYTES:04X} {name}")
        if host_path.is_file() and host_path.stat().st_size == FRAME_BYTES:
            return

    actual = host_path.stat().st_size if host_path.is_file() else None
    raise RuntimeError(
        f"MEMDUMPBIN {VGA_SEG}:{offset:04X} did not produce {FRAME_BYTES} bytes at "
        f"{host_path} (found {actual}); debugger said: {' | '.join(last_body)}"
    )


def _wait_until_static(client: TacClient, scratch: Path) -> bytes:
    """Dump the page until it stays put, i.e. the modal dialog has finished drawing.

    No debugger command may touch the guest before this point: reads issued while
    ``PLAYONE.EXE`` unpacks kill it. Plain dumps of the framebuffer are safe, so the
    wait is driven entirely by repeated dumps.
    """
    scratch.unlink(missing_ok=True)
    dump_frame(client, scratch)
    previous = scratch.read_bytes()
    equal = changes = 0
    for _ in range(MAX_DIALOG_DUMPS):
        dump_frame(client, scratch)
        raster = scratch.read_bytes()
        if raster == previous:
            equal += 1
        else:
            equal = 0
            changes += 1
        previous = raster
        if equal >= SETTLED_DUMPS and changes >= BOOT_PAGES:
            return raster
    raise RuntimeError(
        f"LOAD FILM dialog never settled after {MAX_DIALOG_DUMPS} dumps "
        f"({len(set(previous))} indices on the last page)"
    )


def read_ticks(client: TacClient, dgroup_segment: int) -> tuple[int, int]:
    """Read ``(film_tick, global_tick)`` from DGROUP at ``dgroup_segment``.

    ``film_tick`` is the active film clock at ``DS:0x4896`` (``# [MEM-FLM-TICK]``), the
    tick the page on screen shows. ``global_tick`` is the 50 Hz counter at ``DS:0x22B8``,
    which trails the film clock by about 5; it is kept only to diagnose that lead.
    """
    film_tick = client.read_u16(f"{dgroup_segment:04X}:{playone.FILM_CLOCK_OFFSET:04X}")
    global_tick = client.read_u16(f"{dgroup_segment:04X}:{playone.GLOBAL_TICK_OFFSET:04X}")
    return film_tick, global_tick


def capture(
    out_dir: Path,
    max_frames: int,
    client: TacClient,
    dgroup_segment: int = playone.DGROUP_RUNTIME_SEG,
) -> dict[str, Any]:
    """Drive the LOAD FILM dialog and record up to ``max_frames`` film frames.

    ``PLAYONE.EXE`` opens its modal dialog at startup, so the capture waits for it to
    settle, confirms ``CTRY.FLM`` with BIOS Data Area keystrokes while the emulator
    free-runs, then samples one dump per post-retrace trap hit. Pages are recorded
    when they differ from the previous page and carry film-content color counts,
    which skips the dialog, the load screen, and palette fades. Frames are numbered
    from one in capture order (``tick_{ordinal:04d}.idx``); that ordinal is only a
    file name. Each frame's meta entry also carries ``film_tick`` (the film clock,
    which is what parity matches on) and ``global_tick`` (diagnostic), read from
    DGROUP at ``dgroup_segment``. The debugger has no register read, so the segment
    is a parameter defaulting to the ``DS = 0x1575`` observed live in the T11 check.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch = out_dir / "_scratch.idx"

    dialog = _wait_until_static(client, scratch)
    _LOGGER.info("[capture] dialog settled: %s distinct indices", len(set(dialog)))
    playone.confirm_film(client)
    playone.arm_frame_trap(client)

    frames: list[dict[str, Any]] = []
    previous_raster: bytes | None = None
    palette_source = "dacpal"
    idle = 0

    while len(frames) < max_frames:
        playone.next_frame(client)
        dump_frame(client, scratch)
        raster = scratch.read_bytes()
        distinct = len(set(raster))

        if raster == previous_raster or distinct < FILM_MIN_COLORS:
            idle += 1
            if idle > MAX_IDLE_HITS:
                dominant = max(set(raster), key=raster.count)
                raise RuntimeError(
                    f"no new frame after {idle} trap hits "
                    f"({len(frames)} frame(s) captured, {distinct} indices on the page), "
                    f"dominant index {dominant}"
                )
            continue
        idle = 0
        previous_raster = raster

        film_tick, global_tick = read_ticks(client, dgroup_segment)
        ordinal = len(frames) + 1
        frame_path = out_dir / f"tick_{ordinal:04d}.idx"
        frame_path.write_bytes(raster)
        palette, palette_source = read_palette(client)
        palette_path = out_dir / f"palettes_{ordinal:04d}.json"
        palette_path.write_text(json.dumps([list(rgb) for rgb in palette]), encoding="utf-8")

        frames.append(
            {
                "ordinal": ordinal,
                "film_tick": film_tick,
                "global_tick": global_tick,
                "vga_start": PAGE_OFFSET,
                "frame_file": frame_path.name,
                "palette_file": palette_path.name,
                "distinct_indices": distinct,
            }
        )
        _LOGGER.info(
            "[capture] frame %04d: film tick %d (global %d), %s distinct indices",
            ordinal,
            film_tick,
            global_tick,
            distinct,
        )

    scratch.unlink(missing_ok=True)
    meta = {
        "frames": frames,
        "palette_source": palette_source,
        "dgroup_segment": f"{dgroup_segment:04X}",
        "frame_bytes": FRAME_BYTES,
        "width": FRAME_WIDTH,
        "height": FRAME_HEIGHT,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
