"""Scene-tree walk and MAP.BIN comparison over synthetic bytes (no game data)."""

from __future__ import annotations

import struct
lazy from pathlib import Path

import pytest
import scene_ground

from stunt_reel import scene_tree
from stunt_reel.dataroot import REPO_ROOT


def _segment(words: dict[int, list[int]], size: int = 0x100) -> bytes:
    """A tree segment with word lists placed at byte offsets."""
    buf = bytearray(size)
    for off, ws in words.items():
        struct.pack_into(f"<{len(ws)}H", buf, off, *ws)
    return bytes(buf)


def _map_record(pos: int, colour: int, anchors: list[int]) -> bytes:
    slots = (anchors + [0xFFFF] * 7)[:7]
    return struct.pack("<8h7H", 0, pos, -1, -1, 0, -1, colour, len(anchors), *slots)


# Root 2NODE -> GLEAF (195, anchors 1,2,3) and a LIST holding a LEAF and a GROUND whose coarse
# leaf is colour 14 on anchors 4,5,6 and whose subtree is a POSXZ ending the branch.
TREE = _segment(
    {
        0x00: [4, 0x10, 0x40],
        0x10: [14, 0, 0, 0x46AF, 0, 0, 0, 195, 3, 28, 56, 84],
        0x40: [20, 0x50, 0x60, 0],
        0x50: [10, 0x0391],
        0x60: [12, 500, 100, 0, 0, 0, 0x90, 0, 0, 0, 0, 0, 0, 14, 3, 112, 140, 168],
        0x90: [22, 5, 5, 0],
    }
)


def test_walk_collects_polygons_and_leaves() -> None:
    walked = scene_tree.walk(TREE)
    assert walked.unknown == []
    assert sum(walked.node_types.values()) == 6
    assert sorted((p.kind, p.colour, p.anchors) for p in walked.polygons) == [
        ("gleaf", 195, (1, 2, 3)),
        ("ground-coarse", 14, (4, 5, 6)),
    ]
    assert walked.leaves == {0x0391: 1}


def test_walk_rejects_a_pointer_off_the_anchor_stride() -> None:
    bad = _segment({0x00: [14, 0, 0, 0, 0, 0, 0, 195, 1, 30]})
    with pytest.raises(ValueError, match="28-byte stride"):
        scene_tree.walk(bad)


def test_walk_reports_unknown_node_types() -> None:
    assert scene_tree.walk(_segment({0x00: [7]})).unknown == [(0, 7)]


def test_compare_against_map_bin() -> None:
    map_bin = (
        _map_record(1, 195, [3, 2, 1])  # same polygon, other vertex order
        + _map_record(1, 15, [4, 5, 6])  # recoloured
        + _map_record(1, 91, [7, 8, 9])  # map only
        + _map_record(0, 50, [10, 11, 12])  # inactive: ignored
    )
    patches = scene_tree.parse_map_bin(map_bin)
    assert [p.index for p in patches] == [0, 1, 2]
    result = scene_tree.compare(scene_tree.walk(TREE).polygons, patches)
    assert result.same == 1
    assert [(p.colour, m.colour) for p, m in result.recoloured] == [(14, 15)]
    assert result.tree_only == []
    assert [m.index for m in result.map_only] == [2]


def test_tree_segment_needs_the_offset() -> None:
    with pytest.raises(ValueError, match="shorter than the scene tree"):
        scene_tree.tree_segment(b"\0" * 16)
    assert scene_tree.tree_segment(b"\0" * scene_tree.TREE_IMAGE_OFFSET + b"ab") == b"ab"


def test_walk_keeps_all_eight_anchors_of_a_leaf() -> None:
    seg = _segment({0x00: [14, 0, 0, 0, 0, 0, 0, 14, 8, 28, 56, 84, 112, 140, 168, 196, 224]})
    (poly,) = scene_tree.walk(seg).polygons
    assert poly.anchors == (1, 2, 3, 4, 5, 6, 7, 8)


def test_compare_matches_each_record_at_most_once() -> None:
    twin = scene_tree.GroundPolygon("gleaf", 0, 195, (1, 2, 3))
    patches = scene_tree.parse_map_bin(_map_record(1, 195, [1, 2, 3]) * 2)
    one = scene_tree.compare([twin], patches)
    assert one.same == 1
    assert [m.index for m in one.map_only] == [1]
    two = scene_tree.compare([twin, twin], patches)
    assert two.same == 2
    assert two.map_only == []
    three = scene_tree.compare([twin, twin, twin], patches)
    assert len(three.tree_only) == 1


def test_compare_pairs_same_colour_before_recolouring() -> None:
    patches = scene_tree.parse_map_bin(
        _map_record(1, 14, [1, 2, 3]) + _map_record(1, 195, [1, 2, 3])
    )
    other = scene_tree.GroundPolygon("gleaf", 0, 195, (1, 2, 3))
    exact = scene_tree.GroundPolygon("gleaf", 0, 14, (1, 2, 3))
    result = scene_tree.compare([other, exact], patches)
    assert result.same == 2
    assert result.recoloured == []
    assert result.map_only == []


def test_needs_corpus_sees_a_path_through_the_link(tmp_path: Path) -> None:
    corpus = REPO_ROOT / "corpus"
    assert scene_ground._needs_corpus(corpus / "stisldem" / "MAP.BIN")
    assert not scene_ground._needs_corpus(tmp_path / "MAP.BIN")
    assert not scene_ground._needs_corpus(corpus / ".." / "build" / "playone.img")


def test_check_map_bin_rejects_empty_and_truncated() -> None:
    whole = b"\0" * (scene_tree.MAP_RECORDS * scene_tree.MAP_RECORD + 2)
    scene_tree.check_map_bin(whole)
    for bad in (b"", whole[:-1], whole[:-2] + b"\0"):
        with pytest.raises(ValueError, match=r"MAP\.BIN"):
            scene_tree.check_map_bin(bad)


def test_cli_stops_on_unknown_nodes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    image = tmp_path / "img.bin"
    image.write_bytes(b"\0" * scene_tree.TREE_IMAGE_OFFSET + _segment({0x00: [7]}))
    map_path = tmp_path / "MAP.BIN"
    map_path.write_bytes(b"\0" * (scene_tree.MAP_RECORDS * scene_tree.MAP_RECORD + 2))
    assert scene_ground.main([str(image), str(map_path)]) == 1
    assert "unknown node type 7 at 0x0000" in capsys.readouterr().err
    map_path.write_bytes(b"")
    assert scene_ground.main([str(image), str(map_path)]) == 1
