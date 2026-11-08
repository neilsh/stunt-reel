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
from functools import cached_property
from typing import TYPE_CHECKING, Any

from stunt_reel.tac.luagen import (
    CLOCK_EVERY,
    MAX_DUMPS,
    TRACE_CHANGED,
    TRACE_COMPOSED,
    TRACE_PALETTE,
    TRACE_TORN,
    WINDOW_LEAD,
    WINDOW_SPAN,
    MemRange,
    Window,
    clock_script,
    script,
    window_script,
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
    "MAX_WINDOW_SKEW_TICKS",
    "PALETTE_BYTES",
    "Dump",
    "PlanDivergence",
    "PlanError",
    "PlanResult",
    "Trace",
    "TraceEntry",
    "choose_windows",
    "chunk",
    "dac_rgb",
    "decode_clock",
    "decode_dumps",
    "decode_trace",
    "decode_window_trace",
    "palette_rgb",
    "pick_ticks",
    "run_plan",
    "run_stride_plan",
    "usable",
]

FRAME_BYTES: int = 320 * 200
PALETTE_BYTES: int = 768
#: Film ticks a dumped frame may differ from the trace pass at the same emulated frame. Runs of
#: some films (COUNT.FLM, live 2026-10-30) land a tick apart from boot to boot; a page is always
#: labelled with the tick read in its own Lua step, so jitter moves a sample but never mislabels it.
MAX_SKEW_TICKS: int = 2
#: Film ticks a window pass may drift from the clock pass before the plan fails: a window's
#: width. Long films drift further than MAX_SKEW_TICKS from boot to boot (FLMOnly/Act1.flm, 3
#: ticks near tick 9,000, live 2026-11-01), which only moves the frame a window dumps.
MAX_WINDOW_SKEW_TICKS: int = WINDOW_SPAN
#: Dump passes run at once. Sixteen parallel runs were measured bit-identical on 16 logical
#: cores (capture-dosbox-automation.md § 2), and one pass on the capture profile costs about
#: 0.23 of a core (§ 4.4), so eight use about two cores and leave room for other work.
DEFAULT_PARALLEL_PASSES: int = 8
#: Default seconds one pass may take; a full-length film runs for minutes.
DEFAULT_TIMEOUT_SECONDS: float = 900.0

#: Emulated frames per second (VGA mode 13h), for timeouts that cover a pass in real time.
_EMULATED_HZ: float = 70.087

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
    """Per-frame entries for emulated frames ``first`` onward, or for the frames ``at`` names."""

    first: int
    entries: tuple[TraceEntry, ...]
    #: The emulated frame of each entry, ascending, for a trace that read only some frames (a
    #: window pass); ``None`` for a trace of every frame from ``first``.
    at: tuple[int, ...] | None = None

    @property
    def frames(self) -> Sequence[int]:
        """The emulated frame numbers the trace covers."""
        if self.at is not None:
            return self.at
        return range(self.first, self.first + len(self.entries))

    @cached_property
    def _index(self) -> dict[int, int]:
        return {frame: n for n, frame in enumerate(self.at or ())}

    def entry(self, frame: int) -> TraceEntry:
        """The entry for emulated *frame*."""
        if self.at is None:
            return self.entries[frame - self.first]
        return self.entries[self._index[frame]]


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
    #: Picked frames whose page was unusable in its own dump pass, so no dump was kept; for a
    #: stride plan, the start frames of windows that held no usable page.
    dropped: tuple[int, ...] = ()
    #: A stride plan's clock pass: ``(emulated frame, film tick)`` per sample.
    clock: tuple[tuple[int, int], ...] = ()


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


def chunk[T](frames: Sequence[T], size: int = MAX_DUMPS) -> list[list[T]]:
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


def dac_rgb(units: bytes) -> list[RGB]:
    """RGB triples from 6-bit DAC units (a multiple of 3 bytes), scaled as the video is."""
    if len(units) % 3:
        raise ValueError(f"DAC units come in triples, got {len(units)} bytes")
    scaled = [round(v * 255 / 63) for v in units]
    return [(scaled[i], scaled[i + 1], scaled[i + 2]) for i in range(0, len(scaled), 3)]


