"""Plans: decoding a trace, picking frames, chunking dumps and running both passes offline."""

from __future__ import annotations

import importlib.util
import inspect
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from stunt_reel.tac import framebuffer, luagen, plan, playone
from stunt_reel.tac.automation import MockAutomation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

KEYS = ["KBD_c", "KBD_down", "KBD_enter"]
FIRST = 1300
PAGE = b"\x07" * plan.FRAME_BYTES


@pytest.mark.parametrize("fn", [luagen.script, plan.run_plan, framebuffer.capture])
def test_every_capture_entry_point_requires_a_layout(fn: Callable[..., object]) -> None:
    # A default would read a Patch #3 build at unpatched offsets without a word.
    assert inspect.signature(fn).parameters["layout"].default is inspect.Parameter.empty


def _trace_text(entries: list[tuple[int, int, int]]) -> str:
    return "x" + ",".join(f"{t}:{g}:{c}" for t, g, c in entries)


def test_decode_trace_reads_clocks_changed_flags_and_extra_words() -> None:
    trace = plan.decode_trace("x5:100:1,6:101:0,6:102:1", FIRST)
    assert trace.first == FIRST
    assert [e.film_tick for e in trace.entries] == [5, 6, 6]
    assert [e.global_tick for e in trace.entries] == [100, 101, 102]
    assert [e.changed for e in trace.entries] == [True, False, True]
    assert trace.entry(FIRST + 2).global_tick == 102
    assert trace.frames == range(FIRST, FIRST + 3)

    wide = plan.decode_trace("x5:100:77:0", FIRST)
    assert wide.entries[0].words == (77,)
    assert wide.entries[0].changed is False


def test_trace_decodes_the_flag_mask() -> None:
    trace = plan.decode_trace("x5:7:3,6:8:4", FIRST)

    torn, palette = trace.entries
    assert (torn.changed, torn.torn, torn.palette_changed) == (True, True, False)
    assert (palette.changed, palette.torn, palette.palette_changed) == (False, False, True)


def test_trace_refuses_a_mask_above_seven() -> None:
    with pytest.raises(plan.PlanError):
        plan.decode_trace("x5:7:8", FIRST)


def test_decode_trace_requires_the_letter_prefix() -> None:
    with pytest.raises(plan.PlanError, match="prefix"):
        plan.decode_trace("5:100:1", FIRST)
    with pytest.raises(plan.PlanError, match="malformed"):
        plan.decode_trace("x5:abc:1", FIRST)


def test_chunk_splits_a_frame_list_into_runs_of_at_most_the_dump_limit() -> None:
    chunks = plan.chunk(list(range(200)))

    assert [len(c) for c in chunks] == [40, 40, 40, 40, 40]
    assert [f for c in chunks for f in c] == list(range(200))
    assert plan.chunk([]) == []


def test_chunk_balances_the_passes() -> None:
    """Passes run side by side, so a one-frame last pass would cost a whole replay for nothing."""
    chunks = plan.chunk(list(range(121)))

    assert [len(c) for c in chunks] == [31, 30, 30, 30]
    assert [f for c in chunks for f in c] == list(range(121))


def test_pick_new_film_ticks_takes_the_first_changed_frame_per_stride() -> None:
    entries = [(0, 0, 1), (10, 1, 1), (10, 2, 0), (15, 3, 1), (21, 4, 1), (22, 5, 1), (40, 6, 0)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)

    assert plan.pick_every(trace, stride=11) == [FIRST + 1, FIRST + 4]
    assert plan.pick_every(trace, stride=1) == [FIRST + 1, FIRST + 3, FIRST + 4, FIRST + 5]


def test_pick_ticks_takes_the_first_frame_at_or_after_each_requested_tick() -> None:
    entries = [(5, 0, 1), (9, 1, 1), (12, 2, 1), (30, 3, 1)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)

    assert plan.pick_ticks(trace, [6, 12, 25, 99]) == [FIRST + 1, FIRST + 2, FIRST + 3]


CHANGED, TORN, PALETTE = luagen.TRACE_CHANGED, luagen.TRACE_TORN, luagen.TRACE_PALETTE


