# Journal: the `land` 617 hangar band

## 2026-11-26: the hangar is a world prop and the band a decal on its wall

`[Bounded Observation]`

- **Question**: Is the hangar whose wall band `land` 617 loses under #1099's shader ([its third entry](../1064_projector-vertex-truncation/journal.md#2026-11-25-the-world-mesh-and-near-horizontal-shape-facets-together)) a world prop, and is the band a decal on a steep facet of it?
- **Method**: `mise run parity -- --films land --software-only` on `main` at `c2b23b4b` (`crates/` tree `57fa24d`), on lavapipe (`llvmpipe (LLVM 20.1.2, 256 bits)`), which reproduced the pinned `land` SSIM 0.9310; a scratch script read tick 617's index, layer and shape planes of that render over the hangar (columns 0 to 109, rows 5 to 71) and the capture's indices there; a scratch example (not committed) printed shape 522's decoded triangles from `LAND.ALL` (`stunt_core::sod::decode_sod`, lenient, no anchors) with their palette index, flags and normal.
- **Result**:
  - Of the region's 7,370 pixels, 6,352 lie on layer 3, the world props' (scenery class `SCENERY_PROP`), and 6,173 of those carry shape word 522; the other 1,018 are terrain (layer 2).
  - Sampled every second row and eighth column, the capture's wall is palette index 162 on rows 30 to 44 and 149 above and below them; our render draws 149 on all of those rows.
  - Shape 522 draws its long walls (`z = ±12`, normal along z, so vertical) in 149 and, after them, two stripes in 162 on each long wall, `y` 1.947 to 3.896 and 5.195 to 6.495, flagged decal (`flags` bit 0); the decoder flags them coplanar with the wall drawn before them.
  - So the band is the lower 162 stripe, a decal on a vertical facet of a world prop: the case #1099's shader slides horizontally because its vertex is a world-mesh vertex (`slide_normal` returns world up for any `scenery_class` other than 0), so each vertex of the wall and of the stripe leaves the wall's plane by its own amount and the depth tie between them breaks, as it did for #1027's horizontal-plane form.
- **Verdict**: control; it decides the next entry's hypothesis.
- **Lives in**: [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre).

## 2026-11-26: a world prop's steep facet slides in its own plane

`[Bounded Observation]`