def palette_rgb(palette6: bytes) -> list[RGB]:
    """Convert up to 768 bytes of 6-bit DAC units to RGB triples.

    Extra bytes are ignored; a truncated final triple raises ``ValueError``.
    """
    return dac_rgb(palette6[:PALETTE_BYTES])


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

    *open_runner* opens a fresh emulator per pass; up to *parallel* dump passes run at once.
    *ranges* may be a function of the trace and the picked frames, for memory whose segment the
    trace reads. A dump whose own pass reads its page as torn or in a palette step is dropped
    (reported in ``dropped``) unless *skip_unusable* is off, for a plan that samples memory.
    Raises PlanDivergence if a dump pass strays from the trace pass by more than
    :data:`MAX_SKEW_TICKS`.
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


def decode_clock(text: str, first: int, every: int) -> tuple[tuple[int, int], ...]:
    """Decode a clock pass's ``x<tick>,...`` into ``(frame, tick)`` pairs from frame *first*."""
    if not text.startswith("x"):
        raise PlanError("clock output is missing its letter prefix")
    try:
        ticks = [int(x) for x in text[1:].split(",")] if len(text) > 1 else []
    except ValueError:
        raise PlanError(f"malformed clock output {text[:40]!r}") from None
    return tuple((first + n * every, tick) for n, tick in enumerate(ticks))


def decode_window_trace(text: str) -> Trace:
    """Decode a window pass's ``x<frame>:<tick>:<global>:<mask>,...`` into a sparse :class:`Trace`."""
    if not text.startswith("x"):
        raise PlanError("trace output is missing its letter prefix")
    frames: list[int] = []
    rows: list[str] = []
    for raw in text[1:].split(",") if len(text) > 1 else []:
        frame, _, rest = raw.partition(":")
        try:
            frames.append(int(frame))
        except ValueError:
            raise PlanError(f"malformed trace entry {raw!r}") from None
        rows.append(rest)
    if frames != sorted(set(frames)):
        raise PlanError("window trace frames must ascend without repeats")
    dense = decode_trace("x" + ",".join(rows), 0)
    return Trace(frames[0] if frames else 0, dense.entries, tuple(frames))