def test_pick_every_skips_a_torn_frame_for_the_next_change() -> None:
    entries = [(1, 0, CHANGED), (2, 1, CHANGED | TORN), (3, 2, CHANGED)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)

    assert plan.pick_every(trace, stride=1) == [FIRST, FIRST + 2]


def test_pick_every_skips_the_two_frames_of_a_palette_step() -> None:
    """The DAC shows W(f-1) low and W(f-2) high, so a step at c spoils c and c + 1."""
    entries = [(1, 0, CHANGED), (2, 1, CHANGED | PALETTE), (3, 2, CHANGED), (4, 3, CHANGED)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)

    assert plan.pick_every(trace, stride=1) == [FIRST, FIRST + 3]


def test_pick_ticks_moves_past_an_unusable_frame() -> None:
    entries = [(5, 0, CHANGED), (10, 1, CHANGED | TORN), (11, 2, CHANGED)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)

    assert plan.pick_ticks(trace, [10]) == [FIRST + 2]


def test_a_palette_step_at_the_first_frame_spares_nothing_before_it() -> None:
    entries = [(1, 0, CHANGED | PALETTE), (2, 1, CHANGED), (3, 2, CHANGED)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)

    assert plan.usable(trace, FIRST) is False
    assert plan.usable(trace, FIRST + 1) is False
    assert plan.usable(trace, FIRST + 2) is True


def test_a_dump_pass_that_reads_a_torn_page_drops_it() -> None:
    """Jitter (COUNT.FLM) can move a tear onto a picked frame: drop that page, keep the rest."""
    torn_at_pick = [(t, g, c | (TORN if i == 3 else 0)) for i, (t, g, c) in enumerate(ENTRIES)]
    mock = _runner(ENTRIES, dump_entries=torn_at_pick)
    lines: list[str] = []

    result = plan.run_plan(
        _open(mock),
        keys=KEYS,
        layout=playone.UNPATCHED,
        first=FIRST,
        last=FIRST + 50,
        pick=lambda trace: [trace.first + 3, trace.first + 5],
        timeout=5,
        progress=lines.append,
    )

    assert sorted(result.dumps) == [FIRST + 5]
    assert result.dropped == (FIRST + 3,)
    assert any(f"unusable page at frame {FIRST + 3}" in line for line in lines)


def test_pick_ticks_can_keep_unusable_frames_for_a_memory_probe() -> None:
    """A probe that reads memory, not the page, wants the first frame at the tick, torn or not."""
    entries = [(5, 0, CHANGED), (10, 1, CHANGED | TORN), (11, 2, CHANGED | PALETTE)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)

    assert plan.pick_ticks(trace, [10, 11], skip_unusable=False) == [FIRST + 1, FIRST + 2]


def test_a_plan_that_reads_no_page_keeps_a_torn_dump() -> None:
    torn_at_pick = [(t, g, c | (TORN if i == 3 else 0)) for i, (t, g, c) in enumerate(ENTRIES)]
    mock = _runner(ENTRIES, dump_entries=torn_at_pick)

    result = plan.run_plan(
        _open(mock),
        keys=KEYS,
        layout=playone.UNPATCHED,
        first=FIRST,
        last=FIRST + 50,
        pick=lambda trace: [trace.first + 3, trace.first + 5],
        timeout=5,
        skip_unusable=False,
    )

    assert sorted(result.dumps) == [FIRST + 3, FIRST + 5]
    assert result.dropped == ()


def test_the_light_probe_samples_torn_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """probe_playone_light reads the work and DGROUP segments, which a torn page does not spoil."""
    path = Path(__file__).resolve().parent.parent / "python" / "scripts" / "probe_playone_light.py"
    spec = importlib.util.spec_from_file_location("probe_playone_light", path)
    assert spec is not None
    assert spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    entries = [(5, 0, CHANGED), (10, 1, CHANGED | TORN), (11, 2, CHANGED)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)
    seen: dict[str, Any] = {}

    def run_plan(_open_runner: object, **kwargs: Any) -> plan.PlanResult:
        seen.update(kwargs, picked=list(kwargs["pick"](trace)))
        return plan.PlanResult(trace, {})

    monkeypatch.setattr(plan, "run_plan", run_plan)
    probe.probe(
        _open(_runner(ENTRIES)), KEYS, [10], tmp_path, dump_all=False, layout=playone.UNPATCHED
    )

    assert seen["picked"] == [FIRST + 1]
    assert seen["skip_unusable"] is False


