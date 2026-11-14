"""The `.SPR` schema reads synthetic raw and span-coded images from byte 6."""

from __future__ import annotations

import importlib
import importlib.util
import io
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.kaitai import compile_schemas, ksc_command, load_generated_module

pytestmark = pytest.mark.docs

SCHEMA = Path(__file__).resolve().parent.parent / "research/formats/auxiliary/spr.ksy"
VERIFIER = SCHEMA.parents[3] / "python/scripts/verify_schemas_corpus.py"
_KAITAISTRUCT: Any = importlib.import_module("kaitaistruct")


def _verifier() -> Any:
    """Import the corpus sweep by path; it registers before running for its dataclasses."""
    spec = importlib.util.spec_from_file_location("verify_schemas_corpus", VERIFIER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def spr_parser() -> Any:
    """Compile the schema once and return the generated root type."""
    if ksc_command() is None:
        pytest.skip("Kaitai compiler not on PATH")
    with tempfile.TemporaryDirectory(prefix="stunt-kaitai-spr-") as tmp:
        compile_schemas([SCHEMA], tmp)
        module = load_generated_module(Path(tmp) / "spr.py", "stunt_kaitai_spr")
    return module.Spr


def _parse(parser: Any, data: bytes) -> Any:
    root = parser(_KAITAISTRUCT.KaitaiStream(io.BytesIO(data)))
    assert root._io.pos() == len(data)
    return root


def test_raw_pixels_start_at_byte_six_with_no_trailer(spr_parser: Any) -> None:
    # Opaque to the last pixel: a byte-4 reading would drop 7 and 8 into a non-zero "trailer".
    pixels = bytes([1, 2, 3, 4, 5, 6, 7, 8])
    root = _parse(spr_parser, struct.pack("<3H", 4, 2, 0) + pixels)

    assert (root.width, root.height, root.encoding) == (4, 2, 0)
    assert bytes(root.body.pixels) == pixels


def test_non_zero_encoding_reads_span_rows(spr_parser: Any) -> None:
    row0 = bytes([2]) + struct.pack("<H", 1) + bytes([9, 9]) + bytes([0])
    row1 = bytes([1]) + struct.pack("<H", 0) + bytes([7]) + bytes([1]) + struct.pack("<H", 3)
    row1 += bytes([5, 0])
    root = _parse(spr_parser, struct.pack("<3H", 4, 2, 2) + row0 + row1)

    assert root.encoding == 2
    spans = [[(s.count, s.x, bytes(s.pixels)) for s in row.spans[:-1]] for row in root.body.rows]
    assert spans == [[(2, 1, b"\x09\x09")], [(1, 0, b"\x07"), (1, 3, b"\x05")]]


def test_sweep_sets_pcx2spr_output_aside() -> None:
    verifier = _verifier()
    pcx2spr = struct.pack("<2H", 2, 1) + bytes([5, 6]) + bytes(2)
    with pytest.raises(verifier.OtherLayout):
        list(verifier._spr_cases(pcx2spr))
    raw = struct.pack("<3H", 2, 1, 0) + bytes([5, 6])
    assert [case.data for case in verifier._spr_cases(raw)] == [raw]


def test_sweep_keeps_a_span_coded_image_of_pcx2spr_size() -> None:
    # 4 by 2, encoding 2: three pixels at column 0, then an empty row; 8 + 6 bytes ending 00 00.
    data = struct.pack("<3H", 4, 2, 2) + bytes([3, 0, 0, 9, 9, 9, 0]) + bytes([0])
    assert len(data) == 4 * 2 + 6
    verifier = _verifier()
    assert [case.data for case in verifier._spr_cases(data)] == [data]
