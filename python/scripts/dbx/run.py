"""Arm a plan's probes on a running film, wait for stops, and record each hit as a JSON line.

DOSBox-X's link has no "stopped" event, so a stop is two equal register snapshots `poll` seconds
apart (spec section 3.5). Guest time is not frozen while the controller reads a hit, so every hit
records its own `film_tick` and nothing is inferred from the order of hits.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from dbx.addr import SiteMismatch, site_matches
from dbx.link import LinkError
from dbx.watch import BACK, resolve_writer

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import TextIO

    from dbx.addr import Runtime
    from dbx.link import Link, Regs
    from dbx.plan import Capture, Plan, Probe
    from dbx.watch import Candidate, Verdict

Reason = Literal["spent", "stop_tick", "timeout", "link_lost", "refused", "error"]

#: Bytes read at a break site before arming, compared with the image.
SITE_BYTES: int = 8
#: Bytes read from the stop onwards for the watch filter.
AHEAD: int = 8
#: Spurious stops written out in full; later ones are only counted.
SPURIOUS_RECORDS: int = 50


@dataclass(frozen=True, slots=True)
class Armed:
    """A probe as set: its break or interrupt-vector sites (`seg, off`), or its watched range."""

    probe: Probe
    sites: tuple[tuple[int, int], ...]
    watch: range | None


@dataclass(frozen=True, slots=True)
class RunResult:
    """How the run ended and what it counted per probe."""

    reason: Reason
    hits: dict[str, int]
    spurious: int
    ignored: dict[str, int]


def _segment(name: str, rt: Runtime, regs: Regs, *, literal: bool = True) -> int:
    """A segment's value: `DS` with a literal offset means DGROUP; otherwise the live register."""
    return rt.ds if name == "DS" and literal else int(getattr(regs, name.lower()))


def arm_probe(link: Link, rt: Runtime, probe: Probe) -> Armed:
    """Set one probe; a break site whose live bytes are not the image's raises `SiteMismatch`."""
    if probe.kind == "break" and probe.at is not None:
        seg, off = rt.code_site(probe.at, probe.cs)
        live = link.dump(seg, off, SITE_BYTES)
        if not site_matches(rt.image, probe.at, live):
            expected = rt.image.data[probe.at : probe.at + SITE_BYTES]
            msg = (
                f'probe "{probe.name}": live bytes {live.hex(" ")} at {seg:04X}:{off:04X} are not '
                f"the image's {expected.hex(' ')} at {probe.at:#x} (wrong build or offset?)"
            )
            raise SiteMismatch(msg)
        link.ex(f"BP {seg:04X}:{off:04X}")
        return Armed(probe, ((seg, off),), None)
    if probe.kind == "watch":
        if probe.linear is not None:
            for i in range(probe.size):
                link.ex(f"BPLM {probe.linear + i:X}")
            return Armed(probe, (), range(probe.linear, probe.linear + probe.size))
        if probe.mem is None:
            msg = f'probe "{probe.name}": a watch with neither mem nor linear'
            raise ValueError(msg)
        name, off = probe.mem
        seg = _segment(name, rt, link.regs())
        for i in range(probe.size):
            link.ex(f"BPM {seg:04X}:{(off + i) & 0xFFFF:04X}")
        start = seg * 16 + off
        return Armed(probe, (), range(start, start + probe.size))
    if probe.kind != "int" or probe.int_no is None:
        msg = f'probe "{probe.name}": not a parsed probe'
        raise ValueError(msg)
    vector = link.dump(0, 4 * probe.int_no, 4)
    target = (int.from_bytes(vector[2:4], "little"), int.from_bytes(vector[0:2], "little"))
    ah = f" {probe.ah:02X}" if probe.ah is not None else ""
    link.ex(f"BPINT {probe.int_no:02X}{ah}")
    return Armed(probe, (target,), None)


