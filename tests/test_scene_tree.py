"""Scene-tree walk and MAP.BIN comparison over synthetic bytes (no game data)."""

from __future__ import annotations

import struct
lazy from pathlib import Path

import pytest
import scene_ground
import scene_patches

from stunt_reel import scene_tree


def _segment(words: dict[int, list[int]], size: int = 0x100) -> bytes:
    """A tree segment with word lists placed at byte offsets."""
    buf = bytearray(size)
    for off, ws in words.items():
        struct.pack_into(f"<{len(ws)}H", buf, off, *ws)
    return bytes(buf)


def _map_record(pos: int, colour: int, anchors: list[int]) -> bytes:
    """Build one 30-byte MAP.BIN record with the given colour and anchors."""
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
    """The walk returns each leaf and coarse polygon with its colour and anchors."""
    walked = scene_tree.walk(TREE)
    assert walked.unknown == []
    assert sum(walked.node_types.values()) == 6
    assert sorted((p.kind, p.colour, p.anchors) for p in walked.polygons) == [
        ("gleaf", 195, (1, 2, 3)),
        ("ground-coarse", 14, (4, 5, 6)),
    ]
    assert walked.leaves == {0x0391: 1}


def test_walk_rejects_a_pointer_off_the_anchor_stride() -> None:
    """An anchor pointer off the 28-byte stride is refused."""
    bad = _segment({0x00: [14, 0, 0, 0, 0, 0, 0, 195, 1, 30]})
    with pytest.raises(ValueError, match="28-byte stride"):
        scene_tree.walk(bad)


def test_walk_reports_unknown_node_types() -> None:
    """A node of an unknown type is reported, not skipped silently."""
    assert scene_tree.walk(_segment({0x00: [7]})).unknown == [(0, 7)]


def test_compare_against_map_bin() -> None:
    """Polygons pair with MAP.BIN records by anchor set, and colours compare."""
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
    """An image shorter than the tree offset is refused."""
    with pytest.raises(ValueError, match="shorter than the scene tree"):
        scene_tree.tree_segment(b"\0" * 16)
    assert scene_tree.tree_segment(b"\0" * scene_tree.TREE_IMAGE_OFFSET + b"ab") == b"ab"


def test_walk_keeps_all_eight_anchors_of_a_leaf() -> None:
    """A leaf with eight anchors keeps all eight (record 131's case)."""
    seg = _segment({0x00: [14, 0, 0, 0, 0, 0, 0, 14, 8, 28, 56, 84, 112, 140, 168, 196, 224]})
    (poly,) = scene_tree.walk(seg).polygons
    assert poly.anchors == (1, 2, 3, 4, 5, 6, 7, 8)


def test_parse_map_bin_reads_an_eighth_vertex_from_the_next_record() -> None:
    """A count of 8 takes the next record's first word as its eighth anchor (patch 131)."""
    eight = struct.pack("<8h7H", 0, 1, -1, -1, 0, -1, 14, 8, *range(1, 8))
    nxt = struct.pack("<H", 50) + _map_record(1, 15, [9, 10, 11])[2:]
    (first, _) = scene_tree.parse_map_bin(eight + nxt)
    assert first.anchors == (1, 2, 3, 4, 5, 6, 7, 50)
    (last,) = scene_tree.parse_map_bin(eight)
    assert last.anchors == (1, 2, 3, 4, 5, 6, 7)


def test_compare_matches_each_record_at_most_once() -> None:
    """Two records sharing an anchor set are each matched at most once."""
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
    """A recoloured fallback never takes the record another polygon matches exactly."""
    patches = scene_tree.parse_map_bin(
        _map_record(1, 14, [1, 2, 3]) + _map_record(1, 195, [1, 2, 3])
    )
    other = scene_tree.GroundPolygon("gleaf", 0, 195, (1, 2, 3))
    exact = scene_tree.GroundPolygon("gleaf", 0, 14, (1, 2, 3))
    result = scene_tree.compare([other, exact], patches)
    assert result.same == 2
    assert result.recoloured == []
    assert result.map_only == []


def test_check_map_bin_rejects_empty_and_truncated() -> None:
    """Empty, short or unterminated MAP.BIN data is refused."""
    whole = b"\0" * (scene_tree.MAP_RECORDS * scene_tree.MAP_RECORD + 2)
    scene_tree.check_map_bin(whole)
    for bad in (b"", whole[:-1], whole[:-2] + b"\0"):
        with pytest.raises(ValueError, match=r"MAP\.BIN"):
            scene_tree.check_map_bin(bad)


