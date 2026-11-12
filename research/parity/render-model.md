---
summary: "Compares PLAYONE's back-to-front software painter with our depth-buffer renderer stage by stage, naming each known divergence and the `[I5]` and ground-decal rules that imitate its tie order."
---
# Render Model: PLAYONE's Painter Against Our Depth Buffer

* **Scope**: stage by stage, what `PLAYONE.EXE` does to put a frame on screen, what our renderer does in its place, and where the two are known to differ. It routes to the notes that own each fact rather than restating them.
* **Sources**: the `playone-exe/` and `formats/` notes linked in each row, [`docs/SPEC.md`](../../docs/SPEC.md) section 2.1, the ADRs named below, and the code paths cited.
* **Evidence tier**: each row carries the tier of the note it cites. A divergence marked *measured* has a dated score, in a journal entry or a row of the [parity log](../../work/2026-10/parity-log/log.md); *unmeasured* means we know the mechanisms differ but have not scored the gap.

## 1. The two models

`PLAYONE` is a software painter.
1. Each frame it walks the scenery tree back to front, culling by distance and level of detail.
2. It runs each object's display list, which may itself sort subtrees back to front (`sorton`).
3. It fills every polygon into the Mode 13h framebuffer at a palette index, with no depth buffer. A later polygon covers an earlier one, whatever their depths.
4. The palette, built per frame from film variables, gives the colours.

Our renderer replaces the painting with a GPU depth buffer, by design: [`docs/SPEC.md`](../../docs/SPEC.md) section 2.1 makes "CPU-side Painter's Algorithm / BSP polygon sorting" a non-goal.
- It builds the world once per film (`crates/stunt-core/src/world.rs`) and draws a sky pass, a base pass (`Less`) and an `[I5]` decal pass (`LessEqual`, bias `-2, -2.0`; `crates/stunt-render/src/pipeline.rs`).
- Depth is `Depth24Plus` with near 0.5 m and far 25 km (`renderer.rs`, `camera.rs`).
- Polygons are flat at their palette index through the `[I3]` 256 × 32 lookup, with no lighting (`shaders/mode13h.wgsl`).

The two orders agree wherever the nearer surface is also painted later, which is most of the frame. They differ in three ways:
* **Ties.** Two surfaces at the same depth: the painter takes the later one, a depth buffer takes whichever rounds nearer. Every rule in section 3 exists for this case.
* **Grain.** The painter decides per polygon or per object, the depth buffer per pixel. Objects that pass through each other, or a polygon the walk orders wrongly, come out differently. We do not reproduce the painter's errors.
* **Fixed-once work.** Some things `PLAYONE` decides per frame we decide once per film: level of detail, and which props are ground decals.

## 2. Stage by stage

