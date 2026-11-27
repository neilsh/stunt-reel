"""One-off census of misaligned objects over the readout frames (#1110 plan, "The census's criterion").

Run: mise exec -- uv run python -I work/2026-11/1110_object-misaligned/census.py OUT.json
Reads the render in build/parity/ours and the captures in the data root; the control pass swaps the
CTRY recapture's index plane in for the render's, keeping the render's layer plane.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

from stunt_reel.bench.mismatch import _match, object_shift, readout_mask, shift_gain
from stunt_reel.bench.planes import RenderTree, load_capture
from stunt_reel.parity_artifacts import LAYER_FIRST_ACTOR, LAYER_PROP

FILMS = ["ctry", "intro", "land", "balloon", "traintnl", "bomb", "location"]
MIN_PIXELS, REACH, GAIN, TERRAIN_GAIN, TIMING_SLACK = 64, 24, 0.25, 0.10, 0.05
#: A prop has no id across ticks, so the timing test scores the prop layer inside the object's own
#: bounding box grown by this many pixels, at the render ticks t-2, t-1, t+1 and t+2 (not t itself).
BOX = 3
LAYER_TERRAIN = 2
ROOT = Path("build/parity")
DATA = Path(os.environ["STUNT_DATA_ROOT"])


def components(plane: np.ndarray) -> list[np.ndarray]:
    """8-connected components of a boolean plane."""
    seen = np.zeros_like(plane)
    out = []
    h, w = plane.shape
    for y, x in zip(*np.nonzero(plane), strict=True):
        if seen[y, x]:
            continue
        comp = np.zeros_like(plane)
        stack = [(y, x)]
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            comp[cy, cx] = True
            for ny in range(max(cy - 1, 0), min(cy + 2, h)):
                for nx in range(max(cx - 1, 0), min(cx + 2, w)):
                    if plane[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        out.append(comp)
    return out


def objects(layer: np.ndarray) -> list[tuple[str, np.ndarray]]:
    found = [(f"actor{int(v) - LAYER_FIRST_ACTOR}", layer == v) for v in np.unique(layer) if v >= LAYER_FIRST_ACTOR]
    found += [(f"prop{i}", c) for i, c in enumerate(components(layer == LAYER_PROP))]
    return found


def m0(cap_idx, ren_idx, pixels, mask) -> float:
    ys, xs = np.nonzero(pixels & ~mask)
    return _match(cap_idx, ren_idx, ys, xs, mask, 0, 0)[0] if len(ys) else 0.0


def census(film: str, control: bool) -> list[dict]:
    run = json.loads((ROOT / f"bench/{film}/errors/run.json").read_text())
    caps = load_capture(DATA / f"captures/vault-{film}/frames")
    tree = RenderTree(ROOT / f"ours/{film}_current")
    ticks_available = set(tree.ticks())
    swap = load_capture(DATA / "bench/vault-ctry/recapture") if control else None
    rows = []
    for tick in run["ticks"]:
        rt = run["render_ticks"].get(str(tick), tick)
        cap = caps[tick].idx
        ren = tree.load(rt)
        ren_idx = ren.idx
        if control:
            if tick not in swap:
                continue
            cap, ren_idx = cap, swap[tick].idx
        mask = readout_mask(cap, credits_drawn=bool(ren.credits))
        for name, px in objects(ren.layer):
            if int((px & ~mask).sum()) < MIN_PIXELS:
                continue
            dx, dy, gain = object_shift(cap, ren_idx, px, mask, REACH)
            if gain < GAIN:
                continue
            terr = shift_gain(cap, ren_idx, ren.layer == LAYER_TERRAIN, mask, dx, dy)
            if terr >= TERRAIN_GAIN:
                continue
            best_shift = m0(cap, ren_idx, px, mask) + gain
            ys, xs = np.nonzero(px)
            box = np.zeros_like(px)
            box[max(ys.min() - BOX, 0) : ys.max() + BOX + 1, max(xs.min() - BOX, 0) : xs.max() + BOX + 1] = True
            by_tick = {}
            for t2 in range(rt - 2, rt + 3):
                if t2 == rt or t2 not in ticks_available:
                    continue
                r2 = tree.load(t2)
                p2 = (r2.layer == (LAYER_FIRST_ACTOR + int(name[5:]) if name.startswith("actor") else LAYER_PROP)) & (
                    box if name.startswith("prop") else True
                )
                by_tick[t2 - rt] = m0(cap, r2.idx if not control else ren_idx, p2, mask)
            best_t = max(by_tick.items(), key=lambda kv: kv[1])
            rows.append(
                {
                    "film": film, "tick": tick, "object": name, "pixels": int((px & ~mask).sum()),
                    "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], "shift": [dx, dy], "gain": round(gain, 3), "terrain_gain": round(terr, 3),
                    "time_explained": best_t[1] >= best_shift - TIMING_SLACK,
                    "best_tick_offset": best_t[0], "best_tick_m0": round(best_t[1], 3),
                    "best_shift_m": round(best_shift, 3),
                }
            )
    return rows


def main() -> None:
    out = {"real": [r for f in FILMS for r in census(f, False)], "control": census("ctry", True)}
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
    for kind in ("real", "control"):
        print(kind, len(out[kind]))
        for r in out[kind]:
            print(" ", r)


main()
