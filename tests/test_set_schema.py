"""The `.SET` schema decodes the synthetic scene byte for byte."""

from __future__ import annotations

import importlib
import io
import tempfile
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.kaitai import compile_schemas, ksc_command, load_generated_module

SCHEMA = Path(__file__).resolve().parent.parent / "research/formats/auxiliary/set.ksy"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic_minimal.set"
_KAITAISTRUCT: Any = importlib.import_module("kaitaistruct")


@pytest.fixture(scope="module")
def set_parser() -> Any:
    """Compile the schema once and return the generated root type."""
    if ksc_command() is None:
        pytest.skip("Kaitai compiler not on PATH")
    with tempfile.TemporaryDirectory(prefix="stunt-kaitai-set-") as tmp:
        compile_schemas([SCHEMA], tmp)
        module = load_generated_module(Path(tmp) / "set.py", "stunt_kaitai_set")
    return module.Set


def test_header_and_body_parse(set_parser: Any) -> None:
    data = FIXTURE.read_bytes()
    assert len(data) == 282
    root = set_parser(_KAITAISTRUCT.KaitaiStream(io.BytesIO(data)))

    assert root._io.pos() == len(data)
    assert root.stunt_name.rstrip("\x00 ") == "SYNTHETIC SET"
    assert bytes(root.magic) == b"\x08"
    assert root.recording_mode == 2
    assert root.first_take_bonus == 100
    assert root.crash_penalty == 200
    assert root.vehicle_flags == 5
    assert root.time_of_day == 0x1234
    assert root.weapon_type == 1
    assert root.max_takes == 99
    assert root.take_penalty == 250
    assert root.initial_view_mode == 2

    assert root.num_events == 2
    assert len(root.events) == 2
    first, second = root.events
    assert first.if_type == 1
    assert first.if_object_2 == 0xFE
    assert first.and_1_type == 5
    assert first.and_1_operand == 3
    assert len(first.then_slots) == 8
    assert first.then_slots[0].action_type == 7
    assert first.then_slots[0].operand == 256
    assert first.then_slots[1].operand == 500
    assert (first.then_slots[2].sound_volume, first.then_slots[2].sound_routing) == (3, 1)
    assert second.if_type == 3
    assert second.if_operand == 500
    assert second.then_slots[0].action_type == 12

    assert len(root.props) == 1
    assert root.prop_count == 1
    assert root.props[0][:2] == b"\x00\x00"
    assert root.props[0][0x34] == 0x40


def test_truncated_byte_is_rejected(set_parser: Any) -> None:
    data = FIXTURE.read_bytes()
    with pytest.raises(EOFError):
        set_parser(_KAITAISTRUCT.KaitaiStream(io.BytesIO(data[:-1])))
