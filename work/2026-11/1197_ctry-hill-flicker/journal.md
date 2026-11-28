# Journal

## 2026-11-27: the hill's foot slides kilometres along a grazing ray

`[Bounded Observation]`, `CTRY` ticks 280 to 372 rendered on lavapipe.

- **Question**: why does the green hill on the right of `CTRY`'s airfield shot show on one render tick and not the next from about tick 286 to 366, when the capture keeps it?
- **What is drawn there.**
  Painting each `MAP.BIN` patch in its record number instead of its colour (a throwaway switch, not committed) shows the hill is records 107, 108 and 109 (colours 192 to 194) and the grey face behind it records 11 and 12 (162, 164).
  All three hill records leave the frame together on a tick where the hill is gone, and record 12 fills their pixels; it is not a partial depth fight.
  The hill's corners lie 290 to 440 m in front of record 12's plane and about 4.8 to 5.1 km from the eye (eye at `(3301, 6, 2536)` on tick 300), so depth alone puts the hill in front.
  Switching the depth buffer to `Depth32Float` changed no pixel of ticks 300 to 318.
- **Cause.**
  `playone_vertex` in `mode13h.wgsl` (since #1064) moves each vertex to the centre of the pixel `PLAYONE` truncates it to and slides it along the ray through that pixel to the horizontal plane through the vertex, for every world-mesh vertex.
  The hill's foot corners lie at height 0, 6 m below the eye and about 5 km away, so the ray to them falls about 0.07 degrees below horizontal, less than half a pixel.
  The snapped pixel's ray then meets the horizontal plane far beyond the corner, or not at all (where it keeps its own projection); `PLANE_SLIDE_MAX` let a vertex slide to a million times its own distance.
  Which happens depends on the corner's sub-pixel position, so it changes from tick to tick as the camera moves, and on a tick where a foot corner slides kilometres back the hill's triangles fall behind record 12.
- **Check.**
  Keeping a vertex's own projection whenever the slide would change its distance by more than 10% (throwaway switch) draws the hill on every tick of 300 to 318.
- **Form swept** (`DBG_PLANE_SLIDE_MAX`, not committed; the bound and the switch that replaces its constant in the shader source at pipeline creation are in [`switches/DBG_SNAP_MODE.diff`](switches/DBG_SNAP_MODE.diff), where `DBG_SNAP_MODE=0` is this form): `playone_vertex` keeps a vertex's own projection when sliding it would change its distance from the eye by more than `PLANE_SLIDE_MAX` as a fraction; `1.0e6` is `main`'s behaviour in effect, the values below bound it.
- **Track**: heuristic; the slide is our own device for keeping coplanar ties, not a `PLAYONE` rule.
- **Target frames**: `--target ctry:286-366`, the issue's window.
- **Command** (lavapipe, 4 vCPU cloud container; the branch at `d21e5cd` with the switch): `mise run sweep -- --var DBG_PLANE_SLIDE_MAX=1.0e6,0.3,0.1,0.03 --track heuristic --record work/2026-11/1197_ctry-hill-flicker --topic plane slide bound --images work/2026-11/1197_ctry-hill-flicker/images --crop 140,0,320,100 --target ctry:286-366 --jobs 4`, with `VK_DRIVER_FILES` set to the lavapipe ICD alone.
- **Result** ([`sweeps/plane-slide-bound.toml`](sweeps/plane-slide-bound.toml)): `winner: none adopts (best DBG_PLANE_SLIDE_MAX=0.3: film means short of +0.002 each or +0.004 on one; target idx +0.0045, not above +0.010)`.

  | Film | `1.0e6` (`main`) | `0.3` | `0.1` | `0.03` |
  |---|---|---|---|---|
  | ctry | 0.9459 | 0.9478 | 0.9468 | 0.9455 |
  | intro | 0.9231 | 0.9248 | 0.9236 | 0.9180 |
  | land | 0.9418 | 0.9443 | 0.9430 | 0.9410 |
  | balloon | 0.9094 | 0.9094 | 0.9094 | 0.9093 |
  | traintnl | 0.9221 | 0.9220 | 0.9220 | 0.9217 |
  | bomb | 0.9216 | 0.9223 | 0.9227 | 0.9197 |
  | location | 0.9168 | 0.9178 | 0.9188 | 0.9180 |

  - `0.3` raises five films (`land` by 0.0025, `ctry` 0.0019, `intro` 0.0017) and lowers `traintnl` by 0.0001; the pooled target SSIM rises by 0.0087.
    By eye the hill is back on [364](images/ctry-364-plane-slide-bound.png) but missing on [309](images/ctry-309-plane-slide-bound.png), where `main` draws it (next entry).
  - 90 frames fall by more than 0.005, the worst `intro` 2467 (−0.0212).
    `bomb` 12 to 210, the static opening shot, all fall by the same 0.0058 ([picture](images/bomb-78-plane-slide-bound-guard.png)).
    `[Hypothesis]`: a vertex that now keeps its own projection also loses its pixel snap, so it moves half a pixel back to where `main` drew it before #1064; the next round keeps the snap.

## 2026-11-27: a bounded slide that keeps the snapped pixel, or clamps

`[Bounded Observation]`

- **Question**: does the bound of the previous entry adopt when a vertex it stops sliding still lands on the pixel `PLAYONE` truncates it to, or when the slide is clamped to the bound instead of dropped?
- **Why**: the previous entry's picture of `ctry` 309 ([picture](images/ctry-309-plane-slide-bound.png)) shows `0.3` losing the hill that `main` draws on that tick.
  `[Hypothesis]`: a slide that pulls a far vertex nearer is as wrong as one that pushes it back; a 30% pull moves the mountain's foot corner, about 5.9 km away, some 1.8 km nearer, well past the 290 to 440 m the hill stands in front of it.
  So `0.3` is dropped and `0.03` kept.
- **Form** (`DBG_SNAP_MODE`, not committed, beside `DBG_PLANE_SLIDE_MAX`; [`switches/DBG_SNAP_MODE.diff`](switches/DBG_SNAP_MODE.diff)):
  `0` is the previous entry's form, a vertex whose slide misses or exceeds the bound keeping its own projection, as `main` does for a miss;
  `1` keeps that vertex's clip `z` and `w` but takes the snapped pixel's `x` and `y`;
  `2` clamps the slid point's distance from the eye to within the bound of the vertex's own, on the snapped pixel's ray, and a miss keeps its own projection.
- **Track**: heuristic.
- **Target frames**: `--target ctry:286-366`, as before.
- **Command** (lavapipe, as before): `mise run sweep -- --var DBG_PLANE_SLIDE_MAX=1.0e6,0.1,0.03 --var DBG_SNAP_MODE=0,1,2 --track heuristic --record work/2026-11/1197_ctry-hill-flicker --topic plane slide bound modes --images work/2026-11/1197_ctry-hill-flicker/images --crop 140,0,320,100 --target ctry:286-366 --jobs 4`.
- **Result** ([`sweeps/plane-slide-bound-modes.toml`](sweeps/plane-slide-bound-modes.toml)): `winner: none adopts (best DBG_PLANE_SLIDE_MAX=0.03 DBG_SNAP_MODE=1: film-mean guard balloon -0.0057)`.

  | `DBG_PLANE_SLIDE_MAX` | mode | ctry | intro | land | balloon | traintnl | bomb | location | bomb IoU |
  |---|---|---|---|---|---|---|---|---|---|
  | `1.0e6` (`main`) | 0 | 0.9459 | 0.9231 | 0.9418 | 0.9094 | 0.9221 | 0.9216 | 0.9168 | 0.9707 |
  | `1.0e6` | 1 | 0.9457 | 0.9216 | 0.9422 | 0.9093 | 0.9220 | 0.9208 | 0.9166 | 0.9498 |
  | `1.0e6` | 2 | 0.9458 | 0.9217 | 0.9422 | 0.9093 | 0.9220 | 0.9208 | 0.9166 | 0.9498 |
  | `0.1` | 0 | 0.9468 | 0.9236 | 0.9430 | 0.9094 | 0.9220 | 0.9227 | 0.9188 | 0.9708 |
  | `0.1` | 1 | 0.9489 | 0.9219 | 0.9426 | 0.9037 | 0.9225 | 0.9225 | 0.9186 | 0.9498 |
  | `0.1` | 2 | 0.9485 | 0.9219 | 0.9426 | 0.9049 | 0.9226 | 0.9224 | 0.9181 | 0.9498 |
  | `0.03` | 0 | 0.9455 | 0.9180 | 0.9410 | 0.9093 | 0.9217 | 0.9197 | 0.9180 | 0.9705 |
  | `0.03` | 1 | 0.9491 | 0.9221 | 0.9434 | 0.9037 | 0.9228 | 0.9229 | 0.9190 | 0.9498 |
  | `0.03` | 2 | 0.9490 | 0.9224 | 0.9430 | 0.9040 | 0.9224 | 0.9229 | 0.9188 | 0.9498 |

  - `0.1` mode 0 scores as it did in the previous entry, to the digit.
  - Modes 1 and 2 raise `ctry` by up to 0.0032 but lower `balloon` by 0.0045 to 0.0057, and `bomb`'s mask IoU falls from 0.9707 to 0.9498 in every mode-1 and mode-2 variant, `1.0e6` included.
    Both modes, unlike mode 0, put a vertex whose ray misses its plane (`t` not positive) on the snapped pixel at its own depth, and `1.0e6` changes only those, so that is where the IoU fall comes from; `[Hypothesis]`: a vertex behind the plane's horizon is one whose clip `w` is small or whose snapped `x` and `y` are far from its own, which the snap then throws across the view.
    The worst frames are `intro` 3225 (−0.0899) and `balloon` 507 (−0.0768); pictures: [`intro` 3225](images/intro-3225-plane-slide-bound-modes-guard.png), [`balloon` 507](images/balloon-507-plane-slide-bound-modes-guard.png).
  - So the next round clamps the slide (mode 2's form) and leaves a miss its own projection (mode 0's).

## 2026-11-27: a clamped slide, misses untouched

`[Bounded Observation]`

- **Question**: does clamping the slid distance to the bound, with a miss keeping its own projection as on `main`, adopt?
- **Form**: `DBG_SNAP_MODE=3` in [`switches/DBG_SNAP_MODE.diff`](switches/DBG_SNAP_MODE.diff) (now with mode 3): a vertex whose ray meets its plane in front of the eye lands on the snapped pixel's ray at its slid distance clamped to within `DBG_PLANE_SLIDE_MAX` of its own; a miss keeps its own projection.
- **Track**: heuristic.
- **Target frames**: `--target ctry:286-366`, as before.
- **Command** (lavapipe, as before): `mise run sweep -- --var DBG_PLANE_SLIDE_MAX=1.0e6,0.1,0.03,0.01 --var DBG_SNAP_MODE=3 --track heuristic --record work/2026-11/1197_ctry-hill-flicker --topic plane slide clamp --images work/2026-11/1197_ctry-hill-flicker/images --crop 140,0,320,100 --target ctry:286-366 --jobs 4`; `1.0e6` with mode 3 scores as `main` does to within 0.0001 per film, and the sweep's deltas are against it.
- **Result** ([`sweeps/plane-slide-clamp.toml`](sweeps/plane-slide-clamp.toml)): `winner: none adopts (best DBG_PLANE_SLIDE_MAX=0.01 DBG_SNAP_MODE=3: film-mean guard balloon -0.0052)`.

  | `DBG_PLANE_SLIDE_MAX` | ctry | intro | land | balloon | traintnl | bomb | location |
  |---|---|---|---|---|---|---|---|
  | `1.0e6` (`main`) | 0.9459 | 0.9232 | 0.9419 | 0.9093 | 0.9221 | 0.9216 | 0.9168 |
  | `0.1` | 0.9486 | 0.9234 | 0.9423 | 0.9049 | 0.9226 | 0.9232 | 0.9183 |
  | `0.03` | 0.9491 | 0.9237 | 0.9426 | 0.9040 | 0.9225 | 0.9237 | 0.9190 |
  | `0.01` | 0.9494 | 0.9234 | 0.9435 | 0.9041 | 0.9230 | 0.9238 | 0.9198 |

  - Clamping keeps `bomb`'s mask IoU at `main`'s 0.9707 and raises six films, but `balloon` falls by 0.0044 to 0.0052; its worst frames, 496 to 595, fall by 0.046 to 0.076.
  - `balloon` 507, whole frame (capture | `1.0e6` | `0.03`, mode 3; `mise run frame`, not committed): the variant draws a band of ocean blue along the far edge of the flat ground, which neither the capture nor `main` shows.
    The flat ground and the ocean are huge polygons whose far corners lie on grazing rays; slid all the way, their depths are the exact meeting of each pixel's ray with the plane, and the raised terrain at the horizon ties them; clamped, they are not, and the ocean wins there.
  - So a bound on the slide trades one far surface's error for another's: the slide is right for far geometry in its own plane and wrong only for a vertex slid in a plane it does not lie along.
    The hill's foot corners slide in the horizontal plane, but the hill's facets are steep; `slide_normal` sends every world-mesh vertex to the horizontal plane, terrain included.

## 2026-11-27: steep terrain slides in its own facet's plane

`[Bounded Observation]`

- **Question**: does sliding a raised `MAP.BIN` patch's vertex in the patch's own plane when the patch is steeper than about 26 degrees, as a shape facet already slides (`slide_normal`, `NEAR_HORIZONTAL`), keep the hill on every tick and adopt, with no bound on the slide?
- **Why it fits**: each patch's vertices are its own (`push_terrain` gives them the patch's normal), so a steep patch's corner slides along its own surface, which the snapped pixel's ray crosses at a wide angle when the face is seen, and near-horizontal patches, flat ground and the ocean keep the horizontal plane they share.
  Ticks 300 to 318, even ones (lavapipe; `mise run frame`, not committed): the hill shows on all ten; `balloon` 507 draws as `main` does.
