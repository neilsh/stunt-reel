"""Line/outline masks of one shape from a DBG_LINEMARK=0,1 pair of frame-tool stores."""
import sys, json
from pathlib import Path
import numpy as np
from compression import zstd
from stunt_reel.parity_artifacts import RenderStore

base_dir, mark_dir, out_dir, shape = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4])
word = shape + 1
W, H = 320, 200

def shapes_plane(d: Path):
    rec = json.loads((d / "render.json").read_text())
    data = (d / "shapes.zst").read_bytes()
    planes = {}
    ticks = rec["ticks"]; i = 0
    for chunk, span in zip(rec["chunks"], rec["planes"]["shapes.zst"]["chunks"]):
        raw = zstd.decompress(data[span["offset"]:span["offset"] + span["length"]])
        arr = np.frombuffer(raw, "<u2").reshape(chunk["ticks"], H, W)
        for k in range(chunk["ticks"]):
            planes[ticks[i]["tick"]] = arr[k]; i += 1
    return planes

bs, ms = RenderStore(base_dir), RenderStore(mark_dir)
bshape, mshape = shapes_plane(base_dir), shapes_plane(mark_dir)
kinds = {"zline": 0x2000, "quad": 0x4000, "list": 0x8000}
masks = ["all", "lines", "lines_d1", "fill", "zline", "outline"]
for m in masks: (out_dir / m).mkdir(parents=True, exist_ok=True)
print("tick shape_px zline quad list lines lines_d1 index_same shapeword_same")
for tick in bs.ticks():
    bi = np.frombuffer(bs.frame(tick).indices, np.uint8).reshape(H, W)
    mi = np.frombuffer(ms.frame(tick).indices, np.uint8).reshape(H, W)
    b, m = bshape[tick], mshape[tick]
    same_word = bool(((m & 0x1FFF) == b).all())
    own = b == word
    k = {n: own & ((m & bit) != 0) for n, bit in kinds.items()}
    lines = k["zline"] | k["quad"] | k["list"]
    d = lines.copy()
    d[1:] |= lines[:-1]; d[:-1] |= lines[1:]; d[:, 1:] |= lines[:, :-1]; d[:, :-1] |= lines[:, 1:]
    d &= own
    sel = {"all": own, "lines": lines, "lines_d1": d, "fill": own & ~lines, "zline": k["zline"], "outline": k["quad"] | k["list"]}
    for n, s in sel.items():
        (out_dir / n / f"{tick}.mask").write_bytes(s.astype(np.uint8).tobytes())
    print(tick, int(own.sum()), int(k["zline"].sum()), int(k["quad"].sum()), int(k["list"].sum()), int(lines.sum()), int(d.sum()), bool((bi == mi).all()), same_word)
