"""Best page shift per row band: a uniform camera offset moves every band alike."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path("python/scripts").resolve()))
import parity_probe as pp  # noqa: E402
from stunt_reel.matched_frames import Reference  # noqa: E402
from stunt_reel.parity_artifacts import RenderStore, read_page  # noqa: E402

ours, ref, ticks, bands = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
layer_arg = sys.argv[5] if len(sys.argv) > 5 else "backdrop"
edges = [int(b) for b in bands.split(",")]
store = RenderStore(Path(ours))
g = store.record.geometry
W, R = g.width, g.plane_rows()
reference = Reference(Path(ref), store)
by_tick = {f.film_tick: f for f in reference.capture.frames}
REACH = 5
for tick in pp.parse_ticks(ticks):
    if tick not in by_tick:
        continue
    page = read_page(store, tick)
    kept = {"backdrop": pp.BACKDROP_LAYERS, "props": pp.BACKDROP_LAYERS + (pp.LAYER_PROP,)}.get(layer_arg)
    if layer_arg.startswith("raw"):
        plane = np.asarray(page.layers[: W * R], dtype=np.uint16).reshape(R, W)
        keep = np.isin(plane, [int(x) for x in layer_arg[3:].split("+")]) & pp.edge_band(page.indices, W, R)
    else:
        keep = pp.backdrop_mask(page.layers, W, R, 8, kept) & pp.edge_band(page.indices, W, R)
    cap = reference.matched_frame(by_tick[tick], tick).capture_indices()
    cells = []
    for lo, hi in zip(edges, edges[1:]):
        band = np.zeros_like(keep)
        band[lo:hi, :] = True
        k = keep & band
        n = int(k.sum())
        if n < 150:
            cells.append(f"[{lo}-{hi}) n={n:4d}       -      ")
            continue
        grid = {
            (dx, dy): pp.backdrop_agreement(page.indices, k, cap, W, R, dx, dy)
            for dx in range(-REACH, REACH + 1)
            for dy in range(-REACH, REACH + 1)
        }
        (dx, dy), a = max(grid.items(), key=lambda c: (c[1], -abs(c[0][0]) - abs(c[0][1])))
        cells.append(f"[{lo}-{hi}) n={n:4d} {dx:+d},{dy:+d} {a - grid[0, 0]:+.3f}")
    print(tick, " | ".join(cells))
