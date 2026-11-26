# Journal

## 2026-11-24: the street's loss is in windows it fills alone

- **Question**: does `bomb` 1756's loss on ticks 2036 to 2740 and 3312 to 3477 come from SSIM windows that straddle the edges of the shapes on the street (#1035's hypothesis), or from windows inside the street?
- **Method**: `main` at `4d5c01b0` on the RTX 4070 (the GPU), with a temporary scorer switch kept as [`switches/DBG_WINDUMP.diff`](switches/DBG_WINDUMP.diff): `DBG_WINDUMP_DIR` writes, for each scored tick, the SSIM windows (11 pixels, stride 8, on the 320x240 rescaled frame) and the rescaled loss-class and shape planes; the diff also carries #1034's `DBG_ORACLE_DIR` and `DBG_SHAPE_DUMP`.
  `DBG_WINDUMP_DIR=<dir> mise run parity -- --films bomb` rendered and scored the film (ssim 0.8957, 316 of 339 frames scored).
  [`window_split.py`](window_split.py) charges each window's loss to 1756's pixels as `attribute_shape_loss` does, and calls a window `pure` when all 121 of its pixels are 1756's props pixels, else `mixed`; its film mean, 0.008301, equals the report's `mean_loss_by_shape_scored` for 1756 (0.0083005).
  [`pure_windows.py`](pure_windows.py) counts, in each pure window, the pixels whose index differs from the capture's, and tallies the (capture, ours) index pairs of 1756's disagreeing pixels.
  Output: [`logs/base_window_split.txt`](logs/base_window_split.txt) and [`logs/base_pure_windows.txt`](logs/base_pure_windows.txt), each run as `mise exec -- uv run python …` with the arguments its docstring names.
- **Result**:
  - The two ranges hold 2.3213 of 1756's summed loss over the film's scored frames (2.6230), 88.5%, as #989 found on the canonical lavapipe at `3e53f767`.
  - On 2036 to 2740 (65 scored frames, summed loss 1.9627), pure windows carry 67.8% and mixed 32.2%; on 3312 to 3477 (16 frames, 0.3586), 51.4% and 48.6%.
    At 2421 pure windows carry 73.8% of 1756's loss (0.04727), at 2520 69.7% (0.05508).
  - Pure windows with no disagreeing pixel carry none of it (0.0004 of 1.3302 on 2036 to 2740, 0.0002 of 0.1844 on 3312 to 3477): the street's own loss is in windows holding 1 to 20 disagreeing pixels (83.1% and 93.0% of the pure-window loss).
  - 3.04% of 1756's pixels disagree on 2036 to 2740 (26,271 of 863,004), 1.98% on 3312 to 3477; the commonest pairs are the capture's index 52 where we draw 14 (8,519 pixels) and 14 where we draw 52 (7,562).
    Index 14 is the street's grey, 52 the lane dashes' light grey ([sheet](images/bomb-2520-street-dashes.png)).
- **Verdict**: control (diagnosis); #1035's hypothesis is the smaller part.
  Windows straddling the street's edges carry a third of its loss on 2036 to 2740 and half on 3312 to 3477; the rest is in windows inside the street, over its lane dashes.
