"""VGA Mode 13h reference-frame capture and artifact writing for visual parity.

capture() runs a plan ([`plan`](plan.py)): one trace of the whole film, a choice of frames
from it, then dump passes that read the A000 page and the DS working palette at exactly those
emulated frames. A frame is kept when its page changed and the film clock is running, which
skips the dialog and load screens, and at most one is kept per ``stride`` film ticks (the
sampler's old density), per Invariant [I4]. Every kept frame is tagged with the film clock
(the layout's ``film_clock``, # [MEM-FLM-TICK]) read in the same Lua step as the page, so parity compares it
against the render of the same 50 Hz tick instead of capture order.

The artifact names and JSON layout are a capture contract: frames/tick_NNNN.idx,
frames/palettes_NNNN.json and meta.json (written last) must stay in place; the frame
files sit in a subdirectory so meta.json is visible beside them (ADR 0024). ``meta.json``
is the port's capture document plus the diagnostics this sampler records; the
writer owns its shape, so this module never assembles it by hand. Reference
rasters are evidence only: the caller writes them under the data root.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from stunt_reel.parity_artifacts import (
    CAPTURE_FRAMES_DIR,
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    SCHEMA_VERSION,
    CapturedFrame,
    CaptureSet,
    FilmId,
    Geometry,
    write_capture,
)
from stunt_reel.tac import luagen, plan

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from contextlib import AbstractContextManager
    from pathlib import Path

    from stunt_reel.tac.automation import ScriptRunner
    from stunt_reel.tac.playone import PlayoneLayout

__all__ = [
    "END_HOLD_FRAMES",
    "FILM_STRIDE_TICKS",
    "FRAME_BYTES",
    "FRAME_HEIGHT",
    "FRAME_WIDTH",
    "MAX_TRACE_FRAMES",
    "PAGE_OFFSET",
    "PALETTE_ENTRIES",
    "capture",
]

_LOGGER = logging.getLogger(__name__)

FRAME_WIDTH: int = CAPTURE_WIDTH
FRAME_HEIGHT: int = CAPTURE_HEIGHT
FRAME_BYTES: int = plan.FRAME_BYTES
PAGE_OFFSET: int = 0
PALETTE_ENTRIES: int = 256

#: Emulated frames at an unchanged film clock that mean the film has ended and holds its last
#: picture (the clock advances at most every 2 frames while a film plays).
END_HOLD_FRAMES: int = 30
#: Film ticks between kept frames: the old trap sampler's density (one frame per 11 ticks).
FILM_STRIDE_TICKS: int = 11
#: Cap on a trace, in emulated frames (70.087 per second): well past the longest film.
MAX_TRACE_FRAMES: int = 12000


def capture(
    open_runner: Callable[[], AbstractContextManager[ScriptRunner]],
    out_dir: Path,
    *,
    keys: Sequence[str],
    max_frames: int,
    stride: int = FILM_STRIDE_TICKS,
    film: FilmId | None = None,
    provenance: Mapping[str, str] | None = None,
    progress: Callable[[str], None] | None = None,
    layout: PlayoneLayout,
) -> dict[str, Any]:
    """Plan and run a capture of the film *keys* selects, and write the reference artifacts.

    Frames are numbered from one in emulated-frame order (frames/tick_{ordinal:04d}.idx); that
    ordinal is only a file name. meta.json is the port's capture document: each frame carries
    film_tick (the film clock, which is what parity matches on), and the diagnostics ride beside
    it through the writer. meta.json is written last. *provenance* (when and by which checkout)
    joins the diagnostics in meta.json; it is not part of the capture's identity, which is the
    film and its frames. *layout* is the PLAYONE.EXE build being run; its name is recorded as
    ``playone_build``.
    """
    if max_frames < 1:
        # Otherwise the pick is empty and the capture fails as if the film had no usable frame.
        raise ValueError(f"max_frames must be at least 1, not {max_frames}")

    first = luagen.boot_end(len(keys))
    result = plan.run_plan(
        open_runner,
        keys=keys,
        first=first,
        last=first + MAX_TRACE_FRAMES,
        pick=lambda trace: plan.pick_every(trace, stride=stride)[:max_frames],
        end_hold=END_HOLD_FRAMES,
        progress=progress,
        layout=layout,
    )
    trace = result.trace
    torn = sum(e.torn for e in trace.entries)
    palette_steps = sum(e.palette_changed for e in trace.entries)
    composed = sum(e.composed for e in trace.entries)
    if trace.entries and not composed and progress is not None:
        # The tear test compares against the layout's composed pages; offsets that read no real
        # page make every frame look clean, so a zero here is the visible symptom.
        progress(
            f"no traced page equals a composed page; check {layout.name}'s composed_pages "
            "offsets before trusting the torn count"
        )
    candidates = [
        f for f in trace.frames if trace.entry(f).changed and trace.entry(f).film_tick > 0
    ]
    if candidates and not result.dumps:
        # Every film frame was skipped: say so instead of writing a capture with no frames. The
        # counts are over the frames the message names; meta.json's are over the whole trace.
        candidates_torn = sum(trace.entry(f).torn for f in candidates)
        spoiled = sum(not trace.entry(f).torn and not plan.usable(trace, f) for f in candidates)
        raise plan.PlanError(
            f"no usable frame among {len(candidates)} changed film frames: {candidates_torn} torn, "
            f"{spoiled} spoiled by a palette step (at the frame or the one before), "
            f"{len(result.dropped)} dropped in dump passes"
        )

    # Made only now, so a capture that fails above leaves no empty frames/ behind.
    frames_dir = out_dir / CAPTURE_FRAMES_DIR
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[CapturedFrame] = []
    frame_diagnostics: list[Mapping[str, Any]] = []
    for ordinal, emu_frame in enumerate(sorted(result.dumps), start=1):
        dump = result.dumps[emu_frame]
        entry = dump.entry
        frame_path = frames_dir / f"tick_{ordinal:04d}.idx"
        frame_path.write_bytes(dump.page)
        palette_path = frames_dir / f"palettes_{ordinal:04d}.json"
        palette = [list(rgb) for rgb in plan.palette_rgb(dump.palette6)]
        palette_path.write_text(json.dumps(palette), encoding="utf-8")
        frames.append(
            CapturedFrame(
                ordinal=ordinal,
                film_tick=entry.film_tick,
                frame_file=f"{CAPTURE_FRAMES_DIR}/{frame_path.name}",
                palette_file=f"{CAPTURE_FRAMES_DIR}/{palette_path.name}",
            )
        )
        frame_diagnostics.append(
            {
                "global_tick": entry.global_tick,
                "emu_frame": emu_frame,
                "vga_start": PAGE_OFFSET,
                "distinct_indices": len(set(dump.page)),
            }
        )
        _LOGGER.info(
            "[capture] frame %04d: film tick %d (global %d, emulated frame %d)",
            ordinal,
            entry.film_tick,
            entry.global_tick,
            emu_frame,
        )

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
            "palette_source": "working",
            "dgroup_segment": f"{layout.ds:04X}",
            "frame_bytes": FRAME_BYTES,
            "playone_build": layout.name,
            "torn_frames": torn,
            "palette_steps": palette_steps,
            "composed_matches": composed,
            "dropped_frames": list(result.dropped),
            **(provenance or {}),
        },
        frame_diagnostics=tuple(frame_diagnostics),
    )
