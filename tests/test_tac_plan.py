"""Plans: decoding a trace, picking frames, chunking dumps and running both passes offline."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from stunt_reel.tac import luagen, plan
from stunt_reel.tac.automation import MockAutomation

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

KEYS = ["KBD_c", "KBD_down", "KBD_enter"]
FIRST = 1300
PAGE = b"\x07" * plan.FRAME_BYTES


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


def test_decode_trace_requires_the_letter_prefix() -> None:
    with pytest.raises(plan.PlanError, match="prefix"):
        plan.decode_trace("5:100:1", FIRST)
    with pytest.raises(plan.PlanError, match="malformed"):
        plan.decode_trace("x5:abc:1", FIRST)


def test_chunk_splits_a_frame_list_into_runs_of_at_most_ninety() -> None:
    chunks = plan.chunk(list(range(200)))

    assert [len(c) for c in chunks] == [90, 90, 20]
    assert [f for c in chunks for f in c] == list(range(200))
    assert plan.chunk([]) == []


def test_pick_new_film_ticks_takes_the_first_changed_frame_per_stride() -> None:
    entries = [(0, 0, 1), (10, 1, 1), (10, 2, 0), (15, 3, 1), (21, 4, 1), (22, 5, 1), (40, 6, 0)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)

    assert plan.pick_every(trace, stride=11) == [FIRST + 1, FIRST + 4]
    assert plan.pick_every(trace, stride=1) == [FIRST + 1, FIRST + 3, FIRST + 4, FIRST + 5]


def test_pick_ticks_takes_the_first_frame_at_or_after_each_requested_tick() -> None:
    entries = [(5, 0, 1), (9, 1, 1), (12, 2, 1), (30, 3, 1)]
    trace = plan.decode_trace(_trace_text(entries), FIRST)

    assert plan.pick_ticks(trace, [6, 12, 25, 99]) == [FIRST + 1, FIRST + 2, FIRST + 3]


def _dump_output(frames: list[int], trace: str) -> dict[str, Any]:
    out: dict[str, Any] = {"trace": trace, "done": True}
    for f in frames:
        out[f"p{f}"] = "x" + PAGE.hex()
        out[f"c{f}"] = "x" + bytes(range(64)).hex() * 12
        out[f"m{f}_1"] = "x" + b"\x01\x02".hex()
    return out


def _runner(entries: list[tuple[int, int, int]], *, corrupt: bool = False) -> MockAutomation:
    text = _trace_text(entries)

    def handler(lua: str) -> dict[str, Any]:
        match = re.search(r"local dumps = \{([^}]*)\}", lua)
        frames = [int(x) for x in match.group(1).split(",")] if match and match.group(1) else []
        reply = text if not (corrupt and frames) else _trace_text([(9, 9, 1), *entries[1:]])
        return _dump_output(frames, reply)

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
        first=FIRST,
        last=FIRST + len(ENTRIES) - 1,
        pick=lambda trace: plan.pick_every(trace, stride=2),
        ranges=[luagen.MemRange(0x17C9, 0, 2)],
        timeout=5,
    )

    picked = sorted(result.dumps)
    assert len(picked) == len(ENTRIES) - 1  # tick 0 is not a film frame
    assert len(mock.scripts) == 1 + 3  # one trace pass, then ceil(199 / 90) dump passes
    assert all('out["p"' not in s for s in mock.scripts[:1])
    dump = result.dumps[picked[0]]
    assert dump.page == PAGE
    assert dump.ranges == (b"\x01\x02",)
    assert len(dump.palette6) == 768
    assert result.trace.entry(picked[0]).film_tick == 2


def test_run_plan_with_nothing_picked_runs_only_the_trace() -> None:
    mock = _runner(ENTRIES)

    result = plan.run_plan(
        _open(mock),
        keys=KEYS,
        first=FIRST,
        last=FIRST + 10,
        pick=lambda _trace: [],
        timeout=5,
    )

    assert result.dumps == {}
    assert len(mock.scripts) == 1


def test_a_dump_pass_that_disagrees_with_the_trace_is_a_divergence() -> None:
    mock = _runner(ENTRIES, corrupt=True)

    with pytest.raises(plan.PlanDivergence, match="frame"):
        plan.run_plan(
            _open(mock),
            keys=KEYS,
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
        first=FIRST,
        last=FIRST + len(ENTRIES) - 1,
        pick=lambda trace: [trace.first + 5],
        ranges=ranges,
        timeout=5,
    )

    assert seen == [(len(ENTRIES), [FIRST + 5])]
    assert result.dumps[FIRST + 5].ranges == (b"\x01\x02",)
    assert "0x17C9" in mock.scripts[-1]
