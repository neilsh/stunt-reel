"""Walk ``PLAYONE.EXE``'s embedded scene tree and compare its Ground polygons with ``MAP.BIN``.

The tree is the start of the stack segment of the unpacked load image (image offset
``0x22860``): ``SCENERY.scn`` with 16-bit words, node fields addressed as byte offsets in
that segment. ``SP_GROUND`` (type 12) and ``SP_GLEAF`` (type 14) carry the Ground's polygons
inline, each ``[colour][count][count anchor pointers]`` with pointer ``28 * k`` for anchor
``k``; the drawer is image ``0xBF23`` (``research/playone-exe/world-scene.md`` section 2).
The helpers after :func:`walk` read ``SCENERY.scn`` as such a segment, place the tree's shapes,
and byte-search for a polygon or an ``OP_TAP`` operand by anchor (section 2.1).

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
#: ``MAP.BIN``: a 2-byte list head, then 30-byte records with eight vertex slots
#: (``map.md`` section 2.3); every corpus copy holds 179 records.
MAP_HEAD: int = 2
MAP_RECORD: int = 30
MAP_RECORDS: int = 179
MAP_SLOTS: int = 8
ANCHORS: int = 1024
#: The image's own anchor table: offset and record count (``anchorpt.md`` section 1).
ANCHOR_TABLE_OFFSET: int = 0x15D44
IMAGE_ANCHORS: int = 231
#: An anchor height that marks no point (``anchorpt.md`` ``[BK-MAP-08]``).
SENTINEL_Y: int = -32768
#: ``SCENERY.scn`` links count its leading word, so they are this much higher than the image's.
SCN_LINK_BIAS: int = 2
OP_TAP: int = 0x022E
#: Node visits after which :func:`placements` gives up (the image's tree needs about 300,000).
PLACEMENT_STEPS: int = 5_000_000

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
    link_fields: set[int] = field(default_factory=set)  # byte offsets of every link word read


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
    """Read the little-endian word at ``off``; ``ValueError`` outside the segment."""
    if off < 0 or off + 2 > len(seg):
        raise ValueError(f"tree read at 0x{off:04X} outside the segment")
    value: int = struct.unpack_from("<H", seg, off)[0]
    return value


def _polygon(seg: bytes, off: int, kind: str) -> GroundPolygon:
    """Decode the colour word, vertex count and anchor pointers of the polygon at ``off``."""
    colour = _word(seg, off)
    count = _word(seg, off + 2)
    pointers = [_word(seg, off + 4 + 2 * i) for i in range(count)]
    if any(p % ANCHOR_STRIDE for p in pointers):
        raise ValueError(f"polygon at 0x{off:04X} has an anchor pointer off the 28-byte stride")
    return GroundPolygon(kind, off, colour, tuple(p // ANCHOR_STRIDE for p in pointers))


def walk(seg: bytes, root: int = 0, link_bias: int = 0) -> TreeWalk:
    """Visit every node reachable from ``root``; a zero link ends a branch (except the root).

    ``link_bias`` is subtracted from every non-zero link: ``SCN_LINK_BIAS`` walks a segment made
    by :func:`scn_segment`, whose links still count ``SCENERY.scn``'s leading word.
    """
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
        fields: list[int] = []
        if kind in (SP_POS, SP_1NODE):
            fields = [node + 8]
        elif kind == SP_POSXZ:
            fields = [node + 6]
        elif kind in (SP_2NODE, SP_XPLANE, SP_ZPLANE, SP_HSLOPE, SP_VSLOPE):
            fields = [node + 2, node + 4]
        elif kind == SP_LEAF:
            result.leaves[_word(seg, node + 2)] += 1
        elif kind == SP_GROUND:
            fields = [node + 0x0C, node + 0x0E]
            coarse = node + GROUND_COARSE_LEAF + GLEAF_POLYGON
            if _word(seg, coarse):
                result.polygons.append(_polygon(seg, coarse, "ground-coarse"))
        elif kind == SP_GLEAF:
            fields = [node + 2]
            if _word(seg, node + GLEAF_POLYGON):
                result.polygons.append(_polygon(seg, node + GLEAF_POLYGON, "gleaf"))
        elif kind == SP_LIST:
            cursor = node + 2
            while _word(seg, cursor) != 0:
                fields.append(cursor)
                cursor += 2
        else:
            result.unknown.append((node, kind))
        result.link_fields.update(fields)
        links = [_word(seg, f) for f in fields]
        stack.extend(link - link_bias for link in links if link)
    return result


@dataclass(frozen=True)
class Placement:
    """A shape the tree places: ``SP_LEAF``, or an ``SP_1NODE`` stand-in drawn only when far."""

    obj: int
    x: int
    y: int
    z: int
    stand_in: bool


def placements(seg: bytes, root: int = 0, max_steps: int = PLACEMENT_STEPS) -> set[Placement]:
    """Every shape placement, with the position the ``SP_POS``/``SP_POSXZ`` nodes above it add.

    A subtree gets a copy of the position and the chain after it keeps its own, as in
    FreeFlight's ``simap.cpp``. Shared subtrees are walked once per path, not once per node.
    """
    found: set[Placement] = set()
    stack = [(root, 0, 0, 0)]
    steps = 0
    while stack:
        node, x, y, z = stack.pop()
        first = True
        while node or first:
            first = False
            steps += 1
            if steps > max_steps:
                raise ValueError("placement walk did not end; the tree has a cycle")
            kind = _word(seg, node)
            if kind == SP_POS:
                x += _signed(seg, node + 2)
                y += _signed(seg, node + 4)
                z += _signed(seg, node + 6)
                node = _word(seg, node + 8)
            elif kind == SP_POSXZ:
                x += _signed(seg, node + 2)
                z += _signed(seg, node + 4)
                node = _word(seg, node + 6)
            elif kind == SP_1NODE:
                if obj := _word(seg, node + 2):
                    found.add(Placement(obj, x, y, z, stand_in=True))
                node = _word(seg, node + 8)
            elif kind in (SP_2NODE, SP_XPLANE, SP_ZPLANE, SP_HSLOPE, SP_VSLOPE, SP_GROUND):
                ptr, nxt = (0x0C, 0x0E) if kind == SP_GROUND else (2, 4)
                if child := _word(seg, node + ptr):
                    stack.append((child, x, y, z))
                node = _word(seg, node + nxt)
            elif kind == SP_GLEAF:
                node = _word(seg, node + 2)
            elif kind == SP_LEAF:
                found.add(Placement(_word(seg, node + 2), x, y, z, stand_in=False))
                node = 0
            elif kind == SP_LIST:
                cursor = node + 2
                while child := _word(seg, cursor):
                    stack.append((child, x, y, z))
                    cursor += 2
                node = 0
            else:
                raise ValueError(f"unknown node type {kind} at 0x{node:04X}")
    return found


def _signed(seg: bytes, off: int) -> int:
    """The word at ``off`` as a signed value."""
    word = _word(seg, off)
    return word - 0x10000 if word & 0x8000 else word


def scn_segment(scn: bytes) -> bytes:
    """``SCENERY.scn``'s 32-bit words as a 16-bit tree segment, without the leading ``0`` word.

    The image's tree is the file with 16-bit words; its links are 2 lower because the file's
    leading word is absent (``scenery.md`` section 1), so walk the result with ``SCN_LINK_BIAS``.
    """
    if len(scn) % 4:
        raise ValueError("SCENERY.scn is not a whole number of 32-bit words")
    words = struct.unpack(f"<{len(scn) // 4}i", scn)
    if not words or words[0] != 0:
        raise ValueError("SCENERY.scn does not start with its 0 word")
    if any(not -0x8000 <= w <= 0xFFFF for w in words):
        raise ValueError("SCENERY.scn holds a word that does not fit 16 bits")
    return struct.pack(f"<{len(words) - 1}H", *(w & 0xFFFF for w in words[1:]))


@dataclass(frozen=True)
class SegmentDiff:
    """Word-by-word comparison of a converted ``SCENERY.scn`` with the image's tree."""

    words: int
    link_words: int  # link fields exactly SCN_LINK_BIAS higher in the file
    other: list[int]  # byte offsets of every other differing word, link field or not


