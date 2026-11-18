"""Scene-tree walk and MAP.BIN comparison over synthetic bytes (no game data)."""

from __future__ import annotations

import struct
from pathlib import Path

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


def _map_record(pos: int, colour: int, anchors: list[int], nxt: int = -1) -> bytes:
    """Build one 30-byte MAP.BIN record with the given colour, anchors and next link."""
    slots = (anchors + [0xFFFF] * 8)[:8]
    return struct.pack("<7h8H", pos, nxt, -1, 100, -1, colour, len(anchors), *slots)


def _map_bin(*records: bytes) -> bytes:
    """A MAP.BIN of ``records`` behind a list head naming the first."""
    return struct.pack("<h", 0) + b"".join(records)


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
    map_bin = _map_bin(
        _map_record(1, 195, [3, 2, 1]),  # same polygon, other vertex order
        _map_record(1, 15, [4, 5, 6]),  # recoloured
        _map_record(1, 91, [7, 8, 9]),  # map only
        _map_record(0, 50, [10, 11, 12]),  # inactive: ignored
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


def test_parse_map_bin_reads_eight_vertex_slots_after_the_list_head() -> None:
    """Records start after the 2-byte head and hold eight slots, so patch 131's last is its own."""
    map_bin = _map_bin(
        _map_record(1, 14, [1, 2, 3, 4, 5, 6, 7, 50]), _map_record(1, 15, [9, 10, 11])
    )
    (first, second) = scene_tree.parse_map_bin(map_bin)
    assert (first.colour, first.anchors) == (14, (1, 2, 3, 4, 5, 6, 7, 50))
    assert (second.index, second.anchors) == (1, (9, 10, 11))
    (only,) = scene_tree.parse_map_bin(map_bin[:-1])  # a partial last record is not read
    assert only.index == 0


def test_parse_map_bin_counts_vertices_as_world_rs_does() -> None:
    """Fewer than three vertices is no polygon; a negative count reads all eight slots."""
    negative = bytearray(_map_record(1, 16, list(range(1, 9))))
    struct.pack_into("<h", negative, 12, -1)
    patches = scene_tree.parse_map_bin(
        _map_bin(_map_record(1, 15, [1, 2]), bytes(negative), _map_record(1, 17, []))
    )
    assert [(p.index, p.anchors) for p in patches] == [(1, (1, 2, 3, 4, 5, 6, 7, 8))]


def test_compare_matches_each_record_at_most_once() -> None:
    """Two records sharing an anchor set are each matched at most once."""
    twin = scene_tree.GroundPolygon("gleaf", 0, 195, (1, 2, 3))
    patches = scene_tree.parse_map_bin(_map_bin(*[_map_record(1, 195, [1, 2, 3])] * 2))
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
        _map_bin(_map_record(1, 14, [1, 2, 3]), _map_record(1, 195, [1, 2, 3]))
    )
    other = scene_tree.GroundPolygon("gleaf", 0, 195, (1, 2, 3))
    exact = scene_tree.GroundPolygon("gleaf", 0, 14, (1, 2, 3))
    result = scene_tree.compare([other, exact], patches)
    assert result.same == 2
    assert result.recoloured == []
    assert result.map_only == []


def test_check_map_bin_rejects_empty_and_truncated() -> None:
    """Empty, head-only or partial-record MAP.BIN data is refused."""
    whole = b"\0" * (scene_tree.MAP_HEAD + scene_tree.MAP_RECORDS * scene_tree.MAP_RECORD)
    scene_tree.check_map_bin(whole)
    for bad in (b"", whole[: scene_tree.MAP_HEAD], whole[:-1]):
        with pytest.raises(ValueError, match=r"MAP\.BIN"):
            scene_tree.check_map_bin(bad)


