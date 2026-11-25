"""What the windows one prop shape fills alone hold: index disagreement against the capture.

For each scored tick in the ranges, takes the windows whose 121 pixels are all the shape's
props pixels (`window_split.py`'s `pure`), counts the pixels in each where our index differs
from the capture's (both rows scaled to 240 as the scorer does, row = floor(r * 5 / 6)), and
sums the shape's loss by that count. Also tallies the (capture, ours) index pairs of the
shape's disagreeing pixels at 320x200.

usage: pure_windows.py <capture frames> <render store> <dump dir> <report.json> <shape id> <lo-hi>[,...]
"""

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from stunt_reel.matched_frames import pair
from stunt_reel.parity_artifacts import RenderStore

from window_split import PROPS, WIN, load

H0, W = 200, 320
ROWS = (np.arange(240) * 5) // 6


def main() -> None:
    cap, store_dir, dump, report = map(Path, sys.argv[1:5])
    shape = int(sys.argv[5])
    ranges = [tuple(map(int, r.split("-"))) for r in sys.argv[6].split(",")]
    word = shape + 1
    rep = json.loads(report.read_text(encoding="utf-8"))
    scored = {f["film_tick"] for f in rep["per_frame"] if f["scored"]}
    store = RenderStore(store_dir)
    buckets: Counter = Counter()
    wins: Counter = Counter()
    pairs: Counter = Counter()
    own_px = bad_px = 0
    for m in pair(cap, store).matched:
        t = m.film_tick
        if t not in scored or not any(lo <= t <= hi for lo, hi in ranges):
            continue
        win, classes, shapes = load(dump / f"{t}.win")
        c0 = np.frombuffer(m.capture_indices(), np.uint8).reshape(H0, W)
        o0 = np.frombuffer(store.frame(t).indices, np.uint8).reshape(H0, W)
        bad = (c0 != o0)[ROWS]
        own = (classes == PROPS) & (shapes == word)
        for x, y, s in win:
            if own[y:y + WIN, x:x + WIN].all():
                n = int(bad[y:y + WIN, x:x + WIN].sum())
                key = "0" if n == 0 else "1-5" if n <= 5 else "6-20" if n <= 20 else ">20"
                buckets[key] += (1.0 - float(s)) / len(win)
                wins[key] += 1
        own0 = own[np.searchsorted(ROWS, np.arange(H0))]
        sel = own0 & (c0 != o0)
        own_px += int(own0.sum())
        bad_px += int(sel.sum())
        pairs.update(zip(c0[sel].tolist(), o0[sel].tolist()))
    total = sum(buckets.values())
    print(f"pure-window loss {total:.4f} by disagreeing pixels in the window:")
    for k in ("0", "1-5", "6-20", ">20"):
        print(f"  {k:>4}: {wins[k]} windows, loss {buckets[k]:.4f} ({buckets[k] / total:.1%})")
    print(f"shape pixels {own_px}, disagreeing {bad_px} ({bad_px / own_px:.2%})")
    print("top (capture, ours) index pairs:", pairs.most_common(12))


if __name__ == "__main__":
    main()