def diff_segments(scn_seg: bytes, image_seg: bytes, link_fields: set[int]) -> SegmentDiff:
    """Compare the converted file with the image tree over the file's length.

    Only a word at a byte offset in ``link_fields`` (``TreeWalk.link_fields`` of the image's
    walk) may differ by ``SCN_LINK_BIAS`` as a link; any other difference is reported.
    """
    count = len(scn_seg) // 2
    if len(image_seg) < 2 * count:
        raise ValueError("image tree is shorter than SCENERY.scn")
    ours = struct.unpack_from(f"<{count}H", scn_seg)
    theirs = struct.unpack_from(f"<{count}H", image_seg)
    links = 0
    other = []
    for i, (a, b) in enumerate(zip(ours, theirs, strict=True)):
        if a == b:
            continue
        if 2 * i in link_fields and (a - b) & 0xFFFF == SCN_LINK_BIAS:
            links += 1
        else:
            other.append(2 * i)
    return SegmentDiff(count, links, other)


def image_anchor(image: bytes, index: int) -> tuple[int, int, int] | None:
    """``(x, y, z)`` of anchor ``index`` in the image's own table; ``None`` past its end."""
    if not 0 <= index < IMAGE_ANCHORS:
        return None
    x, y, z = struct.unpack_from("<3h", image, ANCHOR_TABLE_OFFSET + ANCHOR_STRIDE * index)
    return x, y, z


