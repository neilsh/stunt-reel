---
summary: "Compares PLAYONE's back-to-front software painter with our depth-buffer renderer stage by stage, naming each known divergence and the `[I5]` ordered decal pass and ground-decal rules that imitate its tie order."
sidebar_label: "Render model: painter vs depth"
---
# Render Model: PLAYONE's Painter Against Our Depth Buffer

* **Scope**: stage by stage, what `PLAYONE.EXE` does to put a frame on screen, what our renderer does in its place, and where the two are known to differ.
  It routes to the notes that own each fact rather than restating them.
* **Sources**: the `playone-exe/` and `formats/` notes linked in each row, [`docs/SPEC.md`](../../docs/SPEC.md) section 2.1, the ADRs named below, and the code paths cited.
* **Evidence tier**: each row carries the tier of the note it cites.
  A divergence marked *measured* has a dated score, in a journal entry or a row of the [parity log](../../work/2026-10/parity-log/log.md); *unmeasured* means we know the mechanisms differ but have not scored the gap.

## 1. The two models

`PLAYONE` is a software painter.
1. Each frame it walks the scenery tree back to front, culling by distance and level of detail.
2. It runs each object's display list, which may itself sort subtrees back to front (`sorton`).
3. It fills every polygon into the Mode 13h framebuffer at a palette index, with no depth buffer.
   A later polygon covers an earlier one, whatever their depths.
4. The palette, built per frame from film variables, gives the colours.