def _dump_output(frames: list[int], trace: str) -> dict[str, Any]:
    out: dict[str, Any] = {"trace": trace, "done": True}
    for f in frames:
        out[f"p{f}"] = "x" + PAGE.hex()
        out[f"c{f}"] = "x" + bytes(range(64)).hex() * 12
        out[f"m{f}_1"] = "x" + b"\x01\x02".hex()
    return out


def _runner(
    entries: list[tuple[int, int, int]],
    *,
    dump_entries: list[tuple[int, int, int]] | None = None,
) -> MockAutomation:
    """A film whose dump passes trace *dump_entries* (default: the same as the trace pass)."""
    text = _trace_text(entries)
    dump_text = text if dump_entries is None else _trace_text(dump_entries)

    def handler(lua: str) -> dict[str, Any]:
        match = re.search(r"local dumps = \{([^}]*)\}", lua)
        frames = [int(x) for x in match.group(1).split(",")] if match and match.group(1) else []
        return _dump_output(frames, dump_text if frames else text)

    return MockAutomation(handler)


def _open(mock: MockAutomation) -> Any:
    @contextmanager
    def opener() -> Iterator[MockAutomation]:
        yield mock

    return opener


ENTRIES = [(t, t + 100, 1) for t in range(0, 400, 2)]


def test_run_plan_traces_picks_then_dumps_in_chunks() -> None:
    mock = _runner(ENTRIES)

    result = plan.run_plan(
        _open(mock),
        keys=KEYS,
        layout=playone.UNPATCHED,
        first=FIRST,
        last=FIRST + len(ENTRIES) - 1,
        pick=lambda trace: plan.pick_every(trace, stride=2),
        ranges=[luagen.MemRange(0x17C9, 0, 2)],
        timeout=5,
    )

    picked = sorted(result.dumps)
    assert len(picked) == len(ENTRIES) - 1  # tick 0 is not a film frame
    # One trace pass, then ceil(199 / 39) = 6 dump passes: the 2-byte range trims 40 to 39.
    assert len(mock.scripts) == 1 + 6
    assert all('out["p"' not in s for s in mock.scripts[:1])
    dump = result.dumps[picked[0]]
    assert dump.page == PAGE
    assert dump.ranges == (b"\x01\x02",)
    assert len(dump.palette6) == 768
    assert result.trace.entry(picked[0]).film_tick == 2


def test_dump_passes_run_side_by_side_up_to_the_limit() -> None:
    """A long film needs many replays (INTRO: 8 passes, 17 min one after another)."""
    mock = _runner(ENTRIES)
    lock = threading.Lock()
    state = {"open": 0, "most": 0}

    @contextmanager
    def opener() -> Iterator[MockAutomation]:
        with lock:
            state["open"] += 1
            state["most"] = max(state["most"], state["open"])
        try:
            time.sleep(0.05)
            yield mock
        finally:
            with lock:
                state["open"] -= 1

    result = plan.run_plan(
        opener,
        keys=KEYS,
        layout=playone.UNPATCHED,
        first=FIRST,
        last=FIRST + len(ENTRIES) - 1,
        pick=lambda trace: plan.pick_every(trace, stride=2),
        timeout=5,
        parallel=3,
    )

    assert len(result.dumps) == len(ENTRIES) - 1
    assert state["most"] == 3


def test_extra_ranges_shrink_each_pass_to_the_measured_byte_budget() -> None:
    """40 page-only dumps fit Lua's memory; 40 pages plus a 60 KiB segment each would not."""
    mock = _runner(ENTRIES)
    probe_ranges = [luagen.MemRange(0x17C9, 0, 0xF000)]

    plan.run_plan(
        _open(mock),
        keys=KEYS,
        layout=playone.UNPATCHED,
        first=FIRST,
        last=FIRST + len(ENTRIES) - 1,
        pick=lambda trace: plan.pick_every(trace, stride=2)[:40],
        ranges=probe_ranges,
        timeout=5,
    )

    per_pass = [
        len(re.findall(r"\d+", m.group(1)))
        for s in mock.scripts[1:]
        if (m := re.search(r"local dumps = \{([^}]*)\}", s))
    ]
    page_only = plan.FRAME_BYTES + plan.PALETTE_BYTES
    assert max(per_pass) <= page_only * luagen.MAX_DUMPS // (page_only + 0xF000) < luagen.MAX_DUMPS
    assert sum(per_pass) == 40