@dataclass
class _State:
    """The loop's counters."""

    hits: dict[str, int]
    ignored: dict[str, int]
    spurious: int = 0
    armed: list[Armed] = field(default_factory=list)
    spent: set[str] = field(default_factory=set)


def _capture(link: Link, rt: Runtime, regs: Regs, cap: Capture) -> bytes:
    literal = isinstance(cap.off, int)
    seg = _segment(cap.seg, rt, regs, literal=literal)
    off = cap.off if isinstance(cap.off, int) else int(getattr(regs, cap.off.lower()))
    return link.dump(seg, off & 0xFFFF, cap.length)


def _candidate(rt: Runtime, regs: Regs, c: Candidate) -> dict[str, object]:
    return {
        "start": c.start,
        "image": rt.to_image(regs.cs, c.start),
        "text": c.text,
        "linear": c.linear,
    }


def _hit_record(link: Link, rt: Runtime, probe: Probe, n: int, regs: Regs, tick: int, verdict: Verdict | None) -> dict[str, object]:  # fmt: skip
    words = max((c.length for c in probe.capture if c.kind == "stack"), default=0)
    raw = link.dump(regs.ss, regs.sp, 2 * words) if words else b""
    stack = [int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw), 2)]
    mem = {c.key: _capture(link, rt, regs, c).hex() for c in probe.capture if c.kind == "mem"}
    return {
        "type": "hit",
        "probe": probe.name,
        "n": n,
        "film_tick": tick,
        "regs": regs.as_dict(),
        "cs_ip_image": rt.to_image(regs.cs, regs.ip),
        "return_far_image": rt.to_image(stack[1], stack[0]) if len(stack) >= 2 else None,
        "return_near_image": rt.to_image(regs.cs, stack[0]) if stack else None,
        "stack": stack,
        "mem": mem,
        "verdict": verdict.kind if verdict is not None else None,
        "writer": _candidate(rt, regs, verdict.writer)
        if verdict is not None and verdict.writer
        else None,
        "candidates": [_candidate(rt, regs, c) for c in verdict.candidates]
        if verdict is not None
        else [],
    }


def _classify(
    link: Link, rt: Runtime, state: _State, regs: Regs
) -> tuple[Probe, Verdict | None] | str | None:
    """The probe a stop counts for (with its watch verdict), "ignored", or None for spurious."""
    live = [a for a in state.armed if a.probe.name not in state.spent]
    at = (regs.cs, regs.ip)
    linear = regs.cs * 16 + regs.ip
    for a in live:
        if a.probe.kind == "break" and linear in {seg * 16 + off for seg, off in a.sites}:
            return a.probe, None
    ints = [a for a in live if a.probe.kind == "int"]
    if ints:
        here = link.dump(regs.cs, regs.ip, 2)
        for a in ints:
            p = a.probe
            if p.ah is not None and regs.ax >> 8 != p.ah:
                continue
            if here == bytes([0xCD, p.int_no or 0]) or at in a.sites:
                return p, None
    watches = [a for a in live if a.watch is not None]
    if watches:
        first = max(regs.ip - BACK, 0)
        code = link.dump(regs.cs, first, regs.ip - first + AHEAD)
        for a in watches:
            if a.watch is None:
                continue
            verdict = resolve_writer(code, regs.ip, regs, a.watch)
            if verdict.kind == "spurious":
                continue
            writer = verdict.writer or verdict.candidates[0]
            image = rt.to_image(regs.cs, writer.start)
            if image is not None and image in rt.slot_run:
                state.ignored[a.probe.name] += 1
                return "ignored"
            return a.probe, verdict
    return None


