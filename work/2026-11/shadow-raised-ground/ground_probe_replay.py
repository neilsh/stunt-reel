"""Replay PLAYONE's ground probe walk offline (#512 raised-ground journal entry).

Reads the unpacked load image (``mise run unlzexe``) and, for ``census``, a corpus root, both
from the data root at run time; prints counts and offsets only. Three reports:

* ``cubes``: the ``SP_1NODE`` cube nodes the probe ``0x240A`` reaches through ``DS:0x584`` and
  how many of them lie above a ground leaf (``SP_GLEAF``).
* ``points X,Y,Z ...``: the leaf plane address the probe stores at slot ``+0x1E`` for each
  integer slot position (empty for the null plane), at the given ``y`` and at ``y = 0``.
* ``census``: over every distinct corpus ``.FLM``, the shadowed drawn slots more than 20 m up
  (stream ``y`` below -20): the distinct integer positions, how many get a different plane at
  their ``y`` than at ``y = 0``, and the films with such a slot more than 20 m above a non-level
  leaf whose polygon contains it (with a sibling ``.ALL`` or not).

The replay follows the handlers listed in ``memory-map.md`` row ``0x0584`` with the probe
sphere's radius ``0x2302`` taken as 0 and the slot's position for the sphere's centre.

Usage, from the repository root:
``mise exec -- uv run python work/2026-11/shadow-raised-ground/ground_probe_replay.py
<data root> cubes|census|points X,Y,Z ...``
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "python"))

from stunt_reel import scene_tree as st
from stunt_reel.flm_walk import SLICE_HEADER_SIZE, FlmWalkError, walk_film

SHADOWED = 0x07  # SIF_EXISTS | SIF_DRAW | SIF_SHADOW
HIGH = -20.0


class Tree:
    """The image's scene tree with the probe's walk over it."""

    def __init__(self, image: bytes) -> None:
        self.image = image
        self.seg = st.tree_segment(image)

    def word(self, off: int) -> int:
        return int(struct.unpack_from("<H", self.seg, off)[0])

    def short(self, off: int) -> int:
        return int(struct.unpack_from("<h", self.seg, off)[0])

    def anchor(self, pointer: int) -> tuple[int, int, int]:
        xyz = st.image_anchor(self.image, pointer // st.ANCHOR_STRIDE)
        if xyz is None:
            raise ValueError(f"anchor pointer {pointer:#x} past the image's table")
        return xyz

    def plane(self, leaf: int) -> tuple[int, int, int, int]:
        a, b, c = struct.unpack_from("<3h", self.seg, leaf + 4)
        return a, b, c, int(struct.unpack_from("<i", self.seg, leaf + 0xA)[0])

    def outline(self, leaf: int) -> list[tuple[int, int]]:
        n = self.word(leaf + 0x10)
        pts = [self.anchor(self.word(leaf + 0x12 + 2 * i)) for i in range(n)]
        return [(p[0], p[2]) for p in pts]

    def crossings(self, leaf: int, sx: int, sz: int) -> int:
        """The crossing count of ``0x2631..0x26AF`` for the slot's integer x and z."""
        n = self.word(leaf + 0x10)
        ptrs = [self.word(leaf + 0x12 + 2 * i) for i in range(n)]
        count = 0
        prev = self.anchor(ptrs[-1]) if ptrs else (0, 0, 0)
        for ptr in ptrs:
            cur = self.anchor(ptr)
            if (sz >= prev[2]) != (sz >= cur[2]):
                right_a, right_b = sx >= prev[0], sx >= cur[0]
                if right_a and right_b:
                    count += 1
                elif right_a or right_b:
                    num, den = (cur[0] - prev[0]) * (sz - prev[2]), cur[2] - prev[2]
                    q = abs(num) // abs(den)
                    q = q if (num < 0) == (den < 0) else -q
                    if q + prev[0] < sx:
                        count += 1
            prev = cur
        return count

    def probe(self, sx: int, sy: int, sz: int) -> list[int]:
        """Every leaf plane address the walk stores at ``+0x1E``, in order (the last one wins)."""
        found: list[int] = []

        def go(node: int, local: tuple[int, int, int], root: bool = False) -> None:
            while node or root:
                root = False
                kind = self.word(node)
                if kind == st.SP_POS:
                    d = (self.short(node + 2), self.short(node + 4), self.short(node + 6))
                    local = (local[0] + d[0], local[1] + d[1], local[2] + d[2])
                    node = self.word(node + 8)
                elif kind == st.SP_POSXZ:
                    local = (local[0] + self.short(node + 2), local[1], local[2] + self.short(node + 4))
                    node = self.word(node + 6)
                elif kind == st.SP_1NODE:
                    half = self.short(node + 4)
                    if not all(-half <= v <= half for v in local):
                        return
                    node = self.word(node + 8)
                elif kind == st.SP_2NODE:
                    go(self.word(node + 2), local)
                    node = self.word(node + 4)
                elif kind in (st.SP_XPLANE, st.SP_ZPLANE):
                    s = (local[0] if kind == st.SP_XPLANE else local[2]) + self.short(node + 6)
                    if s > 0:
                        node = self.word(node + 4)
                    elif s < 0:
                        node = self.word(node + 2)
                    else:
                        go(self.word(node + 2), local)
                        node = self.word(node + 4)
                elif kind in (st.SP_HSLOPE, st.SP_VSLOPE):
                    a, b = (sx, sz) if kind == st.SP_HSLOPE else (sz, sx)
                    line = ((a * self.short(node + 6) * 2) >> 16) + self.short(node + 8)
                    node = self.word(node + 2) if line >= b else self.word(node + 4)
                elif kind == st.SP_GROUND:
                    half = self.short(node + 4)
                    if (
                        -half <= self.short(node + 6) - sx <= half
                        and -half <= self.short(node + 0xA) - sz <= half
                    ):
                        go(self.word(node + 0xC), local)
                    node = self.word(node + 0xE)
                elif kind == st.SP_GLEAF:
                    if self.crossings(node, sx, sz) & 1:
                        found.append(node + 4)
                    node = self.word(node + 2)
                else:  # SP_LEAF (objects: boxes only) and SP_LIST (0x2579 is a bare ret)
                    return

        go(0, (-sx, -sy, -sz), root=True)
        return found

    def cube_report(self) -> tuple[int, int, int]:
        """(cube nodes reached, ground leaves reached, cubes with a ground leaf below)."""
        cubes: set[int] = set()
        leaves: set[int] = set()
        above: set[int] = set()
        seen: set[tuple[int, tuple[int, ...]]] = set()
        stack: list[tuple[int, tuple[int, ...], bool]] = [(0, (), True)]
        while stack:
            node, under, root = stack.pop()
            while node or root:
                root = False
                if (node, under) in seen:
                    break
                seen.add((node, under))
                kind = self.word(node)
                if kind == st.SP_POS:
                    node = self.word(node + 8)
                elif kind == st.SP_POSXZ:
                    node = self.word(node + 6)
                elif kind == st.SP_1NODE:
                    cubes.add(node)
                    under = (*under, node)
                    node = self.word(node + 8)
                elif kind in (st.SP_2NODE, st.SP_XPLANE, st.SP_ZPLANE, st.SP_HSLOPE, st.SP_VSLOPE):
                    stack.append((self.word(node + 2), under, False))
                    node = self.word(node + 4)
                elif kind == st.SP_GROUND:
                    stack.append((self.word(node + 0xC), under, False))
                    node = self.word(node + 0xE)
                elif kind == st.SP_GLEAF:
                    if self.word(node + 0x0E):
                        leaves.add(node)
                        above.update(under)
                    node = self.word(node + 2)
                else:
                    break
        return len(cubes), len(leaves), len(above)


