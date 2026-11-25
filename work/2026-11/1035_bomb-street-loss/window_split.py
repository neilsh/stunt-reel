"""Split one prop shape's SSIM loss between windows it fills alone and windows it shares.

Reads the `DBG_WINDUMP_DIR` dumps (switches/DBG_WINDUMP.diff) of one scoring run and its
report.json, and charges each window's loss to the shape's pixels as `attribute_shape_loss`
does. A window is `pure` when all its 121 pixels are the shape's props pixels, else `mixed`.

usage: window_split.py <dump dir> <report.json> <shape id> <lo-hi>[,<lo-hi>...] [<tick>,...]
"""

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

W, H, WIN = 320, 240, 11
PROPS = 4
CLASSES = ["sky", "reference_only", "ocean", "terrain", "props", "actors",
           "ocean_render_only", "terrain_render_only", "props_and_actors_render_only", "overlay"]


def load(path: Path):
    raw = path.read_bytes()
    n = int.from_bytes(raw[:4], "little")
    win = np.frombuffer(raw, dtype=[("x", "<u2"), ("y", "<u2"), ("s", "<f4")], count=n, offset=4)
    off = 4 + 8 * n
    classes = np.frombuffer(raw, np.uint8, W * H, off).reshape(H, W)
    shapes = np.frombuffer(raw, "<u2", W * H, off + W * H).reshape(H, W)
    return win, classes, shapes


def split(path: Path, word: int):
    win, classes, shapes = load(path)
    own = (classes == PROPS) & (shapes == word)
    pure = mixed = 0.0
    neighbours: Counter = Counter()
    for x, y, s in win:
        cell = own[y:y + WIN, x:x + WIN]
        n = int(cell.sum())
        if n == 0:
            continue
        share = (1.0 - float(s)) * n / (WIN * WIN)
        if n == WIN * WIN:
            pure += share
            continue
        mixed += share
        c = classes[y:y + WIN, x:x + WIN][~cell]
        w = shapes[y:y + WIN, x:x + WIN][~cell]
        others = Counter()
        for cls, sw in zip(c.tolist(), w.tolist()):
            others[f"shape {sw - 1}" if cls == PROPS and sw else CLASSES[cls]] += 1
        total = sum(others.values())
        for k, v in others.items():
            neighbours[k] += share * v / total
    count = len(win)
    return pure / count, mixed / count, {k: v / count for k, v in neighbours.items()}


def main() -> None:
    dump, report, shape = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    ranges = [tuple(map(int, r.split("-"))) for r in sys.argv[4].split(",")]
    show = {int(t) for t in sys.argv[5].split(",")} if len(sys.argv) > 5 else set()
    rep = json.loads(report.read_text(encoding="utf-8"))
    scored = {f["film_tick"]: f for f in rep["per_frame"] if f["scored"]}
    word = shape + 1
    film_total = 0.0
    sums = {r: [0.0, 0.0, Counter(), 0] for r in ranges}
    print("tick ssim loss pure mixed pure_share")
    for tick in sorted(scored):
        path = dump / f"{tick}.win"
        if not path.exists():
            continue
        pure, mixed, nb = split(path, word)
        film_total += pure + mixed
        for r in ranges:
            if r[0] <= tick <= r[1]:
                acc = sums[r]
                acc[0] += pure
                acc[1] += mixed
                acc[2].update(nb)
                acc[3] += 1
        if tick in show:
            share = pure / (pure + mixed) if pure + mixed else 0.0
            print(f"{tick} {scored[tick]['ssim']:.5f} {pure + mixed:.6f} {pure:.6f} {mixed:.6f} {share:.3f}")
    print(f"film mean over {len(scored)} scored frames: {film_total / len(scored):.6f} "
          f"(report {rep['mean_loss_by_shape_scored'].get(str(shape))})")
    for r, (pure, mixed, nb, n) in sums.items():
        total = pure + mixed
        print(f"range {r[0]}-{r[1]}: {n} scored frames, summed loss {total:.4f}, "
              f"pure {pure:.4f} ({pure / total:.1%}), mixed {mixed:.4f} ({mixed / total:.1%})")
        top = sorted(nb.items(), key=lambda kv: -kv[1])[:8]
        print("  mixed-window loss by the other pixels' kind: "
              + ", ".join(f"{k} {v:.4f} ({v / total:.1%})" for k, v in top))


if __name__ == "__main__":
    main()
