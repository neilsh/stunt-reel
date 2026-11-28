# Journal: class agreement after #1099 (#1125)

All three entries render on `main` `459f46d2` (`crates` `2904ed01`) with the probe switches in [`switches/DBG_SNAP.diff`](switches/DBG_SNAP.diff), on the RTX 4070 Laptop GPU (driver 621.40) and on the canonical lavapipe (`llvmpipe (LLVM 20.1.2, 256 bits)`, `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5`, WSL 2 clone `~/stunt-reel` at the same commit plus the switch).
Each film renders with `stuntreel --headless` as `render_film` (`parity_pipeline.py`) builds it, over the tick span of the 2026-11-26 batch's render of that film (`.agents/worktrees/agreement`, `crates` `57fa24d`), and is compared on that batch's tick set, so the tick counts equal the issue's table.
The count per tick is `class_agreement.compare`, the batch's own measure: index-plane pixels that differ between the two classes.
`mise run parity` could not score the renders: the data root's LAND and BALLOON captures were replaced on 2026-11-28 (hash `bc159031dd44` against `references.toml`'s `5228fd202345` for LAND), so no SSIM was measured here; the batch's SSIM gaps in the issue stand.
Raw figures: [`agreement-variants.txt`](agreement-variants.txt).

## 2026-11-28: The rise is the pixel-centre vertex placement

**Question**: is the 2026-11-26 batch's rise in GPU-against-lavapipe pixels (#1125) caused by #1099, which draws each vertex at the centre of the pixel `PLAYONE`'s projector truncates it to?

**Method**: `DBG_SNAP=off` returns early from `playone_vertex` (#1099) and `snap_edges` (#1197, the terrain's copy of the same placement) in `mode13h.wgsl`, so every vertex keeps its own projection, as before #1099; #1197's per-fragment terrain depth stays.
All seven reference films, both classes, with and without the switch.

**Result**: mean differing pixels per tick, GPU against lavapipe; the pin is `agreement.toml` (`crates` `4d18e7a`, 2026-11-22), the batch is the issue's table (`crates` `57fa24d`):

| Film | Pin | Batch | `main` | `DBG_SNAP=off` |
|---|---|---|---|---|
| CTRY | 3.09 | 8.55 | 8.89 | 3.12 |
| INTRO | 2.25 | 11.94 | 12.35 | 2.09 |
| LAND | 5.23 | 49.59 | 50.08 | 5.22 |
| BALLOON | 4.12 | 53.26 | 54.60 | 4.15 |
| TRAINTNL | 3.84 | 8.59 | 8.39 | 3.62 |
| BOMB | 8.40 | 21.30 | 20.89 | 8.43 |
| LOCATION | 8.60 | 8.12 | 7.59 | 6.22 |

`main` reproduces the batch on every film within 1.34 pixels a tick (BALLOON; the others within 0.53, LOCATION), LAND's 6 ticks over 500 pixels included (525 to 532, largest 715 at 531), on a newer GPU driver (621.40 against the batch's 610.88).
With the placement off, six films are within 0.22 pixels a tick of the pin and LOCATION is 2.38 below it, and no film has a tick over 500.
On the GPU alone the placement moves 2,087.21 pixels a tick on LAND and 2,853.56 on BALLOON.

At `main`, 99.8% of LAND 525 to 532's differing pixels and 99.8% of BALLOON's (every tick) have a 4-neighbour of another index on either class: they are edge pixels.
LAND's hot ticks are an actor toward the view's right edge (99.9% of the pixels in rows 40 to 99; 3,953 of them, 90%, in columns 200 to 319), which a picture of tick 531 (not kept) showed as thin broken streaks on both classes covering different pixels: of 4,389 differing pixels at 525 to 532, 3,799 have the actor layer on exactly one class (1,583 sky against actor, 1,000 terrain against actor), and 88% differ in layer.
BALLOON's are 42,676 pixels that are an actor on both classes (66% of 64,372) and 18,744 a prop against the terrain under it.

**Verdict**: control; with the placement off every film is within 0.22 pixels a tick of the pin or below it, on one render per class.
The switch turns off #1099's placement and #1197's copy of it for terrain together; the batch's tree predates #1197, so its rise is #1099's.

**Lives in**: [`research/parity/lavapipe-pixel-centres.md`](../../../research/parity/lavapipe-pixel-centres.md) section 1.

## 2026-11-28: Vertices off the pixel centre by (5, 3)/256 pixel

**Question**: if the disagreement is the two rasterizers' tie rules on sample points that the placed edges pass through, does moving every placed vertex off the pixel centre remove it?

**Method**: `DBG_SNAP=5,3` draws each placed vertex at `(0.5 + 5/256, 0.5 + 3/256)` within its pixel in place of `(0.5, 0.5)`, in `playone_vertex` and `snap_edges`.
If both rasterizers snap to a 1/256-pixel grid (not checked), the offset survives their snapping; an edge between two such vertices then passes through a pixel centre only when it runs along (5, 3), or is long enough that `5q - 3p` is a multiple of 256 for its direction (p, q).
LAND and BALLOON, both classes.

**Result**: LAND 50.08 to 34.11 pixels a tick (9 ticks over 500, largest 762 at 525), BALLOON 54.60 to 19.89 (largest 445 at 809).
BALLOON's pixels that are an actor on both classes fall from 42,676 to 3,499; its prop-against-terrain pixels stay (18,623 against 18,744).
LAND's actor-on-one-class pixels at 520 to 540 stay: 403.19 pixels a tick there against 392.19.
On the GPU the offset itself moves 243.00 pixels a tick on LAND and 176.92 on BALLOON against `main`.

**Verdict**: rejected as a fix: it leaves LAND at 6.5 and BALLOON at 4.8 times the pin, and moves the render by more than the disagreement it removes, so it would need its own adoption on lavapipe.
It supports the tie-rule reading for BALLOON's in-actor pixels only.

**Lives in**: [`research/parity/lavapipe-pixel-centres.md`](../../../research/parity/lavapipe-pixel-centres.md) section 2.

## 2026-11-28: Capping grazing slides at four times the vertex's distance

**Question**: are the pixels the offset leaves (LAND's actor on one class, BALLOON's prop against the terrain) vertices slid along a ray that grazes their plane, which `playone_vertex` moves up to `PLANE_SLIDE_MAX` (10⁶) ray units, so their depth and `w` are far from the vertex's own?

**Method**: `DBG_SLIDE_RATIO=4` makes `playone_vertex` keep a vertex's own projection when the slid point lies more than 4 times the vertex's distance from the eye; alone, and with `DBG_SNAP=5,3`.
LAND and BALLOON, both classes.

**Result**: alone, LAND 50.07 and BALLOON 54.58 pixels a tick, against 50.08 and 54.60 on `main`; with the offset, 34.10 and 19.88, against 34.11 and 19.89.
On the GPU the cap moves 0.23 pixels a tick on LAND and 0.91 on BALLOON.

**Verdict**: rejected: a cap at 4 times the vertex's distance leaves the disagreement as it was; other caps were not run.

**Lives in**: [`research/parity/lavapipe-pixel-centres.md`](../../../research/parity/lavapipe-pixel-centres.md), Ruled out.
