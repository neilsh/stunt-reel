"""The `.SET` schema decodes the synthetic scene byte for byte."""

from __future__ import annotations

import importlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.kaitai import compile_schemas, ksc_command, load_generated_module

pytestmark = pytest.mark.docs

SCHEMA = Path(__file__).resolve().parent.parent / "research/formats/auxiliary/set.ksy"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic_minimal.set"
VERIFIER = SCHEMA.parents[3] / "python/scripts/verify_schemas_corpus.py"
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


def _verifier() -> Any:
    """Import the corpus sweep by path; it registers before running for its dataclasses."""
    spec = importlib.util.spec_from_file_location("verify_schemas_corpus", VERIFIER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prop(slot: int, flags: bytes, spill: bytes) -> bytes:
    """A 64-byte prop record: slot word, flags word at +2, trailing word at +0x3E."""
    return slot.to_bytes(2, "little") + flags + bytes(58) + spill


def _probe(set_parser: Any, props: list[bytes]) -> list[str]:
    head = FIXTURE.read_bytes()[:-64]
    data = head + b"".join(props)
    root = set_parser(_KAITAISTRUCT.KaitaiStream(io.BytesIO(data)))
    problems: list[str] = _verifier()._probe_set(root, len(data))
    return problems


def test_sweep_accepts_sparse_slots_whose_trailing_word_is_the_next_flags(set_parser: Any) -> None:
    # Slots 0, 1 and 10: slot 1's successor slot 2 is absent, so its trailing word is free.
    props = [_prop(0, b"\x09\x1f", b"\x03\x1b"), _prop(1, b"\x03\x1b", b"\x01\x00")]
    props.append(_prop(10, b"\x09\x13", b"\x00\x00"))
    assert _probe(set_parser, props) == []


def test_sweep_flags_slot_order_range_and_spill(set_parser: Any) -> None:
    props = [_prop(1, b"\x03\x1b", b"\x09\x13"), _prop(1, b"\x09\x13", b"\x00\x00")]
    assert _probe(set_parser, props) == ["prop slot words do not strictly increase"]
    props = [_prop(39, b"\x09\x13", b"\x00\x00"), _prop(40, b"\x09\x13", b"\x00\x00")]
    assert _probe(set_parser, props) == [
        "prop slot word outside 0..39",
        "trailing word differs from the next slot's flags at slot 39",
    ]


def test_truncated_byte_is_rejected(set_parser: Any) -> None:
    data = FIXTURE.read_bytes()
    with pytest.raises(EOFError):
        set_parser(_KAITAISTRUCT.KaitaiStream(io.BytesIO(data[:-1])))
