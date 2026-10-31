"""Capture plans: a trace pass, a frame choice made in Python, and chunked dump passes.

The guest cannot be paused, so a run is replayed instead: the same film and conf give the same
per-frame clocks for ``CTRY.FLM`` and ``INTRO.FLM``, and within a tick for ``COUNT.FLM``
(research/playone-exe/capture-dosbox-automation.md § 4.4). Pass 1 traces every frame; ``pick``
chooses the frames worth keeping; later passes replay the boot and dump exactly those, at most
:data:`~stunt_reel.tac.luagen.MAX_DUMPS` per pass because a larger pass runs out of Lua memory.
Each page is labelled with the tick its own pass read, and a pass that drifts further than
:data:`MAX_SKEW_TICKS` fails loudly (:class:`PlanDivergence`).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from stunt_reel.tac.luagen import (
    MAX_DUMPS,
    TRACE_CHANGED,
    TRACE_COMPOSED,
    TRACE_PALETTE,
    TRACE_TORN,
    MemRange,
    script,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from contextlib import AbstractContextManager

    from stunt_reel.tac.automation import ScriptRunner
    from stunt_reel.tac.playone import PlayoneLayout

__all__ = [
    "DEFAULT_PARALLEL_PASSES",
    "FRAME_BYTES",
    "MAX_SKEW_TICKS",
    "PALETTE_BYTES",
    "Dump",
    "PlanDivergence",
    "PlanError",
    "PlanResult",
    "Trace",
    "TraceEntry",
    "chunk",
    "decode_dumps",
    "decode_trace",
    "palette_rgb",
    "pick_every",
    "pick_ticks",
    "run_plan",
    "usable",
]

FRAME_BYTES: int = 320 * 200
PALETTE_BYTES: int = 768
#: Film ticks a dumped frame may differ from the trace pass at the same emulated frame. Runs of
#: some films (COUNT.FLM, live 2026-10-30) land a tick apart from boot to boot; a page is always
#: labelled with the tick read in its own Lua step, so jitter moves a sample but never mislabels it.
MAX_SKEW_TICKS: int = 2
#: Dump passes run at once. Sixteen parallel runs were measured bit-identical on 16 logical
#: cores (capture-dosbox-automation.md § 4.1), and one pass on the capture profile costs about
#: 0.23 of a core (§ 4.4), so eight use about two cores and leave room for other work.
DEFAULT_PARALLEL_PASSES: int = 8
#: Default seconds one pass may take; a full-length film runs for minutes.
DEFAULT_TIMEOUT_SECONDS: float = 900.0

RGB = tuple[int, int, int]
_MASK_LIMIT: int = (TRACE_CHANGED | TRACE_TORN | TRACE_PALETTE | TRACE_COMPOSED) + 1


class PlanError(RuntimeError):
    """A script's output was not shaped the way the plan asked for."""


class PlanDivergence(PlanError):  # noqa: N818 - the agreed interface name
    """A dump pass drifted from the trace pass by more than the jitter a run is allowed."""


@dataclass(frozen=True)
class TraceEntry:
    """What one frame showed: the clocks, any extra words, and the trace mask's four flags."""

    film_tick: int
    global_tick: int
    words: tuple[int, ...]
    changed: bool
    #: The page mixes the two composed pages (a copy was under way when it was read).
    torn: bool = False
    #: The working palette changed since the previous frame.
    palette_changed: bool = False
    #: Rows 0..191 equal one of the composed pages: the layout's page offsets read real pages.
    composed: bool = False


@dataclass(frozen=True)
class Trace:
    """Per-frame entries for emulated frames ``first`` onward."""

    first: int
    entries: tuple[TraceEntry, ...]

    @property
    def frames(self) -> range:
        """The emulated frame numbers the trace covers."""
        return range(self.first, self.first + len(self.entries))

    def entry(self, frame: int) -> TraceEntry:
        """The entry for emulated *frame*."""
        return self.entries[frame - self.first]


@dataclass(frozen=True)
class Dump:
    """One frame's page, its working palette (6-bit units) and any requested ranges."""

    frame: int
    page: bytes
    palette6: bytes
    ranges: tuple[bytes, ...]
    #: The clocks and words the dump pass itself read at this frame, in the step that read the page.
    entry: TraceEntry


@dataclass(frozen=True)
class PlanResult:
    """The trace and the dumps taken at the picked frames."""

    trace: Trace
    dumps: dict[int, Dump]
    #: Picked frames whose page was unusable in its own dump pass, so no dump was kept.
    dropped: tuple[int, ...] = ()


