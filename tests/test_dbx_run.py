"""The hit loop: arming, stop classification, records and every way a run ends."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
lazy from collections.abc import Iterator

import pytest
from dbx.addr import Runtime, SiteMismatch
from dbx.link import REGS_EV, Link, Listener, Regs
from dbx.plan import Plan, parse_plan
from dbx.run import RunResult, arm_probe, run_plan

import dbx_stubs
from dbx_peer import FakePeer

LOAD = 0x0824
CLOCK = 0x4896
IMG = dbx_stubs.put(
    dbx_stubs.put(dbx_stubs.image(), 0x9100, bytes.fromhex("1ebfd4158edf5589")),
    0x759C - 6,
    bytes.fromhex("909090908bc8"),
)
RT = Runtime(IMG, load=LOAD, dgroup_paragraph=0xD51, vm=0x824)
STOP = Regs(cs=0x1048, ip=0x0EC0, ss=0x2AAA, sp=0xEE94, ds=0x1575, es=0x6B71,
            ax=0x63, bx=0x7FFE, cx=0, dx=0xFFEF, si=0x000C, di=0, bp=0)  # fmt: skip


@dataclass
class Guest:
    """A pretend PLAYONE: each RUN moves to the next stop, then it runs forever."""

    stops: list[Regs]
    memory: dict[int, int] = field(default_factory=dict)
    clock: list[int] = field(default_factory=lambda: [0])
    stuck: Regs | None = None
    close_on_run: int | None = None
    log: list[str] = field(default_factory=list)
    clock_reads: list[int] = field(default_factory=list)
    _at: int = -1
    _runs: int = 0
    _tick: int = 0

    def script(self, command: str) -> list[str] | None:
        self.log.append(command)
        if command == "EXEC RUN":
            self._runs += 1
            if self._runs == self.close_on_run:
                return None
            self._at += 1
            return []
        if command == f"EXEC {REGS_EV}":
            regs = self._regs()
            return ["EV is:", " ".join(f"{v:x}" for v in regs.as_dict().values())]
        if command.startswith(f"EXEC MEMDUMPBIN {RT.ds:04X}:{CLOCK:04X} 2 "):
            value = self.clock[min(len(self.clock_reads), len(self.clock) - 1)]
            self.clock_reads.append(len(self.log) - 1)
            Path(command.rsplit(" ", 1)[1]).write_bytes(value.to_bytes(2, "little"))
        return []

    def _regs(self) -> Regs:
        if self.stuck is not None:
            return self.stuck
        if 0 <= self._at < len(self.stops):
            return self.stops[self._at]
        self._tick += 1
        return replace(STOP, cs=0x0824, ip=self._tick & 0xFFFF)


def mirrored(**extra: int) -> dict[int, int]:
    """Guest memory holding the image at the load paragraph, plus *extra* `linear=value` bytes."""
    memory = {LOAD * 16 + i: b for i, b in enumerate(IMG.data) if b}
    memory |= {int(k[1:], 16): v for k, v in extra.items()}
    return memory


def stack_at(regs: Regs, *words: int) -> dict[int, int]:
    base = regs.ss * 16 + regs.sp
    return {base + 2 * i + j: (w >> (8 * j)) & 0xFF for i, w in enumerate(words) for j in (0, 1)}


@pytest.fixture
def connect(tmp_path: Path) -> Iterator[object]:
    listener = Listener()
    links: list[Link] = []

    def make(guest: Guest) -> Link:
        peer = FakePeer(listener.port, guest.script)
        peer.memory = guest.memory
        link = Link(listener.accept(5.0), tmp_path, timeout=5.0)
        links.append(link)
        return link

    yield make
    for link in links:
        link.close()
    listener.close()


def go(
    link: Link, plan: Plan, hit_timeout: float = 0.4
) -> tuple[RunResult, list[dict[str, object]]]:
    out = io.StringIO()
    header = {"build": "unpatched"}
    result = run_plan(
        link,
        RT,
        plan,
        CLOCK,
        out,
        header=header,
        poll=0.005,
        tick_poll=0.005,
        hit_timeout=hit_timeout,
    )
    return result, [json.loads(line) for line in out.getvalue().splitlines()]


BREAK = (
    '[[probe]]\nname = "light"\nkind = "break"\nat = 0x9100\nhits = {hits}\ncapture = ["stack:4"]\n'
)


def test_break_hit_record(connect) -> None:  # type: ignore[no-untyped-def]
    second = replace(STOP, es=0x6B72)
    guest = Guest(
        [STOP, second],
        memory=mirrored() | stack_at(STOP, 0x2350, 0x0824) | stack_at(second, 0x2350, 0x0824),
    )
    result, records = go(connect(guest), parse_plan(BREAK.format(hits=2), "smoke"))
    assert [r["type"] for r in records] == ["run", "hit", "hit", "end"]
    assert records[0]["plan"] == "smoke"
    assert records[0]["build"] == "unpatched"
    assert records[0]["load"] == LOAD
    hit = records[1]
    assert hit["cs_ip_image"] == 0x9100
    assert hit["return_far_image"] == 0x2350
    assert hit["stack"] == [0x2350, 0x0824, 0, 0]
    assert hit["regs"]["ax"] == 0x63  # type: ignore[index]
    assert result.reason == "spent"
    assert records[-1]["reason"] == "spent"
    assert result.hits == {"light": 2}


def test_site_mismatch_refuses(connect) -> None:  # type: ignore[no-untyped-def]
    link = connect(Guest([]))
    with pytest.raises(SiteMismatch, match="light"):
        arm_probe(link, RT, parse_plan(BREAK.format(hits=1), "p").probes[0])


WATCH = '[[probe]]\nname = "clock"\nkind = "watch"\n{where}\nsize = 2\n'


def test_watch_spurious_counted(connect) -> None:  # type: ignore[no-untyped-def]
    stop = replace(STOP, cs=0x0824, ip=0x759C)
    guest = Guest([stop], memory=mirrored())
    result, records = go(connect(guest), parse_plan(WATCH.format(where='mem = "DS:0x4896"'), "w"))
    assert [r["type"] for r in records] == ["run", "spurious", "end"]
    assert records[1]["cs_ip_image"] == 0x759C
    assert str(records[1]["code"]).startswith(
        "909090908bc8"
    )  # six bytes before the stop, then eight
    assert result.spurious == 1
    assert result.reason == "timeout"


def test_watch_ignored_in_slot_run(connect) -> None:  # type: ignore[no-untyped-def]
    # The first slot, `mov word es:[si-2], imm16` at image 0x8240, wrote es:[0x0C].
    stop = replace(STOP, cs=0x1048, ip=0x0006, es=0x6B71, si=0x000E)
    guest = Guest([stop], memory=mirrored())
    plan = parse_plan(WATCH.format(where="linear = 0x6B71C"), "w")
    result, records = go(connect(guest), plan)
    assert result.ignored == {"clock": 1}
    assert "hit" not in [r["type"] for r in records]


def test_watch_write_is_a_hit(connect) -> None:  # type: ignore[no-untyped-def]
    img = dbx_stubs.put(IMG, 0x43E6 - 2, bytes.fromhex("909011069648"))
    rt = replace(RT, image=img)
    stop = replace(STOP, cs=0x0824, ip=0x43EA)
    guest = Guest([stop], memory={LOAD * 16 + i: b for i, b in enumerate(img.data) if b})
    out = io.StringIO()
    plan = parse_plan(WATCH.format(where='mem = "DS:0x4896"'), "w")
    result = run_plan(
        connect(guest),
        rt,
        plan,
        CLOCK,
        out,
        header={},
        poll=0.005,
        tick_poll=0.005,
        hit_timeout=0.4,
    )
    hit = [json.loads(line) for line in out.getvalue().splitlines()][1]
    assert hit["verdict"] == "write"
    assert hit["writer"]["image"] == 0x43E6
    assert result.reason == "spent"


def test_shared_site_goes_to_first_unspent(connect) -> None:  # type: ignore[no-untyped-def]
    text = BREAK.format(hits=1) + BREAK.format(hits=1).replace('"light"', '"light-2"')
    guest = Guest([STOP, replace(STOP, es=0x6B72)], memory=mirrored())
    result, records = go(connect(guest), parse_plan(text, "two"))
    assert [r.get("probe") for r in records if r["type"] == "hit"] == ["light", "light-2"]
    assert result.reason == "spent"
    assert "EXEC BPDEL *" in guest.log


INT = '[[probe]]\nname = "reads"\nkind = "int"\nint = 0x21\nah = 0x3F\n'


@pytest.mark.parametrize(("ax", "hits"), [(0x3F00, 1), (0x4200, 0)])
def test_int_stop_on_cd(connect, ax: int, hits: int) -> None:  # type: ignore[no-untyped-def]
    stop = replace(STOP, cs=0x0824, ip=0x1234, ax=ax)
    memory = mirrored() | {LOAD * 16 + 0x1234: 0xCD, LOAD * 16 + 0x1235: 0x21}
    guest = Guest([stop], memory=memory)
    result, _ = go(connect(guest), parse_plan(INT, "i"))
    assert result.hits == {"reads": hits}
    assert result.spurious == 1 - hits
    assert any(c.startswith("EXEC BPINT 21 3F") for c in guest.log)


def test_link_lost_writes_end(connect) -> None:  # type: ignore[no-untyped-def]
    guest = Guest([STOP, replace(STOP, es=1)], memory=mirrored(), close_on_run=2)
    result, records = go(connect(guest), parse_plan(BREAK.format(hits=2), "p"))
    assert [r["type"] for r in records] == ["run", "hit", "end"]
    assert result.reason == "link_lost"


def test_timeout_ends_run(connect) -> None:  # type: ignore[no-untyped-def]
    result, records = go(
        connect(Guest([], memory=mirrored())),
        parse_plan(BREAK.format(hits=1), "p"),
        hit_timeout=0.3,
    )
    assert result.reason == "timeout"
    assert records[-1]["type"] == "end"


def test_spurious_stream_still_times_out(connect) -> None:  # type: ignore[no-untyped-def]
    guest = Guest([], memory=mirrored(), stuck=replace(STOP, cs=0x0824, ip=0x0100))
    result, _ = go(connect(guest), parse_plan(BREAK.format(hits=1), "p"), hit_timeout=0.3)
    assert result.reason == "timeout"
    assert result.spurious >= 1


def test_tick_arm_waits(connect) -> None:  # type: ignore[no-untyped-def]
    text = BREAK.format(hits=1).replace("hits = 1", "hits = 1\narm = { tick = 10 }")
    guest = Guest([STOP], memory=mirrored(), clock=[5, 9, 12])
    result, _ = go(connect(guest), parse_plan(text, "t"))
    first_bp = next(i for i, c in enumerate(guest.log) if c.startswith("EXEC BP "))
    assert first_bp > guest.clock_reads[2]
    assert result.reason == "spent"


def test_stop_tick_ends_run(connect) -> None:  # type: ignore[no-untyped-def]
    text = "[run]\nstop_tick = 600\n" + BREAK.format(hits=5)
    result, _ = go(connect(Guest([], memory=mirrored(), clock=[100, 700])), parse_plan(text, "s"))
    assert result.reason == "stop_tick"


def test_mismatch_mid_run_is_refused(connect) -> None:  # type: ignore[no-untyped-def]
    text = BREAK.format(hits=1).replace("hits = 1", "hits = 1\narm = { tick = 10 }")
    result, records = go(connect(Guest([], clock=[12])), parse_plan(text, "m"))
    assert result.reason == "refused"
    assert records[-1]["probe"] == "light"


def test_dialog_probes_arm_before_start(connect) -> None:  # type: ignore[no-untyped-def]
    guest = Guest([STOP], memory=mirrored())
    started: list[int] = []
    out = io.StringIO()
    run_plan(connect(guest), RT, parse_plan(BREAK.format(hits=1), "d"), CLOCK, out, header={},
             poll=0.005, tick_poll=0.005, hit_timeout=0.4, start=lambda: started.append(len(guest.log)))  # fmt: skip
    first_bp = next(i for i, c in enumerate(guest.log) if c.startswith("EXEC BP "))
    assert started
    assert first_bp < started[0]


def test_identical_repeat_stop_resumes(connect) -> None:  # type: ignore[no-untyped-def]
    # The first RUN after a hit leaves the guest where it was; the loop must RUN again.
    second = replace(STOP, es=0x6B72)
    guest = Guest([STOP, STOP, second], memory=mirrored())
    result, _ = go(connect(guest), parse_plan(BREAK.format(hits=2), "r"))
    assert result.reason == "spent"
    assert result.hits == {"light": 2}


def test_unexpected_error_is_recorded(connect) -> None:  # type: ignore[no-untyped-def]
    text = BREAK.format(hits=1).replace("0x9100", "0x10000")
    result, records = go(connect(Guest([], memory=mirrored())), parse_plan(text, "e"))
    assert result.reason == "error"
    assert "0x10000" in str(records[-1]["detail"])


def test_register_ds_capture_reads_live_ds(connect) -> None:  # type: ignore[no-untyped-def]
    stop = replace(STOP, ds=0x2000, dx=0x0010)
    text = BREAK.format(hits=1).replace('["stack:4"]', '["mem:DS:DX:2", "mem:DS:0x49EC:2"]')
    memory = mirrored() | {0x20010: 0xAB, 0x20011: 0xCD, RT.ds * 16 + 0x49EC: 0x63}
    _, records = go(connect(Guest([stop], memory=memory)), parse_plan(text, "c"))
    mem = records[1]["mem"]
    assert mem == {"mem:DS:DX:2": "abcd", "mem:DS:0x49EC:2": "6300"}  # literal offsets read DGROUP