- **Question**: Does the shipped form adopt when a world prop's facet follows the shape rule (horizontal within about 26 degrees of horizontal, its own plane otherwise) while terrain and ocean keep sliding horizontally?
- **Why**: the entry above puts the `land` 617 band on a vertical facet of a world prop; a decal and its base share their facet's plane, so sliding both in it keeps their tie, as the steep-facet shape test shows; the river, the flat prop #1064's world-mesh rule was for, is near horizontal and keeps sliding horizontally under the threshold.
- **Track**: evidence-backed, offsets as in #1064 (`0x9CF1`, `0x9D3A`, `0xAE67`).
- **Variants** (`DBG_PROPSLIDE`, not committed, substituted into `mode13h.wgsl` when the pipeline is built): `0`, `main`; `1`, `slide_normal` treats a `SCENERY_PROP` vertex as a shape facet.
- **Target frames**: `--target land:617-617`.
- **Command**: `mise run sweep -- --var DBG_PROPSLIDE=0,1 --track evidence --record work/2026-11/1100_land-617-hangar-decal --topic "prop facets in their plane" --images work/2026-11/1100_land-617-hangar-decal/images --target land:617-617` with `VK_DRIVER_FILES` naming only the lavapipe ICD.
- **Result** (lavapipe, `llvmpipe (LLVM 20.1.2, 256 bits)`; `main` at `c2b23b4b` (`crates/` tree `57fa24d`) with the uncommitted switch; figures in [`sweeps/prop-facets-in-their-plane.toml`](sweeps/prop-facets-in-their-plane.toml)): none adopts, `winner: none adopts (best DBG_PROPSLIDE=1: film-mean guard location -0.0022)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9439 | 0.9069 | 0.9310 | 0.9067 | 0.9164 | 0.9080 | 0.8967 | 0.9157 |
  | `1` | 0.9443 | 0.9067 | 0.9343 | 0.9067 | 0.9171 | 0.9068 | 0.8945 | 0.9158 |

  - `land` rises by 0.0033 and frame 617 by 0.0102 SSIM: the band is back ([picture](images/land-617-prop-facets-in-their-plane.png), capture, `main`, `1`).
  - `location` falls by 0.0022, past the 0.002 guard, `bomb` by 0.0012 and `intro` by 0.0002; 238 frames fall by more than 0.005, 213 of them `location`'s and the worst `location` 2059 (−0.0301).
  - On `location` 2059 (a `mise run frame` render of both variants), every pixel the variants draw differently lies on the props layer; of the 1,582, `main` matches the capture on 907 and `1` on 298.
    The 907 lie scattered a pixel or two wide along prop edges over the lower two thirds of the view, with a few runs along rows; by the shape `main` drew there, shape 997 (the town lots, flat on the ground) loses the most, 186, and buildings (1662, 1659, 1660) the next most.
    A vertex keeps its pixel under either slide, so only depth order changes.
    `[Inference]`: a steep facet's foot, slid in the facet's plane, no longer lies in the horizontal plane its ground-level neighbours slid in, so the flat prop under it covers or uncovers its lowest row; the pixels were not traced to single facets.
  - Pictures (capture, `main`, `1`) of each film's worst frame, as the sweep drew them: [`location` 2059](images/location-2059-prop-facets-in-their-plane-guard.png), [`bomb` 2949](images/bomb-2949-prop-facets-in-their-plane-guard.png), [`ctry` 826](images/ctry-826-prop-facets-in-their-plane-guard.png), [`land` 837](images/land-837-prop-facets-in-their-plane-guard.png), [`traintnl` 1145](images/traintnl-1145-prop-facets-in-their-plane-guard.png).
- **Verdict**: rejected by the film-mean guard (`location` −0.0022).
- **Lives in**: [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre), Ruled out.

## 2026-11-26: only a decal's plane slides in its own plane

`[Bounded Observation]`

- **Question**: Does the shipped form adopt when only a world prop's steep facets that share a plane with a decal, the decal and the facets before it that it is coplanar with, slide in their own plane, every other world-mesh vertex horizontally?
- **Why**: the entry above restores the band but loses each wall's foot on the flat prop under it; a wall carrying no decal has no tie to keep in its own plane, so it can keep the horizontal slide its foot shares with the ground.
- **Track**: evidence-backed, as above.
- **Variants** (`DBG_PROPSLIDE`, not committed): `0`, `main`; `2`, `identify_coplanar_decals` sets bit `0x80` of `flags` on every filled decal and every earlier filled polygon coplanar with it, and `slide_normal` treats a `SCENERY_PROP` vertex with that bit as a shape facet.
- **Target frames**: `--target land:617-617`.
- **Command**: `mise run sweep -- --var DBG_PROPSLIDE=0,2 --track evidence --record work/2026-11/1100_land-617-hangar-decal --topic "decal planes in their plane" --images work/2026-11/1100_land-617-hangar-decal/images --target land:617-617` with `VK_DRIVER_FILES` naming only the lavapipe ICD.
- **Result** (lavapipe, as above; figures in [`sweeps/decal-planes-in-their-plane.toml`](sweeps/decal-planes-in-their-plane.toml)): `2` adopts, `winner: DBG_PROPSLIDE=2 adopts (evidence, film means; target idx +0.0268 attribution; worst target frame +0.0102 land:617; 70 frames down >0.005, listed)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9439 | 0.9069 | 0.9310 | 0.9067 | 0.9164 | 0.9080 | 0.8967 | 0.9157 |
  | `2` | 0.9440 | 0.9069 | 0.9339 | 0.9067 | 0.9161 | 0.9072 | 0.8970 | 0.9160 |

  - `land` rises by 0.0029 and frame 617 by 0.0102, with the band back ([picture](images/land-617-decal-planes-in-their-plane.png)); `location` now rises by 0.0003, but `bomb` falls by 0.0008, `traintnl` by 0.0003 and `intro` by 0.00002, so a film mean still falls, which #1100 does not allow.
  - The `bomb` frames listed include 19 of the static opening shot, from tick 221 to 420, each −0.0082 ([tick 254](images/bomb-254-decal-planes-in-their-plane-guard.png)). On tick 254 (a `mise run frame` render of both variants), 198 pixels differ, all on the props layer; `main` matches the capture on 193 of them and `2` on 3, and 184 are shape 1651's, drawn in index 164 where the capture and `main` draw 59, in one band of eight rows across the view.
    Shape 1651 (`SUPERSET.ALL`) has a decal in 59 on the vertical plane `x = −6`, `y` 3 to 6, which the decoder pairs with the wall in that plane below it, `y` 0 to 3, though the two only touch along `y = 3`, and a flat polygon at `y = 3` beside them.
    `[Inference]`: with the decal and wall sliding in their plane, the decal's foot no longer lies in the horizontal plane the flat polygon at `y = 3` slid in, and that polygon wins the row, as a steep facet's foot did in the entry above.
  - Pictures (capture, `main`, `2`) of the other films' worst frames: [`ctry` 848](images/ctry-848-decal-planes-in-their-plane-guard.png), [`location` 2927](images/location-2927-decal-planes-in-their-plane-guard.png), [`land` 837](images/land-837-decal-planes-in-their-plane-guard.png), [`traintnl` 1145](images/traintnl-1145-decal-planes-in-their-plane-guard.png).
- **Verdict**: adopts by the rule, but not shipped: it lowers `bomb`, `traintnl` and `intro`.
- **Lives in**: [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre), Ruled out.

## 2026-11-26: only a decal that overlaps its base

`[Bounded Observation]`