def test_cli_stops_on_unknown_nodes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI fails before comparing when the walk meets an unknown node."""
    image = tmp_path / "img.bin"
    image.write_bytes(b"\0" * scene_tree.TREE_IMAGE_OFFSET + _segment({0x00: [7]}))
    map_path = tmp_path / "MAP.BIN"
    map_path.write_bytes(
        b"\0" * (scene_tree.MAP_HEAD + scene_tree.MAP_RECORDS * scene_tree.MAP_RECORD)
    )
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
    fields = scene_tree.walk(TREE).link_fields
    assert fields >= TREE_LINKS
    diff = scene_tree.diff_segments(converted, TREE, fields)
    assert (diff.words, diff.link_words, diff.other) == (len(TREE) // 2, 5, [])
    own = scene_tree.walk(converted, link_bias=scene_tree.SCN_LINK_BIAS)
    assert own.polygons == scene_tree.walk(TREE).polygons
    changed = bytearray(converted)
    changed[0x1E] = 91  # the GLEAF's colour
    assert scene_tree.diff_segments(bytes(changed), TREE, fields).other == [0x1E]


def test_diff_segments_reports_a_non_link_word_two_higher() -> None:
    """A position word 2 higher is a real difference, not a link."""
    converted = bytearray(scene_tree.scn_segment(_scn(TREE, TREE_LINKS)))
    struct.pack_into("<H", converted, 0x92, 5 + scene_tree.SCN_LINK_BIAS)  # POSXZ x
    fields = scene_tree.walk(TREE).link_fields
    assert 0x92 not in fields
    diff = scene_tree.diff_segments(bytes(converted), TREE, fields)
    assert (diff.link_words, diff.other) == (5, [0x92])


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
        scene_tree.diff_segments(b"\0" * 8, b"\0" * 4, set())


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
    records = _map_bin(
        _map_record(1, 195, [1, 2, 3]),
        _map_record(1, 14, [4, 5, 6]),
        _map_record(1, 91, [4, 6, 5]),
    )
    pad = scene_tree.MAP_HEAD + scene_tree.MAP_RECORDS * scene_tree.MAP_RECORD - len(records)
    map_path = tmp_path / "MAP.BIN"
    map_path.write_bytes(records + b"\0" * pad)
    scn_path = tmp_path / "SCENERY.scn"
    scn_path.write_bytes(_scn(TREE, TREE_LINKS))
    scan = tmp_path / "scan"
    scan.mkdir()
    (scan / "SHAPE.ALL").write_bytes(struct.pack("<5H", scene_tree.OP_TAP, 0, 2, 112, 140))
    argv = [str(image_path), str(map_path), "--scn", str(scn_path), "--scan", str(scan)]
    assert scene_patches.main(argv) == 0
    out = capsys.readouterr().out
    assert "1 active MAP.BIN records without one" in out
    assert "5 of 8 link fields 2 higher, 0 other differences []; 2 ground polygons, the same" in out
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


def test_map_links_and_chains() -> None:
    """``a`` names a record by byte offset; chains start where nothing links in."""
    map_bin = _map_bin(
        _map_record(0x00FF, 1, [1, 2, 3], nxt=30),
        _map_record(0x00FF, 1, [1, 2, 3]),
        _map_record(0x07FF, 1, [1, 2, 3]),
    )
    links = scene_tree.map_links(map_bin)
    assert links == {0: (0x00FF, 1), 1: (0x00FF, -1), 2: (0x07FF, -1)}
    assert scene_tree.link_chains(links) == [[0, 1], [2]]
    lines = scene_patches.record_fields(map_bin, {1})
    assert lines == [
        "pos 0x00FF: on 1 drawn records [0]",
        "a chains no record links into (under 10 long): 0->1 (no polygon), 2",
    ]


def test_matched_records_and_scene_ground_report() -> None:
    """Each coarse polygon is reported with the record it matches."""
    patches = scene_tree.parse_map_bin(
        _map_bin(_map_record(1, 195, [1, 2, 3]), _map_record(1, 14, [6, 5, 4]))
    )
    walked = scene_tree.walk(TREE)
    pairs = scene_tree.matched_records(walked.polygons, patches)
    assert sorted((p.colour, r) for p, r in pairs) == [(14, [1]), (195, [0])]
    text = scene_ground.report(walked, scene_tree.compare(walked.polygons, patches), patches)
    assert "coarse SP_GROUND polygons (1): record 1 at 0x007A colour 14" in text


# --- walk_slot: the draw walk with one slot (research/playone-exe/scene-walk-actors.md section 2)

WALK_TREE = (Path(__file__).parent / "fixtures" / "synthetic_walk_tree.bin").read_bytes()
LOOK_Z = (0.0, 0.0, 100.0)


def _walk(
    slot: scene_tree.SlotEntry | None,
    eye: tuple[float, float, float] = (0.0, 0.0, 0.0),
    target: tuple[float, float, float] = LOOK_Z,
) -> scene_tree.SlotWalk:
    return scene_tree.walk_slot(WALK_TREE, eye, target, slot)


def _objects(result: scene_tree.SlotWalk) -> list[str]:
    return [f"0x{s.obj:04X}" if s.kind == "object" else "slot" for s in result.order]


def test_walk_without_a_slot_visits_the_far_side_then_the_eye_side() -> None:
    result = _walk(None)
    # The eye (x = 0) is below the plane at 100, so the greater side is walked first; the
    # SP_2NODE walks its first child with an empty list, and the near SP_1NODE draws nothing.
    # On the eye's side the slope's greater child is the eye's (eye z 0 <= 50).
    assert _objects(result) == ["0x0D01", "0x0D02", "0x0C02", "0x0C01"]
    assert result.leaf is None
    assert result.slot_index is None
    assert result.planes == ()


def test_slot_wholly_below_the_plane_goes_to_the_lesser_child_and_the_slope_splits_it() -> None:
    result = _walk(scene_tree.SlotEntry(50, 0, 70, 5))
    assert result.leaf == 0x22
    assert [(p.kind, p.side, p.why) for p in result.planes] == [
        (scene_tree.SP_XPLANE, "lesser", "whole"),
        (scene_tree.SP_HSLOPE, "lesser", "centre"),
    ]
    assert result.planes[0].coord == 100  # SP_POS x 10 plus the sortvalue 90
    # The slope's far side (the lesser child) is walked first; the slot (depth 70) is deeper
    # than the leaf's object at z = 20, so it is drawn before it.
    assert _objects(result) == ["0x0D01", "0x0D02", "slot", "0x0C02", "0x0C01"]


def test_slot_shallower_than_the_leaf_object_is_drawn_after_it() -> None:
    # z = 5 is on the slope's greater side (50 >= 5), the eye's, so it reaches the other leaf.
    shallow = _walk(scene_tree.SlotEntry(50, 0, 5, 5))  # depth 5 against the object's 20
    assert shallow.leaf == 0x1C
    assert _objects(shallow) == ["0x0D01", "0x0D02", "0x0C02", "0x0C01", "slot"]
    # Looking toward -z the same slot (z = 70) is the shallower of the two.
    behind = _walk(scene_tree.SlotEntry(50, 0, 70, 5), target=(0.0, 0.0, -100.0))
    assert _objects(behind)[-3:] == ["0x0C02", "slot", "0x0C01"]


def test_slot_on_the_greater_side_reaches_the_second_child_of_the_two_node() -> None:
    result = _walk(scene_tree.SlotEntry(150, 0, 0, 5))
    assert result.leaf == 0x5C
    assert [(p.kind, p.side, p.why) for p in result.planes] == [
        (scene_tree.SP_XPLANE, "greater", "whole")
    ]
    # The SP_1NODE it passes is taken as near and reported with its position.
    assert result.gates == ((0x40, 0x0D00, 10, 0, 20),)
    # The slot (depth 0) is shallower than the leaf's object at z = 20, so it follows it.
    assert _objects(result) == ["0x0D01", "0x0D02", "slot", "0x0C02", "0x0C01"]


def test_cut_slot_goes_to_the_eye_side_not_its_centre_side() -> None:
    cut = scene_tree.SlotEntry(98, 0, 0, 5)  # the plane at 100 lies inside 98 +- 5
    below = _walk(cut)  # the eye (x = 0) is on the lesser side
    assert [(p.side, p.why) for p in below.planes[:1]] == [("lesser", "eye")]
    above = _walk(cut, eye=(200.0, 0.0, 0.0))
    assert [(p.side, p.why) for p in above.planes[:1]] == [("greater", "eye")]
    assert above.leaf == 0x5C


def test_a_fractional_eye_moves_the_plane_down_one_metre() -> None:
    # A slot whose extent just reaches the plane at 100: clear with an integer eye, but the
    # high words of the eye and of the negated eye sum to -1, so the plane is at 99 and cuts it.
    slot = scene_tree.SlotEntry(99, 0, 0, 1)
    assert _walk(slot).planes[0].why == "whole"
    assert _walk(slot, eye=(0.5, 0.0, 0.0)).planes[0].why == "eye"


def test_slot_exactly_on_a_plane_with_no_extent_goes_to_the_greater_side() -> None:
    result = _walk(scene_tree.SlotEntry(100, 0, 0, 0))
    assert [(p.side, p.why) for p in result.planes[:1]] == [("greater", "whole")]


def test_slope_line_is_the_scaled_coordinate_plus_the_offset() -> None:
    assert scene_tree._slope_line(100, 0x4000, 5) == 55  # 100 * 0x4000 * 2 >> 16, plus 5
    assert scene_tree._slope_line(-3, 0x4000, 0) == -2  # floors toward minus infinity
    assert scene_tree._slope_line(1000, 0x7FFF, 0x7FFF) == 999 + 0x7FFF - 0x10000  # the word wraps


def test_a_ground_node_drops_the_entry() -> None:
    seg = _segment({0x00: [14, 0, 0, 0, 0, 0, 0, 0]})
    result = scene_tree.walk_slot(seg, (0, 0, 0), LOOK_Z, scene_tree.SlotEntry(0, 0, 0, 1))
    assert result.leaf is None
    assert result.order == ()


def test_a_list_walks_each_child_with_an_empty_list() -> None:
    seg = _segment({0x00: [20, 0x10, 0x20, 0], 0x10: [10, 0x0A01], 0x20: [10, 0x0A02]})
    result = scene_tree.walk_slot(seg, (0, 0, 0), LOOK_Z, scene_tree.SlotEntry(0, 0, 0, 1))
    assert [s.obj for s in result.order] == [0x0A01, 0x0A02]
    assert result.leaf is None


def test_a_cycle_stops_the_slot_walk() -> None:
    seg = _segment({0x00: [4, 0x00, 0x00]})
    with pytest.raises(ValueError, match="cycle"):
        scene_tree.walk_slot(seg, (0, 0, 0), LOOK_Z, None, max_steps=50)


def test_an_unknown_node_type_is_reported() -> None:
    seg = _segment({0x00: [99]})
    with pytest.raises(ValueError, match="unknown node type 99"):
        scene_tree.walk_slot(seg, (0, 0, 0), LOOK_Z, None)


def test_view_depth_is_the_distance_along_the_view_axis() -> None:
    depth = scene_tree.view_depth((0, 0, 0), (0, 0, 10))
    assert depth(3, 4, 7) == pytest.approx(7)
    with pytest.raises(ValueError, match="coincide"):
        scene_tree.view_depth((1, 1, 1), (1, 1, 1))


def _pair(kind: int, *fields: int) -> bytes:
    """A partition node at 0 with leaves 0x0A01 (child +2, greater) and 0x0A02 (child +4)."""
    return _segment(
        {0x00: [kind, 0x20, 0x30, *fields], 0x20: [10, 0x0A01], 0x30: [10, 0x0A02]},
        size=0x40,
    )


def _split(
    seg: bytes, slot: scene_tree.SlotEntry, eye: scene_tree.Vec3 = (0, 0, 0)
) -> scene_tree.SlotWalk:
    return scene_tree.walk_slot(seg, eye, (0.0, 0.0, 100.0), slot)


def test_zplane_splits_on_z_and_reads_the_slots_z_word() -> None:
    zplane = _pair(scene_tree.SP_ZPLANE, 100)
    # x is far from the plane, z is clear of it on the greater side.
    greater = _split(zplane, scene_tree.SlotEntry(-999, 0, 150, 5))
    assert [(p.side, p.why, p.coord) for p in greater.planes] == [("greater", "whole", 100)]
    assert greater.leaf == 0x20
    lesser = _split(zplane, scene_tree.SlotEntry(999, 0, 50, 5))
    assert [(p.side, p.why) for p in lesser.planes] == [("lesser", "whole")]
    assert lesser.leaf == 0x30
    # Cut: the eye's z decides, not the eye's x.
    cut = scene_tree.SlotEntry(999, 0, 98, 5)
    assert _split(zplane, cut, eye=(999, 0, 0)).leaf == 0x30
    assert _split(zplane, cut, eye=(-999, 0, 200)).leaf == 0x20
    # The eye's side is walked last, so the far side's leaf comes first.
    assert [o for o in _objects(_split(zplane, cut, eye=(0, 0, 200))) if o != "slot"] == [
        "0x0A02",
        "0x0A01",
    ]


def test_vslope_compares_the_lines_z_against_x_and_hslope_the_reverse() -> None:
    # line = (coord * 0x4000 * 2 >> 16) + 10 = coord / 2 + 10, taken on z for a VSLOPE.
    vslope = _pair(scene_tree.SP_VSLOPE, 0x4000, 10)
    on_the_line = _split(vslope, scene_tree.SlotEntry(60, 0, 100, 1))  # 100/2 + 10 = 60 >= 60
    assert [(p.side, p.why) for p in on_the_line.planes] == [("greater", "centre")]
    off_the_line = _split(vslope, scene_tree.SlotEntry(61, 0, 100, 1))
    assert off_the_line.planes[0].side == "lesser"
    assert off_the_line.leaf == 0x30
    # The eye: line(0) = 10 >= x = 0 puts it on the greater side, x = 500 on the lesser.
    lesser = scene_tree.SlotEntry(61, 0, 100, 1)
    eye_greater = _objects(_split(vslope, lesser))
    assert [o for o in eye_greater if o != "slot"] == ["0x0A02", "0x0A01"]  # far side first
    eye_lesser = _objects(_split(vslope, lesser, eye=(500, 0, 0)))
    assert [o for o in eye_lesser if o != "slot"] == ["0x0A01", "0x0A02"]
    # The same numbers on an HSLOPE take x as the line's coordinate and compare it with z.
    hslope = _pair(scene_tree.SP_HSLOPE, 0x4000, 10)
    assert _split(hslope, scene_tree.SlotEntry(60, 0, 100, 1)).planes[0].side == "lesser"
    assert _split(hslope, scene_tree.SlotEntry(100, 0, 60, 1)).planes[0].side == "greater"


def test_draw_steps_carry_their_view_depth() -> None:
    result = _walk(scene_tree.SlotEntry(50, 0, 70, 5))
    depths = {(s.kind, s.obj): s.depth for s in result.order}
    assert depths[("slot", 0x0C02)] == pytest.approx(70)
    assert depths[("object", 0x0C02)] == pytest.approx(20)
    assert depths[("object", 0x0D01)] == pytest.approx(20)
