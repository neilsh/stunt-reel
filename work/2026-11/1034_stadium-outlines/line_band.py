import sys
from collections import Counter
from pathlib import Path
import numpy as np
from stunt_reel.parity_artifacts import RenderStore
from stunt_reel.matched_frames import pair
cap, base, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
H, W = 200, 320
store = RenderStore(base)
rd = lambda n, t: np.frombuffer((out / n / f"{t}.mask").read_bytes(), np.uint8).reshape(H, W).astype(bool)
def dil(a):
    d = a.copy(); d[1:] |= a[:-1]; d[:-1] |= a[1:]; d[:, 1:] |= a[:, :-1]; d[:, :-1] |= a[:, 1:]; return d
for n in ("band_z", "band_o"): (out / n).mkdir(exist_ok=True)
agg = Counter()
for m in pair(cap, store).matched:
    t = m.film_tick
    c = np.frombuffer(m.capture_indices(), np.uint8).reshape(H, W)
    o = np.frombuffer(store.frame(t).indices, np.uint8).reshape(H, W)
    own, z, ol = rd("all", t), rd("zline", t), rd("outline", t)
    lines = z | ol
    bz = dil(z) & own & ~lines
    bo = dil(ol) & own & ~lines & ~bz
    (out / "band_z" / f"{t}.mask").write_bytes(bz.astype(np.uint8).tobytes())
    (out / "band_o" / f"{t}.mask").write_bytes(bo.astype(np.uint8).tobytes())
    zcols = Counter(o[z].tolist())
    agg["z_px"] += int(z.sum()); agg["z_bad"] += int((z & (c != o)).sum())
    agg["bz_px"] += int(bz.sum()); agg["bz_bad"] += int((bz & (c != o)).sum())
    agg["bo_px"] += int(bo.sum()); agg["bo_bad"] += int((bo & (c != o)).sum())
    # beside-line pixels where the capture shows a colour our lines draw
    linecols = set(zcols)
    agg["bz_cap_linecol"] += int((bz & (c != o) & np.isin(c, list(linecols))).sum())
    # our line pixels where the capture shows the line colour one pixel away
    near = np.zeros_like(z)
    for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
        sh = np.roll(np.roll(c, dy, 0), dx, 1)
        near |= (sh == o)
    agg["z_bad_linecol_adjacent"] += int((z & (c != o) & near).sum())
    if t == 2729:
        print("2729 line colours", zcols.most_common(5), "z", int(z.sum()), int((z&(c!=o)).sum()), "bz", int(bz.sum()), int((bz&(c!=o)).sum()), "bz cap linecol", int((bz & (c != o) & np.isin(c, list(linecols))).sum()), "bo", int(bo.sum()), int((bo&(c!=o)).sum()))
        print("2729 capture at our disagreeing line px", Counter(c[z & (c != o)].tolist()).most_common(6))
print(dict(agg))