def _vertex_orders(anchors: tuple[int, ...]) -> set[tuple[int, ...]]:
    """Every rotation of ``anchors``, both ways round."""
    out: set[tuple[int, ...]] = set()
    for turn in range(len(anchors)):
        rotated = anchors[turn:] + anchors[:turn]
        out.add(rotated)
        out.add(tuple(reversed(rotated)))
    return out


def polygon_bodies(anchors: tuple[int, ...]) -> dict[str, set[bytes]]:
    """Byte forms a polygon on ``anchors`` takes, in any vertex order.

    ``"pointer"`` is the tree's ``[count][28 * k ...]`` (section 2 of ``world-scene.md``);
    ``"index"`` is ``MAP.BIN``'s ``[count][k ...]``.
    """
    n = len(anchors)
    orders = _vertex_orders(anchors)
    return {
        "pointer": {struct.pack(f"<{n + 1}H", n, *(ANCHOR_STRIDE * a for a in o)) for o in orders},
        "index": {struct.pack(f"<{n + 1}H", n, *o) for o in orders},
    }


def find_all(data: bytes, needle: bytes) -> list[int]:
    """Every offset of ``needle`` in ``data``, overlapping matches included."""
    hits = []
    start = 0
    while (at := data.find(needle, start)) >= 0:
        hits.append(at)
        start = at + 1
    return hits