def test_cli_stops_on_unknown_nodes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI fails before comparing when the walk meets an unknown node."""
    image = tmp_path / "img.bin"
    image.write_bytes(b"\0" * scene_tree.TREE_IMAGE_OFFSET + _segment({0x00: [7]}))
    map_path = tmp_path / "MAP.BIN"
    map_path.write_bytes(b"\0" * (scene_tree.MAP_RECORDS * scene_tree.MAP_RECORD + 2))
    assert scene_ground.main([str(image), str(map_path)]) == 1
    assert "unknown node type 7 at 0x0000" in capsys.readouterr().err
    map_path.write_bytes(b"")
    assert scene_ground.main([str(image), str(map_path)]) == 1
    assert scene_ground.main([str(image), str(tmp_path / "missing.bin")]) == 2


def _scn(segment: bytes, links: set[int]) -> bytes:
    """A SCENERY.scn image of ``segment``: 32-bit words, a leading 0, the given links 2 higher."""
    words = struct.unpack(f"<{len(segment) // 2}H", segment)
    shifted = [w + scene_tree.SCN_LINK_BIAS if 2 * i in links else w for i, w in enumerate(words)]
    return struct.pack(f"<{len(words) + 1}i", 0, *shifted)


# Byte offsets of TREE's non-zero links (2NODE ptr/next, LIST children, GROUND ptr).
TREE_LINKS = {0x02, 0x04, 0x42, 0x44, 0x6C}


def test_scn_segment_walks_like_the_image_tree() -> None:
    """A converted SCENERY.scn walks to the same polygons, and only its links differ."""
    converted = scene_tree.scn_segment(_scn(TREE, TREE_LINKS))
    diff = scene_tree.diff_segments(converted, TREE)
    assert (diff.words, diff.link_words, diff.other) == (len(TREE) // 2, 5, [])
    own = scene_tree.walk(converted, link_bias=scene_tree.SCN_LINK_BIAS)
    assert own.polygons == scene_tree.walk(TREE).polygons
    changed = bytearray(converted)
    changed[0x1E] = 91  # the GLEAF's colour
    assert scene_tree.diff_segments(bytes(changed), TREE).other == [0x1E]


def test_scn_segment_rejects_malformed_files() -> None:
    """A file with a partial word, no leading 0 or a word past 16 bits is refused."""
    for bad, message in (
        (b"\0" * 6, "whole number"),
        (struct.pack("<2i", 1, 0), "0 word"),
        (struct.pack("<2i", 0, 0x10000), "16 bits"),
    ):
        with pytest.raises(ValueError, match=message):
            scene_tree.scn_segment(bad)
    with pytest.raises(ValueError, match="shorter"):
        scene_tree.diff_segments(b"\0" * 8, b"\0" * 4)


def test_polygon_bodies_cover_every_vertex_order() -> None:
    """Both byte forms, every rotation and both windings."""
    bodies = scene_tree.polygon_bodies((1, 2, 3))
    assert struct.pack("<4H", 3, 56, 84, 28) in bodies["pointer"]
    assert struct.pack("<4H", 3, 3, 2, 1) in bodies["index"]
    assert len(bodies["pointer"]) == len(bodies["index"]) == 6
    assert scene_tree.find_all(b"abab", b"ab") == [0, 2]
    assert scene_tree.find_all(b"aaa", b"aa") == [0, 1]


def test_tap_anchors_reads_tap_shaped_operands() -> None:
    """Counts 2 and 3 on the 28-byte stride are read; anything else is not."""
    data = (
        struct.pack("<5H", scene_tree.OP_TAP, 0, 2, 28, 56)
        + struct.pack("<6H", scene_tree.OP_TAP, 12, 3, 0, 84, 196)
        + struct.pack("<5H", scene_tree.OP_TAP, 0, 2, 30, 56)  # off the stride
        + struct.pack("<4H", scene_tree.OP_TAP, 0, 4, 28)  # count 4
        + struct.pack("<3H", scene_tree.OP_TAP, 0, 3)  # truncated
    )
    assert scene_tree.tap_anchors(data) == {1: 1, 2: 1, 0: 1, 3: 1, 7: 1}


def test_image_anchor_and_covers() -> None:
    """Anchors read from the image table; the plan test is even-odd."""
    image = bytearray(scene_tree.ANCHOR_TABLE_OFFSET + scene_tree.ANCHOR_STRIDE * 2)
    struct.pack_into("<3h", image, scene_tree.ANCHOR_TABLE_OFFSET + 28, 5, -32768, 7)
    assert scene_tree.image_anchor(bytes(image), 1) == (5, scene_tree.SENTINEL_Y, 7)
    assert scene_tree.image_anchor(bytes(image), scene_tree.IMAGE_ANCHORS) is None
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert scene_tree.covers((5, 5), square)
    assert not scene_tree.covers((15, 5), square)


def test_scene_patches_reports_a_patch_with_no_polygon(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI finds the patch the tree lacks, its MAP.BIN bytes and the tree polygon under it."""
    image = bytearray(scene_tree.TREE_IMAGE_OFFSET + len(TREE))
    image[scene_tree.TREE_IMAGE_OFFSET :] = TREE
    for k, (x, z) in enumerate([(0, 0), (0, 0), (100, 0), (0, 100), (1, 1), (9, 1), (1, 9)]):
        struct.pack_into("<3h", image, scene_tree.ANCHOR_TABLE_OFFSET + 28 * k, x, 0, z)
    image_path = tmp_path / "img.bin"
    image_path.write_bytes(bytes(image))
    records = (
        _map_record(1, 195, [1, 2, 3])
        + _map_record(1, 14, [4, 5, 6])
        + _map_record(1, 91, [4, 6, 5])
    )
    pad = scene_tree.MAP_RECORDS * scene_tree.MAP_RECORD - len(records)
    map_path = tmp_path / "MAP.BIN"
    map_path.write_bytes(records + b"\0" * (pad + 2))
    scn_path = tmp_path / "SCENERY.scn"
    scn_path.write_bytes(_scn(TREE, TREE_LINKS))
    scan = tmp_path / "scan"
    scan.mkdir()
    (scan / "SHAPE.ALL").write_bytes(struct.pack("<5H", scene_tree.OP_TAP, 0, 2, 112, 140))
    argv = [str(image_path), str(map_path), "--scn", str(scn_path), "--scan", str(scan)]
    assert scene_patches.main(argv) == 0
    out = capsys.readouterr().out
    assert "1 active MAP.BIN records without one" in out
    assert "5 links 2 higher, 0 other differences; 2 ground polygons, the same" in out
    assert "control: polygon bytes of 2 of 2 matched records found in the image" in out
    assert "patch 2 colour 91" in out
    assert "OP_TAP operands naming its anchors: {4: 1, 5: 1}" in out
    assert "ground-coarse 0x007A colour 14, gleaf 0x001E colour 195" in out
    assert "shapes placed inside it: none" in out
    assert scene_patches.main([str(image_path), str(tmp_path / "none.bin")]) == 2


