"""Breakpoint plans: the TOML format of `tools/dosbox-x/plans/`, parsed and checked.

Offsets in a plan are unpatched image offsets and unpatched DS offsets; `for_patched` rewrites a
plan for the Patch #3 build through #78's pairing. The format is spec section 3.2 of
`docs/process/plans/debugger-breakpoints-2026-11-04.md`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from dbx.addr import CodeSegment, Unmappable, to_patched, to_patched_data

if TYPE_CHECKING:
    from pathlib import Path

    from build_pairing import Pairing

Kind = Literal["break", "watch", "int"]
Arm = Literal["dialog"] | int

SEGMENTS = frozenset({"CS", "DS", "ES", "SS"})
REGISTERS = frozenset({"AX", "BX", "CX", "DX", "SI", "DI", "BP", "SP"})
RUN_KEYS = frozenset({"cycles", "stop_tick"})
PROBE_KEYS = frozenset(
    {"name", "kind", "at", "patched_at", "cs", "mem", "linear", "size", "int", "ah", "arm", "hits", "capture"}
)  # fmt: skip
MAX_WATCH: int = 16


class PlanError(ValueError):
    """A plan that cannot be run as written."""


@dataclass(frozen=True, slots=True)
class Capture:
    """`stack:<words>`, `mem:<seg>:<off>:<len>` (`off` may name a register) or `lin:<addr>:<len>`.

    A `lin` capture is a linear address, valid only for the build and emulator that produced it.
    """

    kind: Literal["stack", "mem", "lin"]
    seg: str
    off: str | int
    length: int
    key: str


@dataclass(frozen=True, slots=True)
class Probe:
    """One breakpoint, memory watch or interrupt break."""

    name: str
    kind: Kind
    at: int | None = None
    patched_at: int | None = None
    cs: CodeSegment = "auto"
    mem: tuple[str, int] | None = None
    linear: int | None = None
    size: int = 1
    int_no: int | None = None
    ah: int | None = None
    arm: Arm = "dialog"
    hits: int = 1
    capture: tuple[Capture, ...] = ()


@dataclass(frozen=True, slots=True)
class Plan:
    """A whole plan, with the SHA-256 of its text for the run record."""

    name: str
    cycles: int
    stop_tick: int | None
    probes: tuple[Probe, ...]
    sha256: str


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(text: str) -> int | None:
    try:
        return int(text, 0)
    except ValueError:
        return None


def _capture(key: str, fail: Any) -> Capture:
    parts = key.split(":")
    if parts[0] == "stack" and len(parts) == 2 and (words := _number(parts[1])) and words > 0:
        return Capture("stack", "", 0, words, key)
    if parts[0] == "lin" and len(parts) == 3:
        addr, length = _number(parts[1]), _number(parts[2])
        if addr is not None and length is not None and length > 0:
            return Capture("lin", "", addr, length, key)
    if parts[0] == "mem" and len(parts) == 4 and parts[1] in SEGMENTS:
        off: str | int | None = parts[2] if parts[2] in REGISTERS else _number(parts[2])
        length = _number(parts[3])
        if off is not None and length is not None and length > 0:
            return Capture("mem", parts[1], off, length, key)
    raise fail(
        f"bad capture {key!r} (stack:<n>, mem:<CS|DS|ES|SS>:<reg|int>:<len> or lin:<addr>:<len>)"
    )


def _probe(raw: dict[str, Any]) -> Probe:
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        msg = f"a probe without a name: {raw!r}"
        raise PlanError(msg)

    def fail(why: str) -> PlanError:
        return PlanError(f'probe "{name}": {why}')

    unknown = sorted(set(raw) - PROBE_KEYS)
    if unknown:
        raise fail(f"unknown keys {unknown}")
    kind = raw.get("kind")
    if kind not in ("break", "watch", "int"):
        raise fail(f"kind must be break, watch or int, not {kind!r}")
    hits = _int(raw.get("hits", 1))
    if hits is None or hits < 1:
        raise fail("hits must be at least 1")
    arm_raw = raw.get("arm", "dialog")
    arm: Arm
    if arm_raw == "dialog":
        arm = "dialog"
    elif (
        isinstance(arm_raw, dict)
        and set(arm_raw) == {"tick"}
        and (t := _int(arm_raw["tick"])) is not None
        and t >= 0
    ):
        arm = t
    else:
        raise fail('arm must be "dialog" or { tick = N } with N >= 0')
    cs = raw.get("cs", "auto")
    if cs not in ("auto", "module", "vm"):
        raise fail("cs must be auto, module or vm")
    captures = raw.get("capture", [])
    if not isinstance(captures, list) or not all(isinstance(c, str) for c in captures):
        raise fail("capture must be a list of strings")
    probe = Probe(
        name=name,
        kind=cast("Kind", kind),
        hits=hits,
        arm=arm,
        cs=cast("CodeSegment", cs),
        capture=tuple(_capture(c, fail) for c in captures),
    )
    if kind == "break":
        at = _int(raw.get("at"))
        if at is None:
            raise fail("a break needs at = <image offset>")
        patched = raw.get("patched_at")
        if patched is not None and _int(patched) is None:
            raise fail("patched_at must be an int")
        return dataclasses.replace(probe, at=at, patched_at=_int(patched))
    if kind == "watch":
        has_mem, has_linear = "mem" in raw, "linear" in raw
        if has_mem == has_linear:
            raise fail("a watch needs exactly one of mem and linear")
        size = _int(raw.get("size", 1))
        if size is None or not 1 <= size <= MAX_WATCH:
            raise fail(f"size must be 1 to {MAX_WATCH}")
        if has_linear:
            linear = _int(raw["linear"])
            if linear is None:
                raise fail("linear must be an int")
            return dataclasses.replace(probe, linear=linear, size=size)
        seg, _, off = str(raw["mem"]).partition(":")
        offset = _number(off)
        if seg not in SEGMENTS or offset is None:
            raise fail('mem must be "<CS|DS|ES|SS>:<offset>"')
        return dataclasses.replace(probe, mem=(seg, offset), size=size)
    int_no = _int(raw.get("int"))
    if int_no is None or not 0 <= int_no <= 0xFF:
        raise fail("an int probe needs int = <0..0xFF>")
    ah = raw.get("ah")
    if ah is not None and (_int(ah) is None or not 0 <= ah <= 0xFF):
        raise fail("ah must be 0..0xFF")
    return dataclasses.replace(probe, int_no=int_no, ah=_int(ah))


def parse_plan(text: str, name: str) -> Plan:
    """Parse and check a plan's TOML *text*."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        msg = f"plan {name}: {exc}"
        raise PlanError(msg) from exc
    run = doc.get("run", {})
    unknown = sorted(set(run) - RUN_KEYS) + sorted(set(doc) - {"run", "probe"})
    if unknown:
        msg = f"plan {name}: unknown keys {unknown}"
        raise PlanError(msg)
    cycles = _int(run.get("cycles", 8000))
    stop_tick = run.get("stop_tick")
    if cycles is None or cycles < 1 or (stop_tick is not None and _int(stop_tick) is None):
        msg = f"plan {name}: cycles and stop_tick must be ints"
        raise PlanError(msg)
    probes = tuple(_probe(raw) for raw in doc.get("probe", []))
    if not probes:
        msg = f"plan {name}: no probes"
        raise PlanError(msg)
    names = [p.name for p in probes]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        msg = f"plan {name}: duplicate probe names {duplicates}"
        raise PlanError(msg)
    return Plan(name, cycles, _int(stop_tick), probes, hashlib.sha256(text.encode()).hexdigest())


