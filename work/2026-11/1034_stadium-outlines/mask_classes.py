"""Index disagreement of one shape's pixel classes, and band/interior masks."""
import sys
from pathlib import Path
import numpy as np
from stunt_reel.parity_artifacts import RenderStore
from stunt_reel.matched_frames import pair

cap, base, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
H, W = 200, 320
store = RenderStore(base)
rd = lambda n, t: np.frombuffer((out / n / f"{t}.mask").read_bytes(), np.uint8).reshape(H, W).astype(bool)
for n in ("band", "interior"): (out / n).mkdir(exist_ok=True)
print("tick class px disagree frac")
tot = {}
for m in pair(cap, store).matched:
    t = m.film_tick
    c = np.frombuffer(m.capture_indices(), np.uint8).reshape(H, W)
    o = np.frombuffer(store.frame(t).indices, np.uint8).reshape(H, W)
    own, z, ol, d = rd("all", t), rd("zline", t), rd("outline", t), rd("lines_d1", t)
    band = d & ~(z | ol); interior = own & ~d
    (out / "band" / f"{t}.mask").write_bytes(band.astype(np.uint8).tobytes())
    (out / "interior" / f"{t}.mask").write_bytes(interior.astype(np.uint8).tobytes())
    for name, s in (("all", own), ("zline", z), ("outline", ol), ("band", band), ("interior", interior)):
        px, bad = int(s.sum()), int((s & (c != o)).sum())
        a = tot.setdefault(name, [0, 0]); a[0] += px; a[1] += bad
        if t == 2729: print(t, name, px, bad, f"{bad/max(px,1):.3f}")
for name, (px, bad) in tot.items(): print("ALL27", name, px, bad, f"{bad/px:.3f}")