def choose_windows(
    clock: Sequence[tuple[int, int]], *, stride: int, limit: int, floor: int
) -> list[Window]:
    """One window per *stride* film ticks, where the sampled clock first reaches each goal.

    Goals run 1, 1 + *stride*, ... (clock zero is the dialog and load screens). A window starts
    the frame after the last sample below its goal. A goal the clock jumps past moves to the
    next one above the sample; a window that would start before *floor* or overlap the previous
    one (lead frames included) is left out. At most *limit* windows.
    """
    windows: list[Window] = []
    goal = 1
    previous: int | None = None
    for frame, tick in clock:
        if tick >= goal:
            if previous is not None and previous + 1 >= floor:
                start = previous + 1
                windows.append(Window(start, goal))
                floor = start + WINDOW_SPAN + WINDOW_LEAD
                if len(windows) >= limit:
                    break
            goal += stride * ((tick - goal) // stride + 1)
        previous = frame
    return windows


def _pass_timeout(timeout: float, frames: int) -> float:
    """*timeout*, or long enough to emulate *frames* in real time with a margin when that is longer."""
    return max(timeout, frames / _EMULATED_HZ * 1.25 + 60.0)


def _check_window(clock: Mapping[int, int], window: Window, own: Trace, dumped: int | None) -> int:
    """Raise unless the window pass's clock agrees with the clock pass within MAX_SKEW_TICKS.

    The last frame the window read (its dump, or its last frame) is compared with the clock pass
    interpolated between the samples on either side of it; returns the skew in whole ticks.
    Drift only moves which frame a window dumps, because the window tests and labels each page
    with its own pass's clock; a skew past :data:`MAX_WINDOW_SKEW_TICKS`, which can carry a
    goal out of its window, means the two passes are not playing the same film.
    """
    before = window.start - 1
    after = next((f for f in range(window.start, window.start + WINDOW_SPAN) if f in clock), None)
    read = [f for f in range(window.start, window.start + WINDOW_SPAN) if f in own.frames]
    if before not in clock or after is None or not read:
        return 0
    frame = dumped if dumped is not None else read[-1]
    slope = (clock[after] - clock[before]) / (after - before)
    expected = clock[before] + slope * (frame - before)
    skew = round(abs(own.entry(frame).film_tick - expected))
    if skew > MAX_WINDOW_SKEW_TICKS:
        raise PlanDivergence(
            f"window pass disagrees with the clock pass at frame {frame} by {skew} ticks"
        )
    return skew


def run_stride_plan(
    open_runner: Callable[[], AbstractContextManager[ScriptRunner]],
    *,
    keys: Sequence[str],
    first: int,
    last: int,
    stride: int,
    limit: int,
    end_hold: int,
    layout: PlayoneLayout,
    stop_tick: int | None = None,
    every: int = CLOCK_EVERY,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    progress: Callable[[str], None] | None = None,
    parallel: int = DEFAULT_PARALLEL_PASSES,
) -> PlanResult:
    """Sample the film clock, then dump one usable page per *stride* film ticks, in windows.

    Unlike :func:`run_plan`, whose per-frame trace exhausts the Lua budget about 7,800 ticks into
    a film (research/playone-exe/capture-dosbox-automation.md § 4.7), pass 1 reads only the
    clock, every *every* frames, until it has held for *end_hold* frames or reaches *stop_tick*.
    :func:`choose_windows` places at most *limit* windows; window passes (at most
    :data:`~stunt_reel.tac.luagen.MAX_DUMPS` windows each) dump the first usable page of each
    by :func:`~stunt_reel.tac.luagen.window_script`'s rule. The result's trace holds only the
    window frames and ``dropped`` the starts of windows with no usable page.

    Raises ValueError if *every* exceeds :data:`~stunt_reel.tac.luagen.WINDOW_SPAN`, and
    PlanDivergence if a window pass's clock drifts too far from the clock pass.
    """
    # _check_window needs a clock sample inside every window to measure drift.
    if every > WINDOW_SPAN:
        raise ValueError(f"every must be at most WINDOW_SPAN ({WINDOW_SPAN}), got {every}")
    say = progress or (lambda _line: None)
    say("pass 1: sampling the film clock")
    hold = -(-end_hold // every)
    with open_runner() as runner:
        out = runner.run_script(
            clock_script(
                keys=keys,
                first=first,
                last=last,
                every=every,
                end_hold=hold,
                stop_tick=stop_tick,
                layout=layout,
            ),
            timeout=_pass_timeout(timeout, last - first),
        )
    clock = decode_clock(str(out.get("clock", "")), first, every)
    say(f"sampled {len(clock)} clock readings")
    windows = choose_windows(clock, stride=stride, limit=limit, floor=first + WINDOW_LEAD)
    by_frame = dict(clock)
    runs = chunk(windows)

    def window_pass(run: list[Window]) -> tuple[Trace, dict[int, Dump], list[int], list[int]]:
        with open_runner() as runner:
            out = runner.run_script(
                window_script(keys=keys, windows=run, layout=layout),
                timeout=_pass_timeout(timeout, run[-1].start + WINDOW_SPAN - first),
            )
        own = decode_window_trace(str(out.get("trace", "")))
        dumps: dict[int, Dump] = {}
        empty: list[int] = []
        skews: list[int] = []
        for window in run:
            span = range(window.start, window.start + WINDOW_SPAN)
            dumped = next((f for f in span if f"p{f}" in out), None)
            skews.append(_check_window(by_frame, window, own, dumped))
            if dumped is None:
                empty.append(window.start)
                continue
            dumps.update(decode_dumps(out, [dumped], 0, own))
        return own, dumps, empty, skews

    traces: list[Trace] = []
    dumps: dict[int, Dump] = {}
    dropped: list[int] = []
    skews: list[int] = []
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(runs)))) as pool:
        futures = []
        for number, run in enumerate(runs, start=1):
            say(f"window pass {number}/{len(runs)}: {len(run)} windows")
            futures.append(pool.submit(window_pass, run))
        try:
            for future in futures:
                own, kept, empty, skew = future.result()
                traces.append(own)
                dumps.update(kept)
                dropped.extend(empty)
                skews.extend(skew)
        except BaseException:
            pool.shutdown(cancel_futures=True)
            raise
    frames = tuple(f for t in traces for f in t.frames)
    entries = tuple(e for t in traces for e in t.entries)
    trace = Trace(frames[0] if frames else first, entries, frames)
    drifted = [s for s in skews if s > MAX_SKEW_TICKS]
    if drifted:
        say(
            f"{len(drifted)} of {len(windows)} windows read a clock more than {MAX_SKEW_TICKS} "
            f"ticks from the clock pass (at most {max(drifted)})"
        )
    if dropped:
        say(f"{len(dropped)} of {len(windows)} windows held no usable page")
    return PlanResult(trace, dumps, tuple(dropped), clock)
