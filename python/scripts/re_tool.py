"""Disassemble `PLAYONE.EXE`, find the code using a value, and follow the VM dispatch to a handler.

Usage:

* ``mise run disasm -- <start> <end>``: the instructions from image offset ``start`` to ``end``.
* ``mise run xref -- <imm16> [--code-end 0xN]``: every instruction whose 16-bit immediate or
  displacement is ``imm16``. ``mise run xref -- <exe> --string TEXT | --offset 0xN --ds 0xSEG``
  is ``xref.py``'s file mode, passed through unchanged.
* ``mise run vm-handler -- <opcode>``: the display-list VM handler for ``opcode``, read from its
  dispatch slot at image ``0x8246 + opcode``. A handler that calls through a word table at
  ``[bx + disp16]`` (``OP_IPG``'s subtype table at ``work:0x1954``) has the table's entries listed.

Each reads ``--image`` (default ``corpus/stuntisl/PLAYONE.EXE`` in the data root, unpacked in
memory), which may be an MZ, LZEXE 0.91 or bare load-image file. Addresses are load-image
offsets, as in ``research/``. ``--vm-seg`` and ``--work-seg`` default to the unpatched build's
paragraphs (``research/playone-exe/static-tooling.md`` section 3).

Lives in ``python/scripts/`` beside ``build_pairing.py`` because it needs iced-x86 (ADR 0033).
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
lazy from collections.abc import Callable

import unlzexe
import xref
from iced_x86 import Decoder, FlowControl, Formatter, FormatterSyntax, Instruction, OpKind, Register

from stunt_reel.dataroot import read_data_file_or_report

#: The unpatched build's display-list VM code segment and its work segment, as paragraphs.
VM_SEG = 0x0824
WORK_SEG = 0x15D4
#: Image offset of ``DGROUP``, the first data segment: the default end of the code ``xref`` reads.
DGROUP = 0xD510
#: The dispatch table's offset in the VM segment, and its 108 nine-byte slots.
TABLE = 0x0006
SLOT = 9
SLOTS = 108
#: How many instructions of a handler are read looking for its subtype-table call.
HANDLER_SCAN = 16


@dataclass(frozen=True)
class Layout:
    """Where the VM's code and work segments sit in the image, as paragraphs."""

    vm_seg: int = VM_SEG
    work_seg: int = WORK_SEG

    @property
    def vm_base(self) -> int:
        """Image offset of VM-segment offset 0."""
        return self.vm_seg * 16

    @property
    def work_base(self) -> int:
        """Image offset of work-segment offset 0."""
        return self.work_seg * 16

    @property
    def table_end(self) -> int:
        """Image offset just past the last dispatch slot."""
        return self.vm_base + TABLE + SLOTS * SLOT


@dataclass(frozen=True)
class SubtypeTable:
    """A word table a handler calls through, and the handlers its entries name."""

    via: Instruction
    offset: int
    entries: list[tuple[int, int]]


@dataclass(frozen=True)
class Handler:
    """Where an opcode's dispatch slot jumps, and the subtype table it calls through, if any."""

    opcode: int
    slot: int
    target: int
    subtypes: SubtypeTable | None


def _decode(data: bytes, image_at: int, base: int) -> Decoder:
    """A decoder at image offset ``image_at`` whose IPs are offsets from image offset ``base``."""
    return Decoder(16, data[image_at:], ip=image_at - base)