def run_plan(
    link: Link,
    rt: Runtime,
    plan: Plan,
    film_clock: int,
    out: TextIO,
    *,
    header: Mapping[str, object],
    poll: float = 0.05,
    tick_poll: float = 0.1,
    hit_timeout: float = 120.0,
    start: Callable[[], None] | None = None,
) -> RunResult:
    """Run *plan* on the booted film behind *link*, writing JSONL records to *out*.

    *start* (the boot's last key, Enter) is called once the `dialog` probes are armed, so they
    see the film from its first instruction.
    """

    def write(record: Mapping[str, object]) -> None:
        out.write(json.dumps(record) + "\n")
        out.flush()

    def clock() -> int:
        return int.from_bytes(link.dump(rt.ds, film_clock, 2), "little")

    state = _State(hits={p.name: 0 for p in plan.probes}, ignored={p.name: 0 for p in plan.probes})
    pending = [p for p in plan.probes if p.arm != "dialog"]
    write({"type": "run", **header, "load": rt.load, "plan": plan.name, "plan_sha256": plan.sha256})
    reason: Reason = "error"
    arming: str | None = None
    detail = ""

    def arm(probe: Probe) -> Armed:
        nonlocal arming
        arming = probe.name
        armed = arm_probe(link, rt, probe)
        arming = None
        return armed

    try:
        try:
            state.armed = [arm(p) for p in plan.probes if p.arm == "dialog"]
            if start is not None:
                start()
            if state.armed:
                link.ex("RUN")
            last_counted = time.monotonic()
            next_tick = 0.0
            last_stop: Regs | None = None
            while True:
                if len(state.spent) == len(plan.probes):
                    reason = "spent"
                    break
                now = time.monotonic()
                if now - last_counted > hit_timeout:
                    reason = "timeout"
                    break
                if (pending or plan.stop_tick is not None) and now >= next_tick:
                    next_tick = now + tick_poll
                    tick = clock()
                    if plan.stop_tick is not None and tick >= plan.stop_tick:
                        reason = "stop_tick"
                        break
                    due = [p for p in pending if isinstance(p.arm, int) and tick >= p.arm]
                    for p in due:
                        pending.remove(p)
                        state.armed.append(arm(p))
                    if due:
                        link.ex("RUN")
                first = link.regs()
                time.sleep(poll)
                regs = link.regs()
                if first != regs:
                    last_stop = None
                    continue
                if not state.armed:
                    continue
                if regs == last_stop:
                    # Still the stop just handled: the last RUN has not resumed the guest yet.
                    link.ex("RUN")
                    continue
                last_stop = regs
                found = _classify(link, rt, state, regs)
                if found is None:
                    state.spurious += 1
                    if state.spurious <= SPURIOUS_RECORDS:
                        lo = max(regs.ip - BACK, 0)
                        code = link.dump(regs.cs, lo, regs.ip - lo + AHEAD)
                        write({
                            "type": "spurious",
                            "film_tick": clock(),
                            "regs": regs.as_dict(),
                            "cs_ip_image": rt.to_image(regs.cs, regs.ip),
                            "code": code.hex(),
                        })  # fmt: skip
                elif found == "ignored":
                    last_counted = time.monotonic()
                elif isinstance(found, tuple):
                    probe, verdict = found
                    state.hits[probe.name] += 1
                    write(
                        _hit_record(link, rt, probe, state.hits[probe.name], regs, clock(), verdict)
                    )
                    last_counted = time.monotonic()
                    if state.hits[probe.name] >= probe.hits:
                        state.spent.add(probe.name)
                        link.ex("BPDEL *")
                        live = [a.probe for a in state.armed if a.probe.name not in state.spent]
                        state.armed = [a for a in state.armed if a.probe.name in state.spent]
                        state.armed += [arm(p) for p in live]
                link.ex("RUN")
        except SiteMismatch as exc:
            reason, detail = "refused", str(exc)
        except LinkError as exc:
            reason, detail = "link_lost", str(exc)
        except Exception as exc:
            reason, detail = "error", repr(exc)
    finally:
        write({
            "type": "end",
            "reason": reason,
            "hits": state.hits,
            "spurious": state.spurious,
            "ignored": state.ignored,
            "probe": arming if reason == "refused" else None,
            "detail": detail,
        })  # fmt: skip
    return RunResult(reason, state.hits, state.spurious, state.ignored)