- **Question**: Does `2` stop lowering a film mean when a decal and the earlier polygons it is coplanar with slide in their plane only where the decal overlaps one of them within that plane, not where their bounds only touch along an edge?
- **Why**: the entry above traces `bomb`'s fall to a decal that only touches its wall; a decal drawn over a wall, like the hangar's stripe, overlaps it.
- **Track**: evidence-backed, as above; the third and last round of the [loop's cap](../../../.agents/skills/running-unattended/loop-and-bounds.md#implementing-an-issue-and-bounding-rounds).
- **Variants** (`DBG_PROPSLIDE`, not committed): `0`, `main`; `3`, `2` with the pair counted only when their bounds overlap by more than the plane tolerance (1e-4 m) along both axes other than the one nearest the decal's normal.
- **Target frames**: `--target land:617-617`.
- **Command**: `mise run sweep -- --var DBG_PROPSLIDE=0,3 --track evidence --record work/2026-11/1100_land-617-hangar-decal --topic "overlapping decal planes in their plane" --images work/2026-11/1100_land-617-hangar-decal/images --target land:617-617` with `VK_DRIVER_FILES` naming only the lavapipe ICD.
- **Result** (lavapipe, as above; figures in [`sweeps/overlapping-decal-planes-in-their-plane.toml`](sweeps/overlapping-decal-planes-in-their-plane.toml)): `3` adopts, `winner: DBG_PROPSLIDE=3 adopts (evidence, film means; target idx +0.0268 attribution; worst target frame +0.0102 land:617; 5 frames down >0.005, listed)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9439 | 0.9069 | 0.9310 | 0.9067 | 0.9164 | 0.9080 | 0.8967 | 0.9157 |
  | `3` | 0.9441 | 0.9069 | 0.9340 | 0.9067 | 0.9160 | 0.9083 | 0.8975 | 0.9162 |

  - `land` rises by 0.0030 and frame 617 by 0.0102, with the band back ([picture](images/land-617-overlapping-decal-planes-in-their-plane.png)); `location` rises by 0.0008, `bomb` by 0.0002 and `ctry` by 0.0002, and `bomb`'s opening shot no longer falls.
  - `traintnl` falls by 0.0004 and `intro` by 0.00002, so a film mean still falls; five frames fall by more than 0.005, the worst `traintnl` 1145 (−0.0084, [picture](images/traintnl-1145-overlapping-decal-planes-in-their-plane-guard.png)), then `location` 3125 (−0.0082, [picture](images/location-3125-overlapping-decal-planes-in-their-plane-guard.png)), `land` 837 (−0.0073, [picture](images/land-837-overlapping-decal-planes-in-their-plane-guard.png)), `traintnl` 914 and 1156.
  - On `traintnl` 1145 (a `mise run frame` render of both variants), 264 pixels differ; `main` matches the capture on 246 and `3` on 15; 255 of the 264 are shape 1523's in `main`, a structure behind the biplane whose front wall (index 148, the plane `x = −2`) carries an arch decal (index 3) that overlaps it, between two side walls (73 and 77) whose normals lie 57 degrees from the front wall's, steep and undecorated.
    176 of the lost pixels are the front wall's 148 drawn as a side wall's 73 or 77: with the front wall sliding in its plane and the side walls horizontally, the corners they share slide to different depths, and the side walls cover the front wall's edges.
- **Verdict**: adopts by the rule, but not shipped: it lowers `traintnl` and `intro`, which #1100 does not allow.
- **Lives in**: [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre), section 10.

## Handoff

- **Found**: the `land` 617 band is the lower 162 stripe of shape 522, a decal on a vertical wall of a world prop, lost because every world-mesh vertex slides horizontally (first entry).
  `draw_order::a_decal_on_a_steep_world_prop_facet_wins_over_its_base_near_and_far`, a decal on a steep facet of a world prop, fails on `main` on lavapipe (`near: [0.0, 0.0, 0.0] at pixel (160, 120) shows Some(40), expected index 15`) and passes with `DBG_PROPSLIDE=1`; it is in the switch patch, not committed, since it fails on `main`.
- **Not shipped**: none of the three forms keeps every film mean; each lost tie is a facet that now slides in its plane meeting one that still slides horizontally: a wall's foot and the flat prop under it (`1`), a decal's foot and a flat polygon (`2`), a decorated wall and its undecorated neighbours (`3`).
  `3` is the best: every film but `traintnl` (−0.0004) and `intro` (−0.00002) rises or holds, and it adopts by the rule; shipping it is a choice for the maintainer, since #1100 asks for no film mean to fall.
- **Switch**: [`switches/DBG_PROPSLIDE.diff`](switches/DBG_PROPSLIDE.diff), against `main` at `c2b23b4b` (`crates/` tree `57fa24d`): the shader switch, the decoder's `0x80` marking for `2` and `3`, and the test.
- **Open**: a form whose shared corners slide to one point, such as sliding every steep facet of a decorated prop in its plane, or a decal tie kept by the decal pass rather than by the slide.
