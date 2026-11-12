"""Unpacking a synthetic LZEXE 0.91 executable, plain and behind an entry stub."""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path
from typing import Any

import pytest

from stunt_reel import dataroot

SCRIPT = Path(__file__).resolve().parents[1] / "python" / "scripts" / "unlzexe.py"
IMAGE = b"HELLO"
RELOCS = [5, 0x10003]
ENTRY = {"ip": 0x0010, "cs": 0x0000, "sp": 0x0200, "ss": 0x0001}


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("unlzexe_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stream(literals: bytes) -> bytes:
    """Encode literals then the end marker, refilling the bit word as the decoder reads it."""
    out = bytearray(2)
    word_at, nbits, word = 0, 0, 0

    def bit(value: int) -> None:
        nonlocal word_at, nbits, word
        word |= value << nbits
        nbits += 1
        struct.pack_into("<H", out, word_at, word)
        if nbits == 16:
            word_at, nbits, word = len(out), 0, 0
            out.extend(b"\0\0")

    for byte in literals:
        bit(1)
        out.append(byte)
    bit(0)
    bit(1)
    out.extend(b"\0\0\0")  # long match with length field 0: end of stream
    return bytes(out)


def _relocation_table(relocs: list[int]) -> bytes:
    """Encode linear offsets as 0.91 spans; each must lie within 0xFFFF of the last."""
    out = bytearray()
    last = 0
    for lin in relocs:
        span = lin - last
        if span < 0x100:
            out.append(span)
        else:
            out += b"\0" + struct.pack("<H", span)
        last = lin
    out += b"\0" + struct.pack("<H", 1)
    return bytes(out)


def _packed(stub: bytes = b"", push_ax: bool = False) -> bytes:
    """Header, stream, loader paragraph-aligned after it, then an optional stub."""
    stream = _stream(IMAGE)
    stream += b"\0" * (-len(stream) % 16)
    loader = bytearray(0x158)
    struct.pack_into("<4H", loader, 0, ENTRY["ip"], ENTRY["cs"], ENTRY["sp"], ENTRY["ss"])
    code = bytes.fromhex("060e1f8b0e0c008bf14e89f78cdb031e0a008ec3fdf3a4")
    if push_ax:
        code = b"P" + code
    loader[0x0E : 0x0E + len(code)] = code
    loader += _relocation_table(RELOCS)
    body = stream + bytes(loader)
    loader_cs, ip = len(stream) // 16, 0x0E
    if stub:
        body += b"\0" * (-len(body) % 16)
        loader_cs, ip = len(body) // 16, 0
        body += stub
    header = bytearray(0x20)
    struct.pack_into("<2s", header, 0, b"MZ")
    struct.pack_into("<H", header, 8, 2)  # header paragraphs
    struct.pack_into("<2H", header, 0x14, ip, loader_cs)
    header[0x1C:0x20] = b"LZ91"
    return bytes(header) + body


def test_unpacks_image_entry_and_relocations() -> None:
    image, meta = _load().unpack(_packed())
    assert bytes(image) == IMAGE
    assert meta["entry"] == ENTRY
    assert meta["relocs"] == RELOCS
    assert "stub" not in meta


def test_unpacks_the_push_ax_loader_build() -> None:
    """Patch #3 `PLAYONE.EXE` and `MAKEONE.EXE`: the same loader with a `push ax` ahead of its code."""
    image, meta = _load().unpack(_packed(push_ax=True))
    assert bytes(image) == IMAGE
    assert meta["entry"] == ENTRY
    assert meta["relocs"] == RELOCS


def test_unpacks_the_program_under_an_entry_stub() -> None:
    """corpus/stuntisl/STUNT.EXE: a resident stub took the entry; the loader is unchanged."""
    stub = bytes.fromhex("e99f01") + b"\x90" * 0x40
    image, meta = _load().unpack(_packed(stub))
    assert bytes(image) == IMAGE
    assert meta["entry"] == ENTRY
    assert meta["relocs"] == RELOCS
    assert meta["stub"]["ip"] == 0


def test_refuses_a_file_without_the_loader() -> None:
    packed = bytearray(_packed())
    packed[packed.find(b"\x06\x0e\x1f") : packed.find(b"\x06\x0e\x1f") + 3] = b"\0\0\0"
    with pytest.raises(ValueError, match=r"no LZEXE 0\.91 loader"):
        _load().unpack(bytes(packed))


def test_with_no_paths_unpacks_the_data_roots_playone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "corpus" / "stuntisl" / "PLAYONE.EXE"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(_packed())
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    dataroot.data_root.cache_clear()
    assert _load().main(["unlzexe"]) == 0
    assert (tmp_path / "build" / "re" / "playone.img").read_bytes() == IMAGE