| Stage | `PLAYONE` | Ours | Known divergence | Owner |
|---|---|---|---|---|
| Frame composition | One 3D scene per frame, then the credits text; no second view or inset | One scene per frame | None found | [`sod-vm.md`](../playone-exe/sod-vm.md) section 9 |
| Palette and fades | Built per frame from vars 13-15, interpolated like the other film variables, sent to the DAC | The same variables into the `[I3]` lookup (`contracts/palette.rs`) | The DAC shows entries 0-127 one frame and 128-255 two frames late (section 5.2); the scorer compensates for fades | [`palette-fade.md`](../playone-exe/palette-fade.md), [`palette-and-shading.md`](../formats/concepts/palette-and-shading.md) |
| Sky | Zenith and horizon colours from the palette build | A full-screen sky pass drawn first, no depth | Unmeasured | [`palette-fade.md`](../playone-exe/palette-fade.md) section 3 |
| Visibility order | Back-to-front walk of the scenery tree, no depth buffer | Depth buffer | Ties, grain and fixed-once work (section 1) | [`world-scene.md`](../playone-exe/world-scene.md) section 1, [SPEC](../../docs/SPEC.md) 2.1 |
| Level of detail | Per frame, an `SP_1NODE` distance gate scaled by the lens and detail word | Per film, static stand-ins; the camera path's Euclidean distance, scale 0.5 | Measured: scale 0.5 was the best tried; per-frame switching is not reproduced | [`lod.md`](../playone-exe/lod.md) section 4.1 |
| Projection | The lens variable zooms the view matrix | `lens_fov_degrees`, square 256 px projection | Measured and adopted | [`lod.md`](../playone-exe/lod.md) sections 2.2, 4.2 |
| Ground | Type-14 leaves drawn flat at their stored colour through the raw gateway, no light | `MAP.BIN` patches drawn flat (`push_terrain`), patch 131 with its 8th anchor | We draw every active record; 20 active records have no leaf in the image (#175) | [`world-scene.md`](../playone-exe/world-scene.md) section 2 |
| Ground tiles | Painted after the leaf under them, so they always cover it | Ground decals: a flat prop within 10 cm of the terrain is snapped onto it and drawn in the `[I5]` pass | Measured: CTRY 0.8645, INTRO 0.7973; see section 3 | [`world-scene.md`](../playone-exe/world-scene.md) section 6, [ADR 0035](../../docs/adr/0035-ground-lying-props-are-terrain-decals.md) |
| Sorting inside a shape | `sorton` walks the two subtrees back to front against a separating plane (`[Supported Inference]`) | `OP_SORT` emits both branches; the depth buffer orders them (`sod/vm.rs`) | Unmeasured | [`sod-opcodes.md`](../formats/sod-opcodes.md) section 2.5 |
| Decals inside a shape | A coplanar polygon later in the stream covers the earlier one | `identify_coplanar_decals` marks it and nudges it along its normal; drawn in the `[I5]` pass (`sod/decal.rs`) | Measured when the bias sign was fixed (2026-10-23) | [SPEC](../../docs/SPEC.md) `[I5]` |
| Flat shading (`SHADE*`) | `base + shade`, the shade from `N . L` with the world light from var 13, rotated into a rotated object's frame | The world light `(99, 32766, -17)` from var 13 in the raw model frame for every shape, actors unrotated (`ShadeLight`, `sod/light.rs`) | Measured 2026-11-05: CTRY 0.8646 -> 0.8641, INTRO 0.7986 -> 0.8128, all of it on the aircraft; an actor's rotated light is not modelled | [`terrain-shade.md`](../playone-exe/terrain-shade.md) section 4.2, [`sod-vm.md`](../playone-exe/sod-vm.md) section 8.5 |
| Gouraud polygons (`GVPOLY`, `GVPOLY16`) | A per-vertex ramp on the palette index, 8.8 fixed point, hard bands along screen-linear iso-lines | The ramp base plus each vertex's level, interpolated in screen space and rounded per fragment; the vertex fraction is dropped | Measured 2026-11-05: CTRY 0.8641 -> 0.8642, INTRO 0.8128 -> 0.8166 | [`terrain-shade.md`](../playone-exe/terrain-shade.md) sections 1, 6, 7 |
| Raster blits (`OP_ANIMATE`) | A screen-space blit of an image resource, zero bytes transparent | Not drawn: `sod/vm.rs` has no handler for it | Unmeasured | [`sod-animate.md`](../playone-exe/sod-animate.md) |
| Rasterisation | Software span filling in 320 × 200, its own clipping | GPU rasterisation at 320 × 200, 4:3 presentation | Edge and sub-pixel coverage differ; mask IoU 0.9897 CTRY, 0.9856 INTRO | [`attribution.md`](attribution.md), [`method.md`](method.md) |

## 3. Where we imitate the painter

The depth buffer gets one case visibly wrong: a later polygon that ties an earlier one. Each place we imitate `PLAYONE`'s order is a rule that says which surface is "later":

* **Within a shape** (`[I5]`): a coplanar polygon later in the display list is a decal of the one under it.
* **Between a prop and the terrain** (ADR 0035): a flat prop lying within 10 cm of the terrain is a decal of it.

Both draw the decal after its base with `LessEqual` and a bias toward the viewer. A decal therefore wins any near-tie, not only the one against its own base, while still losing to anything clearly in front, as in the painter. Where a rule's net is wrong, we differ:
- **Wrong winner:** on `INTRO` tick 1086 a tile now covers a prop; whether `PLAYONE`'s order covers it too is not known (open question 4 there).

Rejected ways to win the tie:
- Sinking the terrain by a constant: only right while the constant exceeds the depth step, which grows with the square of distance.
- A third pipeline with a slope bias on the terrain: 37 `INTRO` ticks lost.

Both are in [`world-scene.md`](../playone-exe/world-scene.md) section 6.3.

**Precision.** `Depth24Plus` with near 0.5 m resolves about z² / (0.5 × 2²⁴): 1 cm at 300 m, 12 cm at 1 km. The decal rules do not depend on it, because they make the surfaces coplanar and let the bias decide. Renderer tests hold a snapped tile at 8 km. Reversed-Z with `Depth32Float` is the fallback if a non-coplanar case shows far away (ADR 0035).

## Ruled out

* **A painter's renderer of our own:** it would be the exact model, but [SPEC](../../docs/SPEC.md) section 2.1 rules out CPU painting, and the ties it would fix are handled by the decal rules at a cost of a few ticks.
* **A constant terrain sink, a biased terrain pass:** section 3 and [`world-scene.md`](../playone-exe/world-scene.md) section 6.3.

## Open questions

1. **Painter errors in the films.** No frame has been traced where `PLAYONE`'s walk order covers a nearer object. If one exists, the depth buffer draws that frame "better" than the capture.
2. **Actors in the walk.** Where film actors enter `PLAYONE`'s back-to-front order relative to the scenery, and whether an actor on the ground ties the terrain like a tile, is not traced.
3. **`SHADE*` light per actor.** The world light is in ([#221](https://github.com/neilsh/stunt-reel/issues/221), [`sod-vm.md`](../playone-exe/sod-vm.md) section 8.5); an actor's own light, turned by its rotation and the view each frame, would need shading after decode.
4. **`GVPOLY` ramp fraction.** The per-vertex index is interpolated ([#221](https://github.com/neilsh/stunt-reel/issues/221)); carrying each vertex's 8.8 fraction and flooring, as the filler does, is not tried.
5. **`OP_ANIMATE`.** Draw the blit, or show that the two demo films never reach it.