def tap_anchors(data: bytes) -> Counter[int]:
    """Anchors referenced by anything shaped like ``OP_TAP`` in ``data``, at any byte offset.

    ``OP_TAP`` is ``0x022E, reg_off, count, count * (28 * k)`` with ``count`` 2 or 3
    (``sod-vm.md`` section 2). Matching at every offset over-counts, which is safe for proving
    that an anchor is never tapped.
    """
    found: Counter[int] = Counter()
    for at in find_all(data, struct.pack("<H", OP_TAP)):
        if at + 6 > len(data):
            continue
        count = struct.unpack_from("<H", data, at + 4)[0]
        if count not in (2, 3) or at + 6 + 2 * count > len(data):
            continue
        offsets = struct.unpack_from(f"<{count}H", data, at + 6)
        if all(o % ANCHOR_STRIDE == 0 and o // ANCHOR_STRIDE < ANCHORS for o in offsets):
            found.update(o // ANCHOR_STRIDE for o in offsets)
    return found


def covers(point: tuple[float, float], outline: list[tuple[int, int]]) -> bool:
    """Whether ``point`` lies inside ``outline`` in plan (even-odd rule)."""
    x, z = point
    inside = False
    for (x1, z1), (x2, z2) in zip(outline, outline[1:] + outline[:1], strict=True):
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            inside = not inside
    return inside


def tree_segment(image: bytes) -> bytes:
    """The scene-tree segment of an unpacked load image."""
    if len(image) <= TREE_IMAGE_OFFSET:
        raise ValueError("image is shorter than the scene tree offset")
    return image[TREE_IMAGE_OFFSET:]


def _map_record_count(data: bytes) -> int:
    """Whole records after ``MAP.BIN``'s list head."""
    return max(0, (len(data) - MAP_HEAD) // MAP_RECORD)


def map_links(data: bytes) -> dict[int, tuple[int, int]]:
    """Every record's ``pos`` word and the record its ``a`` (next) link names (``-1`` for none).

    ``a`` is ``-1`` or ``30 * index`` on disk (``map.md`` section 2.2).
    """
    links = {}
    for index in range(_map_record_count(data)):
        pos, a = struct.unpack_from("<Hh", data, MAP_HEAD + MAP_RECORD * index)
        links[index] = (pos, a // MAP_RECORD if a >= 0 else -1)
    return links


def link_chains(links: dict[int, tuple[int, int]]) -> list[list[int]]:
    """The ``a`` chains that start at a record no other record names, in index order."""
    named = {a for _, a in links.values() if a >= 0}
    chains = []
    for head in sorted(set(links) - named):
        chain = [head]
        while (nxt := links[chain[-1]][1]) >= 0 and nxt in links and nxt not in chain:
            chain.append(nxt)
        chains.append(chain)
    return chains


def matched_records(
    polygons: list[GroundPolygon], patches: list[MapPatch]
) -> list[tuple[GroundPolygon, list[int]]]:
    """Each polygon with the records of the same anchor set and colour."""
    by_key: dict[tuple[frozenset[int], int], list[int]] = {}
    for patch in patches:
        by_key.setdefault((frozenset(patch.anchors), patch.colour), []).append(patch.index)
    return [
        (poly, by_key.get((frozenset(poly.anchors), poly.colour & 0xFF), [])) for poly in polygons
    ]


def parse_map_bin(data: bytes) -> list[MapPatch]:
    """Active ``MAP.BIN`` records whose anchors all index the 1,024-entry table."""
    patches = []
    for index in range(_map_record_count(data)):
        r = struct.unpack_from("<7h8H", data, MAP_HEAD + MAP_RECORD * index)
        pos, colour, count = r[0], r[5], max(r[6], 0)
        anchors = tuple(r[7 : 7 + min(count, MAP_SLOTS)])
        if pos & 0xFF and all(a < ANCHORS for a in anchors):
            patches.append(MapPatch(index, colour, anchors))
    return patches


def check_map_bin(data: bytes) -> None:
    """Raise ``ValueError`` unless ``data`` is a list head followed by whole 30-byte records."""
    if len(data) < MAP_HEAD + MAP_RECORD or (len(data) - MAP_HEAD) % MAP_RECORD:
        raise ValueError(
            f"MAP.BIN has {len(data)} bytes, not a 2-byte head and whole 30-byte records"
        )


def compare(polygons: list[GroundPolygon], patches: list[MapPatch]) -> Comparison:
    """Match polygons to patches by anchor set; colours compare on the low byte."""
    by_set: dict[frozenset[int], list[MapPatch]] = {}
    for patch in patches:
        by_set.setdefault(frozenset(patch.anchors), []).append(patch)
    matched: set[int] = set()
    same = 0
    # Each record matches at most one polygon. Same-colour pairs are taken first, so a
    # recoloured fallback cannot use up the record another polygon matches exactly.
    leftover: list[GroundPolygon] = []
    for poly in polygons:
        candidates = by_set.get(frozenset(poly.anchors), [])
        exact = next((p for p in candidates if p.colour == poly.colour & 0xFF), None)
        if exact is None:
            leftover.append(poly)
            continue
        candidates.remove(exact)
        matched.add(exact.index)
        same += 1
    recoloured: list[tuple[GroundPolygon, MapPatch]] = []
    tree_only: list[GroundPolygon] = []
    for poly in leftover:
        candidates = by_set.get(frozenset(poly.anchors), [])
        if not candidates:
            tree_only.append(poly)
            continue
        patch = candidates.pop(0)
        matched.add(patch.index)
        recoloured.append((poly, patch))
    map_only = [p for p in patches if p.index not in matched]
    return Comparison(same, recoloured, tree_only, map_only)