- **Lives in**: [`prop-shape-loss.md` § 2.6](../../../research/parity/prop-shape-loss.md#26-the-streets-dashes-are-drawn-a-pixel-off).

## 2026-11-24: the street's own pixels own its loss, its dashes most of it

- **Question**: how much of 1756's loss its own pixels, its dash pixels and the pixels around it own.
- **Method**: the capture-side oracle of #1034 ([`probes.md` § 7](../../../research/parity/probes.md#7-no-rebuild-experiments-on-the-capture)) on the previous entry's render: `DBG_ORACLE_DIR` copies our index into the capture on a mask's pixels before scoring.
  [`street_masks.py`](street_masks.py) (`<capture frames> <render store> <mask dir> 1756 52,14 2036-2740,3312-3477`, [`logs/base_street_masks.txt`](logs/base_street_masks.txt)) wrote four masks per tick: `all` (1756's pixels, 1,154,443 over the two ranges), `others` (every other pixel), `swap` (1756's pixels where the capture and we disagree as 52 and 14 either way, 18,319, 1.6% of the street) and `rest` (1756's other disagreeing pixels, 13,735).
  Each was scored with `DBG_ORACLE_DIR=<mask dir> DBG_WINDUMP_DIR=<dump dir> target/release/stuntreel.exe parity --reference <data root>/captures/vault-bomb/frames --test build/parity/ours/bomb_current --output <dir>`, then split by `window_split.py` ([`logs/oracle_window_split.txt`](logs/oracle_window_split.txt)); the loss a mask removes is 1756's summed loss without the oracle minus its loss with it.
- **Result**: loss removed, as a share of 1756's summed loss on each range:

  | Mask | 2036 to 2740 (of 1.9627) | 3312 to 3477 (of 0.3586) |
  |---|---|---|
  | `all`: the street's pixels | 1.7225 (87.8%) | 0.2641 (73.6%) |
  | `swap`: its dash pixels, 52 against 14 | 1.4594 (74.4%) | 0.1707 (47.6%) |
  | `rest`: its other disagreeing pixels | 0.2550 (13.0%) | 0.0909 (25.3%) |
  | `others`: every pixel but the street's | 0.2156 (11.0%) | 0.0922 (25.7%) |

  With `all`, what is left lies in mixed windows, and the kind of their other pixels most charged is `actors` (0.1280 of the 0.2402 left on 2036 to 2740, 0.0666 of 0.0945 on 3312 to 3477), apportioned by pixel count, which says what shares the window, not what caused its loss.
- **Verdict**: control (attribution).
  The neighbours own 11% of the street's loss on 2036 to 2740 and 26% on 3312 to 3477, so #1035's hypothesis is recorded as a negative for the bulk; the street's own pixels own 88% and 74%, and its lane dashes, 1.6% of its pixels, 74% and 48%.
- **Lives in**: [`prop-shape-loss.md` § 2.6](../../../research/parity/prop-shape-loss.md#26-the-streets-dashes-are-drawn-a-pixel-off).

## 2026-11-24: the dashes are outline lines a pixel off

- **Question**: what draws the street's dashes, and which way the capture's lie from ours.
- **Method**: #1034's [`DBG_LINEMARK`](../1034_stadium-outlines/switches/DBG_LINEMARK.diff) on `4d5c01b0`, `mise run frame -- --film bomb --ticks <the 81 scored ticks of the two ranges> --var DBG_LINEMARK=0,1` on the GPU.
  [`mark_tally.py`](mark_tally.py) (`<capture frames> <store_0_0> <store_1_1> 1756 52,14`, [`logs/base_mark_tally.txt`](logs/base_mark_tally.txt)) tallies 1756's pixels by what drew them; #1034's [`line_masks.py`](../1034_stadium-outlines/line_masks.py) (`<store_0_0> <store_1_1> <mask dir> 1756`, [`logs/base_line_masks.txt`](logs/base_line_masks.txt)) and [`line_direction.py`](../1034_stadium-outlines/line_direction.py) (`<capture frames> <store_0_0> <mask dir> 92.5`, [`logs/base_direction.txt`](logs/base_direction.txt)) count, for each disagreeing outline pixel, the four-neighbours where the capture shows our index, toward the projection centre (160, 92.5) or away.
  The marked render's index and shape planes equal the unmarked one's at every tick, and the unmarked frame store scores 1756 exactly as the film render does (1.9627 and 0.3586, [`logs/proto_window_split.txt`](logs/proto_window_split.txt), `base`).
- **Result**:
  - Every line pixel of 1756 is from the world's outline line list (`mesh.rs`'s `LineList`): 53,047 of its 1,154,443 pixels over the 81 frames, no `ZLINETO` line and no outline quad.
    Of the 22,924 pixels we draw in 52, 19,885 are outline-list pixels and 3,039 fill.
  - The capture's 52 where we draw 14 falls on our fill (9,623 pixels; 322 on the outline list); our 52 where the capture shows 14 is our outline-list pixels (8,163; 211 fill).
  - Of 10,244 disagreeing outline pixels, below the centre (the street) the capture shows our index in the row above 7,374 times and the row below 496; left of the centre in the column to the right 1,769 times and to the left 303; right of the centre in the column to the right 1,625 times and to the left 131.
  - [Sheet](images/bomb-2520-street-dashes.png), tick 2520 (`street_sheet.py <capture frames> build/parity/ours/bomb_current 1756 52,14 2520 <png>`): the capture, our render, and 1756's pixels (grey where our index matches the capture's, red where the capture shows 52 and we 14, blue the reverse, yellow any other disagreement, among them the capture's clock digits).
- **Verdict**: control (diagnosis).
  The dashes are outlines drawn a pixel off: the capture's lie a row higher, toward the projection centre, and a column to the right on both sides of the centre, so the horizontal offset is not toward the centre.
- **Lives in**: [`prop-shape-loss.md` § 2.6](../../../research/parity/prop-shape-loss.md#26-the-streets-dashes-are-drawn-a-pixel-off).

## 2026-11-24: the projector truncation prototype on the street

- **Question**: does drawing vertices where `PLAYONE`'s projectors truncate them ([`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre), [#1064](https://github.com/neilsh/stunt-reel/issues/1064)) remove the street's dash loss, as it removed about a third of the stadium's (#1034)?
- **Method**: the shader of `proto/1027-projector-rounding` (`f2e12e39`), applied as `git diff origin/main...f2e12e39 -- crates/stunt-render/src/shaders/mode13h.wgsl` on `4d5c01b0` with the scorer switch, then `mise run frame -- --film bomb --ticks <the 81>` on the GPU.
  The baseline frame store of the previous entry (`DBG_LINEMARK=0`) and the prototype's were each scored with `DBG_WINDUMP_DIR` and split by `window_split.py` ([`logs/proto_window_split.txt`](logs/proto_window_split.txt)); frame SSIM by a comparison of the two reports ([`logs/proto_frame_ssim.txt`](logs/proto_frame_ssim.txt)); disagreement by `pure_windows.py` on the prototype ([`logs/proto_pure_windows.txt`](logs/proto_pure_windows.txt)).
  This is an attribution on one shape's frames, not a sweep: adopting the rule is #1064's.
- **Result**:
  - 1756's summed loss falls on 2036 to 2740 from 1.9627 to 1.2342 (37.1%) and on 3312 to 3477 from 0.3586 to 0.2789 (22.2%); at 2421 from 0.04727 to 0.03350, at 2520 from 0.05508 to 0.04429.
  - Mean frame SSIM over the 81 frames rises from 0.86763 to 0.88252, on 71 of them (57 of 65 on 2036 to 2740, 14 of 16 on 3312 to 3477).
  - On 2036 to 2740, 1756's disagreeing pixels fall from 26,271 to 15,856 (3.04% to 1.83%), the 52 against 14 pairs from 8,519 and 7,562 to 5,393 and 4,332.
- **Verdict**: control (attribution), evidence-backed by the rule § 8.14 cites; not adopted here.
  The truncation rule removes about a third of the street's loss on 2036 to 2740 and a fifth on 3312 to 3477, about half of what its dashes own; #1064 is the follow-up.
  The rest of the dash mismatch, and the column to the right on both sides of the centre, are left for the outline-pixel question of `sod-vm-lines-spans.md` § 10 that #1034 also pointed at.
- **Lives in**: [`prop-shape-loss.md` § 2.6](../../../research/parity/prop-shape-loss.md#26-the-streets-dashes-are-drawn-a-pixel-off).