def decode_trace(text: str, first: int) -> Trace:
    """Decode ``x<tick>:<global>[:word...]:<mask>,...`` into a :class:`Trace`.

    The mask is the sum of ``luagen.TRACE_*`` flags; a two-state trace (0 or 1) decodes as
    neither torn nor a palette step nor composed.
    """
    if not text.startswith("x"):
        raise PlanError("trace output is missing its letter prefix")
    entries: list[TraceEntry] = []
    for raw in text[1:].split(",") if len(text) > 1 else []:
        fields = raw.split(":")
        try:
            numbers = [int(x) for x in fields]
        except ValueError:
            raise PlanError(f"malformed trace entry {raw!r}") from None
        if len(numbers) < 3 or not 0 <= numbers[-1] < _MASK_LIMIT:
            raise PlanError(f"malformed trace entry {raw!r}")
        mask = numbers[-1]
        entries.append(
            TraceEntry(
                numbers[0],
                numbers[1],
                tuple(numbers[2:-1]),
                changed=bool(mask & TRACE_CHANGED),
                torn=bool(mask & TRACE_TORN),
                palette_changed=bool(mask & TRACE_PALETTE),
                composed=bool(mask & TRACE_COMPOSED),
            )
        )
    return Trace(first, tuple(entries))


def chunk(frames: Sequence[int], size: int = MAX_DUMPS) -> list[list[int]]:
    """Split *frames* into the fewest runs of at most *size*, as even as possible."""
    if not frames:
        return []
    count = -(-len(frames) // size)
    base, extra = divmod(len(frames), count)
    runs, start = [], 0
    for n in range(count):
        end = start + base + (1 if n < extra else 0)
        runs.append(list(frames[start:end]))
        start = end
    return runs


def usable(trace: Trace, frame: int) -> bool:
    """False when *frame*'s page is torn, or the DAC may still lag the working palette.

    The DAC shows the working palette of frame - 1 in its low half and of frame - 2 in its high
    half (tear-palette investigation § 2.1), so it equals frame's own only if the palette changed
    neither at *frame* nor at *frame* - 1. A frame before the trace counts as unchanged.
    """
    entry = trace.entry(frame)
    if entry.torn or entry.palette_changed:
        return False
    return frame == trace.first or not trace.entry(frame - 1).palette_changed


def pick_every(trace: Trace, *, stride: int) -> list[int]:
    """Usable frames whose page changed and whose film clock is *stride* or more past the last pick.

    Clock zero is not film content (the dialog and load screens run with the clock at zero). An
    unusable frame is passed over, so the next changed frame takes its place.
    """
    picked: list[int] = []
    last_tick: int | None = None
    for frame in trace.frames:
        entry = trace.entry(frame)
        if not entry.changed or entry.film_tick <= 0 or not usable(trace, frame):
            continue
        if last_tick is None or entry.film_tick - last_tick >= stride:
            picked.append(frame)
            last_tick = entry.film_tick
    return picked


def pick_ticks(trace: Trace, ticks: Sequence[int], *, skip_unusable: bool = True) -> list[int]:
    """The first usable frame at or after each requested film clock.

    Clocks the film never reaches are dropped; an unusable frame consumes no pending clock.
    With *skip_unusable* off, any frame qualifies: a plan that samples memory rather than the
    page (the light probe) is not spoiled by a torn page or a palette step.
    """
    picked: list[int] = []
    pending = sorted(ticks)
    for frame in trace.frames:
        if skip_unusable and not usable(trace, frame):
            continue
        tick = trace.entry(frame).film_tick
        while pending and tick >= pending[0]:
            if not picked or picked[-1] != frame:
                picked.append(frame)
            pending.pop(0)
        if not pending:
            break
    return picked


def palette_rgb(palette6: bytes) -> list[RGB]:
    """256 RGB triples from 6-bit DAC units, scaled the way dosbox-automation's video does."""
    scaled = [round(v * 255 / 63) for v in palette6]
    return [(scaled[i], scaled[i + 1], scaled[i + 2]) for i in range(0, PALETTE_BYTES, 3)]


def _unhex(output: Mapping[str, Any], key: str, length: int | None = None) -> bytes:
    value = output.get(key)
    if not isinstance(value, str) or not value.startswith("x"):
        raise PlanError(f"dump output {key!r} is missing or lacks its letter prefix")
    data = bytes.fromhex(value[1:])
    if length is not None and len(data) != length:
        raise PlanError(f"dump output {key!r} holds {len(data)} bytes, expected {length}")
    return data


def decode_dumps(
    output: Mapping[str, Any], frames: Sequence[int], range_count: int, trace: Trace
) -> dict[int, Dump]:
    """Decode the ``p``/``c``/``m`` outputs of a dump pass for *frames*, with its own *trace*."""
    return {
        f: Dump(
            frame=f,
            page=_unhex(output, f"p{f}", FRAME_BYTES),
            palette6=_unhex(output, f"c{f}", PALETTE_BYTES),
            ranges=tuple(_unhex(output, f"m{f}_{n}") for n in range(1, range_count + 1)),
            entry=trace.entry(f),
        )
        for f in frames
    }


def _check_close(expected: Trace, got: Trace, frames: Sequence[int], label: str) -> None:
    """Raise unless the dump pass reached every dumped frame within MAX_SKEW_TICKS of the trace."""
    for frame in frames:
        if frame not in got.frames:
            raise PlanDivergence(
                f"{label} traced only {len(got.entries)} frames and never reached frame {frame}"
            )
        skew = abs(got.entry(frame).film_tick - expected.entry(frame).film_tick)
        if skew > MAX_SKEW_TICKS:
            raise PlanDivergence(
                f"{label} disagrees with the trace pass at frame {frame} by {skew} ticks: "
                f"{got.entry(frame)} against {expected.entry(frame)}"
            )


def run_plan(
    open_runner: Callable[[], AbstractContextManager[ScriptRunner]],
    *,
    keys: Sequence[str],
    first: int,
    last: int,
    pick: Callable[[Trace], Sequence[int]],
    ranges: Sequence[MemRange] | Callable[[Trace, Sequence[int]], Sequence[MemRange]] = (),
    words: Sequence[tuple[int, int]] = (),
    end_hold: int | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    progress: Callable[[str], None] | None = None,
    parallel: int = DEFAULT_PARALLEL_PASSES,
    layout: PlayoneLayout,
    skip_unusable: bool = True,
) -> PlanResult:
    """Run the trace pass, let *pick* choose frames from it, then dump them in chunks.

    *open_runner* opens a fresh emulator for each pass (every pass reboots the film), and up to
    *parallel* dump passes run at once. *ranges* may be a function of the trace and the picked
    frames, for memory whose segment the trace reads. With *skip_unusable* off, a dump whose own
    pass reads its page as torn or in a palette step is kept: for a plan that samples memory.
    """
    common: dict[str, Any] = {
        "keys": keys,
        "first": first,
        "last": last,
        "words": words,
        "end_hold": end_hold,
        "layout": layout,
    }
    say = progress or (lambda _line: None)
    say("pass 1: tracing the film")
    with open_runner() as runner:
        out = runner.run_script(script(**common), timeout=timeout)
    trace = decode_trace(str(out.get("trace", "")), first)
    say(f"traced {len(trace.entries)} frames")
    dumps: dict[int, Dump] = {}
    picked = list(pick(trace))
    dump_ranges = ranges(trace, picked) if callable(ranges) else ranges
    # MAX_DUMPS was measured with pages and palettes only; extra ranges spend the same Lua heap.
    page_only = FRAME_BYTES + PALETTE_BYTES
    per_frame = page_only + sum(r.length for r in dump_ranges)
    chunks = chunk(picked, max(1, page_only * MAX_DUMPS // per_frame))

    def dump_pass(frames: list[int]) -> dict[int, Dump]:
        with open_runner() as runner:
            out = runner.run_script(
                script(**common, dump_frames=frames, ranges=dump_ranges), timeout=timeout
            )
        own = decode_trace(str(out.get("trace", "")), first)
        _check_close(trace, own, frames, "dump pass")
        # Jitter (COUNT.FLM) can move a tear or a palette step onto a picked frame; that page
        # is dropped rather than failing a capture whose other pages are good.
        kept = {f for f in frames if not skip_unusable or usable(own, f)}
        for f in frames:
            if f not in kept:
                say(f"dump pass read an unusable page at frame {f}, dropped: {own.entry(f)}")
        return {
            f: d for f, d in decode_dumps(out, frames, len(dump_ranges), own).items() if f in kept
        }

    # Each pass is its own emulator, so passes run side by side; results join in frame order.
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(chunks)))) as pool:
        futures = []
        for number, frames in enumerate(chunks, start=1):
            say(f"dump pass {number}/{len(chunks)}: {len(frames)} frames")
            futures.append(pool.submit(dump_pass, frames))
        try:
            for future in futures:
                dumps.update(future.result())
        except BaseException:
            pool.shutdown(cancel_futures=True)
            raise
    moved = [f for f, d in dumps.items() if d.entry.film_tick != trace.entry(f).film_tick]
    if moved:
        worst = max(abs(dumps[f].entry.film_tick - trace.entry(f).film_tick) for f in moved)
        say(
            f"{len(moved)} of {len(dumps)} dumped frames read another tick than the trace pass "
            f"(at most {worst})"
        )
    dropped = tuple(sorted(set(picked) - set(dumps)))
    return PlanResult(trace, dumps, dropped)
