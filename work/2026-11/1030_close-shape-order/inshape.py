# ruff: noqa: T201, B023
"""#1030 scratch: score the CPU painter planes of DBG_INSHAPE against the capture.

usage: inshape.py <film> <shape> <tick>... [--crop x0,y0,x1,y1] [--scale N]
Writes build/scratch/1030/ (create it first) <film>-<tick>-inshape.png: capture | ours | ours+painter | ours+cpu-zbuf.
"""

from __future__ import annotations

import sys
from compression import zstd
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python" / "scripts"))

import parity_probe  # noqa: E402
from parity_probe import locate  # noqa: E402

from stunt_reel import dataroot, parity_pipeline  # noqa: E402
from stunt_reel.matched_frames import Reference  # noqa: E402
from stunt_reel.parity_artifacts import RenderStore  # noqa: E402
from stunt_reel.parity_artifacts.capture import read_capture  # noqa: E402

W, H = 320, 200


def main() -> None:
    args = sys.argv[1:]
    crop = None
    scale = 2
    if "--crop" in args:
        i = args.index("--crop")
        crop = tuple(int(v) for v in args[i + 1].split(","))
        del args[i : i + 2]
    if "--scale" in args:
        i = args.index("--scale")
        scale = int(args[i + 1])
        del args[i : i + 2]
    film, shape, *ticks = args
    shape_id = int(shape)
    ticks_i = [int(t) for t in ticks]
    store_dir = ROOT / "build/scratch/frame" / film / "store"
    store = RenderStore(store_dir)
    raw_shapes = zstd.decompress((store_dir / "shapes.zst").read_bytes())
    shapes_all = np.frombuffer(raw_shapes, dtype="<u2")
    stored_ticks = store.ticks()
    root = dataroot.data_root()
    with parity_pipeline.reference_job(root, film) as job:
        found, _ = locate(read_capture(job.capture), ticks_i)
        ref = Reference(job.capture, store)
        for tick in ticks_i:
            ordinal = found[tick]
            m = ref.match(ordinal, tick)
            cap = np.frombuffer(m.capture_indices(), dtype=np.uint8)[: W * H].astype(np.int32)
            ours = np.frombuffer(m.page.indices, dtype=np.uint8)[: W * H].astype(np.int32)
            row = stored_ticks.index(tick)
            shp = shapes_all[row * W * H : (row + 1) * W * H].astype(np.int32)
            b = store_dir / f"inshape_{tick - 1}.bin"
            planes = np.frombuffer(b.read_bytes(), dtype="<u2").reshape(4, -1)
            rows = planes.shape[1] // W

            def full(p: np.ndarray) -> np.ndarray:
                out = np.full(W * H, 0xFFFF, dtype=np.int32)
                out[: W * rows] = p
                return out

            paint, zb, pid, zid = (full(p) for p in planes)
            mask = shp == shape_id + 1
            mask &= paint != 0xFFFF
            n = int(mask.sum())
            if n == 0:
                print(f"{film} {tick}: no pixel of {shape_id}; shape ids {np.unique(shp)[:20]}")
                continue

            def agree(a: np.ndarray) -> float:
                return float((a[mask] == cap[mask]).mean())

            ours_zb = float((ours[mask] == zb[mask]).mean())
            differ = int((pid[mask] != zid[mask]).sum())
            print(
                f"{film} {tick} shape {shape_id}: {n} px; capture agreement ours {agree(ours):.3f}"
                f" cpu-zbuf {agree(zb):.3f} painter {agree(paint):.3f};"
                f" cpu-zbuf=ours {ours_zb:.3f}; painter!=zbuf polygon on {differ} px"
            )
            comp_p = ours.copy()
            comp_p[mask] = paint[mask]
            comp_z = ours.copy()
            comp_z[mask] = zb[mask]
            box = crop or (0, 0, W, rows)
            palette = m.capture_palette()
            panels = [
                parity_probe.render_region(bytes(a.astype(np.uint8)), palette, box, scale, W)
                for a in (cap, ours, comp_p, comp_z)
            ]
            divider = [255, 0, 255] * 2
            out_rows = []
            for parts in zip(*panels, strict=True):
                r: list[int] = []
                for i, part in enumerate(parts):
                    r += (divider if i else []) + part
                out_rows.append(r)
            png = ROOT / "build/scratch/1030" / f"{film}-{tick}-inshape.png"
            parity_probe.write_png(png, ((box[2] - box[0]) * scale + 2) * 4 - 2, out_rows)
            print(png)


if __name__ == "__main__":
    main()
