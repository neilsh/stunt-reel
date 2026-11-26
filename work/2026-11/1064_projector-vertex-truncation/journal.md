# Journal: drawing vertices where PLAYONE's projector truncates them

## 2026-11-25: the world mesh slides in the horizontal plane, shapes in their facet's

`[Bounded Observation]`

- **Question**: Does the shipped form of [#1027](../1027_projection-truncation/journal.md#2026-11-24-the-shipped-projector-rounding-against-main), which slides each snapped vertex in its own facet's plane, adopt once the world mesh (terrain, ocean and props, scenery class 1 to 3) slides in the horizontal plane through the vertex, as `4` of #1027 did, while a shape's vertices keep their facet's plane?
- **Why this form**: `4` raised `balloon` by 0.0065 and failed `draw_order::a_decal_wins_over_its_base_near_and_far`, a shape's decal on a facet tilted about the vertical; the shipped form passes that test and lowers `balloon` by 0.0043.
  `[Hypothesis]`: the `balloon` loss is the river, a flat prop on sloped terrain, whose vertices slide in a horizontal plane while the terrain's facet slides in its tilted one, so their depth tie breaks; if so, giving the whole world mesh one plane (horizontal) restores it; whether a decal sits on a steep facet of a world prop, which that plane would break, was not checked.
- **Track**: evidence-backed, offsets as in #1027 ([`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)): `0x9CF1`, `0x9D3A`, `0xAE67`.
- **Variants** (`DBG_PROJ`, not committed; the shader of `proto/1027-projector-rounding` at `f2e12e39` rebased on `main`, whose camera uniform no longer holds `inv_rotation_proj`, so the ray through the snapped pixel comes from the projection's rows): `0`, `main`'s projection (baseline); `1`, the shipped form; `2`, `1` with every world-mesh vertex's slide plane horizontal.
- **Target frames**: the four of #1027, `--target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540`.
- **Command**: `mise run sweep -- --var DBG_PROJ=0,1,2 --track evidence --record work/2026-11/1064_projector-vertex-truncation --topic world horizontal --images work/2026-11/1064_projector-vertex-truncation/images` with the targets above, on the GPU.
- **Result** (GPU, RTX 4070 Laptop; `main` at `16483bbb` with the uncommitted switch; figures in [`sweeps/world-horizontal.toml`](sweeps/world-horizontal.toml)): none adopts, `winner: none adopts (best DBG_PROJ=2: film-mean guard balloon -0.0024)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location |
  |---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9385 | 0.8937 | 0.9248 | 0.9059 | 0.9107 | 0.8957 | 0.8863 |
  | `1` (shipped) | 0.9458 | 0.9083 | 0.9333 | 0.9016 | 0.9170 | 0.9070 | 0.8939 |
  | `2` (world horizontal) | 0.9440 | 0.9069 | 0.9311 | 0.9035 | 0.9163 | 0.9085 | 0.8967 |

  - `2` moves `balloon` from −0.0043 (`1`) to −0.0024 against `0`, so the world mesh's plane explains about 0.0019 of the loss; the other six films rise by 0.0055 to 0.0132 (under `1`, 0.0063 to 0.0146).
  - The guard fails by 0.0004, so the hypothesis is partly confirmed: the rest of `balloon`'s fall is not the world mesh's plane.

## 2026-11-25: facets near horizontal slide horizontally

`[Bounded Observation]`

- **Question**: Does `balloon` pass the guard when a facet close to horizontal, in the world mesh or a shape, slides in the horizontal plane through its vertices while a steeper one keeps its own plane?
- **Why**: [`4` of #1027](../1027_projection-truncation/journal.md#2026-11-24-the-projector-rounding-with-an-unsnapped-fallback) slid every vertex horizontally and raised `balloon` by 0.0065; a decal and its base, one plane, keep their tie under any plane they share, and the vertices of a near-horizontal facet leave its own plane little by sliding horizontally.
- **Track**: evidence-backed, as above.
- **Variants** (`DBG_PROJ`, not committed): `0`, `main`; `2`, as the entry above (the world mesh horizontal, every shape facet in its own plane); `3`, every facet of the world mesh or a shape whose normal is within about 26 degrees of vertical (|n.y| ≥ 0.9 |n|) slides horizontally, any other in its own plane; `4`, the same within 60 degrees (|n.y| ≥ 0.5 |n|).
- **Target frames**: as above.
- **Command**: `mise run sweep -- --var DBG_PROJ=0,2,3,4 --track evidence --record work/2026-11/1064_projector-vertex-truncation --topic "shape facets near horizontal" --images work/2026-11/1064_projector-vertex-truncation/images --target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540` on the GPU.
- **Result** (GPU, the same adapter; `main` at `16483bbb` with the uncommitted switch; figures in [`sweeps/shape-facets-near-horizontal.toml`](sweeps/shape-facets-near-horizontal.toml)): `3` adopts, `winner: DBG_PROJ=3 adopts (evidence, film means; target idx +0.0042 attribution; worst target frame -0.0185 traintnl:12; 327 frames down >0.005, listed) (noise floor +/-0.002; winner is ~within noise)`; the noise note is `3`'s margin over `2`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9385 | 0.8937 | 0.9248 | 0.9059 | 0.9107 | 0.8957 | 0.8863 | 0.9079 |
  | `2` | 0.9440 | 0.9069 | 0.9311 | 0.9035 | 0.9163 | 0.9085 | 0.8967 | 0.9153 |
  | `3` (26 degrees) | 0.9452 | 0.9066 | 0.9314 | 0.9052 | 0.9171 | 0.9073 | 0.8945 | 0.9153 |
  | `4` (60 degrees) | 0.9447 | 0.9069 | 0.9349 | 0.9107 | 0.9173 | 0.9066 | 0.8952 | 0.9166 |

  - `3` moves `balloon` to −0.0007 against `0`, inside the 0.002 the evidence track allows, and raises the other six films by 0.0064 (`traintnl`) to 0.0129 (`intro`); `2` to `3` recovers 0.0017 of `balloon`'s 0.0024, so the near-horizontal facets' plane explains most of what the world mesh's did not.
  - `4` scores a mean of 0.9166 against `3`'s 0.9153 (+0.0013) and, on `balloon`, +0.0048 against `main` where `3` is -0.0007, but the mean margin is inside the 0.002 noise floor; `ctry` and `bomb` sit 0.0005 and 0.0007 below `3`; a facet 60 degrees from horizontal moves further from the vertex's own plane than one 26 degrees from it, so `4` is left as an open threshold question in the note.
  - The worst movers are `balloon` 298 (−0.0572), `location` 2630 (−0.0421) and 6326 (−0.0392); `balloon` 298 was also `1`'s worst of #1027.
    `3` was not shipped, so these frames were not examined; the third round's movers, which are the shipped form's, are explained below.

## 2026-11-25: the world mesh and near-horizontal shape facets together

`[Bounded Observation]`

- **Question**: Does the form that combines the two rounds above, the whole world mesh sliding horizontally (`2`) and every near-horizontal shape facet sliding horizontally too (`3`'s threshold), adopt?
  It is the shader the implementation commits (`e5e4d689`), and it was not swept as such: `2` has the world mesh and `3` the threshold, each without the other.
- **Why**: `2` and `3` each recovered part of `balloon`'s fall against the facet-plane form (−0.0024 and −0.0007 against −0.0043), by different vertices.
- **Track**: evidence-backed, as above; the third and last round of the [loop's cap](../../../.agents/skills/running-unattended/loop-and-bounds.md#implementing-an-issue-and-bounding-rounds).
- **Variants** (`DBG_PROJ`, not committed): `0`, `main`; `1`, the shader as committed.
- **Target frames**: as above.
- **Command**: `mise run sweep -- --var DBG_PROJ=0,1 --track evidence --record work/2026-11/1064_projector-vertex-truncation --topic "world and shape facets horizontal" --images work/2026-11/1064_projector-vertex-truncation/images --target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540` on the GPU.

- **Result** (GPU, the same adapter; `main` at `16483bbb` with the uncommitted switch, `1` being `e5e4d689`'s shader; figures in [`sweeps/world-and-shape-facets-horizontal.toml`](sweeps/world-and-shape-facets-horizontal.toml)): `1` adopts, `winner: DBG_PROJ=1 adopts (evidence, film means; target idx +0.0046 attribution; worst target frame -0.0185 traintnl:12; 297 frames down >0.005, listed)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9385 | 0.8937 | 0.9248 | 0.9059 | 0.9107 | 0.8957 | 0.8863 | 0.9079 |
  | `1` (shipped) | 0.9439 | 0.9069 | 0.9312 | 0.9068 | 0.9164 | 0.9085 | 0.8967 | 0.9158 |

  - Every film's SSIM rises, `balloon` by 0.0009 and the others by 0.0054 (`ctry`) to 0.0132 (`intro`); mask IoU falls by 0.0001 to 0.0013 on four (`ctry`, `intro`, `land`, `location`) and rises on the other three; the world mesh's plane and the shape facets' plane each recovered part of `balloon`'s fall, and together they take it from −0.0043 under the facet-plane form to +0.0009.
  - The worst movers, from the sweep's own list of 297 frames down by more than 0.005: `location` 3334 (−0.0716), 3356 (−0.0674) and 3345 (−0.0622), then `balloon` 298 (−0.0571); each film's worst is `location` 3334, `balloon` 298, `ctry` 331 (−0.0375), `intro` 2476 (−0.0344), `land` 617 (−0.0334), `bomb` 3071 (−0.0327) and `traintnl` 452 (−0.0280).
  - What those seven `-guard` pictures show, from the three panels and a per-pixel comparison of `main` against this PR: in all seven the pixels that differ lie mostly along polygon edges, lines, tree and actor outlines, a pixel off, as pairs of pixels the PR lost against the capture and pixels it gained; the lost outnumber the gained in every one (`location` 3334 4,493 against 1,513, `land` 617 2,963 against 480, `ctry` 331 1,486 against 540, `intro` 2476 1,681 against 617, `bomb` 3071 1,607 against 1,069, `traintnl` 452 1,083 against 249, `balloon` 298 1,323 against 974), counting a pixel lost when `main` matched the capture exactly and the PR does not.
    Three also show a solid region lost: `land` 617, where the grey-green band across a hangar wall that the capture and `main` draw is covered by the wall's pink in the PR; `location` 3334 and `ctry` 331, where a wedge along the horizon's ridge edge differs.
    The `land` 617 band is the one picture that fits a decal losing its tie to a steep facet, the failure of #1027's `4`; the pictures do not show whether that hangar is a world prop or a shape, or whether the band is a decal, so the cause of that or of the other falls was not found, and none is claimed.
  - Pictures (capture, `main`, `1`): the targets [`traintnl` 12](images/traintnl-12-world-and-shape-facets-horizontal.png), [`bomb` 331](images/bomb-331-world-and-shape-facets-horizontal.png), [`location` 683](images/location-683-world-and-shape-facets-horizontal.png) and [`balloon` 540](images/balloon-540-world-and-shape-facets-horizontal.png), and each film's worst mover, `-guard`, in the same folder.
- **Shipped as** `1`, with no switch (`e5e4d689`): `slide_normal` returns world up for a world-mesh vertex (`scenery_class` ≠ 0) and for a shape facet whose normal is within 0.9 of vertical.
  `draw_order::a_decal_on_a_near_horizontal_facet_wins_over_its_base_near_and_far` pins a decal on a facet 23 degrees from horizontal, beside the existing steep-facet decal test, the tile-on-terrain and actor-on-scenery tests, the ZLINETO test and `lines::a_polygon_within_one_pixel_draws_it_either_way`; all pass on the GPU.

## 2026-11-25: the shipped form on the canonical lavapipe

`[Bounded Observation]`

- **Question**: Do the shipped shader's scores on the canonical lavapipe agree with `3`'s on the GPU, and what do the pins become?
- **Command**: `mise run parity -- --software-only` on `e5e4d689` with `crates/` clean, in Ubuntu 24.04 under WSL (`llvmpipe (LLVM 20.1.2, 256 bits)`), then `mise run parity-repin -- --class lavapipe`.
- **Result**: against the pins of `4b5c69c` (`main`'s `crates/` is `4833af84`, so the pins lag it; the table below is a change since those pins, not since `main`):

  | Film | ctry | intro | land | balloon | traintnl | bomb | location |
  |---|---|---|---|---|---|---|---|
  | pinned | 0.9385 | 0.8937 | 0.9248 | 0.9059 | 0.9107 | 0.8957 | 0.8863 |
  | shipped | 0.9439 | 0.9069 | 0.9310 | 0.9067 | 0.9164 | 0.9080 | 0.8967 |

  - Every film's SSIM rises on lavapipe, `balloon` by 0.0008, and mask IoU falls by 0.0001 to 0.0013 on the same four films as on the GPU; the GPU's `3` put `balloon` at −0.0007 against `main` (a different adapter and baseline, so the two are not one comparison).
  - The pins were repinned to `a160e577` (`git rev-parse e5e4d689:crates`) in `b60aba3a`; the test change of the next entry and its comment edits moved them again, to `bd8f452f` (`git rev-parse 60d7b49e:crates`), with every score and `sha256` identical to the ones above, so the file no longer carries `a160e577` [`mise run parity -- --software-only` then `mise run parity-repin -- --class lavapipe` on `60d7b49e` with `crates/` clean, in Ubuntu 24.04 under WSL (`llvmpipe (LLVM 20.1.2, 256 bits)`), 2026-11-26].
  - A comment-only change to `mode13h.wgsl` (finding 8 of the first review) moved the `crates` tree hash, and `loop-rules.md` § After adopting allows no hand restamp of the pins, so it was reverted; the shader's `t` comment ("this many times its own distance") stays as committed in `e5e4d689` and is imprecise, to be fixed in a PR that repins.

## 2026-11-26: one index of difference in the Gouraud ground test on lavapipe

`[Bounded Observation]`

- **Question**: The shader now draws a vertex on the pixel `PLAYONE`'s projectors truncate it to, which `a_gouraud_ground_polygon_under_a_low_eye_keeps_its_gradient` (a 120 m ground square, index 40 to 100, under a 3 m eye) did not model, and CI's lavapipe failed it; what does the test have to allow, and does it still reject a perspective-correct gradient?
- **Builds**: `mode13h.wgsl` as committed in `e5e4d689` throughout; the test of `ac98edbf` is in `crates` trees `a7acdb14`, `2c5a4012` and `bd8f452f`, which differ only in that test's comment, so its count holds for each.
  Windows: mesa-dist-win 25.2.8 (`lvp_icd.x86_64.json` in `VK_DRIVER_FILES`; the adapter string was not read), `STUNT_REQUIRE_GPU=1`.
  The canonical lavapipe is Ubuntu 24.04's Mesa 25.2.8 under WSL and CI.
  The test is `software_only` (`gpu_or_skip_software`), so it cannot run on the RTX 4070.
- **Command** (Windows runs): `cargo test -p stunt-render --test gpu -- a_gouraud_ground_polygon_under --nocapture`.
- **Results** (each figure's source in brackets):
  - The test before the change, `7121a185`'s, fails with `11588 of 47040 ground pixels are not screen-linear` [a committed test and the committed shader, rerun on 2026-11-26 on Windows; CI's lavapipe gave the same count, per the commit body of `ac98edbf`].
  - After the model snaps the front corners to the truncated pixels (`playone_pixel_ndc`), 2,951 pixels differ, counted with the old allowance for a rounding boundary [the previous session's uncommitted variant, quoted from `ac98edbf`'s message; not rerun].
  - With the test of `ac98edbf` (its code is unchanged in `c790e3e1`; it asserts no pixel beyond one index off and at most 4,500 one index off) plus a temporary `eprintln!` of its counters, `checked=47040 one_off=3167 beyond_one=0 apart=46457`, and the gap at pixel (319, 139) is 74.61 indices [uncommitted instrumented copy of the committed test, run on Windows on 2026-11-26].
    The same 3,167 on the canonical lavapipe was reported by the previous session [not rerun here; a pass there shows at most 4,500 one-off pixels, not the count].
  - With the slide disabled, 0 of 47,040 pixels are one index off or more, so every pixel is equal [uncommitted variant on Windows on 2026-11-26: the final `return` of `playone_vertex` replaced by `vec4<f32>(ndc * clip.w, clip.z, clip.w)`, which keeps the truncated pixel and the vertex's own depth; the previous session's variant, which `ac98edbf`'s message also reports as "none off", was not recorded].
  - The 46,457 pixels are those where the world-X-linear perspective index differs from the unrounded screen-linear model by 3 or more; rounding is monotone, so a perspective-correct render lands 2 or more indices away at each of them, and the committed test's `MIN_APART_PIXELS` is 40,000.
  - An RTX 4070 render of this scene with the slide on, every pixel equal, was reported by the previous session [an unrecorded observation of an uncommitted variant, pointed at the GPU by hand; not rerun, and the committed test cannot reproduce it].
  - "Up to about 0.7 index" of difference, quoted in `ac98edbf`'s message, was not recomputed and is no longer claimed by the test or the PR.
- **Reason**: observed, with the slide on, 3,167 of 47,040 pixels are one index off and none beyond; with the slide disabled, none; the slide-disabled run shows the one-index difference needs the slide.
  `[Hypothesis]` for the cause: the slide changes the two front corners' depths (the polygon reaches behind the eye, so the clipper cuts it), the clipper's fallback then bends the gradient, and rounding turns the bend into one-index flips.
  The run did not isolate the clipper, the ratio's f32 arithmetic or the rasteriser as the cause, and `lavapipe.md` § 3 says the `shade·w / w` ratio is exact at a vertex the clipper makes, which does not fit the hypothesis; the two are not reconciled.
- **Pass without `VK_DRIVER_FILES`**: on Windows with the variable unset the test prints `Skipping software-only GPU test: no software fallback adapter with clip distances (WARP lacks them; ADR 0054)` and passes, with or without `STUNT_REQUIRE_GPU=1`, so a green run there that did not name the lavapipe manifest checked nothing.
- **Pin**: the repin after this change is `bd8f452f` (`git rev-parse 60d7b49e:crates`, the commit that hedged the test's comment to the observation), from `mise run parity -- --software-only` then `mise run parity-repin -- --class lavapipe` on `60d7b49e` with `crates/` clean, in Ubuntu 24.04 under WSL (`llvmpipe (LLVM 20.1.2, 256 bits)`), 2026-11-26; every film's SSIM, IoU and `sha256` equal the pins on `2c5a4012` (`git rev-parse c790e3e1:crates`, the tree that cut the comment to its contract), and `a7acdb14` was the tree of the comment before that.

## Handoff

- **Adopted**: the world mesh and near-horizontal shape facets slide in the horizontal plane, steeper shape facets in their own, on the pixel `PLAYONE`'s projectors truncate each vertex to ([`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)); the forms tried and not adopted are in its Ruled out.
- **Open**: the slide threshold (60 degrees, tried without the world-mesh rule, scored a mean of 0.9166 against the shipped form's 0.9158, +0.0008 and +0.0013 against `3`, inside the 0.002 noise floor, and a higher `balloon` but a lower `bomb`: 0.9066 against 0.9085); `parity_probe.py register` on #990's ticks, to see whether the backdrop's one-row shift is gone; the PR's evidence is the pictures of the third entry; the `land` 617 hangar band above is the first thing to look at for a decal on a steep world-prop facet.