def load_plan(path: Path) -> Plan:
    """Read and parse a plan file; its name is the file stem."""
    return parse_plan(path.read_text(encoding="utf-8"), path.stem)


def for_patched(plan: Plan, pairing: Pairing) -> tuple[Plan, dict[str, str]]:
    """The plan with code and DS offsets moved to Patch #3, and a note per probe of what moved."""
    notes: dict[str, str] = {}
    probes: list[Probe] = []
    for probe in plan.probes:
        moved: list[str] = []
        try:
            changes: dict[str, Any] = {}
            if probe.kind == "break" and probe.at is not None:
                at = (
                    probe.patched_at
                    if probe.patched_at is not None
                    else to_patched(pairing, probe.at)
                )
                moved.append(
                    f"at {probe.at:#x}->{at:#x}"
                    + (" (patched_at)" if probe.patched_at is not None else "")
                )
                changes["at"] = at
            if probe.mem is not None and probe.mem[0] == "DS":
                off = to_patched_data(pairing, probe.mem[1])
                moved.append(f"DS:{probe.mem[1]:#x}->{off:#x}")
                changes["mem"] = ("DS", off)
            captures: list[Capture] = []
            for cap in probe.capture:
                if cap.kind == "mem" and cap.seg == "DS" and isinstance(cap.off, int):
                    off = to_patched_data(pairing, cap.off)
                    moved.append(f"{cap.key}->{off:#x}")
                    cap = dataclasses.replace(cap, off=off)  # noqa: PLW2901
                captures.append(cap)
            changes["capture"] = tuple(captures)
        except Unmappable as exc:
            msg = f'probe "{probe.name}": {exc}'
            raise PlanError(msg) from exc
        probes.append(dataclasses.replace(probe, **changes))
        if moved:
            notes[probe.name] = "; ".join(moved)
    return dataclasses.replace(plan, probes=tuple(probes)), notes
