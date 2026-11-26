# Journal: the `land` 617 hangar decal fix

## 2026-11-26: every steep facet of a decorated world prop slides in its own plane

`[Bounded Observation]`

- **Question**: Does the band come back with no film mean falling when every steep facet of a world prop whose shape carries a decal slides in its own plane, its near-horizontal facets and every undecorated prop horizontally (#1127's first form)?
- **Why**: [#1100's third entry](../1100_land-617-hangar-decal/journal.md#2026-11-26-only-a-decal-that-overlaps-its-base) lost `traintnl` 1145 where a decorated wall sliding in its plane met undecorated side walls of the same prop sliding horizontally; sliding the whole prop's steep facets in their planes gives those shared corners one rule.
- **Track**: evidence-backed, offsets as in #1064 (`0x9CF1`, `0x9D3A`, `0xAE67`).
- **Variants** (`DBG_PROPSLIDE`, not committed; [#1100's switch](../1100_land-617-hangar-decal/switches/DBG_PROPSLIDE.diff) plus the marking below): `0`, `main`; `4`, `identify_coplanar_decals` sets bit `0x80` of `flags` on every polygon of a shape holding a filled decal, and `slide_normal` treats a `SCENERY_PROP` vertex with that bit as a shape facet; `5`, as `4`, but only for a shape where a filled decal overlaps a coplanar earlier polygon in its plane (variant `3`'s pairing).
- **Target frames**: `--target land:617-617`.
- **Command**: `mise run sweep -- --var DBG_PROPSLIDE=0,4,5 --track evidence --record work/2026-11/1127_land-617-decal-fix --topic "decorated props in their plane" --images work/2026-11/1127_land-617-decal-fix/images --target land:617-617` with `VK_DRIVER_FILES` naming only the lavapipe ICD.
- **Result** (lavapipe, `llvmpipe (LLVM 20.1.2, 256 bits)`; `main` at `30a6b54` with the uncommitted switch; figures in [`sweeps/decorated-props-in-their-plane.toml`](sweeps/decorated-props-in-their-plane.toml)): `winner: DBG_PROPSLIDE=4 adopts (evidence, film means; target idx +0.0267 attribution; worst target frame +0.0102 land:617; 205 frames down >0.005, listed) (noise floor +/-0.002; winner is ~within noise)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9439 | 0.9069 | 0.9310 | 0.9067 | 0.9164 | 0.9080 | 0.8967 | 0.9157 |
  | `4` | 0.9444 | 0.9068 | 0.9343 | 0.9067 | 0.9174 | 0.9064 | 0.8951 | 0.9159 |
  | `5` | 0.9439 | 0.9068 | 0.9338 | 0.9067 | 0.9174 | 0.9064 | 0.8954 | 0.9158 |

  - Change against `0` (the figures file's film `ssim`, unrounded): `4`: `ctry` +0.00045, `intro` −0.00010, `land` +0.00328, `traintnl` +0.00095, `bomb` −0.00164, `location` −0.00162; `5`: `ctry` +0.00000, `intro` −0.00010, `land` +0.00276, `traintnl` +0.00098, `bomb` −0.00162, `location` −0.00130; `balloon` −0.000005 under both.
  - The band is back on `land` 617 (+0.0102 SSIM under both, [picture](images/land-617-decorated-props-in-their-plane.png), capture, `main`, `4`), and `traintnl` now rises (+0.00095), where #1100's `3` lowered it; `[Inference]`: the decorated front wall of shape 1523 and the side walls sharing its corners, which `3` split, now slide by one rule (not traced).
  - `bomb` and `location` fall under both, so the bar fails: 205 frames fall by more than 0.005 under `4`, 136 of them on `location` and 63 on `bomb`; the worst is a run of `location`'s stadium, 4665 to 4830 (4665 −0.0273, [picture](images/location-4665-decorated-props-in-their-plane-guard.png)); the pixels were not traced.
    `bomb`'s opening shot (ticks 12 to 420) falls by 0.0055 to 0.0089 a frame, where #1100's `2` lost shape 1651's row ([`bomb` 2949](images/bomb-2949-decorated-props-in-their-plane-guard.png)).
    `[Inference]`: a decorated prop's steep foot now meets the flat ground or prop under it at another depth, the failure of #1100's `1`, on fewer props.
  - Other worst frames (capture, `main`, `4`): [`ctry` 826](images/ctry-826-decorated-props-in-their-plane-guard.png), [`land` 837](images/land-837-decorated-props-in-their-plane-guard.png), [`traintnl` 1145](images/traintnl-1145-decorated-props-in-their-plane-guard.png).
- **Verdict**: `4` adopts by the rule, but neither form ships: each lowers `bomb`, `location` and `intro`, which #1127 does not allow.
- **Lives in**: [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre), Ruled out.

## 2026-11-26: the decal pass pulls a world prop's steep decal toward the eye

`[Bounded Observation]`

- **Question**: Does the band come back with no film mean falling when the base keeps `main`'s horizontal slide and only the decal pass changes: a world prop's decal on a steep facet slides in its own plane and then moves toward the eye along its ray by the depth a horizontal slide could have moved its base (#1127's second form)?
- **Why**: every slide form so far broke a tie where a facet sliding in its plane met one sliding horizontally; leaving every base facet alone leaves those ties as `main` has them.
  A vertex keeps its pixel under any slide, so the decal covers the same pixels and only its depth moves.
  The bound: a horizontal slide moves a vertex along its ray to the horizontal plane through it, and the truncation turns the ray by up to about one row, angle `α`, so its depth moves by up to about `α / |u.y|` of its distance, `u` the unit ray; the decal vertex moves toward the eye by `pull · α / |u.y|` of its distance (at most 0.95 of it).
- **Track**: heuristic: no `PLAYONE` rule sets the margin; `PLAYONE` paints a decal after its base with no depth test, which the margin approximates.
- **Variants** (`DBG_PROPSLIDE`, not committed): `0`, `main`; `6`, a vertex flagged decal (bit `0x01`) of a `SCENERY_PROP` facet steeper than the shape rule's 26 degrees slides in its facet's plane and moves toward the eye by `pull = 1`; `7`, as `6` with `pull = 2`.
- **Target frames**: `--target land:617-617`.
- **Command**: `mise run sweep -- --var DBG_PROPSLIDE=0,6,7 --track heuristic --record work/2026-11/1127_land-617-decal-fix --topic "decal pass pulls steep prop decals" --images work/2026-11/1127_land-617-decal-fix/images --target land:617-617 --jobs 4` with `VK_DRIVER_FILES` naming only the lavapipe ICD.
- **Result** (lavapipe, as above; `main` at `30a6b54` with the uncommitted switch; figures in [`sweeps/decal-pass-pulls-steep-prop-decals.toml`](sweeps/decal-pass-pulls-steep-prop-decals.toml)): `winner: none adopts (best DBG_PROPSLIDE=6: film means short of +0.002 each or +0.004 on one; target branch needs 3 scored target frames, has 1)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9439 | 0.9069 | 0.9310 | 0.9067 | 0.9164 | 0.9080 | 0.8967 | 0.9157 |
  | `6` | 0.9431 | 0.9069 | 0.9344 | 0.9067 | 0.9154 | 0.9074 | 0.8977 | 0.9160 |
  | `7` | 0.9423 | 0.9069 | 0.9344 | 0.9067 | 0.9147 | 0.9072 | 0.8973 | 0.9156 |

  - Change against `0` (unrounded): `6`: `ctry` −0.00087, `land` +0.00342, `traintnl` −0.00101, `bomb` −0.00060, `location` +0.00097; `7`: `ctry` −0.00165, `land` +0.00334, `traintnl` −0.00171, `bomb` −0.00081, `location` +0.00062; `intro` rises by under 0.00001 and `balloon` holds under both.
  - The band is back on `land` 617 (+0.0098 SSIM, [picture](images/land-617-decal-pass-pulls-steep-prop-decals.png), capture, `main`, `6`), and no base facet moves, so `location` rises and `intro` holds.
  - `ctry`, `traintnl` and `bomb` fall, more under `7` than `6`: on `ctry` 848, the worst frame under `6` (−0.0215, [picture](images/ctry-848-decal-pass-pulls-steep-prop-decals-guard.png)), a red decal shows through the green slope in front of it, so the pulled decal beats nearer geometry, not only its base.
    The margin grows as `1 / |u.y|`, so it is largest on rays near the horizontal, as near the eye's height.
  - Other worst frames (capture, `main`, `6`): [`traintnl` 1178](images/traintnl-1178-decal-pass-pulls-steep-prop-decals-guard.png), [`bomb` 3422](images/bomb-3422-decal-pass-pulls-steep-prop-decals-guard.png), [`location` 3731](images/location-3731-decal-pass-pulls-steep-prop-decals-guard.png).
- **Verdict**: rejected; a smaller margin is the next entry.
- **Lives in**: [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre), Ruled out.

## 2026-11-26: a smaller decal-pass margin

`[Bounded Observation]`

- **Question**: Does the entry above's form keep the band without lowering a film mean when its margin is smaller, so a pulled decal no longer beats the nearer geometry in front of it?
- **Why**: `land` gained alike under `pull = 1` and `2` (+0.00342 and +0.00334), so the band may need less; `ctry` 848's loss is a decal beating a nearer slope, which a smaller margin avoids.
- **Track**: heuristic, as above; the third and last round of the [loop's cap](../../../.agents/skills/running-unattended/loop-and-bounds.md#implementing-an-issue-and-bounding-rounds).
- **Variants** (`DBG_PROPSLIDE`, not committed): `0`, `main`; `8`, `6` with `pull = 0.25`; `9`, `6` with the decal moved at most 2% of its distance toward the eye.
- **Target frames**: `--target land:617-617`.
- **Command**: `mise run sweep -- --var DBG_PROPSLIDE=0,8,9 --track heuristic --record work/2026-11/1127_land-617-decal-fix --topic "smaller decal pass margin" --images work/2026-11/1127_land-617-decal-fix/images --target land:617-617 --jobs 4` with `VK_DRIVER_FILES` naming only the lavapipe ICD.
- **Result** (lavapipe, as above; figures in [`sweeps/smaller-decal-pass-margin.toml`](sweeps/smaller-decal-pass-margin.toml)): `winner: none adopts (best DBG_PROPSLIDE=9: film means short of +0.002 each or +0.004 on one; target branch needs 3 scored target frames, has 1)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9439 | 0.9069 | 0.9310 | 0.9067 | 0.9164 | 0.9080 | 0.8967 | 0.9157 |
  | `8` | 0.9438 | 0.9069 | 0.9340 | 0.9067 | 0.9158 | 0.9073 | 0.8964 | 0.9159 |
  | `9` | 0.9439 | 0.9069 | 0.9342 | 0.9067 | 0.9157 | 0.9079 | 0.8973 | 0.9161 |

  - Change against `0` (unrounded): `8`: `ctry` −0.00010, `intro` +0.00001, `land` +0.00303, `traintnl` −0.00060, `bomb` −0.00069, `location` −0.00034; `9`: `ctry` −0.00004, `land` +0.00321, `traintnl` −0.00069, `bomb` −0.00011, `location` +0.00062, `intro` +0.000004; `balloon` holds under both.
  - The band is back on `land` 617 under both (+0.0132 SSIM, [picture](images/land-617-smaller-decal-pass-margin.png), capture, `main`, `9`).
  - `9`, the 2% cap, lists the fewest frames: 10 fall by more than 0.005, the worst `traintnl` 914 (−0.0121, [picture](images/traintnl-914-smaller-decal-pass-margin-guard.png)) and 1145 (−0.0120), the tunnel structure behind the biplane where #1100's `3` lost too; the pixels were not traced.
    `traintnl` still falls by 0.00069 and `bomb` by 0.00011, so the bar fails.
  - Other worst frames (capture, `main`, `9`): [`ctry` 848](images/ctry-848-smaller-decal-pass-margin-guard.png), [`land` 595](images/land-595-smaller-decal-pass-margin-guard.png), [`location` 2465](images/location-2465-smaller-decal-pass-margin-guard.png).
- **Verdict**: rejected; neither margin keeps every film mean.
- **Lives in**: [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre), Ruled out.

## Handoff

- **Not shipped**: both of #1127's forms bring the band back and lower some film mean on lavapipe.
  Sliding every steep facet of a decorated world prop in its plane (`4`, `5`) lowers `bomb` and `location` by up to 0.0016 each, `intro` by 0.0001 and `balloon` by 0.000005; a decal-pass margin (`6` to `9`) lowers `traintnl` by 0.0006 to 0.0017, `bomb` by 0.0001 to 0.0008 and `ctry` by 0.00004 to 0.0017.
  The closest of all is still #1100's `3` ([its entry](../1100_land-617-hangar-decal/journal.md#2026-11-26-only-a-decal-that-overlaps-its-base): `traintnl` −0.0004, `intro` −0.00002), then this folder's `9` (`traintnl` −0.00069, `bomb` −0.00011, `ctry` −0.00004).
- **Decision for the maintainer** (#1127 to `status:ready-for-human`): ship #1100's `3`, accepting `traintnl` −0.0004 and `intro` −0.00002 for `land` +0.0030, or leave the band.
- **Switch**: [`switches/DBG_PROPSLIDE.diff`](switches/DBG_PROPSLIDE.diff), against `main` at `30a6b54`: #1100's switch and test plus variants `4` to `9`.
  The steep world-prop decal test (`draw_order::a_decal_on_a_steep_world_prop_facet_wins_over_its_base_near_and_far`) stays in the patch, uncommitted, since it fails on `main` ([#1100's handoff](../1100_land-617-hangar-decal/journal.md#handoff)).

## 2026-11-26: #1100's variant `3` as the renderer's own rule

`[Bounded Observation]`

- **Question**: Does #1100's variant `3` ([its entry](../1100_land-617-hangar-decal/journal.md#2026-11-26-only-a-decal-that-overlaps-its-base)), written as the renderer's rule, score as it did in that sweep against today's `main`?
- **Why**: the owner chose to ship `3`, accepting its `traintnl` and `intro` falls, after the forms above did no better (handoff above).
- **Track**: evidence-backed, offsets as in #1064 (`0x9CF1`, `0x9D3A`, `0xAE67`).
- **Variants** (`DBG_TIE`, not committed): `0`, `main`'s slide (no vertex marked); `1`, the rule as committed: `decal_ties` puts each filled decal that overlaps an earlier coplanar filled polygon within their plane, and each such polygon, in a decal tie, which the tessellator stores in the vertex byte that was padding (`SodVertex::decal_tie`), and `slide_normal` slides a world prop's vertex in a decal tie as a shape facet.
  The flag bit `0x80` #1100's switch used is `VERTEX_FLAG_PRESHADED` on today's `main`, so the tie has its own byte.
- **Target frames**: `--target land:617-617`.
- **Command**: `mise run sweep -- --var DBG_TIE=0,1 --track evidence --record work/2026-11/1127_land-617-decal-fix --topic "decal ties in their plane" --images work/2026-11/1127_land-617-decal-fix/images --target land:617-617` with `VK_DRIVER_FILES` naming only the lavapipe ICD.
- **Result** (lavapipe, `llvmpipe (LLVM 20.1.2, 256 bits)`; `main` at `a8d0a066` with the rule and the uncommitted switch; figures in [`sweeps/decal-ties-in-their-plane.toml`](sweeps/decal-ties-in-their-plane.toml)): `1` adopts, `winner: DBG_TIE=1 adopts (evidence, film means; target idx +0.0268 attribution; worst target frame +0.0102 land:617; 5 frames down >0.005, listed)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9439 | 0.9069 | 0.9310 | 0.9067 | 0.9164 | 0.9080 | 0.8967 | 0.9157 |
  | `1` | 0.9441 | 0.9069 | 0.9340 | 0.9067 | 0.9160 | 0.9083 | 0.8975 | 0.9162 |

  - Against `0`: `land` +0.0030 (frame 617 +0.0102, the band back: [picture](images/land-617-decal-ties-in-their-plane.png)), `location` +0.0008, `bomb` +0.0002, `ctry` +0.0002, `balloon` unchanged; `traintnl` −0.0004 and `intro` −0.00002, the falls the owner accepted.
    Each film's change agrees with #1100's `3` to the fifth decimal.
  - The five frames down by more than 0.005 are those of `3`: `traintnl` 1145 (−0.0084, [picture](images/traintnl-1145-decal-ties-in-their-plane-guard.png)), `location` 3125 (−0.0082, [picture](images/location-3125-decal-ties-in-their-plane-guard.png)), `land` 837 (−0.0073, [picture](images/land-837-decal-ties-in-their-plane-guard.png)), `traintnl` 914 and 1156.
  - The switch is [`switches/DBG_TIE.diff`](switches/DBG_TIE.diff), against this PR's rule.
- **Verdict**: adopted, by the owner's decision to accept `traintnl` −0.0004 and `intro` −0.00002; the expected lavapipe scores are repinned on it.
  `draw_order::a_decal_on_a_steep_world_prop_facet_wins_over_its_base_near_and_far` pins the tie in the renderer, `decal_tests::a_decal_and_the_wall_it_overlaps_are_in_a_decal_tie` which polygons are tied, and `tessellate_tests::a_tied_polygon_keeps_its_own_vertices` the vertex byte.
- **Lives in**: [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre).
