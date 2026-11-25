import sys
from pathlib import Path
import numpy as np
from PIL import Image
from stunt_reel.parity_artifacts import RenderStore
from stunt_reel.matched_frames import pair
cap, base, proto, masks, out = map(Path, sys.argv[1:6])
tick, (x0, y0, x1, y1), k = 2729, (16, 48, 296, 142), 2
H, W = 200, 320
bs, ps = RenderStore(base), RenderStore(proto)
m = next(f for f in pair(cap, bs).matched if f.film_tick == tick)
c = np.frombuffer(m.capture_indices(), np.uint8).reshape(H, W)
def rgb(ix, pal):
    p = np.array(pal, np.uint8).reshape(256, 3); return p[ix]
cpal = m.capture_palette()
o = np.frombuffer(bs.frame(tick).indices, np.uint8).reshape(H, W)
q = np.frombuffer(ps.frame(tick).indices, np.uint8).reshape(H, W)
opal = np.frombuffer(bs.frame(tick).palette, np.uint8).reshape(256, 3)
qpal = np.frombuffer(ps.frame(tick).palette, np.uint8).reshape(256, 3)
rd = lambda n: np.frombuffer((masks / n / f"{tick}.mask").read_bytes(), np.uint8).reshape(H, W).astype(bool)
own, z, ol, band, interior = rd("all"), rd("zline"), rd("outline"), rd("band"), rd("interior")
bad = c != o
cls = np.full((H, W, 3), 40, np.uint8)
cls[own] = (90, 90, 90)
for msk, col in ((interior, (60, 120, 255)), (band, (255, 150, 0)), (ol, (255, 255, 0)), (z, (255, 40, 40))):
    cls[own & msk & bad] = col
panels = [rgb(c, cpal), opal[o], qpal[q], cls]
crops = [p[y0:y1, x0:x1] for p in panels]
vs = np.full((y1 - y0, 2, 3), (255, 0, 255), np.uint8)
top = np.concatenate([crops[0], vs, crops[1]], 1); bot = np.concatenate([crops[2], vs, crops[3]], 1)
hs = np.full((2, top.shape[1], 3), (255, 0, 255), np.uint8)
grid = np.concatenate([top, hs, bot], 0)
img = Image.fromarray(grid).resize((grid.shape[1] * k, grid.shape[0] * k), Image.NEAREST)
img.save(out); print(out, img.size)
