"""Finding the code that references a string, on a synthetic MZ executable."""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "python" / "scripts" / "xref.py"

# mov ax,1 (relocated); mov ds,ax; mov dx,12h; mov ah,3Dh; int 21h; ret.
CODE = bytes.fromhex("b801008ed8ba1200b43dcd21c3")
# DGROUP is paragraph 1, so its offset 0x12 is image offset 0x22.
IMAGE = CODE.ljust(0x22, b"\0") + b"map.bin\0"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("xref_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mz(image: bytes) -> bytes:
    """A 2-paragraph header whose one relocation is the `mov ax` immediate."""
    total = 0x20 + len(image)
    header = bytearray(0x20)
    struct.pack_into("<2s4H", header, 0, b"MZ", total % 512, -(-total // 512), 1, 2)
    struct.pack_into("<H", header, 0x18, 0x1C)
    struct.pack_into("<2H", header, 0x1C, 1, 0)
    return bytes(header) + image


def test_load_reads_the_image_and_its_relocated_segments() -> None:
    image = _load().load(_mz(IMAGE))
    assert image.data == IMAGE
    assert image.header == 0x20
    assert dict(image.relocated) == {1: 1}


def test_a_string_resolves_to_its_segment_and_the_instruction_using_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exe = tmp_path / "SD.EXE"
    exe.write_bytes(_mz(IMAGE))
    assert _load().main([str(exe), "--string", "MAP.BIN", "--context", "1"]) == 0
    out = capsys.readouterr().out
    assert "'MAP.BIN' at image 0x22, file 0x42" in out
    assert "DS 0x0001 (mov ds x1, relocated x1): offset 0x0012, 1 reference(s)" in out
    assert "> 00005  mov dx,12h" in out
    assert "  00003  mov ds,ax" in out
    assert "  00008  mov ah,3Dh" in out


def test_an_offset_in_a_bare_image_needs_only_ds() -> None:
    xref = _load()
    refs = xref.find_references(IMAGE, 0x12, 0x10, context=0)
    assert [ref.start for ref in refs] == [5]
    lines = xref.report(xref.Image(IMAGE), [("DS:0x0012", None, 0x12)], 1, 0, None)
    assert lines[0] == "DS 0x0001 (--ds): offset 0x0012, 1 reference(s)"


def test_the_instruction_start_is_the_one_straight_line_decode_reaches() -> None:
    """`2e a1 12 00` is `mov ax,cs:[12h]`; `a1 12 00` alone also decodes, but nothing reaches it."""
    code = bytes.fromhex("9090902ea11200c3")
    (ref,) = _load().find_references(code, 0x12, len(code), context=0)
    assert ref.start == 3


@pytest.mark.parametrize(
    ("args", "message"),
    [(["--context", "-1", "--string", "x"], "--context"), (["--string", "☃"], "Latin-1")],
)
def test_bad_arguments_are_usage_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    exe = tmp_path / "SD.EXE"
    exe.write_bytes(_mz(IMAGE))
    with pytest.raises(SystemExit) as exit_info:
        _load().main([str(exe), *args])
    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


def test_a_latin_1_string_folds_case_as_the_image_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`bytes.lower()` folds only ASCII, so byte `0xC9` must be searched as `0xC9`, not `0xE9`."""
    exe = tmp_path / "SD.EXE"
    exe.write_bytes(_mz(CODE.ljust(0x22, b"\0") + b"CAF\xc9\0"))
    assert _load().main([str(exe), "--string", "cafÉ"]) == 0
    assert "at image 0x22" in capsys.readouterr().out
