"""For our line/outline pixels the capture disagrees on: where the capture shows our colour one pixel away, is that pixel toward the projection centre or away?"""
import sys
from collections import Counter
from pathlib import Path
import numpy as np
from stunt_reel.parity_artifacts import RenderStore
from stunt_reel.matched_frames import pair
cap, base, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
H, W = 200, 320
CX, CY = 160.0, float(sys.argv[4])
store = RenderStore(base)
rd = lambda n, t: np.frombuffer((out / n / f"{t}.mask").read_bytes(), np.uint8).reshape(H, W).astype(bool)
yy, xx = np.mgrid[0:H, 0:W]
res = {k: Counter() for k in ("zline", "outline")}
for m in pair(cap, store).matched:
    t = m.film_tick
    c = np.frombuffer(m.capture_indices(), np.uint8).reshape(H, W)
    o = np.frombuffer(store.frame(t).indices, np.uint8).reshape(H, W)
    for k in res:
        s = rd(k, t) & (c != o)
        s[0, :] = s[-1, :] = False; s[:, 0] = s[:, -1] = False
        for dy, dx, axis in ((0, 1, "x"), (0, -1, "x"), (1, 0, "y"), (-1, 0, "y")):
            nb = np.zeros_like(c); nb[1:-1, 1:-1] = c[1 + dy:H - 1 + dy, 1 + dx:W - 1 + dx]
            hit = s & (nb == o)
            toc = (CX - xx) * dx + (CY - yy) * dy  # >0: neighbour lies toward the centre
            side = (yy < CY) if axis == "y" else (xx < CX)
            for half, sm in (("lo", side), ("hi", ~side)):
                res[k][(axis, half, "toward")] += int((hit & sm & (toc > 0.5)).sum())
                res[k][(axis, half, "away")] += int((hit & sm & (toc < -0.5)).sum())
        res[k]["bad"] += int(s.sum())
for k, v in res.items(): print(k, dict(v))
