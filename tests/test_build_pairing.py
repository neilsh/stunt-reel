"""Function pairing between two builds, on two hand-assembled synthetic load images.

The left image is a tiny real-mode program: an entry routine that loads `DS`, calls two
functions and far-calls a display-list segment of three dispatch slots. The right image is
the same program relinked: one function added, its data moved, and the middle dispatch slot
dropped. Nothing here is game-derived.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
lazy from types import ModuleType

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"


def _load() -> ModuleType:
    """Import `python/scripts/build_pairing.py`, which is tooling, not part of `stunt_reel`."""
    spec = importlib.util.spec_from_file_location("build_pairing", SCRIPTS / "build_pairing.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bp = _load()
ALIGNED = bp.ALIGNED
BRACKETED = bp.BRACKETED
IMMEDIATE = bp.IMMEDIATE
MEM = bp.MEM
REFERENCED = bp.REFERENCED
UNMAPPED = bp.UNMAPPED
LoadImage = bp.LoadImage
Pairing = bp.Pairing
Ref = bp.Ref
dispatch_slots = bp.dispatch_slots
map_code = bp.map_code
map_data = bp.map_data
pair_images = bp.pair_images
pair_slots = bp.pair_slots
periodic = bp.periodic

VM_PARAGRAPH = 0x0008
STACK_PARAGRAPH = 0x0050


@dataclass
class Asm:
    """A minimal assembler: raw bytes, labels and near-call fixups."""

    base: int
    code: bytearray = field(default_factory=bytearray)
    labels: dict[str, int] = field(default_factory=dict)
    fixups: list[tuple[int, str]] = field(default_factory=list)
    relocs: list[int] = field(default_factory=list)

    @property
    def here(self) -> int:
        return self.base + len(self.code)

    def emit(self, raw: str) -> None:
        self.code += bytes.fromhex(raw)

    def label(self, name: str) -> None:
        self.labels[name] = self.here

    def call(self, name: str) -> None:
        self.code += b"\xe8\x00\x00"
        self.fixups.append((len(self.code) - 2, name))

    def reloc_word(self, value: int) -> None:
        self.relocs.append(self.here)
        self.code += struct.pack("<H", value)

    def link(self) -> bytes:
        for at, name in self.fixups:
            struct.pack_into("<h", self.code, at, self.labels[name] - (self.base + at + 2))
        return bytes(self.code)


def program(*, dgroup: int, shift: int, extra: bool, slots: tuple[str, ...]) -> Any:
    """Assemble one build; *shift* moves the data at 0x0100 and 0x0200, not 0x0300."""
    main = Asm(0)
    main.emit("b8")
    main.reloc_word(dgroup)  # mov ax, DGROUP
    main.emit("8ed8")  # mov ds, ax
    if extra:
        main.call("f0")
    main.call("f1")
    main.call("f2")
    main.emit("9a0000")
    main.reloc_word(VM_PARAGRAPH)  # call far VM:0000
    main.emit("cd20")  # int 0x20
    if extra:
        main.label("f0")
        main.emit("33c0c3")  # xor ax, ax; ret
    main.label("f1")
    main.emit("a1" + struct.pack("<H", 0x0100 + shift).hex())  # mov ax, [0x0100]
    main.emit("a3" + struct.pack("<H", 0x0102 + shift).hex())  # mov [0x0102], ax
    main.emit("c3")
    main.label("f2")
    main.emit("be" + struct.pack("<H", 0x0200 + shift).hex())  # mov si, 0x0200
    main.emit("8b1e0003")  # mov bx, [0x0300]
    main.emit("c3")

    handlers = {"ax": "40c3", "bx": "43c3", "cx": "41c3"}  # inc reg; ret
    table = 9 * len(slots)
    starts: dict[str, int] = {}
    at = table
    for reg in slots:
        starts[reg] = at
        at += len(handlers[reg]) // 2
    vm = bytearray()
    for k, reg in enumerate(slots):
        vm += bytes.fromhex("26c744fe") + struct.pack("<H", starts[reg])
        vm += b"\xe9" + struct.pack("<h", starts[reg] - (9 * k + 9))
    for reg in slots:
        vm += bytes.fromhex(handlers[reg])

    data = bytearray(STACK_PARAGRAPH * 16)
    code = main.link()
    data[: len(code)] = code
    vm_base = VM_PARAGRAPH * 16
    data[vm_base : vm_base + len(vm)] = vm
    data[dgroup * 16 + 0x0100 + shift : dgroup * 16 + 0x0104 + shift] = b"WXYZ"
    return LoadImage(bytes(data), frozenset(main.relocs), 0, 0, STACK_PARAGRAPH)


def _pairing() -> Any:
    left = program(dgroup=0x0010, shift=0, extra=False, slots=("ax", "bx", "cx"))
    right = program(dgroup=0x0012, shift=0x10, extra=True, slots=("ax", "cx"))
    return pair_images(left, right)


def test_segments_and_dgroup_come_from_the_relocations() -> None:
    pairing = _pairing()
    assert pairing.left.dgroup() == 0x0010
    assert pairing.right.dgroup() == 0x0012
    assert pairing.segments == {0x0000: 0x0000, VM_PARAGRAPH: VM_PARAGRAPH}


def test_functions_pair_around_an_added_one() -> None:
    pairing = _pairing()
    main = next(s for s in pairing.stats if s.left == 0)
    assert main.left_functions == 3
    assert main.right_functions == 4
    assert main.paired == 3
    assert len(main.unpaired_right) == 1


def test_a_memory_operand_maps_its_offset() -> None:
    found = map_data(_pairing(), 0x0100)
    assert (found.mapped, found.how, found.agreeing, found.references) == (
        0x0110,
        REFERENCED,
        1,
        1,
    )
    assert map_data(_pairing(), 0x0300).mapped == 0x0300


def test_an_immediate_maps_a_pointer() -> None:
    found = map_data(_pairing(), 0x0200)
    assert (found.mapped, found.how) == (0x0210, IMMEDIATE)


def test_an_unreferenced_offset_takes_a_shared_neighbour_shift_or_none() -> None:
    pairing = _pairing()
    inside = map_data(pairing, 0x0101)
    assert (inside.mapped, inside.how) == (0x0111, BRACKETED)
    between = map_data(pairing, 0x0250)
    assert (between.mapped, between.how, between.below, between.above) == (
        None,
        UNMAPPED,
        0x0102,
        0x0300,
    )


def test_code_addresses_follow_the_aligned_instructions() -> None:
    pairing = _pairing()
    left_f1 = next(
        f.start for f, _, _ in pairing.functions if f.insns[0].refs == (Ref(MEM, "", 0x0100),)
    )
    found = map_code(pairing, left_f1)
    assert found.how == ALIGNED
    assert pairing.right.data[found.mapped or 0] == 0xA1
    assert map_code(pairing, left_f1 + 1).mapped == (found.mapped or 0) + 1


def test_dispatch_slots_pair_through_their_handlers() -> None:
    pairing = _pairing()
    assert len(dispatch_slots(pairing.left, VM_PARAGRAPH)) == 3
    assert len(dispatch_slots(pairing.right, VM_PARAGRAPH)) == 2
    assert pair_slots(pairing, VM_PARAGRAPH) == [(0, 0), (1, None), (2, 1)]


def test_periodic_marks_only_long_repeats() -> None:
    a, b, c = ("push", "ax"), ("jmp", "T"), ("ret",)
    assert periodic((a, b) * 4 + (c,)) == set(range(8))
    assert periodic((a, b) * 3 + (c,)) == set()
    assert periodic((c,) * 4) == {0, 1, 2, 3}
