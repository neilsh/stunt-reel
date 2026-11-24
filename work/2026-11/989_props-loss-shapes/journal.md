# Journal

## 2026-11-23: the costliest prop shapes on LOCATION and BOMB

- **Question**: which prop shapes carry the `props` loss on `location` and `bomb`, how much falls under `unattributed`, and on which frames each shape's loss sits.
- **Method**: `main` at `3e53f767` (`crates/` tree `d897adc`), `mise run parity -- --films location,bomb --software-only` on the canonical lavapipe under WSL (`llvmpipe (LLVM 20.1.2, 256 bits)`, [`render-on-lavapipe.md` § 5](../../../docs/howto/render-on-lavapipe.md#5-render-the-canonical-lavapipe-under-wsl)); both films reproduced their `expected/lavapipe.toml` SSIM and IoU to seven decimals.
  The ranking is each report's `mean_loss_by_shape_scored` ([`ranking.csv`](ranking.csv)).
  #904's temporary scorer print ([`DBG_SHAPE_DUMP.diff`](../904_near-clip-host-shapes/switches/DBG_SHAPE_DUMP.diff), its `eprintln!` changed to append to a file, since `mise run parity` does not pass the scorer's stderr through) rescored the same renders with `--no-render` and wrote each frame's loss for the eight worst shapes of each film; [`shape-frames.csv`](shape-frames.csv) keeps its scored rows with a loss above 0.
  A scratch script decoded the frame tool's `shapes.zst` to tint one shape's pixels and to count how many of them carry the capture's colour (`own-pixel agreement` below, [`own-pixel.txt`](own-pixel.txt), from `mise run frame` renders of the ticks named).
- **Result**:
  - `location`: SSIM 0.8728, `props` 0.0784, spread over 1,014 shapes; the worst, 1145, holds 0.00169 (2.2%), the ten worst 0.0136 (17.4%).
    `bomb`: SSIM 0.8949, `props` 0.0597 over 127 shapes; 1756 holds 0.00830 (13.9%), 1737 0.00704 (11.8%), the ten worst 0.0386 (64.7%).
    Neither film has an `unattributed` key.
  - On `location` each of the eight worst shapes loses on 14 to 27 of 732 scored frames, all of its loss in the worst 10% of its frames: a shape costs on one to three short runs of frames (runs split at gaps over 60 ticks).
    1145, 1164, 1179 and 1162 lose on two runs each within the canyon run, ticks 6711 to 7437, where each covers up to 49,314 of the 59,200 view pixels with own-pixel agreement 0.16 to 0.56; 1150 on three, ticks 2201 to 2322 (a crater, 33,333 pixels, 0.67), 7097 to 7151 in the canyon and 7536 to 7569; 1745 on ticks 4335 to 4467 (the railway track the camera rides along, 0.71); 613 on ticks 2652 to 2817 (the stadium, 0.89); 996 on ticks 2047 to 2190 (town lots, 0.82).
  - On `bomb` the shapes lose on 48 to 150 of 316 scored frames, the worst 10% (32 frames) holding 51% (1737) to 96% (1654) of each.
    1756 is the street (its worst frame tick 3302, the camera cut of [`attribution.md`](../../../research/parity/attribution.md) open question 7; 7% of its loss on ticks 221 to 420, 35% on 2036 to 2399, 40% on 2410 to 2740, 18% on 3302 to 3477); 1737 the red lot under the hero's bombing run (ticks 3103 to 3191, and 2861 to 2905); 1650 the fire station and 1648 the church, each a near-constant 0.040 to 0.043 a frame on the static opening shot (ticks 133 to 343); 545 and 542 the red autumn trees (ticks 2289 to 2388, 2070 to 2179); 1754 a red road (ticks 2961 to 3081); 1654 a building (ticks 3191 to 3268).
    Own-pixel agreement at the tick examined is 0.94 (1737), 0.95 (1650), 0.92 (1648), 0.89 (1654), 0.97 (1756), 0.81 (1754), and 0.67 to 0.68 for the two trees.
- **Verdict**: control (diagnosis).
  `location`'s props loss has no dominant shape; half of its eight worst shapes are canyon rocks losing on the canyon run.
  `bomb`'s high own-pixel agreement puts most of its worst shapes' loss at their edges, not in their colour.
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 1.

## 2026-11-23: the LOCATION canyon run steps late

- **Question**: does a timing offset explain the canyon run's loss on 1145, 1164, 1179 and 1162?
- **Method**: the same `location` render, relabelled and rescored without a build, `mise run parity -- --films location --no-render --no-build --software-only --retime N` ([`probes.md` § 6](../../../research/parity/probes.md#6-timing-hypotheses-post-hoc-retime)) for N in -10, -3, -1, +1, +2, +3, +5, +8, +10 and +12; per-frame SSIM in [`retime-location.csv`](retime-location.csv).
  A scratch script hashed the render's index plane at every tick from 6600 to 7420 to find where our picture changes.
- **Result**:
  - Between ticks 6713 and 7150 our render changes only at 6731, 6741, …, 7141, every 10 ticks at ticks ending in 1, and at 6772, 6892, 6893, 7012 and 7013; before 6713 it changes every tick.
    From 7151 it changes on most ticks again, in irregular runs.
  - Mean SSIM over the 64 scored frames from 6700 to 7400: 0.8312 at offset 0, 0.8174 at -1, 0.7911 at -3, 0.8404 at +1, 0.8500 at +2, 0.8542 at +3, 0.8548 at +5, 0.8379 at +8, 0.7978 at +12.
    Over 7100 to 7400 (27 frames): 0.7830 at 0, 0.8303 at +3.
  - The frames that gain are those whose capture already shows the next 10-tick step: 6810 (0.842 to 0.895 at +1), 6920 (0.778 to 0.881 at +1), 7030 (0.741 to 0.880 at +1), 7184 (0.723 to 0.923 at +1), 7129 (0.815 to 0.904 at +2), 6788 (0.841 to 0.921 at +3), 7283 (0.588 to 0.841 at +2).
    Each takes the step our render shows 1 to 3 ticks later.
  - Before the run, from 6601 to 6700, offset 0 is best on 8 of the 10 scored frames and -1 on the other two (6645, 6667).
    Over the whole film, +1 raises 49 frames by more than 0.02 and lowers 401; -1 raises 101 and lowers 366, so outside this run a one-tick offset helps frames in both directions and gives no sign.
  - Frames that no offset from -10 to +12 raises by more than 0.05 remain: 7019 (0.762; 0.800 at -10), 7317 (0.651; 0.698 at +10), 6722 (0.812), 6755 (0.795, 0.813 at +10).
- **Verdict**: control (diagnosis), not a fix: a relabelled render is not a timing rule.
  On the canyon run the frames that straddle a 10-tick camera step show the next step 1 to 3 ticks before our render does; the loss of the frames no offset raises is not timing.
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.1.

## 2026-11-23: what the canyon and BOMB frames show

- **Question**: for the worst frames of the top shapes and for the error readout's `scenery-missing` ticks (`bomb` 1585 and 1904), is each case missing, misplaced, a wrong shape, a wrong shade or a wrong draw order?
- **Method**: `mise run frame -- --film <film> --ticks … --software-only` on the same tree under WSL, crops at 2× and 3×.
  Each sheet is that tool's output from `3e53f767`: the capture first, then our render; [`bomb-1904-lod.png`](images/bomb-1904-lod.png) has four panels, the capture, then our render at `DBG_FAR=0` (the baseline), `1` and `2` (the last entry).
  A scratch script found, for each frame, the whole-frame shift of our panel in -4..4 pixels in each axis that makes the most pixels carry the capture's colour (every other column, a 6-pixel border and the clock rows left out; [`frame-shift.txt`](frame-shift.txt)).
- **Result**:
  - **Canyon, ticks 6810, 6920 and 7019** ([sheet](images/location-7019.png)): the far ridges sit where the capture's do; in the lower half the capture shows more and differently shaded facets of the same rocks.
    At 7019, which no offset raises, our render draws a large near face of 1145 across the lower left that the capture does not show; there the capture shows farther facets of 1145.
  - **BOMB trees 542 and 545** (ticks 2080, 2300): placed where the capture's are (best shift 0 at 2300, one column at 2080), but their overlapping leaf clusters cover each other differently.
  - **BOMB buildings and lots 1648, 1650, 1737, 1654, 1754** ([sheet](images/bomb-155.png), capture then our render): the same shapes, 0.89 to 0.95 of the first four's pixels in the capture's colour in place and 0.81 of 1754's at 2961, the whole frame displaced: ours 1 row low on the opening shot (ticks 155 and 233: agreement 0.912 to 0.948 and 0.960 to 0.963 when our panel moves up a row), 2 rows low at 3191 (0.898 to 0.922), 3 rows high and a column left at 3268 (0.903 to 0.947), and 4 columns left and a row high at 2961 (0.670 to 0.805, the edge of the search).
    The offset changes between shots and is a whole-frame one, so it is the camera's, not the shapes' placement.
  - **BOMB 1756** at 2740: agreement 0.936, 0.950 with our panel a column left; 3302 is the known camera cut; the next entry looks at the rest.
  - **LOCATION 1150** at 2212: agreement 0.730, and 0.741 at the best shift, our panel 4 columns right (the edge of the search), so no whole-frame shift explains it: the crater's near rim and the pink wall under it differ in outline.
    These frames do not tell a camera-position difference from a shape or cover-order one.
    **1745** at 4390: the sleepers are where the capture's are within a fraction of their spacing; +1 tick raises ticks 4330 to 4470 from 0.8939 to 0.9076.
  - **`scenery-missing`, BOMB 1585 and 1904** ([sheet](images/bomb-1904-lod.png), its first two panels): the distant town's houses, which the capture draws as white walls and roofs, are missing from ours, which shows lots, roads and trees there.
- **Verdict**: control (diagnosis); each cause is tested or filed in the entries below.
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.

## 2026-11-23: the BOMB street 1756 loses in place

- **Question**: does a whole-frame offset explain `bomb` 1756's loss outside the opening shot and the 3302 cut?
- **Method**: [`shape-frames.csv`](shape-frames.csv) summed by tick range; `mise run frame -- --film bomb --ticks 2190,2355,2421,2520,2586,2630,2718,3345 --software-only` on `3e53f767` under WSL, then the previous entry's shift search ([`frame-shift.txt`](frame-shift.txt)) and own-pixel agreement ([`own-pixel.txt`](own-pixel.txt)) on each.
- **Result**:
  - Of 1756's summed loss (2.62 over 101 frames): 7% on ticks 221 to 420 (the opening shot, whose frame sits a row low at 155 and 233), 4% on tick 3302 (0.115), 75% on ticks 2036 to 2740 and 14% on 3312 to 3477.
  - At the eight ticks and at 2740 the best whole-frame shift is 0 or one column, raising agreement by at most 0.014, and 0.95 to 0.98 of 1756's pixels carry the capture's colour; its loss there is 0.020 to 0.066 a frame.
- **Verdict**: control (diagnosis); the 89% outside the opening shot and the cut is unexplained.
  The street is drawn in place, in the capture's colours, so neither a camera offset nor a wrong shade explains it.
  `[Hypothesis]`: each pixel takes a share of every SSIM window's loss over it ([`report-fields.md`](../../../research/parity/report-fields.md)), so windows straddling the edges of the lots, trees and buildings on the street charge part of their loss to it; testing it is [#1035](https://github.com/neilsh/stunt-reel/issues/1035).
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.6.

## 2026-11-23: the BOMB far town is the level-of-detail gate

- **Question**: are BOMB's missing far houses cut by the `scale_index` distance cut (image `0x1B28`) or by the `SP_1NODE` level-of-detail gate (image `0x2121`)?
- **Method**: a temporary switch, saved as [`switches/DBG_FAR.diff`](switches/DBG_FAR.diff): `DBG_FAR=1` makes `CameraTransform::scale_reach_keeps` keep everything; `DBG_FAR=2` builds both branches of every `SP_1NODE` and makes `lod_keeps_subtree` keep the near one.
  `mise run frame -- --film bomb --ticks 1585,1904 --software-only --var DBG_FAR=0,1,2` on `3e53f767` under WSL; then `DBG_FAR=2 mise run parity -- --films location,bomb --software-only`, compared frame by frame with the baseline reports of the first entry.
- **Result**:
  - At 1904 and 1585, `DBG_FAR=1` draws the same picture as the baseline; `DBG_FAR=2` draws the town's houses as walls and roofs, as the capture does ([sheet](images/bomb-1904-lod.png)).
  - Over the films, `DBG_FAR=2` lowers `location` from 0.8728 to 0.8549 (`props` 0.0784 to 0.0901; 6 frames up by more than 0.005, 478 down) and `bomb` from 0.8949 to 0.8831 (`props` 0.0597 to 0.0699; none up, 134 down).
    Tick 1585 falls from 0.9230 to 0.9202 and 1904 from 0.8834 to 0.8787: at 3× the forced near branch draws the town as white roofs packed tighter than the capture's walls and roofs.
    Per-frame SSIM of both runs: [`far-lod.csv`](far-lod.csv).
- **Verdict**: control (diagnosis), not a candidate: drawing every near branch everywhere is not `PLAYONE`'s rule, and it scores lower.
  The distance cut is ruled out: it keeps the town in both renders.
  Our gate shows the town's stand-ins where the capture shows houses, and the near branch draws houses there; but the near branch does not raise those two ticks, so whether `PLAYONE`'s gate picks the near branch at that depth, or draws a stand-in we draw differently, is open.
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.4.
