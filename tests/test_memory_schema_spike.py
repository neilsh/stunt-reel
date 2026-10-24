"""Spike: the actor-record `.ksy` decodes the same bytes as the streamer's struct reader."""

from __future__ import annotations

import importlib
import io
import struct
import tempfile
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.kaitai import compile_schemas, ksc_command, load_generated_module
from stunt_reel.tac.client import TacClient
from stunt_reel.tac.streamer import TrajectoryStreamer
from stunt_reel.tac.transport import MockTransport

SCHEMA = Path(__file__).resolve().parent.parent / "research/formats/memory/actor_record.ksy"


def _actor_bytes(next_off: int, next_seg: int) -> bytes:
    head = struct.pack(
        "<I8s3i4fHH",
        7,
        b"FOKKER\x00\x00",
        round(5.0 * 65536),
        round(-15.5 * 65536),
        round(25.25 * 65536),
        0.0,
        0.0,
        0.0,
        1.0,
        0x0003,
        2,
    )
    joints = struct.pack("<HHHHHHHH", 1, 0x4000, 2, 0xC000, 0, 0, 0, 0)
    return head + joints + struct.pack("<HH", next_off, next_seg)


@pytest.mark.skipif(ksc_command() is None, reason="Kaitai compiler not on PATH")
@pytest.mark.parametrize("link", [(0, 0), (0x0CE0, 0x0D51)])
def test_actor_ksy_matches_struct_reader(link: tuple[int, int]) -> None:
    raw = _actor_bytes(*link)
    assert len(raw) == 64

    with tempfile.TemporaryDirectory(prefix="stunt-kaitai-") as tmp:
        compile_schemas([SCHEMA], tmp)
        module = load_generated_module(Path(tmp) / "actor_record.py", "stunt_kaitai_actor")
        ks: Any = importlib.import_module("kaitaistruct")
        rec = module.ActorRecord(ks.KaitaiStream(io.BytesIO(raw)))

    mock = MockTransport()
    mock.write_bytes(0x0D51, 0x0CA0, raw)
    actor, next_addr = TrajectoryStreamer(TacClient(mock)).decode_actor_from_memory("0D51:0CA0")

    assert rec.actor_id == actor.actor_id
    assert rec.model_name_raw.split(b"\x00", 1)[0].decode("ascii") == actor.model_name
    assert rec.pos_meters == pytest.approx(actor.position_meters)
    assert rec.state_mask == actor.state_mask
    assert [(j.sub_id, j.bam) for j in rec.joints[: rec.joint_count]] == actor.joint_angles_bam
    expect_next = None if link == (0, 0) else f"{link[1]:04X}:{link[0]:04X}"
    assert (
        None if (rec.next_off, rec.next_seg) == (0, 0) else f"{rec.next_seg:04X}:{rec.next_off:04X}"
    ) == expect_next
    assert next_addr == expect_next