def slot_target(data: bytes, layout: Layout, opcode: int) -> tuple[int, int]:
    """The image offsets of ``opcode``'s dispatch slot and of the near jump's target.

    The jump is decoded in VM-segment coordinates, so a target wraps within the segment as the
    CPU's does. Raises ``ValueError`` for an opcode with no slot or a slot holding no jump.
    """
    if opcode % SLOT or not 0 <= opcode < SLOTS * SLOT:
        raise ValueError(f"0x{opcode:04X} is not a dispatch slot: opcodes are 9 * 0..{SLOTS - 1}")
    slot = layout.vm_base + TABLE + opcode
    jump = _decode(data, slot, layout.vm_base).decode()
    if int(jump.flow_control) != int(FlowControl.UNCONDITIONAL_BRANCH) or int(jump.op0_kind) != int(
        OpKind.NEAR_BRANCH16
    ):
        raise ValueError(f"slot 0x{opcode:04X} at image 0x{slot:X} holds no near jump")
    return slot, layout.vm_base + jump.near_branch16


def _table_call(data: bytes, layout: Layout, handler: int) -> Instruction | None:
    """The handler's first call or jump through ``[bx|si|di + disp16]`` in ``DS``, if any.

    Reading stops at an unconditional branch or return, so only the handler's own entry run is
    searched. ``DS`` is the work segment while the VM runs.
    """
    decoder = _decode(data, handler, layout.vm_base)
    for _ in range(HANDLER_SCAN):
        instruction = decoder.decode()
        if instruction.is_invalid:
            return None
        flow = int(instruction.flow_control)
        if (
            flow in (int(FlowControl.INDIRECT_CALL), int(FlowControl.INDIRECT_BRANCH))
            and int(instruction.op0_kind) == int(OpKind.MEMORY)
            and int(instruction.memory_segment) == int(Register.DS)
            and int(instruction.memory_base)
            in (int(Register.BX), int(Register.SI), int(Register.DI))
            and int(instruction.memory_index) == int(Register.NONE)
            and instruction.memory_displ_size == 2
        ):
            return instruction
        if flow in (int(FlowControl.UNCONDITIONAL_BRANCH), int(FlowControl.RETURN)):
            return None
    return None


def subtype_entries(data: bytes, layout: Layout, offset: int) -> list[tuple[int, int]]:
    """``(index, handler)`` for each word of the work-segment table at ``offset``.

    The index is the byte offset the stream word names. The table ends at the first word that
    is not an address in the VM segment's code, past its dispatch slots and before the work
    segment.
    """
    entries: list[tuple[int, int]] = []
    at = layout.work_base + offset
    code_end = min(layout.work_base, layout.vm_base + 0x10000)
    while at + 2 <= len(data):
        target = layout.vm_base + struct.unpack_from("<H", data, at)[0]
        if not layout.table_end <= target < code_end:
            break
        entries.append((at - layout.work_base - offset, target))
        at += 2
    return entries


def resolve_handler(data: bytes, layout: Layout, opcode: int) -> Handler:
    """``opcode``'s slot, its handler and the handler's subtype table."""
    slot, target = slot_target(data, layout, opcode)
    call = _table_call(data, layout, target)
    subtypes = None
    if call is not None:
        offset = call.memory_displacement
        subtypes = SubtypeTable(call, offset, subtype_entries(data, layout, offset))
    return Handler(opcode, slot, target, subtypes)


def disassemble(data: bytes, start: int, end: int) -> list[Instruction]:
    """The instructions decoded straight on from image offset ``start`` that begin before ``end``."""
    found: list[Instruction] = []
    for instruction in Decoder(16, data[start:], ip=start):
        if instruction.ip >= end:
            break
        found.append(instruction)
    return found


def _formatter() -> Formatter:
    return Formatter(FormatterSyntax.NASM)


def _vm(layout: Layout, image: int) -> str:
    return f"image 0x{image:X} (VM 0x{image - layout.vm_base:04X})"


def handler_lines(handler: Handler, layout: Layout) -> list[str]:
    """The report ``vm-handler`` prints."""
    slot, target = _vm(layout, handler.slot), _vm(layout, handler.target)
    lines = [f"op 0x{handler.opcode:04X}: slot {slot} -> handler {target}"]
    table = handler.subtypes
    if table is not None:
        via = table.via
        lines.append(
            f"  {_vm(layout, layout.vm_base + via.ip)}  {_formatter().format(via)}: "
            f"subtype table work:0x{table.offset:04X} (image 0x{layout.work_base + table.offset:X}),"
            " indexed by the stream word"
        )
        lines.extend(
            f"    type 0x{index:04X} -> {_vm(layout, target)}" for index, target in table.entries
        )
    return lines


