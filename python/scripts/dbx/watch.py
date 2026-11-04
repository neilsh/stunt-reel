"""Which instruction a `BPM`/`BPLM` stop followed, and whether it wrote the watched bytes.

A memory-breakpoint stop leaves `IP` after the instruction that changed the byte, or on a `rep`
string instruction that DOSBox re-executes in place. The stop's registers are the ones after the
write, so string ops have already moved `SI`/`DI` and `push`/`call` have already moved `SP`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import iced_x86 as ix

if TYPE_CHECKING:
    from dbx.link import Regs

#: How many start points before the stop are tried (the longest real-mode write is six bytes).
BACK: int = 6

_WRITES = frozenset(
    int(a) for a in (ix.OpAccess.WRITE, ix.OpAccess.COND_WRITE, ix.OpAccess.READ_WRITE, ix.OpAccess.READ_COND_WRITE)
)  # fmt: skip
_INFO = ix.InstructionInfoFactory()


@dataclass(frozen=True, slots=True)
class Candidate:
    """A decoded instruction that ends at the stop and writes the watched range."""

    start: int  # offset within the code segment
    length: int
    text: str
    linear: int  # the write address it resolves to


@dataclass(frozen=True, slots=True)
class Verdict:
    """`write` names one writer; `ambiguous` keeps every candidate; `spurious` has none."""

    kind: Literal["write", "ambiguous", "spurious"]
    writer: Candidate | None
    candidates: tuple[Candidate, ...]


def _values(regs: Regs) -> dict[int, int]:
    r = ix.Register
    pairs = (
        (r.ES, regs.es), (r.CS, regs.cs), (r.SS, regs.ss), (r.DS, regs.ds),
        (r.AX, regs.ax), (r.BX, regs.bx), (r.CX, regs.cx), (r.DX, regs.dx),
        (r.SI, regs.si), (r.DI, regs.di), (r.BP, regs.bp), (r.SP, regs.sp),
    )  # fmt: skip
    return {int(reg): value for reg, value in pairs} | {int(r.NONE): 0}


def _writes(insn: ix.Instruction, regs: Regs) -> list[tuple[int, int]]:
    """Each `(linear, size)` the instruction writes, worked back to its pre-instruction registers."""
    values = _values(regs)
    sp_before = (regs.sp - insn.stack_pointer_increment) & 0xFFFF
    out: list[tuple[int, int]] = []
    for mem in _INFO.info(insn).used_memory():
        if int(mem.access) not in _WRITES:
            continue
        base = sp_before if int(mem.base) == int(ix.Register.SP) else values.get(int(mem.base), 0)
        index = values.get(int(mem.index), 0)
        offset = (base + index * mem.scale + mem.displacement) & 0xFFFF
        size = (
            ix.MemorySizeExt.size(mem.memory_size) or ix.MemorySizeExt.size(insn.memory_size) or 2
        )
        seg = values.get(int(mem.segment), 0)
        if insn.is_string_instruction:
            # SI/DI already moved by one element in either direction.
            out.extend(((seg * 16 + ((offset + d) & 0xFFFF)), size) for d in (0, -size, size))
        else:
            out.append((seg * 16 + offset, size))
    return out


def _hit(writes: list[tuple[int, int]], watch: range) -> int | None:
    for linear, size in writes:
        if linear < watch.stop and watch.start < linear + size:
            return linear
    return None


def _decode(code: bytes, at: int, ip: int) -> ix.Instruction | None:
    insn = next(iter(ix.Decoder(16, code[at:], ip=ip)))
    return None if insn.is_invalid else insn


def resolve_writer(code: bytes, ip: int, regs: Regs, watch: range) -> Verdict:
    """Decide what wrote *watch*; *code* runs from `max(ip - 6, 0)` to `ip + 8`."""
    first = max(ip - BACK, 0)
    stop_at = ip - first
    found: list[Candidate] = []
    for at in range(stop_at + 1):
        insn = _decode(code, at, first + at)
        if insn is None:
            continue
        at_stop = at == stop_at
        if at_stop and not (insn.has_rep_prefix or insn.has_repne_prefix):
            continue
        if at_stop and not insn.is_string_instruction:
            continue
        if not at_stop and at + insn.len != stop_at:
            continue
        linear = _hit(_writes(insn, regs), watch)
        if linear is not None:
            found.append(Candidate(first + at, insn.len, str(insn), linear))
    if len(found) == 1:
        return Verdict("write", found[0], tuple(found))
    return Verdict("ambiguous" if found else "spurious", None, tuple(found))