def test_run_plan_with_nothing_picked_runs_only_the_trace() -> None:
    mock = _runner(ENTRIES)

    result = plan.run_plan(
        _open(mock),
        keys=KEYS,
        layout=playone.UNPATCHED,
        first=FIRST,
        last=FIRST + 10,
        pick=lambda _trace: [],
        timeout=5,
    )

    assert result.dumps == {}
    assert len(mock.scripts) == 1


def test_a_dump_keeps_the_tick_its_own_pass_read_when_the_film_jitters() -> None:
    """A tick of jitter between passes (live on COUNT.FLM) labels the page with its own tick."""
    lagging = [(max(t - 1, 0), g - 1, c) for t, g, c in ENTRIES]
    mock = _runner(ENTRIES, dump_entries=lagging)
    lines: list[str] = []

    result = plan.run_plan(
        _open(mock),
        keys=KEYS,
        layout=playone.UNPATCHED,
        first=FIRST,
        last=FIRST + 50,
        pick=lambda trace: [trace.first + 3, trace.first + 5],
        timeout=5,
        progress=lines.append,
    )

    assert result.trace.entry(FIRST + 3).film_tick == 6
    assert result.dumps[FIRST + 3].entry.film_tick == 5
    assert result.dumps[FIRST + 3].entry.global_tick == 105
    assert "2 of 2 dumped frames read another tick than the trace pass (at most 1)" in lines


def test_a_dump_pass_that_drifts_past_the_skew_is_a_divergence() -> None:
    far = [(t + plan.MAX_SKEW_TICKS + 1, g, c) for t, g, c in ENTRIES]
    mock = _runner(ENTRIES, dump_entries=far)

    with pytest.raises(plan.PlanDivergence, match="frame"):
        plan.run_plan(
            _open(mock),
            keys=KEYS,
            layout=playone.UNPATCHED,
            first=FIRST,
            last=FIRST + 50,
            pick=lambda trace: [trace.first + 3],
            timeout=5,
        )


def test_a_dump_pass_that_ends_before_a_picked_frame_is_a_divergence() -> None:
    mock = _runner(ENTRIES, dump_entries=ENTRIES[:3])

    with pytest.raises(plan.PlanDivergence, match="traced only"):
        plan.run_plan(
            _open(mock),
            keys=KEYS,
            layout=playone.UNPATCHED,
            first=FIRST,
            last=FIRST + 50,
            pick=lambda trace: [trace.first + 3],
            timeout=5,
        )


def test_the_palette_scales_six_bit_levels_like_the_video_dac() -> None:
    palette6 = bytes([0, 31, 63] + [0] * 765)

    rgb = plan.palette_rgb(palette6)

    assert rgb[0] == (0, 125, 255)  # round(31 * 255 / 63) is 125.48
    assert len(rgb) == 256


def test_ranges_may_depend_on_the_trace_and_the_picked_frames() -> None:
    mock = _runner(ENTRIES)
    seen: list[tuple[int, list[int]]] = []

    def ranges(trace: plan.Trace, frames: Sequence[int]) -> list[luagen.MemRange]:
        seen.append((len(trace.entries), list(frames)))
        return [luagen.MemRange(0x17C9, 0, 2)]

    result = plan.run_plan(
        _open(mock),
        keys=KEYS,
        layout=playone.UNPATCHED,
        first=FIRST,
        last=FIRST + len(ENTRIES) - 1,
        pick=lambda trace: [trace.first + 5],
        ranges=ranges,
        timeout=5,
    )

    assert seen == [(len(ENTRIES), [FIRST + 5])]
    assert result.dumps[FIRST + 5].ranges == (b"\x01\x02",)
    assert "0x17C9" in mock.scripts[-1]
