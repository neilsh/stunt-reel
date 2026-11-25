# Journal: does PLAYONE truncate projected vertices toward the centre?

## 2026-11-24: the register projectors truncate toward the centre

`[Established]` for the instructions, static, in the unpatched image (`mise run re-tool -- disasm 0x9CF1 0x9DB5`, `0xAE67 0xB011` and `0xB80E 0xB83A`; the Patch #3 image not read, nothing traced live).

- **Question**: How do the projectors that write a register's screen words (`+6`, `+8`), which the polygon walks and the line routines read, turn a view point into a pixel: truncated, floored or rounded?
- **Method**: read both register projectors `0x9100` can put in `work:0x8082`, `0x9CF1` (no outcode) and `0x9D3A` (the clipping variant), and the anchor transform `0xAE67`, which projects the anchors a ground leaf (`0xBF23`, called at `0xBF45`) and `OP_TAP` (`0xAD88`) read.
- **Result**:
  - `0x9CF1`, column (`0x9D05..0x9D13`): `DX:AX` is the view `x'` shifted left 8 (`mov dh,al; mov al,ah; cbw; xchg dx,ax; xor al,al`), then `idiv bp` by the depth `z'`, then `add ax,[41C8h]`, stored at `[di+6]`.
    Row (`0x9D16..0x9D2B`): the same for `y'` with `[41CAh]`, stored at `[di+8]`.
  - `0x9D3A`, for an unflagged register: the same sequence, column at `0x9D69..0x9D77` and row at `0x9D7A..0x9D88`.
  - `idiv` truncates its quotient toward zero, and nothing adjusts it before the centre is added, so each screen word is `trunc(256 · x' / z') + work:0x41C8` and `trunc(256 · y' / z') + work:0x41CA`: the offset from the projection centre (160, 92) truncated toward that centre, as the disc generator `0xA08E` does ([`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) section 8.8).
  - `0xAE67` (`SI` four bytes before the anchor record): turns the anchor's words `[si+4]`, `[si+6]`, `[si+8]` by the view matrix `work:0x80C0..0x80D0` and adds the translation `work:0x41D4..0x41DE`, storing `x'`, `y'`, `z'` as dwords at `[si+0Ah]`, `[si+0Eh]`, `[si+12h]` (`0xAE67..0xAF02`).
    It writes an outcode at `[si+1Eh]` (`0xAF03..0xAF84`: 1 for `z' < 0`, 2 and 4 for `x' ≥ z'` and `x' < −z'`, 8 and 16 the same for `y'`) and returns without projecting unless it is 0.
    Otherwise `0xB80E` shifts the dword `z'` right by the fewest bits `n` that leave it under 2^15, returning it in `AX` (`bp`) and `n` in `CL`; each of `x'` and `y'` is shifted left `8 − n` bits (`0xAFD0..0xB006`) or, for `n ≥ 8`, right `n − 8` bits, arithmetically (`0xAF91..0xAFC5`), divided by `idiv bp`, and the centre added: column `[si+16h]` = quotient + `work:0x41C8` (`0xAFA7`, `0xAFE8`), row `[si+1Ah]` = quotient + `work:0x41CA` (`0xAFC5`, `0xB006`).
    With `z' < 2^15` (`n = 0`) that is the register projectors' `trunc(256 · x' / z')` exactly; a deeper point loses `z'`'s low `n` bits, and for `n > 8` `x'`'s and `y'`'s low bits, floored, before the same truncating `idiv`.
    So a ground leaf's unclipped vertex and a tapped anchor are truncated toward the centre too.
  - Not read: how the clippers place a vertex where an edge crosses the view's side, `0xC6AF` for the SOD VM and `0xBF82` for a ground leaf.
  - The fillers take these words as pixel indices: the flat filler `0x7571` fills from the top row to the bottom row inclusive ([`sod-vm-lines-spans.md`](../../../research/playone-exe/sod-vm-lines-spans.md) section 8.11).
    So a vertex PLAYONE puts at pixel `(X, Y)` corresponds, in a renderer that samples pixel centres, to the point `(X + 0.5, Y + 0.5)` pixels from the view's top-left corner.
- **What it predicts for ours.**
  Our projection puts the optical axis at `(160, 92.5)` pixels from the top-left of the 320 × 185 view (half of each side), so a vertex `o` pixels off the axis lies at `(160 + o.x, 92.5 + o.y)`.
  PLAYONE's lies at `(160 + trunc(o.x) + 0.5, 92 + trunc(o.y) + 0.5)`.
  The difference is `trunc(o.y) − o.y` rows: between 0 and −1 below the centre (PLAYONE's edges higher, the `dy = −1` of #990), between 0 and +1 above it.
  Across columns it is `trunc(o.x) − o.x + 0.5`: between −0.5 and +0.5 right of the centre, +0.5 to +1.5 left of it.
  The centre alone, without truncation, moves nothing vertically (PLAYONE's row 92 is centred on our 92.5) and half a column right.

## 2026-11-24: PLAYONE's projector rounding on the evidence track

`[Bounded Observation]`

- **Question**: Does placing every projected vertex where the register projectors put it raise the reference films?
- **Track**: evidence-backed, image offsets `0x9CF1..0x9D2B` and `0x9D3A..0x9D88` (the entry above).
- **Variants** (`DBG_PROJ_SNAP`, not committed; the vertex shader `snap_vertex` moves each projected vertex in front of the eye, a line corner's two endpoints before the line is widened, and leaves disc rims to `snap_disc`):
  - `0`: baseline, as `main` draws.
  - `1`: the read: `(floor(cx) + trunc(o.x) + 0.5, floor(cy) + trunc(o.y) + 0.5)` pixels, with `(cx, cy)` = `(160, 92.5)` our axis and `o` the vertex's offset from it.
  - `2`: PLAYONE's centre without truncation: `(160.5 + o.x, 92.5 + o.y)`, half a column right.
- **Target frames**, echoed by the sweep; attribution only on this track: four of the six ticks #990's `register` classifies `page` or `either` with a page shift of `dx = 0, dy = −1` ([`register-backdrop.txt`](../990_bg-misregistration/register-backdrop.txt)), one per film that has one: `balloon` 540, `bomb` 331 and `location` 683 are `page`, `traintnl` 12 is `either` (its best time offset, +4, is at the search's reach); `traintnl` 452 (`either`) and 1233 (`page`) were left out, `--target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540`.
- **Command**: `mise run sweep -- --var DBG_PROJ_SNAP=0,1,2 --track evidence --record work/2026-11/1027_projection-truncation --topic projector rounding --images work/2026-11/1027_projection-truncation/images` with the targets above, on the GPU.
- **Result** (GPU, `NVIDIA GeForce RTX 4070 Laptop GPU`; every variant built from `main` at `d4f00c76` with the uncommitted switch; figures in [`sweeps/projector-rounding.toml`](sweeps/projector-rounding.toml)): none adopts.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location |
  |---|---|---|---|---|---|---|---|
  | `0` | 0.9385 | 0.8833 | 0.9245 | 0.9059 | 0.9107 | 0.8949 | 0.8727 |
  | `1` | 0.9473 | 0.8940 | 0.9361 | 0.9069 | 0.9178 | 0.9090 | 0.8862 |
  | `2` | 0.9363 | 0.8777 | 0.9239 | 0.9034 | 0.9075 | 0.8958 | 0.8719 |

  - `1`, the read, raises every film's `mean_ssim_scored` (+0.0010 `balloon` to +0.0141 `bomb`), and the frame-mean index agreement on every film but `bomb` (+0.0014 to +0.0073; `bomb` −0.0021), but a target frame falls past the 0.025 bound: `balloon` 540 by 0.0528 SSIM.
    Its other targets: `traintnl` 12 −0.0184, `location` 683 −0.0102, `bomb` 331 +0.0157.
    Its worst frames are `intro` 3136 (−0.1110) and 3081, and `balloon` 595, 584, 573, 507 and 562 (−0.065 to −0.078).
    `bomb`'s mask IoU falls from 0.9660 to 0.9486.
  - `2`, the centre alone, lowers six films (`intro` by 0.0056, past the film-mean guard).
  - **Why `1` fails at `balloon` 540.**
    `mise run frame -- --film balloon --ticks 540 --var DBG_PROJ_SNAP=0,1` draws a band of water between the grass and the hills, about six rows deep, that neither the capture nor the baseline shows; column 30 rows 134 to 139 read layer 1 (ocean), index 208, where the baseline has terrain, index 162.
    The ocean is painted on the ground plane before the terrain ([`render-model.md` § 3](../../../research/parity/render-model.md#3-where-we-imitate-the-painter)), and the terrain there lies in the same plane: snapping each mesh's vertices on its own moves each triangle's depth plane by up to a pixel's depth step, which near the horizon is large, so the ocean wins pixels the tie gave the terrain.
    That is our depth buffer misapplying the rule, not the rule: `PLAYONE` paints, with no depth test.
    The figures' worst frames were not each looked at.

## 2026-11-24: the projector rounding with coplanar ground kept coplanar

`[Bounded Observation]`

- **Question**: With every snapped vertex kept on the horizontal world plane it lies in, so that surfaces in one horizontal plane stay coplanar, does the rule adopt?
- **Track**: evidence-backed, the same offsets; this round corrects how the renderer applies the rule, not the rule.
- **Variant** `3` (`DBG_PROJ_SNAP=3`, not committed): the pixel of variant `1`, reached by moving the vertex along the ray through that pixel to the world height `y` it had, instead of keeping its view depth; when the ray does not meet that plane in front of the eye it falls back to `1`.
  `mise run frame -- --film balloon --ticks 540 --var DBG_PROJ_SNAP=0,1,3` shows no water band under `3`.
- **Target frames**: the same four, `--target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540`.
- **Command**: `mise run sweep -- --var DBG_PROJ_SNAP=0,1,3 --track evidence --record work/2026-11/1027_projection-truncation --topic projector rounding on plane --images work/2026-11/1027_projection-truncation/images` with the targets above, on the GPU.
- **Result** (GPU, the same adapter, `d4f00c76` with the switch; figures in [`sweeps/projector-rounding-on-plane.toml`](sweeps/projector-rounding-on-plane.toml)): `3` adopts by the rule's winner line, `winner: DBG_PROJ_SNAP=3 adopts (evidence, film means; target idx +0.0032 attribution; worst target frame -0.0185 traintnl:12; 334 frames down >0.005, listed)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location |
  |---|---|---|---|---|---|---|---|
  | `0` | 0.9385 | 0.8833 | 0.9245 | 0.9059 | 0.9107 | 0.8949 | 0.8727 |
  | `3` | 0.9436 | 0.8938 | 0.9310 | 0.9124 | 0.9171 | 0.9054 | 0.8824 |

  - `balloon` 540 rises 0.0205 SSIM under `3` (0.8851 to 0.9055), against −0.0528 under `1`.
  - **Not taken: a defect the verdict does not see.**
    `bomb`'s mask IoU falls from 0.9660 to 0.9486 under both `1` and `3`.
    Rescoring `bomb` alone (`mise run parity -- --films bomb`, with and without `DBG_PROJ_SNAP=3`): 22 frames, the film's opening shot from tick 12, each lose 0.328 IoU.
    `mise run frame -- --film bomb --ticks 12 --var DBG_PROJ_SNAP=0,3` draws the grass below the church as ocean.
    The far corners of the ground lie a fraction of a row below the axis, so they snap onto the axis row, whose ray never meets the ground plane; they fall back to `1`'s snap at their own view depth, and the ocean wins the tie again.
    So `3` still misapplies the rule there, and is not taken.

## 2026-11-24: the projector rounding with an unsnapped fallback

`[Bounded Observation]`

- **Question**: Does `3` adopt with a vertex whose snapped ray misses its horizontal plane left where it projects, unsnapped?
- **Track**: evidence-backed, the same offsets; the third and last round of the [loop's cap](../../../.agents/skills/running-unattended/loop-and-bounds.md#implementing-an-issue-and-bounding-rounds).
- **Variant** `4` (`DBG_PROJ_SNAP=4`, not committed): `3`, except that a vertex whose ray through the snapped pixel does not meet its plane in front of the eye keeps its own projection.
  `mise run frame -- --film bomb --ticks 12 --var DBG_PROJ_SNAP=0,3,4` draws the grass under `4`.
- **Target frames**: the same four, `--target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540`.
- **Command**: `mise run sweep -- --var DBG_PROJ_SNAP=0,3,4 --track evidence --record work/2026-11/1027_projection-truncation --topic projector rounding unsnapped fallback --images work/2026-11/1027_projection-truncation/images` with the targets above, on the GPU.
- **Result** (GPU, the same adapter, `d4f00c76` with the switch; figures in [`sweeps/projector-rounding-unsnapped-fallback.toml`](sweeps/projector-rounding-unsnapped-fallback.toml)): `4` adopts, `winner: DBG_PROJ_SNAP=4 adopts (evidence, film means; target idx +0.0045 attribution; worst target frame -0.0185 traintnl:12; 330 frames down >0.005, listed) (noise floor +/-0.002; winner is ~within noise)`; the noise note is `4`'s margin over `3`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location |
  |---|---|---|---|---|---|---|---|
  | `0` | 0.9385 | 0.8833 | 0.9245 | 0.9059 | 0.9107 | 0.8949 | 0.8727 |
  | `4` | 0.9437 | 0.8939 | 0.9309 | 0.9124 | 0.9171 | 0.9061 | 0.8826 |

  - `bomb`'s mask IoU is 0.9693 under `4`, against 0.9660 at the baseline and 0.9486 under `3`.
  - The worst movers are a run on `location` from tick 3334 to 3422 (−0.0716 to −0.0298 SSIM), `balloon` 298 (−0.0561) and `ctry` 331 (−0.0394).
    At `location` 3334 the capture draws a near bank at the left that neither render has, and the snapped render draws less of the dark slope our baseline puts in its place; the others were not attributed.
  - Pictures (capture, baseline, `4`; both render panels from `d4f00c76` with the switch): the targets [`traintnl` 12](images/traintnl-12-projector-rounding-unsnapped-fallback.png), [`bomb` 331](images/bomb-331-projector-rounding-unsnapped-fallback.png), [`location` 683](images/location-683-projector-rounding-unsnapped-fallback.png) and [`balloon` 540](images/balloon-540-projector-rounding-unsnapped-fallback.png), and the worst mover [`location` 3334](images/location-3334-projector-rounding-unsnapped-fallback-guard.png); the sweeps' other pictures were not kept.
- **The gate.**
  Shipping `4` as written failed two GPU tests: `draw_order::a_decal_wins_over_its_base_near_and_far` (a decal on a facet tilted 35 degrees about the vertical lost to its base near the eye, since sliding along the horizontal plane takes a non-horizontal facet's vertices off its plane) and `lines::only_a_front_facing_polygon_draws_its_outline` (the outline cull compared snapped edge ends with an unsnapped apex).
  The shipped shader therefore slides each vertex in its own facet's plane (its normal, or for an outline corner the plane of its edge and apex; world up for a line, a degenerate facet or a shadow), which is `4`'s horizontal plane for ground facets, snaps the outline's apex too, and draws a segment whose two ends share a pixel as that pixel, as the spans draw a polygon on one row (`0xCAB4`).
  At 5000 m the test's triangle lies within one pixel, which `PLAYONE` draws whatever its winding, so the cull test now runs at 1500 m and a new test checks the one pixel.

## 2026-11-24: the shipped projector rounding against main

`[Bounded Observation]`

- **Question**: Does the shader as shipped, which differs from `4` as the entry above says, adopt against `main`?
- **Track**: evidence-backed, the same offsets; the fourth and last round the parity loop allows, a confirmation of the adopted rule as the gate required it to be drawn.
- **Variants** (`DBG_PROJ_MAIN`, not committed): `1`, `main`'s projection (the baseline: `playone_vertex` returns the vertex unmoved and the one-pixel segment rule is off); `0`, the shipped shader.
- **Target frames**: the same four, `--target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540`.
- **Command**: `mise run sweep -- --var DBG_PROJ_MAIN=1,0 --track evidence --record work/2026-11/1027_projection-truncation --topic projector rounding shipped --images work/2026-11/1027_projection-truncation/images` with the targets above, on the GPU.
- **Result** (GPU, the same adapter; both built from the shipped shader on `d4f00c76` with the uncommitted switch, which `1` turns off; `f2e12e39` commits that shader without the switch; figures in [`sweeps/projector-rounding-shipped.toml`](sweeps/projector-rounding-shipped.toml)): none adopts, `winner: none adopts (best DBG_PROJ_MAIN=0: film-mean guard balloon -0.0043)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location |
  |---|---|---|---|---|---|---|---|
  | `1` (main) | 0.9385 | 0.8833 | 0.9245 | 0.9059 | 0.9107 | 0.8949 | 0.8727 |
  | `0` (shipped) | 0.9458 | 0.8952 | 0.9331 | 0.9016 | 0.9169 | 0.9049 | 0.8805 |

  - Six films rise, by more than under `4` on `ctry`, `intro` and `land`; `balloon` falls 0.0043, where `4` raised it 0.0065.
    44 of `balloon`'s 107 scored frames fall by more than 0.005 and 28 rise by more; its worst are 298 (−0.0572), 1156 (−0.0394), 628 (−0.0387) and 111 (−0.0358).
  - At `balloon` 1156, by eye in `mise run frame -- --film balloon --ticks 1156,628 --var DBG_PROJ_MAIN=1,0`, the river on the slope left of the balloon loses part of its length; at 628 the difference is a few pixels of the balloon's bands.
    Its worst mover is pictured in [`balloon` 298](images/balloon-298-projector-rounding-shipped-guard.png) (capture, `main` at `d4f00c76`, shipped as at `f2e12e39`).
    `[Hypothesis]`, not tested: the river is a flat prop snapped onto sloped terrain ([`world-scene-residuals.md`](../../../research/playone-exe/world-scene-residuals.md) section 6), whose own normal is not its terrain facet's, so it slides off the terrain's plane and loses the decal tie that the horizontal plane of `4` kept.
  - This is the parity loop's fourth round and the implementer's cap, so the renderer change is not shipped.
    The shipped form, with no switch and the gate passing, is on `proto/1027-projector-rounding` at `f2e12e39`.

## Handoff

- **Established**: the register projectors and the anchor transform `0xAE67` truncate each unclipped vertex's screen offset toward the projection centre (first entry); the clippers' crossing points were not read, now in [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre).
- **Measured**: drawing vertices on those pixels lifts every reference film by 0.005 to 0.011 when coplanar ground keeps its depth tie (`4`); `parity_probe.py register` was not rerun on #990's ticks, since nothing was adopted.
  No form both passed the gate and adopted: the depth buffer has to keep every tie the painter's order makes, on horizontal and tilted facets, decals and outlines alike.
- **Next**: [#1064](https://github.com/neilsh/stunt-reel/issues/1064), which starts from the prototype branch.
