"""Capture-side oracle masks of one prop shape for `DBG_ORACLE_DIR` (switches/), at 320x200.

Writes `<out>/<mask>/<tick>.mask` (one byte a pixel, nonzero where the scorer copies our index
into the capture) for every matched tick in the ranges:

- `all`: the shape's pixels;
- `others`: every pixel not the shape's;
- `swap`: the shape's pixels where (capture, ours) is (a, b) or (b, a) for the given pair;
- `rest`: the shape's disagreeing pixels outside `swap`.

usage: street_masks.py <capture frames> <render store> <out dir> <shape id> <a>,<b> <lo-hi>[,...]
"""

import json
import sys
from pathlib import Path

import numpy as np
from compression import zstd
from stunt_reel.matched_frames import pair
from stunt_reel.parity_artifacts import RenderStore

H, W = 200, 320


def shapes_plane(d: Path) -> dict[int, np.ndarray]:
    rec = json.loads((d / "render.json").read_text(encoding="utf-8"))
    data = (d / "shapes.zst").read_bytes()
    planes, ticks, i = {}, rec["ticks"], 0
    for chunk, span in zip(rec["chunks"], rec["planes"]["shapes.zst"]["chunks"]):
        raw = zstd.decompress(data[span["offset"]:span["offset"] + span["length"]])
        arr = np.frombuffer(raw, "<u2").reshape(chunk["ticks"], H, W)
        for k in range(chunk["ticks"]):
            planes[ticks[i]["tick"]] = arr[k]
            i += 1
    return planes


def main() -> None:
    cap, store_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    word = int(sys.argv[4]) + 1
    a, b = map(int, sys.argv[5].split(","))
    ranges = [tuple(map(int, r.split("-"))) for r in sys.argv[6].split(",")]
    store = RenderStore(store_dir)
    planes = shapes_plane(store_dir)
    names = ("all", "others", "swap", "rest")
    for n in names:
        (out / n).mkdir(parents=True, exist_ok=True)
    totals = dict.fromkeys(names, 0)
    for m in pair(cap, store).matched:
        t = m.film_tick
        if not any(lo <= t <= hi for lo, hi in ranges):
            continue
        c = np.frombuffer(m.capture_indices(), np.uint8).reshape(H, W)
        o = np.frombuffer(store.frame(t).indices, np.uint8).reshape(H, W)
        own = planes[t] == word
        swap = own & (((c == a) & (o == b)) | ((c == b) & (o == a)))
        masks = {"all": own, "others": ~own, "swap": swap, "rest": own & (c != o) & ~swap}
        for n, s in masks.items():
            (out / n / f"{t}.mask").write_bytes(s.astype(np.uint8).tobytes())
            totals[n] += int(s.sum())
    print("pixels over the ranges:", totals)


if __name__ == "__main__":
    main()