- **Form** (`DBG_TERRAIN_FACET`, not committed; [`switches/DBG_TERRAIN_FACET.diff`](switches/DBG_TERRAIN_FACET.diff), the earlier switches set to `main`'s behaviour by `DBG_PLANE_SLIDE_MAX=1.0e6 DBG_SNAP_MODE=0` in the environment): with `1`, `slide_normal` treats a terrain vertex (scenery class 2) as a shape facet's, not a world-mesh vertex's.
- **Track**: heuristic.
- **Target frames**: `--target ctry:286-366`, as before.
- **Command** (lavapipe, as before): `DBG_PLANE_SLIDE_MAX=1.0e6 DBG_SNAP_MODE=0 mise run sweep -- --var DBG_TERRAIN_FACET=0,1 --track heuristic --record work/2026-11/1197_ctry-hill-flicker --topic steep terrain facet slide --images work/2026-11/1197_ctry-hill-flicker/images --crop 140,0,320,100 --target ctry:286-366 --jobs 4`.
- **Result** ([`sweeps/steep-terrain-facet-slide.toml`](sweeps/steep-terrain-facet-slide.toml)): `winner: none adopts (best DBG_TERRAIN_FACET=1: film-mean guard land -0.0033)`.

  | Film | `0` (`main`) | `1` | Δ |
  |---|---|---|---|
  | ctry | 0.9459 | 0.9469 | +0.0010 |
  | intro | 0.9231 | 0.9229 | −0.0002 |
  | land | 0.9418 | 0.9385 | −0.0033 |
  | balloon | 0.9094 | 0.9077 | −0.0017 |
  | traintnl | 0.9221 | 0.9220 | −0.0001 |
  | bomb | 0.9216 | 0.9216 | +0.0000 |
  | location | 0.9168 | 0.9168 | +0.0000 |

  - The target frames rise (pooled SSIM +0.0091, worst target frame +0.0014): the hill stays on every captured tick of the window ([298](images/ctry-298-steep-terrain-facet-slide.png), [331](images/ctry-331-steep-terrain-facet-slide.png), [364](images/ctry-364-steep-terrain-facet-slide.png)).
  - `land` 551 (−0.0481, the worst frame; whole frame by `mise run frame`, not committed): the variant draws a grey mountain above the horizon, behind the aircraft, where the capture and `main` show only the haze band of the sky.
    So `PLAYONE` does not draw that mountain there, and `main` hides it only because its foot corners slide kilometres back along grazing rays, the fault this issue is about; the [guard picture](images/land-551-steep-terrain-facet-slide-guard.png)'s crop misses it.
    `[Hypothesis]`: `PLAYONE` drops far terrain by a rule we do not draw, such as the scenery cull's distance cut (`0x1B0C`, [`world-scene-residuals.md`](../../../research/playone-exe/world-scene-residuals.md) section 6.4) applied to ground leaves; not checked.
- **End of the loop.**
  Four rounds, none adopted, so the loop stops here ([loop rules](../../../.agents/skills/improving-render-parity/loop-rules.md)).
  The cause stands: the horizontal slide of a steep terrain patch's corner.
  The fix that follows from it, sliding steep terrain in its own plane, needs the far-terrain rule first, or `land` and `balloon` pay for mountains `main` hides by accident.

## 2026-11-27: `land` 551's mountain is hidden by a nearer face, not left out

`[Bounded Observation]`, lavapipe, `land` 551 (#1206).

- **Question**: by what rule does `PLAYONE` leave out the mountain the steep facet slide draws above `land` 551's horizon?
- **Method**: on the branch at `7123480` with [`switches/DBG_TERRAIN_FACET.diff`](switches/DBG_TERRAIN_FACET.diff) applied, `land` 551 rendered with each `MAP.BIN` patch painted in its record number (a throwaway switch, not committed), `DBG_TERRAIN_FACET=0` and `1`; the capture page's indices read from `captures/vault-land`; the records' anchors projected through the frame's camera (`render.json`: eye `(5477.4, 3.3, 6920.1)`, lens field of view 11.16 degrees); the ground handlers read with `mise run re-tool -- disasm 0x2360 0x2410` on the unpatched image, and the same gate's bytes found at `0x2498` in the Patch #3 image.
- **Result**:
  - The mountain is records 46 and 50 (colours 164 and 161), a 600 m peak whose corners lie 7.4 to 9.8 km from the eye; projected, the peak sits at row 0 and the feet at row 61.
  - What the capture shows above the horizon is not sky: rows 0 to 59 are index 162 across the frame, and `main` draws the same rows as record 2 (colour 162), a 1,000 m face 4.4 to 5.7 km away whose peak projects to row −108 and whose feet lie off both sides of the frame at row 61.
    Record 2 is nearer than 46 and 50 and covers them, in the capture and on `main`.
  - Records 46 and 50 slope at 25 and 24 degrees (their leaves' plane normals), under the 26 at which `DBG_TERRAIN_FACET=1` gives a facet its own plane, so their feet, 3 m below the eye and 7 to 10 km off, still slide in the horizontal plane.
    The pixel those feet truncate to lies toward the centre row, below the horizon, so its ray meets that plane nearer than the foot: half a pixel at this lens puts it about 3.4 km away, in front of record 2.
    With the steep facet slide, record 2 slides in its own plane and keeps its depth, so 46 and 50 win; on `main` record 2's feet slide in the horizontal plane too, and it covers them.
  - `SP_GLEAF` (`0x23BF`) tests only the leaf's facing (`0x23C5..0x23EC`) and calls no distance cut, so `0x1B0C` does not reach ground leaves; 46 and 50 face the eye, and their path from the root holds only `SP_2NODE`, `SP_HSLOPE` and `SP_VSLOPE` nodes (a throwaway walk of the tree's links from `SS:0`, not committed).
  - `SP_GROUND` (`0x2360`) is a level-of-detail switch that our renderer does not draw: it draws its own coarse polygon when its depth word exceeds `splitdist` (`0x239C`), else its finer patches. Neither 46 nor 50 lies under one, so it does not bear on this frame; filed as #1207.
- **Verdict**: no far-terrain rule; the issue's premise was wrong.
  The fault is the horizontal slide of a raised patch that is not steep, which pulls a far foot nearer as #1197's pushes one back.
- **Lives in**: [`sod-vm-lines-spans.md`](../../../research/playone-exe/sod-vm-lines-spans.md) section 8.14, [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 2.

## 2026-11-27: every raised terrain patch slides in its own plane

`[Bounded Observation]`

- **Question**: does sliding every raised `MAP.BIN` patch's vertex in the patch's own plane, with no steepness threshold, keep `ctry`'s hill and draw `land` 551 as the capture does, and adopt?
- **Why**: the previous entry; flat ground and the ocean keep the horizontal plane they lie in.
  By eye (`mise run frame`, not committed): `land` 551 matches the capture (index mismatch 4.4%, as `main`; the steep facet slide 16.6%), `ctry` 309 keeps the hill (4.6% against `main`'s 5.1%), and `balloon` 507 draws as `main` does.
- **Form** (`DBG_TERRAIN_FACET=2`, not committed; [`switches/DBG_TERRAIN_FACET.diff`](switches/DBG_TERRAIN_FACET.diff), now a `u32` mode): `slide_normal` returns the facet's own normal for every terrain vertex (scenery class 2) outside a layer.
- **Track**: heuristic.
- **Target frames**: `--target ctry:286-366`, as before.
- **Command** (lavapipe, as before; the branch at `7123480` with the switch, which made every picture below): `DBG_PLANE_SLIDE_MAX=1.0e6 DBG_SNAP_MODE=0 mise run sweep -- --var DBG_TERRAIN_FACET=0,2 --track heuristic --record work/2026-11/1197_ctry-hill-flicker --topic "raised terrain facet slide" --images work/2026-11/1197_ctry-hill-flicker/images --crop 140,0,320,100 --target ctry:286-366 --jobs 4`.
- **Result** ([`sweeps/raised-terrain-facet-slide.toml`](sweeps/raised-terrain-facet-slide.toml)): `winner: none adopts (best DBG_TERRAIN_FACET=2: film means short of +0.002 each or +0.004 on one; target idx +0.0049, not above +0.010)`.

  | Film | `0` (`main`) | `2` | Δ |
  |---|---|---|---|
  | ctry | 0.9459 | 0.9475 | +0.0016 |
  | intro | 0.9231 | 0.9246 | +0.0015 |
  | land | 0.9418 | 0.9406 | −0.0012 |
  | balloon | 0.9094 | 0.9075 | −0.0018 |
  | traintnl | 0.9221 | 0.9220 | −0.0000 |
  | bomb | 0.9216 | 0.9216 | +0.0000 |
  | location | 0.9168 | 0.9167 | −0.0001 |

  - `land` 551 scores as on `main` (0.93956 against 0.93952), where the steep facet slide lost 0.048 there.
  - The target frames rise (pooled SSIM +0.0088, worst target frame +0.0014; [298](images/ctry-298-raised-terrain-facet-slide.png), [331](images/ctry-331-raised-terrain-facet-slide.png), [364](images/ctry-364-raised-terrain-facet-slide.png)).
  - 93 frames fall by more than 0.005, the worst `location` 2312 (−0.0205) and `balloon` 1156 (−0.0192); no `balloon` frame rises by more than 0.001 and 36 fall by more.
    In the guard pictures ([`land` 199](images/land-199-raised-terrain-facet-slide-guard.png), [`balloon` 1156](images/balloon-1156-raised-terrain-facet-slide-guard.png); the sweep also drew the worst frames of `location` and `intro`, [`location` 2312](images/location-2312-raised-terrain-facet-slide-guard.png) and [`intro` 2058](images/intro-2058-raised-terrain-facet-slide-guard.png), whose losses were not examined) the loss is ocean blue along the foot of far raised terrain, a row or a few pixels wide, which neither the capture nor `main` shows.
    `[Hypothesis]`: a raised patch's foot corners at height 0 now keep their own depth, while the flat ground beside them slides to where each pixel's ray meets the ground plane, beyond the island's edge on grazing rows, so the ocean wins the seam between them; the horizontal slide kept the foot and the ground on one plane there.
- **Verdict**: rejected by the adoption rule (no film branch; `balloon` −0.0018 and `land` −0.0012).
- **Next**: a raised patch's corners need both planes: its own for the hill (#1197) and `land` 551, the ground's at the seam with the flat ground; a form that does both was not tried.

## 2026-11-28: the ocean strip is the raised face's foot losing to the ocean

`[Bounded Observation]`, lavapipe, `balloon` 1156, `DBG_TERRAIN_FACET=2` against `main`.

- **Question**: where the ocean strip shows along the foot of far raised terrain, does the ocean beat a raised patch's bottom corner or the flat ground beside it?
- **Method**: `balloon` 1156 (the worst `balloon` frame of the previous sweep) rendered by `mise run frame` with each `MAP.BIN` patch painted by its record number (a throwaway switch, not committed; [`switches/DBG_TERRAIN_MIX.diff`](switches/DBG_TERRAIN_MIX.diff) carries it with the next entry's), the render store's index and layer planes read pixel by pixel, the corners of the records printed from `push_terrain`.
  The pixel reading is a `[Bounded Observation]`; the depth mechanism below is a `[Hypothesis]`, not tested.
- **Result**:
  - The strip is row 53, x 51 to 126 (75 of the 158 pixels the mode changes): record 5, which `main` draws there, is replaced by ocean; record 4 below it is untouched.
    Rows 54 to 58 hold six ocean pixels each where record 8 was.
  - Record 5 is a raised triangle, corners (3730, 0, 785), (5112, 1000, 1296), (4220, 0, 2581), and record 4, the flat ground beside it, shares its bottom edge (3730, 0, 785) to (4220, 0, 2581).
    Record 8 has the same shape (a raised triangle with its foot on the ground).
  - So the ocean beats the raised face at its foot, not the ground.
    `[Hypothesis]` for the cause: the mode slides record 5's feet in its own plane, which a grazing ray meets far beyond the ground plane; the face's pixels near its foot take depths beyond the ocean's, which slides in the horizontal plane with record 4, and the ocean wins them.
    On `main` the feet lie on that horizontal plane too and tie with the ocean, which the face wins by draw order.
- **Verdict**: the previous entry's `[Hypothesis]` held in the part that matters (the foot and the ground need one plane at the seam), but it is the raised face that loses, by depth, not a gap between meshes.

## 2026-11-28: a mixed slide, raised patches in their plane except on the ground

`[Bounded Observation]`, lavapipe.

- **Question**: does sliding a raised patch's corner in the patch's own plane, except a corner on the ground plane (height 0), which slides horizontally while that changes its distance by at most `DBG_MIX_PCT` (else its own plane), keep the hill and `land` 551 without the ocean strip, and adopt?
- **Form** (`DBG_TERRAIN_FACET=3`, `DBG_MIX_PCT`; not committed; [`switches/DBG_TERRAIN_MIX.diff`](switches/DBG_TERRAIN_MIX.diff), against `main`, whose slide has no bound): `push_terrain` marks each corner on the ground plane in bit 7 of `decal_tie` (and the record number in the low bits, for the painting), `playone_vertex`'s ray is intersected with the horizontal plane first for such a corner, and the corner keeps that plane only inside the bound.
- **Track**: heuristic.
- **Target frames**: `--target ctry:286-366`.
- **Command** (lavapipe): `mise run sweep -- --var DBG_TERRAIN_FACET=0,3 --var DBG_MIX_PCT=0.05,0.2 --track heuristic --record work/2026-11/1197_ctry-hill-flicker --topic "mixed terrain slide" --images work/2026-11/1197_ctry-hill-flicker/images --crop 140,0,320,100 --target ctry:286-366 --jobs 4`.
- **Result** ([`sweeps/mixed-terrain-slide.toml`](sweeps/mixed-terrain-slide.toml)): `winner: none adopts (best DBG_TERRAIN_FACET=3 DBG_MIX_PCT=0.2: film means short of +0.002 each or +0.004 on one; target idx +0.0049, not above +0.010)`.

  | Film | `0` (`main`) | `3`, 5% | Δ | `3`, 20% | Δ |
  |---|---|---|---|---|---|
  | ctry | 0.9459 | 0.9475 | +0.0016 | 0.9475 | +0.0016 |
  | intro | 0.9231 | 0.9247 | +0.0016 | 0.9248 | +0.0018 |
  | land | 0.9418 | 0.9407 | −0.0012 | 0.9409 | −0.0009 |
  | balloon | 0.9094 | 0.9084 | −0.0010 | 0.9093 | −0.0000 |
  | traintnl | 0.9221 | 0.9220 | −0.0000 | 0.9220 | −0.0000 |
  | bomb | 0.9216 | 0.9216 | +0.0000 | 0.9217 | +0.0001 |
  | location | 0.9168 | 0.9170 | +0.0001 | 0.9173 | +0.0005 |

  (Deltas from the sweep file's unrounded means.)

  - The hill stays on the target frames ([287](images/ctry-287-mixed-terrain-slide.png), [342](images/ctry-342-mixed-terrain-slide.png): the hill `main` loses is drawn); pooled target SSIM +0.0088 (5%) and +0.0090 (20%), worst target frame +0.0014 and +0.0015.
  - At 20% `balloon` 1156 scores exactly as `main` does (0.8782; 0.8615 at 5%), so the strip's frame is level, and the `balloon` mean is level (−0.00001); `land` is still −0.0009 and 46 frames fall by more than 0.005, `land` 199 the worst (−0.0133) and 70 `location` frames moved.
    `land` 199's [guard picture](images/land-199-mixed-terrain-slide-guard.png) draws one row of ocean along a far foot (one frame, one picture): the corner's horizontal slide changes its distance by more than the bound, so it fell back to its own plane, the case this bound exists for.
    It scores 0.92443 at both bounds, exactly as under `DBG_TERRAIN_FACET=2`, which fits that fallback.
    The [`location` 2520](images/location-2520-mixed-terrain-slide-guard.png) loss was not examined; it too scores as `DBG_TERRAIN_FACET=2` does (0.92606), so it is probably the same fallback.
  - The gain matches the plain raised slide's (`ctry` +0.0016; `intro` +0.0016 to +0.0018 against +0.0015), so the bar that fails it fails this: no film reaches +0.002 and the target index +0.0049 stays under +0.010.
- **Verdict**: not adopted.
  At 20% the mixed form removes the strip on `balloon` 1156 and the film means lose at most 0.0009 (`land`; 5%: 0.0012), with 46 frames down more than 0.005 (`location` 2520's, −0.0130, not examined); where the horizontal slide changes a far foot's distance by more than the bound, the foot appears to need its own plane on `ctry` (the hill) and the ground's on `land` 199 (the ocean), which a distance bound cannot tell apart; a larger bound is what [the earlier bound sweeps](#2026-11-27-the-hills-foot-slides-kilometres-along-a-grazing-ray) tried, where 30% did not hold the hill on every tick.
- **Next**: per-fragment depth (a design call, step 3 of the plan, needs an ADR) is the form left; nothing cheaper is queued.


## 2026-11-28: per-fragment depth from the polygon's own plane

`[Bounded Observation]`, lavapipe (4 vCPU cloud container; no GPU here), the prototype of [ADR 0059](../../../docs/adr/0059-terrain-takes-its-depth-per-fragment-from-its-own-plane.md).

- **Question**: if a terrain vertex keeps main's snapped pixel but each fragment takes its depth from the plane of its own polygon, does the hill stay on every tick of `ctry:286-366` without the ocean strip or a film regression?
- **Form** (`DBG_FRAG_DEPTH`, not committed; [`switches/DBG_FRAG_DEPTH.diff`](switches/DBG_FRAG_DEPTH.diff), against `main`): `vertex_output` passes a terrain polygon's eye-relative plane (unit normal, offset from the provoking vertex) as a flat varying and moves the vertex only in x and y, to the pixel `playone_vertex` picks, keeping its own `z` and `w` (a vertex whose ray misses the horizontal plane keeps its own projection, as on `main`); `fs_main` and `fs_main_plane` write `frag_depth` as the depth of the ray through the fragment's pixel centre meeting that plane.
  Modes: `0` is `main`'s scene (every fragment writes its own depth), `1` terrain, `2` terrain and ocean, `3` terrain with the depth no farther than the ground plane's along the same ray (`max` in reversed depth; the plane's eye-relative height is the model matrix's translation `y`), `4` mode 3 with the ocean per fragment, `5` mode 3 for sloped patches only (`|n.y| < 0.9999`); flat patches and the ocean keep `main`'s slide in mode 5, the ocean in modes 1 and 3.
  The committed diff is the final code, with the snapping rule below; modes 1 and 3 as first run (before that rule) cannot be reproduced from it.
  The prototype writes `frag_depth` for every fragment of `fs_main` and `fs_main_plane`, decals included (`true_depth` returns the rasteriser's `clip_position.z`, without the decal pipelines' depth bias, where a fragment has no plane), in mode 0 too.
- **Track**: heuristic.
- **Target frames**: `--target ctry:286-366`.
- **Command** (lavapipe, `VK_DRIVER_FILES` the lavapipe ICD alone): `mise run sweep -- --var DBG_FRAG_DEPTH=<modes> --track heuristic --record work/2026-11/1197_ctry-hill-flicker --topic "<topic>" --images work/2026-11/1197_ctry-hill-flicker/images --crop 140,0,320,100 --target ctry:286-366 --jobs 4`, five sweeps (modes 1 and 2, then 3, then 2 and 4, then 5, then 3 again); each sweep's `0` is its own baseline and scored as `main` every time.
- **Result**: five sweeps, each with its own `0` (`main`, scored the same every time); scores, unrounded deltas in the figures files ([`…-terrain-depth`](sweeps/per-fragment-terrain-depth.toml), [`…-terrain-depth-clamped`](sweeps/per-fragment-terrain-depth-clamped.toml), [`…-sloped-terrain-clamped`](sweeps/per-fragment-depth-sloped-terrain-clamped.toml)) [`…-clamped-fixed-snap`](sweeps/per-fragment-depth-clamped-fixed-snap.toml) and, for the sweep of modes 2 and 4, whose figures file was not kept, in the console output ([`per-fragment-depth-console.txt`](sweeps/per-fragment-depth-console.txt)):

  | Mode | ctry | intro | land | balloon | traintnl | bomb | location | frames down > 0.005 |
  |---|---|---|---|---|---|---|---|---|
  | `0` (`main`) | 0.9459 | 0.9231 | 0.9418 | 0.9094 | 0.9221 | 0.9216 | 0.9168 | |
  | `1` | 0.9475 | 0.9246 | 0.9406 | 0.9075 | 0.9220 | 0.9209 | 0.9168 | 112 |
  | `2` (after the fix, below) | 0.9475 | 0.9244 | 0.9406 | 0.9075 | 0.9220 | 0.9216 | 0.9167 | 93 |
  | `3` (first run) | 0.9477 | 0.9250 | 0.9418 | 0.9091 | 0.9221 | 0.9210 | 0.9179 | 20 |
  | `3` (re-run, below) | 0.9477 | 0.9248 | 0.9418 | 0.9091 | 0.9221 | 0.9216 | 0.9179 | 1 |
  | `4` | 0.9470 | 0.9238 | 0.9403 | 0.9066 | 0.9216 | 0.9215 | 0.9159 | 167 |
  | `5` | 0.9477 | 0.9248 | 0.9418 | 0.9091 | 0.9221 | 0.9216 | 0.9179 | 1 |

  Mode 5 against `main` (unrounded means): `ctry` +0.0018, `intro` +0.0017, `land` −0.0000, `balloon` −0.0002, `traintnl` +0.0000, `bomb` −0.0000, `location` +0.0011; the re-run of mode 3 scores the same to four places.
  Modes 1 to 3 ran before a fix to the vertex snap: they snapped a vertex whose ray misses the horizontal plane too (which `main` leaves unsnapped), and `bomb`'s mask IoU fell to 0.9499 in mode 2 as it did in [the snap-mode sweep](#2026-11-27-a-bounded-slide-that-keeps-the-snapped-pixel-or-clamps); modes 2, 4 and 5 ran after it, with `main`'s rule.
  `winner: none adopts (best DBG_FRAG_DEPTH=5: film means short of +0.002 each or +0.004 on one; target idx +0.0051, not above +0.010)`.
  - **The depth method is not what loses the ocean strip.**
    Modes 1 and 2 match the plain raised slide (`DBG_TERRAIN_FACET=2`) on `land` (0.9406) and `balloon` (0.9075) with the same worst frames (`location` 2312 −0.0205, `balloon` 1156 −0.0192, `land` 199 −0.0133).
    So a raised face's pixels near its foot lose to the ocean wherever the snapped foot edge sits below the face's true foot (the pixel's ray meets the ground first), whether the depth comes from a slide or per fragment (`[Hypothesis]`: the ocean is drawn first and the face then fails the `Greater` test; not probed pixel by pixel here); the capture draws the face there.
  - **Clamping to the ground plane removes it on the frames scored.**
    Mode 3 takes the nearer of the face's plane and the ground plane along the pixel's ray, which only changes a pixel the ray meets the ground first; `land` and `balloon` return to `main` (no frame of either moved by more than 0.005 outside the target window) and the hill is drawn on the target frames pictured ([298](images/ctry-298-per-fragment-depth-sloped-terrain-clamped.png), [331](images/ctry-331-per-fragment-depth-sloped-terrain-clamped.png), [364](images/ctry-364-per-fragment-depth-sloped-terrain-clamped.png); the pooled target SSIM rises 0.0097, the worst target frame 0.0014).
    `[Hypothesis]` for why: the ground and the ocean are drawn first and the face passes `Greater` against them wherever it is no farther; a tie loses, and the ground's depth is rasterised where the clamp's is per fragment, so a pixel can still lose.
  - **The first run of mode 3 lost `bomb`, and the cause was the snapping rule, not a flat patch.**
    It drew ocean over `bomb`'s near ground on 20 frames (−0.0127 each; [picture](images/bomb-56-per-fragment-terrain-depth-clamped-guard.png)) and its masks fell as the snap-mode sweep's did; it snapped a vertex whose ray misses the horizontal plane, which `main` leaves unsnapped.
    Re-run with `main`'s rule it scores as mode 5 (one frame down more than 0.005, `location` 4104 −0.0072; no `bomb` frame moves), so no carve-out for flat patches is needed; mode 5 was run on the first run's explanation (a depth tie with the ocean), which the re-run does not support.
    The ocean and flat ground are drawn by `ground_pipeline`, whose compare is `Always`, so draw order settles them, not depth.
    Mode 4 (the ocean per fragment too, after the fix) is worse, 167 frames down more than 0.005.
    Mode 5: one frame of 297 down more than 0.005 (`location` 4104, −0.0071), 69 frames outside the target moved more than 0.005 (`ctry` 10, `intro` 31, `location` 28).
  - **The gain is the slide family's.**
    Mode 5's target index gain is +0.0051, the same +0.005 every slide variant of this issue reached, short of the +0.010 bar; no film reaches +0.002 (`ctry` +0.0018, `intro` +0.0017).
    The bar's reason is circularity (the sweep picks the variant that scores best on frames the round chose, [`loop-rules.md`](../../../.agents/skills/improving-render-parity/loop-rules.md)); here the variant was not chosen by the target score, and every earlier form tried the same target and reached the same +0.005, which is a ceiling of the frames, not a selection effect (`[Hypothesis]`: the hill covers a small part of each frame).
  - **Cost.**
    Lavapipe renders of `location`, 300 ticks, three runs each, mean 5.58 s (mode 0) against 5.59 s (mode 5), which includes the `frag_depth` write in both; a GPU's early-depth loss was not measured (no GPU in this thread; it needs Legion).
- **Verdict**: not adopted under the rule; modes 3 and 5 (the same to four places) are the first form that keeps the hill with no film loss beyond 0.0003 (`balloon` −0.00024), and [ADR 0059](../../../docs/adr/0059-terrain-takes-its-depth-per-fragment-from-its-own-plane.md) proposes it; the owner accepted it, waiving the bar, the same day.

## 2026-11-28: ADR 0059 implemented as a terrain pipeline

`[Bounded Observation]`, lavapipe (cloud container), `crates/` at the commit that adds `vs_terrain` and `fs_terrain`.

- **Form**: the world's base slice draws through `terrain_pipeline` (`pipeline.rs`), the base pipeline with entry points `vs_terrain` and `fs_terrain` (`fs_terrain_plane`) in the parity look; a terrain vertex outside a shadow, line or disc moves only in x and y, to `playone_vertex`'s pixel where `playone_vertex` would move it, and its fragments write `frag_depth` as in the prototype's mode 3.
  Other draws, the decal pipelines and the modern and diagnostic looks keep their entry points, so only the world's base draw loses early depth testing and no decal loses its bias.
- **A fault in the prototype, fixed here**: the prototype found a fragment's NDC point from its framebuffer position, which is right only when the view starts at the page's top-left corner.
  A letterboxed page, as in the GPU test's 320 × 240 page, put every ray rows off; the hill then lost to the face behind it on every height tried.
  The terrain path reads an interpolated clip position instead.
  The films score as the prototype did to four places, so their pages put the view at the top-left (not otherwise checked).
- **Test**: `a_far_hill_stays_in_front_of_the_face_behind_it` (`tests/gpu/scene_renderer.rs`): a 45-degree slope whose foot lies 5 km off on the ground and 6 m below the eye, 300 m in front of a vertical face, keeps at least three quarters of the pixels it covers alone at eye heights 5.95, 6.00 and 6.05 m.
  On `main` it covers none of them; here 55 of 72, the rest being the row of both feet, where the ground plane's depth bounds both faces and the one drawn first wins the tie.
- **Result** (`mise run parity -- --software-only`, clean `crates/`, against the lavapipe table): `ctry` +0.0018, `intro` +0.0016, `location` +0.0011, `balloon` −0.0002, `land` −0.0000, `traintnl` −0.0000, `bomb` −0.0000; mask IoU unchanged on every film.
  `research/parity/expected/lavapipe.toml` repinned on that tree.
