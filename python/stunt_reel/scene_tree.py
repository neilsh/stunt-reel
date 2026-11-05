"""Walk ``PLAYONE.EXE``'s embedded scene tree and compare its Ground polygons with ``MAP.BIN``.

The tree is the start of the stack segment of the unpacked load image (image offset
``0x22860``): ``SCENERY.scn`` with 16-bit words, node fields addressed as byte offsets in
that segment. ``SP_GROUND`` (type 12) and ``SP_GLEAF`` (type 14) carry the Ground's polygons
inline, each ``[colour][count][count anchor pointers]`` with pointer ``28 * k`` for anchor
``k``; the drawer is image ``0xBF23`` (``research/playone-exe/world-scene.md`` section 2).

Pure functions over bytes; nothing here reads a file or holds game data.
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field

#: Image offset of the scene tree (MZ ``SS = 0x2286``).
TREE_IMAGE_OFFSET: int = 0x22860
#: Bytes per anchor record; a polygon's anchor pointer is ``ANCHOR_STRIDE * k``.
ANCHOR_STRIDE: int = 28
#: Offset of a ``SP_GLEAF`` polygon from its node, and of a ``SP_GROUND`` coarse leaf.
GLEAF_POLYGON: int = 0x0E
GROUND_COARSE_LEAF: int = 0x0C
MAP_RECORD: int = 30
MAP_RECORDS: int = 179
MAP_SLOTS: int = 7
ANCHORS: int = 1024

SP_POS, SP_1NODE, SP_2NODE, SP_XPLANE, SP_ZPLANE, SP_LEAF = 0, 2, 4, 6, 8, 10
SP_GROUND, SP_GLEAF, SP_HSLOPE, SP_VSLOPE, SP_LIST, SP_POSXZ = 12, 14, 16, 18, 20, 22


@dataclass(frozen=True)
class GroundPolygon:
    """One inline Ground polygon: where it sits, its colour word and its anchor indices."""

    kind: str  # "gleaf" or "ground-coarse"
    offset: int  # byte offset of the polygon in the tree segment
    colour: int
    anchors: tuple[int, ...]


@dataclass
class TreeWalk:
    """What a walk visited."""

    node_types: Counter[int] = field(default_factory=Counter)
    polygons: list[GroundPolygon] = field(default_factory=list)
    leaves: Counter[int] = field(default_factory=Counter)
    unknown: list[tuple[int, int]] = field(default_factory=list)  # (offset, type)


@dataclass(frozen=True)
class MapPatch:
    """An active ``MAP.BIN`` record."""

    index: int
    colour: int
    anchors: tuple[int, ...]


@dataclass(frozen=True)
class Comparison:
    """Tree polygons against ``MAP.BIN`` patches, matched by anchor set."""

    same: int
    recoloured: list[tuple[GroundPolygon, MapPatch]]
    tree_only: list[GroundPolygon]
    map_only: list[MapPatch]


def _word(seg: bytes, off: int) -> int:
    if off < 0 or off + 2 > len(seg):
        raise ValueError(f"tree read at 0x{off:04X} outside the segment")
    value: int = struct.unpack_from("<H", seg, off)[0]
    return value


def _polygon(seg: bytes, off: int, kind: str) -> GroundPolygon:
    colour = _word(seg, off)
    count = _word(seg, off + 2)
    pointers = [_word(seg, off + 4 + 2 * i) for i in range(count)]
    if any(p % ANCHOR_STRIDE for p in pointers):
        raise ValueError(f"polygon at 0x{off:04X} has an anchor pointer off the 28-byte stride")
    return GroundPolygon(kind, off, colour, tuple(p // ANCHOR_STRIDE for p in pointers))


def walk(seg: bytes, root: int = 0) -> TreeWalk:
    """Visit every node reachable from ``root``; a zero link ends a branch (except the root)."""
    result = TreeWalk()
    seen: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        kind = _word(seg, node)
        result.node_types[kind] += 1
        links: list[int] = []
        if kind in (SP_POS, SP_1NODE):
            links = [_word(seg, node + 8)]
        elif kind == SP_POSXZ:
            links = [_word(seg, node + 6)]
        elif kind in (SP_2NODE, SP_XPLANE, SP_ZPLANE, SP_HSLOPE, SP_VSLOPE):
            links = [_word(seg, node + 2), _word(seg, node + 4)]
        elif kind == SP_LEAF:
            result.leaves[_word(seg, node + 2)] += 1
        elif kind == SP_GROUND:
            links = [_word(seg, node + 0x0C), _word(seg, node + 0x0E)]
            coarse = node + GROUND_COARSE_LEAF + GLEAF_POLYGON
            if _word(seg, coarse):
                result.polygons.append(_polygon(seg, coarse, "ground-coarse"))
        elif kind == SP_GLEAF:
            links = [_word(seg, node + 2)]
            if _word(seg, node + GLEAF_POLYGON):
                result.polygons.append(_polygon(seg, node + GLEAF_POLYGON, "gleaf"))
        elif kind == SP_LIST:
            cursor = node + 2
            while (child := _word(seg, cursor)) != 0:
                links.append(child)
                cursor += 2
        else:
            result.unknown.append((node, kind))
        stack.extend(link for link in links if link)
    return result


def tree_segment(image: bytes) -> bytes:
    """The scene-tree segment of an unpacked load image."""
    if len(image) <= TREE_IMAGE_OFFSET:
        raise ValueError("image is shorter than the scene tree offset")
    return image[TREE_IMAGE_OFFSET:]


def parse_map_bin(data: bytes) -> list[MapPatch]:
    """Active ``MAP.BIN`` records, vertex count capped at the seven slots."""
    patches = []
    for index in range(min(MAP_RECORDS, len(data) // MAP_RECORD)):
        r = struct.unpack_from("<15h", data, MAP_RECORD * index)
        pos, colour, count = r[1], r[6], min(max(r[7], 0), MAP_SLOTS)
        anchors = tuple(v & 0xFFFF for v in r[8 : 8 + count])
        if pos & 0xFF and all(a < ANCHORS for a in anchors):
            patches.append(MapPatch(index, colour, anchors))
    return patches


def check_map_bin(data: bytes) -> None:
    """Raise ``ValueError`` unless ``data`` holds 179 records and the 2-byte null terminator."""
    need = MAP_RECORDS * MAP_RECORD + 2
    if len(data) < need:
        raise ValueError(
            f"MAP.BIN has {len(data)} bytes, expected {need} (179 records + terminator)"
        )
    if data[need - 2 : need] != b"\0\0":
        raise ValueError("MAP.BIN terminator word is not zero")


def compare(polygons: list[GroundPolygon], patches: list[MapPatch]) -> Comparison:
    """Match polygons to patches by anchor set; colours compare on the low byte."""
    by_set: dict[frozenset[int], list[MapPatch]] = {}
    for patch in patches:
        by_set.setdefault(frozenset(patch.anchors), []).append(patch)
    matched: set[int] = set()
    same = 0
    recoloured: list[tuple[GroundPolygon, MapPatch]] = []
    tree_only: list[GroundPolygon] = []
    for poly in polygons:
        key = frozenset(poly.anchors)
        candidates = by_set.get(key)
        if not candidates:
            tree_only.append(poly)
            continue
        patch = candidates.pop(0)  # each record matches at most one polygon
        matched.add(patch.index)
        if patch.colour == poly.colour & 0xFF:
            same += 1
        else:
            recoloured.append((poly, patch))
    map_only = [p for p in patches if p.index not in matched]
    return Comparison(same, recoloured, tree_only, map_only)
