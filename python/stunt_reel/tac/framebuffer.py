"""VGA Mode 13h reference-frame capture and artifact writing for visual parity.

capture() is a sampler over a Session: it records a page only when it differs from
the previous page and carries enough palette indices to be film content, which
skips the modal dialog, palette fades, and the DOS text screen that surround
playback, per Invariant [I4]. Every recorded page is tagged with the film clock
(DS:0x4896, # [MEM-FLM-TICK]) read while the guest is halted at the trap, so parity
compares it against the render of the same 50 Hz tick instead of capture order.

The artifact names and JSON layout are a capture contract: tick_NNNN.idx,
palettes_NNNN.json and meta.json (written last) must stay in place. ``meta.json``
is the port's capture document plus the diagnostics this sampler records; the
writer owns its shape, so this module never assembles it by hand. Reference
rasters are evidence only: the caller writes them under build/.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stunt_reel.parity_artifacts import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    SCHEMA_VERSION,
    CapturedFrame,
    CaptureSet,
    FilmId,
    Geometry,
    write_capture,
)
from stunt_reel.tac.transport import FRAME_BYTES, PAGE_OFFSET, PALETTE_ENTRIES

if TYPE_CHECKING:
    from stunt_reel.tac.session import Session

__all__ = [
    "END_HOLD_FRAMES",
    "END_IDLE_HITS",
    "FILM_MIN_COLORS",
    "FRAME_BYTES",
    "FRAME_HEIGHT",
    "FRAME_WIDTH",
    "MAX_IDLE_HITS",
    "PAGE_OFFSET",
    "PALETTE_ENTRIES",
    "capture",
]

_LOGGER = logging.getLogger(__name__)

FRAME_WIDTH: int = CAPTURE_WIDTH
FRAME_HEIGHT: int = CAPTURE_HEIGHT

#: Distinct indices that mark film content; the modal dialog only ever uses six.
FILM_MIN_COLORS: int = 20
#: Trap hits allowed without a new frame before the capture gives up.
MAX_IDLE_HITS: int = 2000
#: Consecutive captured frames at one film clock that mean the film has ended.
END_HOLD_FRAMES: int = 3
#: Trap hits without a new film frame, once frames exist, that mean the film has ended
#: (faded to black or back to the dialog).
END_IDLE_HITS: int = 300


def capture(
    session: Session,
    out_dir: Path,
    max_frames: int,
    *,
    stop_after_repeats: int = END_HOLD_FRAMES,
    film: FilmId | None = None,
) -> dict[str, Any]:
    """Sample film frames from an open session and write the reference artifacts.

    Frames are numbered from one in capture order (tick_{ordinal:04d}.idx); that
    ordinal is only a file name. meta.json is the port's capture document: each
    frame carries film_tick (the film clock, which is what parity matches on), and
    the sampler's diagnostics ride beside it through the writer.

    Capture stops early once stop_after_repeats consecutive frames share one film
    clock (the film has ended and is holding its last picture; running on risks the
    emulator dropping the connection), and max_frames is only a cap. meta.json is
    written last.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    frames: list[CapturedFrame] = []
    frame_diagnostics: list[Mapping[str, Any]] = []
    previous_raster: bytes | None = None
    palette_source = "dacpal"
    idle = 0
    repeats = 0

    while len(frames) < max_frames:
        page = session.next_frame()
        raster = page.raster
        distinct = len(set(raster))

        if raster == previous_raster or distinct < FILM_MIN_COLORS:
            idle += 1
            if frames and idle > END_IDLE_HITS:
                _LOGGER.info(
                    "[capture] no new film frame for %d trap hits after %d frames: "
                    "end of film (%d indices on the page)",
                    idle,
                    len(frames),
                    distinct,
                )
                break
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

        film_tick, global_tick = page.film_clock
        if frames and film_tick == frames[-1].film_tick:
            repeats += 1
        else:
            repeats = 0
        ordinal = len(frames) + 1
        frame_path = out_dir / f"tick_{ordinal:04d}.idx"
        frame_path.write_bytes(raster)
        palette, palette_source = page.palette
        palette_path = out_dir / f"palettes_{ordinal:04d}.json"
        palette_path.write_text(json.dumps([list(rgb) for rgb in palette]), encoding="utf-8")

        frames.append(
            CapturedFrame(
                ordinal=ordinal,
                film_tick=film_tick,
                frame_file=frame_path.name,
                palette_file=palette_path.name,
            )
        )
        frame_diagnostics.append(
            {
                "global_tick": global_tick,
                "vga_start": PAGE_OFFSET,
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
        if stop_after_repeats > 0 and repeats + 1 >= stop_after_repeats:
            _LOGGER.info("[capture] film clock holding at %d: end of film", film_tick)
            break

    capture_set = CaptureSet(
        schema_version=SCHEMA_VERSION,
        film=film if film is not None else FilmId(),
        geometry=Geometry(width=FRAME_WIDTH, height=FRAME_HEIGHT),
        frames=tuple(frames),
    )
    return write_capture(
        out_dir,
        capture_set,
        diagnostics={
            "palette_source": palette_source,
            "dgroup_segment": f"{session.dgroup_segment:04X}",
            "frame_bytes": FRAME_BYTES,
        },
        frame_diagnostics=tuple(frame_diagnostics),
    )