Our renderer replaces the painting with a GPU depth buffer, by design: [`docs/SPEC.md`](../../docs/SPEC.md) section 2.1 makes "CPU-side Painter's Algorithm / BSP polygon sorting" a non-goal.
- It builds the world once per film (`crates/stunt-core/src/world/mod.rs`) and draws a sky pass, a world ground pass (`Always`, depth write) that paints the flat ground in walk order ([ADR 0045](../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md)), a base pass (`Greater`) and an `[I5]` decal pass (`GreaterEqual`, bias `2, 2.0`, no depth write; `crates/stunt-render/src/pipeline.rs`, [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)).
- Depth is reversed and infinite in `Depth24Plus`: `0.1 m / w` (the near plane is a sweep pick, not read from `PLAYONE`, whose polygon clipper has none; [`attribution.md` § 2](attribution.md#2-current-breakdown)), 1 at the near plane and 0 at infinity, with no far plane ([ADR 0054](../../docs/adr/0054-depth-is-reversed-and-infinite.md); `renderer/mod.rs`, `camera.rs`).
- Polygons are flat at their palette index through the `[I3]` 256 × 32 lookup, with no lighting (`shaders/mode13h.wgsl`).

The two orders agree wherever the nearer surface is also painted later, which is most of the frame.
They differ in three ways:
* **Ties.**
  Two surfaces at the same depth: the painter takes the later one, a depth buffer takes whichever rounds nearer.
  Every rule in section 3 exists for this case.
* **Grain.**
  The painter decides per polygon or per object, the depth buffer per pixel.
  Objects that pass through each other, or a polygon the walk orders wrongly, come out differently.
  We do not reproduce the painter's errors.
* **Fixed-once work.**
  Some things `PLAYONE` decides per frame we decide once per film, when the world is built, whatever the camera does: which props are ground decals ([ADR 0035](../../docs/adr/0035-ground-lying-props-are-terrain-decals.md)) and which prop triangles are flat ground ([ADR 0045](../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md)).
  Level of detail is per frame in both; what ours fixes once per film is which `SP_1NODE` nodes get both branches built, from the camera path, with the stand-in alone for the rest ([`lod.md`](../playone-exe/lod.md) section 4.1), and the renderer gates each built branch per frame.

## 2. Stage by stage

| Stage | `PLAYONE` | Ours | Known divergence | Owner |
|---|---|---|---|---|
| Frame composition | One 3D scene per frame, then the credits text; no second view or inset | One scene per frame | None found | [`sod-vm-frame.md`](../playone-exe/sod-vm-frame.md) section 9 |
| Palette and fades | Built per frame from vars 13-15, interpolated like the other film variables, sent to the DAC | The same variables into the `[I3]` lookup (`contracts/palette/mod.rs`) | The DAC shows entries 0-127 one frame and 128-255 two frames late (section 5.2); the scorer compensates for fades | [`palette-fade.md`](../playone-exe/palette-fade.md), [`palette-and-shading.md`](../formats/concepts/palette-and-shading.md) |
| Sky | Zenith and horizon colours from the palette build | A full-screen sky pass drawn first, no depth | Unmeasured | [`palette-fade.md`](../playone-exe/palette-fade.md) section 3 |
| Visibility order | Back-to-front walk of the scenery tree, no depth buffer | Depth buffer | Ties, grain and fixed-once work (section 1) | [`world-scene.md`](../playone-exe/world-scene.md) section 1, [SPEC](../../docs/SPEC.md) 2.1 |
| Level of detail | Per frame, an `SP_1NODE` distance gate on half the view-space depth, scaled by the lens and detail word | Per frame, the same gate (`LodBranch` groups); both branches built for nodes the camera path comes near | Measured and adopted | [`lod.md`](../playone-exe/lod.md) section 4.1 |
| Projection | The lens variable zooms the view matrix | `lens_fov_degrees`, square 256 px projection | Measured and adopted | [`lod.md`](../playone-exe/lod.md) sections 2.2, 4.3 |
| Ground | Type-14 leaves drawn flat at their stored colour through the raw gateway, no light | `MAP.BIN` patches drawn flat (`push_terrain`), patch 131 with its 8th anchor | We draw every active record; 20 active records have no leaf in the image (#175) | [`world-scene.md`](../playone-exe/world-scene.md) section 2 |
| Ground tiles | Painted after the leaf under them, so they always cover it | Ground decals: a flat prop within 10 cm of the terrain is snapped onto it and drawn in the `[I5]` pass | Measured: CTRY 0.8645, INTRO 0.7973; see section 3 | [`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md) section 6, [ADR 0035](../../docs/adr/0035-ground-lying-props-are-terrain-decals.md) |
| Sorting inside a shape | Polygons and spheres in list order; `sorton` runs its inline branch first while its facing flag is set, the other first while clear (`[Established]`, static) | `OP_SORT` emits both branches, inline first; a sphere is an icosahedron. A shape whose places are at least a tenth spheres draws in list order: each polygon at its rank sphere's nearest depth, a step per place ([ADR 0056](../../docs/adr/0056-sphere-shapes-are-drawn-in-list-order.md)); any other shape is ordered by the depth buffer | List order raises the share of `bomb`'s tree pixels in the capture's index from 0.59–0.69 to 0.85–0.91 on a CPU painter, and in the renderer `bomb` by 0.0027 SSIM on lavapipe with no film or frame falling past the bars; `OP_SORT` branches in facing order fixed `intro`'s propeller in a prototype but, lower every film ([#1066](https://github.com/neilsh/stunt-reel/issues/1066)) | [`sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) section 8.6, [`prop-shape-loss.md`](prop-shape-loss.md) section 2.3 |
| Decals inside a shape | A coplanar polygon later in the stream covers the earlier one | `identify_coplanar_decals` flags it in place (`sod/decal.rs`); the `[I5]` pass draws decals in stream order with no depth write | Measured 2026-11-13 (section 3) | [SPEC](../../docs/SPEC.md) `[I5]`, [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) |
| Flat shading (`SHADE*`) | `base + shade`, the shade from `N . L` with the world light from var 13, rotated into a rotated object's frame | The world light `(99, 32766, -17)` from var 13 in the raw model frame for every shape, actors unrotated (`ShadeLight`, `sod/light.rs`) | Measured 2026-11-05: CTRY 0.8646 -> 0.8641, INTRO 0.7986 -> 0.8128, all of it on the aircraft; an actor's rotated light is not modelled | [`terrain-shade.md`](../playone-exe/terrain-shade.md) section 4.2, [`sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) section 8.5 |
| Gouraud polygons (`GVPOLY`, `GVPOLY16`) | A per-vertex ramp on the palette index, 8.8 fixed point, hard bands along screen-linear iso-lines | The ramp base plus each vertex's level, interpolated in screen space and rounded per fragment; the vertex fraction is dropped | Measured 2026-11-05: CTRY 0.8641 -> 0.8642, INTRO 0.8128 -> 0.8166 | [`terrain-shade.md`](../playone-exe/terrain-shade.md) sections 1, 6, 7 |
| Raster blits (`OP_ANIMATE`) | A screen-space blit of an image resource, zero bytes transparent, in the painter's order | A camera-facing square of the frame in its actor's layer, drawn at its slot's place in the scenery walk: over the depth-tested world, under the props the walk draws after it and the actors nearer than its slot | `INTRO` +0.0013, `CTRY` +0.0001 when added (one run, one GPU); `CTRY`, `INTRO` and `BOMB` up when placed (one run, lavapipe); actors ordered by depth, not by their walk | [`sod-animate.md`](../playone-exe/sod-animate.md) |
| Rasterisation | Software span filling in 320 × 200, its own clipping | GPU rasterisation at 320 × 200, 4:3 presentation | Edge and sub-pixel coverage differ; mask IoU 0.9897 CTRY, 0.9856 INTRO | [`attribution.md`](attribution.md), [`method.md`](method.md) |

## 3. Where we imitate the painter

The depth buffer gets one case visibly wrong: a later polygon that ties an earlier one.
Each place we imitate `PLAYONE`'s order is a rule that says which surface is "later":

* **Within a shape** (`[I5]`): a coplanar polygon later in the display list is a decal of the one under it, and a `MOVETO`/`ZLINETO` line later in it that lies on a decal is a decal too, since `PLAYONE` draws a line when it runs, with no depth test ([`sod-vm-lines-spans.md`](../playone-exe/sod-vm-lines-spans.md) section 8.10).
  A line on a facet that is no decal stays in the base pass: flagging it too drew lines over a near wall in `BOMB` that the capture does not show ([`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md) section 6.6).
  _Source: [2026-11-17: lines lying on an earlier facet are decals of it](../../work/2026-11/448_zlineto-under-facet/journal.md#2026-11-17-lines-lying-on-an-earlier-facet-are-decals-of-it)._
* **Between a prop and the terrain** (ADR 0035): a flat prop lying within 10 cm of the terrain is a decal of it.
* **On the ground plane** (ADR 0045): the ocean, flat `MAP.BIN` patches and prop triangles within 0.1 m of `y = base_y`, put on it, are not depth-tested at all; they are painted first, in walk order, each over the last.

The first two draw the decal after its base with `GreaterEqual` (depth is reversed), a bias toward the viewer and no depth write.
A decal therefore wins any near-tie, not only the one against its own base, while still losing to anything clearly in front, as in the painter.
Writing no depth makes the decal pass an ordered one: each decal is tested against the base geometry's depth, not against other decals, so a later decal covers an earlier one stacked on the same facet, as the painter does; a decal's outline is drawn right after its fill, per fan in a shape and per slice in the world, for the same reason.
No decal is moved off its facet.
`[Supported Inference]`: the rule is the painter's of section 1, and the pass that follows it was scored on all seven reference films and adopted on the evidence track, BOMB's target frames rising most (+0.0190 SSIM).

_Source: [prototype A wins the comparison](../../work/2026-11/489_ordered-decal-pass/comparison.md#2026-11-13-prototype-a-depth-bias-wins-the-comparison)._

Where a rule's net is wrong, we differ:
- **Wrong winner:** on `INTRO` tick 1086 a tile now covers a prop; whether `PLAYONE`'s order covers it too is not known (open question 3 of [`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md)).
- **Near surfaces:** the bias is in depth-buffer units, so a decal also beats any other surface within a few depth steps of it; two steps of `Depth24Plus` are about 24 cm at 1 km by the arithmetic below, more at grazing angles, where the slope term grows (`[Hypothesis]`, not measured).
  In one sweep under standard depth (`[Bounded Observation]`), the constant changed no score from −1 to −8, a slope of `-8` let decals through near surfaces (109 frames down by more than 0.005) and `-0.5` cost a target frame 0.016.
- **Edge pixels between coplanar decals:** on `LOCATION`'s facades, pixels where coplanar bands and a roof edge meet changed owner (tick 3202, 343 pixels, −0.0152, the worst frame of the judge's list); in the two rows looked at, the capture matches the old render.
  The outlines of one world decal slice are drawn after all of its fills, while an earlier slice's outline now lies under every later slice; which of the two moves these pixels is not attributed. `[Bounded Observation]`.
- **Overhangs:** a decal that overhangs its base writes no depth there, so a decal drawn later behind it can paint over the overhang.
  Not seen in a film.

_Source: [decals in stream order, no depth write, hardware depth bias](../../work/2026-11/489_ordered-decal-pass/depth-bias.md#2026-11-13-decals-in-stream-order-no-depth-write-hardware-depth-bias)._

Rejected ways to win the tie:
- Sinking the terrain by a constant: only right while the constant exceeds the depth step, which grows with the square of distance.
- A third pipeline with a slope bias on the terrain: 37 `INTRO` ticks lost.

Both are in [`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md) section 6.3.

**Precision.**
Depth `0.1 m / w` in `Depth24Plus` resolves about z² / (0.1 × 2²⁴): 5 cm at 300 m, 60 cm at 1 km, five times coarser than the 0.5 m near plane before it ([ADR 0054](../../docs/adr/0054-depth-is-reversed-and-infinite.md)).
The decal rules do not depend on it, because they make the surfaces coplanar and let the bias decide; a fixed geometric offset would (ruled out below).
Renderer tests hold a snapped tile at 8 km.

## Ruled out

* **A painter's renderer of our own:** it would be the exact model, but [SPEC](../../docs/SPEC.md) section 2.1 rules out CPU painting, and the ties it would fix are handled by the decal rules and, on the ground plane, by the GPU's draw order (ADR 0045), at a cost of a few ticks.
* **A constant terrain sink, a biased terrain pass:** section 3 and [`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md) section 6.3.
* **Moving decals off their facet** (`[I5]` before ADR 0046: 1 mm along the stored normal; PR #488: `k` mm per stacked level): the stored normal sinks clockwise ground decals; equal offsets tie stacked decals; per-level offsets do not separate past about 100 m, bury actor shadows and bake offsets into exports ([#489](https://github.com/neilsh/stunt-reel/issues/489)).
* **A stencil id per base, matched by its decals with no depth test** (prototype B): adopts too, with a worse worst target frame (−0.0071 against −0.0037) and twice the frames down by more than 0.005; [comparison](../../work/2026-11/489_ordered-decal-pass/comparison.md#2026-11-13-prototype-a-depth-bias-wins-the-comparison).

## Open questions

1. **Painter errors in the films.**
   `CTRY` tick 871 is one: the walk draws the explosion, whose slot lies 22.5 m along the view axis, over the towers at 20.7 and 21.7 m, as the capture shows ([`scene-walk-actors.md`](../playone-exe/scene-walk-actors.md) § 4); we copy that order for `OP_ANIMATE` sprites (item 6).
   No frame has been traced where the walk order puts a scenery object or a 3D actor over a nearer one; where one exists, the depth buffer draws that frame "better" than the capture.
2. **Actors in the walk.**
   How an actor's entry passes the scenery walk is traced statically: the partition planes split it, and at the leaf it reaches it is ordered against that leaf's object by depth ([`scene-walk-actors.md`](../playone-exe/scene-walk-actors.md) § 2); we draw `OP_ANIMATE` sprites so (item 6) and keep 3D actors depth-tested.
   Whether an actor on the ground ties the terrain like a tile is not traced.
3. **`SHADE*` light per actor.**
   The world light is in ([#221](https://github.com/neilsh/stunt-reel/issues/221), [`sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) section 8.5); an actor's own light, turned by its rotation and the view each frame, would need shading after decode.
4. **`GVPOLY` ramp fraction.**
   The per-vertex index is interpolated ([#221](https://github.com/neilsh/stunt-reel/issues/221)); carrying each vertex's 8.8 fraction and flooring, as the filler does, is not tried.
5. **Edge pixels between coplanar decals.**
   Attribute `LOCATION` 3202's edge pixels to the outline order inside or between world decal slices, then decide whether per-fan outlines in the world mesh (per-polygon draws, or the edge buffer split per fan) bring them to the capture or away from it.
6. **`OP_ANIMATE` draw order.**
   The blit takes its slot's place in the scenery walk against the world's props; against 3D actors it is ordered by the slots' view depths, as a shared leaf's sort orders them, not by a plane where their entries part ([`scene-walk-actors.md`](../playone-exe/scene-walk-actors.md) § 6; [`sod-animate.md`](../playone-exe/sod-animate.md), Open questions).
