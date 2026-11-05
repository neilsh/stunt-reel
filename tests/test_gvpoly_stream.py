"""GVPOLY records of PLAYONE's live display list (world-scene.md section 4.1)."""

from __future__ import annotations

import json
import struct
lazy from pathlib import Path

import gvpoly_stream as cli

from stunt_reel.gvpoly_stream import Polygon, decode_record

G168, G2BE = 0x995C, 0x9A24


def record(base: int, shades: list[int], next_ip: int) -> bytes:
    return struct.pack(f"<H{len(shades)}HH", base << 8 | len(shades), *shades, next_ip)


def test_count_low_nibble_only() -> None:
    poly = decode_record(struct.pack("<H", 0xC32D) + bytes(30), 0x1000, G168)
    assert poly is not None
    assert (poly.base, poly.count) == (0xC3, 13)


def test_record_shades_and_next_ip() -> None:
    poly = decode_record(record(0xC4, [1, 2, 3], 0x17E4), 0x6B71C, G168)
    assert poly == Polygon(0x6B71C, G168, 0xC4, 3, (1, 2, 3), 0x17E4)


def test_short_record_is_none() -> None:
    assert decode_record(record(0xC4, [1, 2, 3], 0x17E4)[:-1], 0, G168) is None


def hit(es: int, si: int, ip: int, image: int, data: bytes) -> dict[str, object]:
    return {
        "type": "hit",
        "probe": "gvpoly",
        "film_tick": 10,
        "regs": {"es": es, "si": si, "ip": ip, "cs": 0x1048},
        "cs_ip_image": image,
        "mem": {"mem:ES:SI:40": data.ljust(40, b"\0").hex()},
    }


def test_cli_groups_by_es(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    rows = [
        {"type": "run", "build": "unpatched"},
        hit(0x6B71, 0x000E, 0x171C, G168, record(0xC4, [1, 2], 0x1241)),
        hit(0x6B71, 0x0040, 0x17E4, G2BE, record(0xC4, [3], 0x1241)),
        hit(0x6BC2, 0x000E, 0x171C, G168, record(0xC1, [1, 2, 3], 0x1241)),
        {"type": "end", "reason": "spent"},
    ]
    path = tmp_path / "g.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert cli.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "6B71: 2 polygons" in out
    assert "6BC2: 1 polygons" in out
    assert "0xc4 x2" in out


def test_cli_counts_a_record_hit_twice_once(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    # The same record is drawn every frame; a second hit at the same ES:SI is not a new polygon.
    again = hit(0x6B71, 0x000E, 0x171C, G168, record(0xC4, [1, 2], 0x1241))
    path = tmp_path / "g.jsonl"
    path.write_text(json.dumps(again) + "\n" + json.dumps(again) + "\n", encoding="utf-8")
    assert cli.main([str(path)]) == 0
    assert "6B71: 1 polygons; 0xc4 x1" in capsys.readouterr().out
