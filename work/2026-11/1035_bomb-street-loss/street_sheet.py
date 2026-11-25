"""Sheet of one tick: capture, ours, and the shape's pixels by how they disagree, at 3x.

Map panel: grey where our index equals the capture's, red where the capture shows <a> and we
<b>, blue the reverse, yellow any other disagreement, black outside the shape.

usage: street_sheet.py <capture frames> <render store> <shape id> <a>,<b> <tick> <out.png> [x0,y0,x1,y1]
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from stunt_reel.matched_frames import pair
from stunt_reel.parity_artifacts import RenderStore

from street_masks import H, W, shapes_plane


def main() -> None:
    cap, store_dir = Path(sys.argv[1]), Path(sys.argv[2])
    word = int(sys.argv[3]) + 1
    a, b = map(int, sys.argv[4].split(","))
    tick, out = int(sys.argv[5]), Path(sys.argv[6])
    x0, y0, x1, y1 = map(int, sys.argv[7].split(",")) if len(sys.argv) > 7 else (0, 0, W, H)
    store = RenderStore(store_dir)
    m = next(f for f in pair(cap, store).matched if f.film_tick == tick)
    c = np.frombuffer(m.capture_indices(), np.uint8).reshape(H, W)
    frame = store.frame(tick)
    o = np.frombuffer(frame.indices, np.uint8).reshape(H, W)
    pal_c = np.array(m.capture_palette(), np.uint8).reshape(256, 3)
    own = shapes_plane(store_dir)[tick] == word
    rgb = lambda idx, pal: pal[idx]
    cap_rgb, our_rgb = rgb(c, pal_c), rgb(o, pal_c)
    mp = np.zeros((H, W, 3), np.uint8)
    mp[own] = (110, 110, 110)
    mp[own & (c == a) & (o == b)] = (255, 40, 40)
    mp[own & (c == b) & (o == a)] = (60, 120, 255)
    mp[own & (c != o) & ~(((c == a) & (o == b)) | ((c == b) & (o == a)))] = (255, 220, 0)
    panels = [p[y0:y1, x0:x1] for p in (cap_rgb, our_rgb, mp)]
    gap = np.full((y1 - y0, 4, 3), 255, np.uint8)
    sheet = np.concatenate([panels[0], gap, panels[1], gap, panels[2]], axis=1)
    img = Image.fromarray(sheet).resize((sheet.shape[1] * 3, sheet.shape[0] * 3), Image.NEAREST)
    img.save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main()
