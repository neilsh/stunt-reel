"""Disassembly, value cross-references and VM dispatch on a synthetic load image."""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "python" / "scripts" / "re_tool.py"

# The VM segment is paragraph 1 (image 0x10), so its dispatch table is image 0x16 and ends at
# 0x16 + 108 * 9 = 0x3E2. The work segment is paragraph 0x50 (image 0x500).
VM_SEG, WORK_SEG = 0x01, 0x50
HANDLER = 0x400  # VM offset, image 0x410
# es lodsw; mov bx,ax; call word [bx+1954h]; es lodsw; jmp ax
HANDLER_CODE = bytes.fromhex("26ad8bd8ff97541926adffe0")
SUBTYPES = [0x0420, 0x0430, 0x0004]  # the third is no code address, so the table ends there


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("re_tool_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jump(image: bytearray, slot: int, target_vm: int) -> None:
    """A near jump at image ``slot`` to VM offset ``target_vm``."""
    rel = (target_vm - (slot - VM_SEG * 16 + 3)) & 0xFFFF
    image[slot : slot + 3] = b"\xe9" + struct.pack("<H", rel)


def _image() -> bytes:
    image = bytearray(0x500 + 0x1954 + 2 * len(SUBTYPES))
    _jump(image, 0x16 + 0x63, HANDLER)
    image[0x10 + HANDLER : 0x10 + HANDLER + len(HANDLER_CODE)] = HANDLER_CODE
    struct.pack_into(f"<{len(SUBTYPES)}H", image, 0x500 + 0x1954, *SUBTYPES)
    # mov ax,[si+16h]; mov [es:8124h],ax at image 0x20
    image[0x20:0x27] = bytes.fromhex("8b441626a32481")
    return bytes(image)


def test_a_slot_jump_resolves_to_its_handler_in_image_offsets() -> None:
    tool = _load()
    layout = tool.Layout(VM_SEG, WORK_SEG)
    assert tool.slot_target(_image(), layout, 0x63) == (0x79, 0x410)


def test_a_slot_jump_wraps_within_the_vm_segment() -> None:
    tool = _load()
    image = bytearray(_image())
    image[0x16:0x19] = b"\xe9" + struct.pack("<h", -0x10)  # VM 0x0009 - 0x10 = 0xFFF9
    assert tool.slot_target(bytes(image), tool.Layout(VM_SEG, WORK_SEG), 0) == (0x16, 0x10009)


@pytest.mark.parametrize(
    ("opcode", "message"),
    [(0x004B, "not a dispatch slot"), (108 * 9, "not a dispatch slot"), (0x0009, "no near jump")],
)
def test_an_opcode_without_a_jump_slot_is_refused(opcode: int, message: str) -> None:
    tool = _load()
    with pytest.raises(ValueError, match=message):
        tool.slot_target(_image(), tool.Layout(VM_SEG, WORK_SEG), opcode)


def test_a_handler_calling_through_a_work_table_lists_its_subtypes() -> None:
    tool = _load()
    layout = tool.Layout(VM_SEG, WORK_SEG)
    handler = tool.resolve_handler(_image(), layout, 0x63)
    assert handler.target == 0x410
    assert handler.subtypes is not None
    assert handler.subtypes.offset == 0x1954
    assert handler.subtypes.entries == [(0, 0x430), (2, 0x440)]
    lines = tool.handler_lines(handler, layout)
    assert lines[0] == "op 0x0063: slot image 0x79 (VM 0x0069) -> handler image 0x410 (VM 0x0400)"
    assert "subtype table work:0x1954 (image 0x1E54)" in lines[1]
    assert lines[2:] == [
        "    type 0x0000 -> image 0x430 (VM 0x0420)",
        "    type 0x0002 -> image 0x440 (VM 0x0430)",
    ]


def test_a_handler_that_returns_first_has_no_subtype_table() -> None:
    tool = _load()
    image = bytearray(_image())
    image[0x10 + HANDLER] = 0xC3  # ret ahead of the table call
    handler = tool.resolve_handler(bytes(image), tool.Layout(VM_SEG, WORK_SEG), 0x63)
    assert handler.subtypes is None


def test_vm_handler_reads_the_image_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    img = tmp_path / "playone.img"
    img.write_bytes(_image())
    argv = ["vm-handler", "0x63", "--image", str(img), "--vm-seg", "1", "--work-seg", "0x50"]
    assert _load().main(argv) == 0
    assert "handler image 0x410" in capsys.readouterr().out


def test_disasm_decodes_whole_instructions_that_start_in_range(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    img = tmp_path / "playone.img"
    img.write_bytes(_image())
    assert _load().main(["disasm", "0x20", "0x24", "--image", str(img)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "00020  8b4416         mov ax,[si+16h]",
        "00023  26a32481       mov [es:8124h],ax",
    ]


def test_xref_finds_a_value_used_as_a_displacement(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    img = tmp_path / "playone.img"
    img.write_bytes(_image())
    assert _load().main(["xref", "0x8124", "--image", str(img), "--context", "1"]) == 0
    out = capsys.readouterr().out
    assert "0x8124: 1 reference(s) below image 0xD510" in out
    assert "  > 00023  mov [es:8124h],ax" in out
    assert "    00020  mov ax,[si+16h]" in out


def test_xref_passes_a_file_and_its_options_to_the_string_search(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    img = tmp_path / "playone.img"
    img.write_bytes(_image())
    argv = ["xref", str(img), "--offset", "0x8124", "--ds", "0x100", "--context", "0"]
    assert _load().main(argv) == 0
    assert "DS 0x0100 (--ds): offset 0x8124, 1 reference(s)" in capsys.readouterr().out