def test_placements_carry_the_position_above_them() -> None:
    """A subtree gets a copy of the position; the chain after it keeps its own."""
    seg = _segment(
        {
            0x00: [4, 0x10, 0x20],  # 2NODE: subtree 0x10, then 0x20
            0x10: [0, 5, 0xFFFE, 7, 0x30],  # POS (5, -2, 7) -> LEAF
            0x20: [22, 100, 200, 0x38],  # POSXZ (100, 200) -> 1NODE
            0x30: [10, 0x0391],
            0x38: [2, 0x0402, 0, 0, 0x30],  # 1NODE stand-in, then the same LEAF
        }
    )
    assert scene_tree.placements(seg) == {
        scene_tree.Placement(0x0391, 5, -2, 7, stand_in=False),
        scene_tree.Placement(0x0402, 100, 0, 200, stand_in=True),
        scene_tree.Placement(0x0391, 100, 0, 200, stand_in=False),
    }
    assert {p.obj for p in scene_tree.placements(TREE)} == {0x0391}
    with pytest.raises(ValueError, match="unknown node type 7"):
        scene_tree.placements(_segment({0x00: [7]}))
    with pytest.raises(ValueError, match="cycle"):
        scene_tree.placements(
            _segment({0x00: [0, 0, 0, 0, 0x10], 0x10: [0, 0, 0, 0, 0x10]}), max_steps=100
        )