def shadowed_positions(data: bytes) -> list[tuple[int, int, float, float, float]]:
    """``(tick, slot, x, y, z)`` at each slice end for every shadowed drawn slot (stream metres)."""
    tick = 0
    flags: dict[int, int] = {}
    pos: dict[int, tuple[int, int, int]] = {}
    out: list[tuple[int, int, float, float, float]] = []
    for view in walk_film(data):
        p = view.start + SLICE_HEADER_SIZE
        moves, rotates, animates = view.moves, view.rotates, view.animates
        while p < view.end:
            tag = data[p]
            p += 1
            if tag == 0xFF:
                break
            group, slot = tag >> 6, tag & 0x3F
            bit = 1 << slot
            if group == 0:
                f = data[p]
                p += 1
                flags[slot] = f
                moves = moves | bit if f & 0x08 else moves & ~bit
                rotates = rotates | bit if f & 0x10 else rotates & ~bit
                animates = animates | bit if f & 0x20 else animates & ~bit
                if f & 0x01:
                    p += 2 if f & 0x02 else 0
                    if not f & 0x08:
                        pos[slot] = struct.unpack_from("<iii", data, p)
                        p += 12
                    p += 0 if f & 0x10 else 6
            elif group == 1:
                if moves & bit:
                    pos[slot] = struct.unpack_from("<iii", data, p)
                    p += 12
                p += 6 if rotates & bit else 0
                p += 2 if animates & bit else 0
            elif tag < 0x90 or tag >= 0xA0:
                p += 2
            elif tag == 0x99:
                p = data.index(b"\0", data.index(b"\0", p) + 1) + 1
            elif tag == 0x9B:
                p += 1
            elif tag == 0x9C:
                p += 3
        for slot, f in flags.items():
            if f & SHADOWED == SHADOWED and slot in pos:
                x, y, z = (v / 65536 for v in pos[slot])
                out.append((tick, slot, x, y, z))
        tick += data[view.start + 2]
    return out


