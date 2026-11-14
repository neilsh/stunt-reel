"""The SOD dispatch-table parser on a synthetic load image, and its names from the opcode table.

The image is assembled here from bytes: a run of 9-byte slots at TABLE, each naming a distinct
handler offset at HANDLERS. Nothing is game-derived. The real executable is only read by
`mise run ghidra-sod-table`.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path
lazy from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
TABLE = 0x100
HANDLERS = 0x1000
PREFIX = bytes.fromhex("26c744fe")


def _load() -> ModuleType:
    """Import `python/scripts/ghidra_sod_dispatch.py`, tooling rather than a package."""
    target = SCRIPTS / "ghidra_sod_dispatch.py"
    spec = importlib.util.spec_from_file_location("ghidra_sod_dispatch", target)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ghidra = _load()
NAMES: tuple[str, ...] = ghidra.read_names()


def _image(count: int) -> tuple[bytes, list[int]]:
    """A synthetic image with *count* slots at TABLE naming handlers at HANDLERS."""
    handlers = [HANDLERS + index for index in range(count)]
    data = bytearray(HANDLERS + count + 16)
    for index, handler in enumerate(handlers):
        at = TABLE + index * 9
        data[at : at + 4] = PREFIX
        struct.pack_into("<H", data, at + 4, handler - TABLE)
        data[at + 6] = 0xE9
        struct.pack_into("<h", data, at + 7, handler - (at + 9))
    return bytes(data), handlers


def test_the_run_is_found_and_every_handler_read() -> None:
    data, handlers = _image(108)
    table = ghidra.parse_slot_table(data, NAMES)
    assert table.image == TABLE
    assert [slot.handler for slot in table.slots] == handlers
    assert [slot.opcode for slot in table.slots] == [9 * index for index in range(108)]
    assert table.slots[0].imm16 == handlers[0] - TABLE


def test_a_108_slot_build_names_the_handler_each_slot_pairs_with() -> None:
    data, _ = _image(108)
    names = [slot.name for slot in ghidra.parse_slot_table(data, NAMES).slots]
    assert names[91] == "OP_TEXTURE"
    assert names[92] == "OP_033C_UNPATCHED_ONLY"
    assert names[93] == "OP_VECELLIPSE"
    assert names[107] == "OP_CIRCLESL"


def test_a_107_slot_build_names_the_slot_itself() -> None:
    data, _ = _image(107)
    names = [slot.name for slot in ghidra.parse_slot_table(data, NAMES).slots]
    assert names[92] == "OP_VECELLIPSE"
    assert names[106] == "OP_CIRCLESL"


def test_an_unknown_slot_count_names_by_index_and_leaves_the_overflow_unnamed() -> None:
    assert ghidra.handler_name(0, 109, NAMES) == "OP_CLRV"
    assert ghidra.handler_name(107, 109, NAMES) is None


def test_the_opcode_table_has_107_rows_at_9_pitch() -> None:
    assert len(NAMES) == 107
    assert NAMES[0] == "OP_CLRV"
    assert NAMES[11] == "OP_IPG"
    assert NAMES[106] == "OP_CIRCLESL"


def test_a_self_patch_word_that_disagrees_with_the_jump_is_rejected() -> None:
    data, _ = _image(108)
    broken = bytearray(data)
    at = TABLE + 9 * 5
    struct.pack_into("<H", broken, at + 4, 0x1234)
    with pytest.raises(ValueError, match="self-patch word"):
        ghidra.parse_slot_table(bytes(broken), NAMES)


def test_a_run_shorter_than_the_minimum_is_not_the_table() -> None:
    data, _ = _image(99)
    with pytest.raises(ValueError, match="no run of 100"):
        ghidra.parse_slot_table(data, NAMES)


def test_the_run_stops_at_a_slot_without_its_jump() -> None:
    data, _ = _image(108)
    extended = bytearray(data)
    at = TABLE + 9 * 108
    extended[at : at + 4] = PREFIX
    struct.pack_into("<H", extended, at + 4, 0x777)
    table = ghidra.parse_slot_table(bytes(extended), NAMES)
    assert len(table.slots) == 108


def test_the_slot_file_has_the_header_and_one_line_per_handler() -> None:
    data, handlers = _image(107)
    table = ghidra.parse_slot_table(data, NAMES)
    lines = ghidra.slot_lines(table, "patch3")
    assert lines[0] == f"# ghidra-sod-dispatch build=patch3 table=0x{TABLE:X} slots=107"
    assert lines[1] == "# index\topcode\thandler\tname"
    assert lines[2] == f"0\t0x0000\t0x{handlers[0]:04X}\tOP_CLRV"
    assert len(lines) == 2 + 107


def test_an_opcode_table_whose_rows_are_not_9_apart_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "opcodes.md"
    path.write_text("| **0** | `0x0001` | 1 | `OP_ONE` | x |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not 9 x index"):
        ghidra.read_names(path)


def test_an_opcode_table_with_an_index_gap_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "opcodes.md"
    path.write_text("| **1** | `0x0009` | 9 | `OP_GETV` | x |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Index column"):
        ghidra.read_names(path)