def _load(image: Path | None) -> bytes | None:
    path = unlzexe.default_exe() if image is None else image
    raw = read_data_file_or_report("re_tool", path)
    return None if raw is None else xref.load(raw).data


def _int(text: str) -> int:
    return int(text, 0)


def _parser(prog: str, about: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=about)
    parser.add_argument(
        "--image",
        type=Path,
        help="MZ, LZEXE 0.91 or load-image file (default: the data root's PLAYONE.EXE)",
    )
    return parser


def _layout_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--vm-seg", type=_int, default=VM_SEG, help="VM code segment paragraph")
    parser.add_argument("--work-seg", type=_int, default=WORK_SEG, help="work segment paragraph")


def disasm_main(argv: list[str]) -> int:
    parser = _parser("disasm", "Disassemble image offsets start..end")
    parser.add_argument("start", type=_int)
    parser.add_argument("end", type=_int)
    args = parser.parse_args(argv)
    if args.end <= args.start:
        parser.error("end must be past start")
    data = _load(args.image)
    if data is None:
        return 2
    formatter = _formatter()
    for instruction in disassemble(data, args.start, args.end):
        raw = data[instruction.ip : instruction.next_ip].hex()
        print(f"{instruction.ip:05X}  {raw:<14} {formatter.format(instruction)}")
    return 0


def _is_value(text: str) -> bool:
    try:
        _int(text)
    except ValueError:
        return False
    return True


def _line(formatter: Formatter, instruction: Instruction, mark: str) -> str:
    return f"  {mark} {instruction.ip:05X}  {formatter.format(instruction)}"


def xref_main(argv: list[str]) -> int:
    if not argv or not _is_value(argv[0]):
        return xref.main(argv)
    parser = _parser("xref", "Find the instructions whose 16-bit operand is a value")
    parser.add_argument("value", type=_int, help="16-bit immediate or displacement")
    parser.add_argument(
        "--code-end", type=_int, default=DGROUP, help="search image offsets below this"
    )
    parser.add_argument("--context", type=int, default=4, help="instructions shown each side")
    args = parser.parse_args(argv)
    if not 0 <= args.value <= 0xFFFF:
        parser.error("the value must fit in 16 bits")
    if args.context < 0:
        parser.error("--context must be zero or more")
    data = _load(args.image)
    if data is None:
        return 2
    refs = xref.find_references(data, args.value, args.code_end, args.context)
    print(f"0x{args.value:04X}: {len(refs)} reference(s) below image 0x{args.code_end:X}")
    formatter = _formatter()
    for ref in refs:
        lines = [_line(formatter, i, " ") for i in ref.before]
        lines.append(_line(formatter, ref.instruction, ">"))
        lines.extend(_line(formatter, i, " ") for i in ref.after)
        print("\n".join(lines) + "\n")
    return 0


def vm_handler_main(argv: list[str]) -> int:
    parser = _parser("vm-handler", "Follow an opcode's VM dispatch slot to its handler")
    parser.add_argument("opcode", type=_int)
    _layout_args(parser)
    args = parser.parse_args(argv)
    data = _load(args.image)
    if data is None:
        return 2
    layout = Layout(args.vm_seg, args.work_seg)
    try:
        handler = resolve_handler(data, layout, args.opcode)
    except ValueError as err:
        print(f"vm-handler: {err}", file=sys.stderr)
        return 1
    print("\n".join(handler_lines(handler, layout)))
    return 0


COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "disasm": disasm_main,
    "xref": xref_main,
    "vm-handler": vm_handler_main,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    sys.exit(main())
