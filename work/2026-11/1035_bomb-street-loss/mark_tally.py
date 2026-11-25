"""What drew one shape's pixels of one index, from a `DBG_LINEMARK=0,1` pair of frame-tool stores.

`DBG_LINEMARK=1` (#1034's switches/DBG_LINEMARK.diff) sets bit 0x2000 of a pixel's shape word
for a ZLINETO line, 0x4000 for an outline quad and 0x8000 for the world's outline line list.
Tallies, over every tick of the pair, the shape's pixels by tag: those we draw in <index>, and
the disagreeing ones where (capture, ours) is (<index>, <fill>) or (<fill>, <index>).
Also checks that the marked render's index plane equals the unmarked one's.

usage: mark_tally.py <capture frames> <DBG_LINEMARK=0 store> <DBG_LINEMARK=1 store> <shape id> <index>,<fill>
"""

import sys
from collections import Counter
from pathlib import Path

import numpy as np
from stunt_reel.matched_frames import pair
from stunt_reel.parity_artifacts import RenderStore

from street_masks import H, W, shapes_plane


def tag(m: np.ndarray) -> np.ndarray:
    out = np.full(m.shape, "fill", dtype=object)
    out[(m & 0xC000) != 0] = "outline"
    out[(m & 0x2000) != 0] = "zline"
    return out


def main() -> None:
    cap, base_dir, mark_dir = map(Path, sys.argv[1:4])
    word = int(sys.argv[4]) + 1
    index, fill = map(int, sys.argv[5].split(","))
    base, mark = RenderStore(base_dir), RenderStore(mark_dir)
    bshape, mshape = shapes_plane(base_dir), shapes_plane(mark_dir)
    tallies = {k: Counter() for k in ("ours_index", "cap_index_ours_fill", "cap_fill_ours_index")}
    same = True
    for m in pair(cap, base).matched:
        t = m.film_tick
        c = np.frombuffer(m.capture_indices(), np.uint8).reshape(H, W)
        o = np.frombuffer(base.frame(t).indices, np.uint8).reshape(H, W)
        same &= bool((o == np.frombuffer(mark.frame(t).indices, np.uint8).reshape(H, W)).all())
        same &= bool(((mshape[t] & 0x1FFF) == bshape[t]).all())
        own = bshape[t] == word
        tags = tag(mshape[t])
        sel = {
            "ours_index": own & (o == index),
            "cap_index_ours_fill": own & (c == index) & (o == fill),
            "cap_fill_ours_index": own & (c == fill) & (o == index),
        }
        for k, s in sel.items():
            tallies[k].update(tags[s].tolist())
    print("marked render equals unmarked:", same)
    for k, v in tallies.items():
        print(k, dict(v))


if __name__ == "__main__":
    main()