def census(tree: Tree, corpus: Path) -> None:
    """Print the y-sensitivity count and the raised-ground candidate films."""
    raised = []
    for p in tree_leaves(tree):
        a, _, c, d = tree.plane(p)
        if a or c or d:
            raised.append((p, tree.plane(p), tree.outline(p)))
    seen: set[str] = set()
    positions: dict[tuple[int, int, int], bool] = {}
    films = 0
    candidates: list[tuple[int, str, bool, tuple[int, int, float]]] = []
    for path in sorted(corpus.rglob("*")):
        if path.suffix.upper() != ".FLM":
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        try:
            rows = shadowed_positions(data)
        except (FlmWalkError, IndexError, ValueError, struct.error):
            continue
        high = [r for r in rows if r[3] < HIGH]
        films += bool(high)
        over: list[tuple[int, int, float]] = []
        for tick, slot, x, y, z in high:
            key = (int(x // 1), int(y // 1), int(z // 1))
            if key not in positions:
                positions[key] = tree.probe(*key) != tree.probe(key[0], 0, key[2])
            for _leaf, (a, b, c, d), outline in raised:
                if st.covers((x, z), outline) and (d - a * x - c * z) / b - y > -HIGH:
                    over.append((tick, slot, round(y, 1)))
        if over:
            has_all = any(
                q.stem.upper() == path.stem.upper() and q.suffix.upper() == ".ALL"
                for q in path.parent.iterdir()
            )
            candidates.append((len(over), path.relative_to(corpus).as_posix(), has_all, over[0]))
    differ = sum(positions.values())
    print(f"distinct films {len(seen)}, with a shadowed slot above 20 m {films}")
    print(f"distinct integer positions {len(positions)}, plane differs from y = 0 at {differ}")
    print(
        f"films with such a slot over a non-level leaf {len(candidates)}, "
        f"with a sibling .ALL {sum(c[2] for c in candidates)}"
    )
    for count, name, has_all, first in sorted(candidates, reverse=True):
        print(f"  {count:5d} {'ALL' if has_all else '-  '} {name} first (tick, slot, y) {first}")


def tree_leaves(tree: Tree) -> list[int]:
    """Every ``SP_GLEAF`` with a polygon that the draw walk reaches."""
    return [
        p.offset - st.GLEAF_POLYGON for p in st.walk(tree.seg).polygons if p.kind == "gleaf"
    ]


def main(argv: list[str]) -> int:
    """Run the report named in ``argv[1]`` against the data root ``argv[0]``."""
    root = Path(argv[0])
    tree = Tree((root / "build/re/playone.img").read_bytes())
    if argv[1] == "cubes":
        cubes, leaves, above = tree.cube_report()
        print(f"cube nodes reached {cubes}, ground leaves reached {leaves}, cubes above a leaf {above}")
    elif argv[1] == "points":
        for arg in argv[2:]:
            x, y, z = (int(float(v) // 1) for v in arg.split(","))
            at_y = [hex(v) for v in tree.probe(x, y, z)]
            at_0 = [hex(v) for v in tree.probe(x, 0, z)]
            print(f"{arg}: at y {at_y}, at y = 0 {at_0}")
    elif argv[1] == "census":
        census(tree, root / "corpus")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
