---
summary: "Compares PLAYONE's back-to-front software painter with our depth-buffer renderer stage by stage, naming each known divergence and the `[I5]` ordered decal pass and ground-decal rules that imitate its tie order."
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
- It builds the world once per film (`crates/stunt-core/src/world/mod.rs`) and draws a sky pass, a world ground pass (`Always`, depth write) that paints the flat ground in walk order ([ADR 0045](../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md)), a base pass (`Less`) and an `[I5]` decal pass (`LessEqual`, bias `-2, -2.0`, no depth write; `crates/stunt-render/src/pipeline.rs`, [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)).
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
| Level of detail | Per frame, an `SP_1NODE` distance gate on half the view-space depth, scaled by the lens and detail word | Per frame, the same gate (`LodBranch` groups); both branches built for nodes the camera path comes near | Measured and adopted | [`lod.md`](../playone-exe/lod.md) section 4.1 |
| Projection | The lens variable zooms the view matrix | `lens_fov_degrees`, square 256 px projection | Measured and adopted | [`lod.md`](../playone-exe/lod.md) sections 2.2, 4.3 |
| Ground | Type-14 leaves drawn flat at their stored colour through the raw gateway, no light | `MAP.BIN` patches drawn flat (`push_terrain`), patch 131 with its 8th anchor | We draw every active record; 20 active records have no leaf in the image (#175) | [`world-scene.md`](../playone-exe/world-scene.md) section 2 |
| Ground tiles | Painted after the leaf under them, so they always cover it | Ground decals: a flat prop within 10 cm of the terrain is snapped onto it and drawn in the `[I5]` pass | Measured: CTRY 0.8645, INTRO 0.7973; see section 3 | [`world-scene.md`](../playone-exe/world-scene.md) section 6, [ADR 0035](../../docs/adr/0035-ground-lying-props-are-terrain-decals.md) |
| Sorting inside a shape | `sorton` walks the two subtrees back to front against a separating plane (`[Supported Inference]`) | `OP_SORT` emits both branches; the depth buffer orders them (`sod/vm.rs`) | Unmeasured | [`sod-opcodes.md`](../formats/sod-opcodes.md) section 2.5 |
| Decals inside a shape | A coplanar polygon later in the stream covers the earlier one | `identify_coplanar_decals` flags it in place (`sod/decal.rs`); the `[I5]` pass draws decals in stream order with no depth write | Measured 2026-11-13 (section 3) | [SPEC](../../docs/SPEC.md) `[I5]`, [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) |
| Flat shading (`SHADE*`) | `base + shade`, the shade from `N . L` with the world light from var 13, rotated into a rotated object's frame | The world light `(99, 32766, -17)` from var 13 in the raw model frame for every shape, actors unrotated (`ShadeLight`, `sod/light.rs`) | Measured 2026-11-05: CTRY 0.8646 -> 0.8641, INTRO 0.7986 -> 0.8128, all of it on the aircraft; an actor's rotated light is not modelled | [`terrain-shade.md`](../playone-exe/terrain-shade.md) section 4.2, [`sod-vm.md`](../playone-exe/sod-vm.md) section 8.5 |
| Gouraud polygons (`GVPOLY`, `GVPOLY16`) | A per-vertex ramp on the palette index, 8.8 fixed point, hard bands along screen-linear iso-lines | The ramp base plus each vertex's level, interpolated in screen space and rounded per fragment; the vertex fraction is dropped | Measured 2026-11-05: CTRY 0.8641 -> 0.8642, INTRO 0.8128 -> 0.8166 | [`terrain-shade.md`](../playone-exe/terrain-shade.md) sections 1, 6, 7 |
| Raster blits (`OP_ANIMATE`) | A screen-space blit of an image resource, zero bytes transparent, in the painter's order | A camera-facing square of the frame, depth-tested in its actor's layer: cut where an object stands inside it | `INTRO` +0.0013, `CTRY` +0.0001 when added (one run, one GPU) | [`sod-animate.md`](../playone-exe/sod-animate.md) |
| Rasterisation | Software span filling in 320 × 200, its own clipping | GPU rasterisation at 320 × 200, 4:3 presentation | Edge and sub-pixel coverage differ; mask IoU 0.9897 CTRY, 0.9856 INTRO | [`attribution.md`](attribution.md), [`method.md`](method.md) |

## 3. Where we imitate the painter

The depth buffer gets one case visibly wrong: a later polygon that ties an earlier one. Each place we imitate `PLAYONE`'s order is a rule that says which surface is "later":

* **Within a shape** (`[I5]`): a coplanar polygon later in the display list is a decal of the one under it.
* **Between a prop and the terrain** (ADR 0035): a flat prop lying within 10 cm of the terrain is a decal of it.
* **On the ground plane** (ADR 0045): the ocean, flat `MAP.BIN` patches and prop triangles on `y = base_y` are not depth-tested at all; they are painted first, in walk order, each over the last.

The first two draw the decal after its base with `LessEqual`, a bias toward the viewer and no depth write. A decal therefore wins any near-tie, not only the one against its own base, while still losing to anything clearly in front, as in the painter. Writing no depth makes the decal pass an ordered one: each decal is tested against the base geometry's depth, not against other decals, so a later decal covers an earlier one stacked on the same facet, as the painter does; a decal's outline is drawn right after its fill, per fan in a shape and per slice in the world, for the same reason. No decal is moved off its facet. `[Supported Inference]`: the rule is the painter's of section 1, and the pass that follows it was scored on all seven reference films and adopted on the evidence track, BOMB's target frames rising most (+0.0190 SSIM).

_Source: [prototype A wins the comparison](../../work/2026-11/489_ordered-decal-pass/comparison.md#2026-11-13-prototype-a-depth-bias-wins-the-comparison)._

Where a rule's net is wrong, we differ:
- **Wrong winner:** on `INTRO` tick 1086 a tile now covers a prop; whether `PLAYONE`'s order covers it too is not known (open question 4 there).
- **Near surfaces:** the bias is in depth-buffer units, so a decal also beats any other surface within a few depth steps of it; two steps of `Depth24Plus` are about 24 cm at 1 km by the arithmetic below, more at grazing angles, where the slope term grows (`[Hypothesis]`, not measured). In one sweep (`[Bounded Observation]`), the constant changed no score from −1 to −8, a slope of `-8` let decals through near surfaces (109 frames down by more than 0.005) and `-0.5` cost a target frame 0.016.
- **Edge pixels between coplanar decals:** on `LOCATION`'s facades, pixels where coplanar bands and a roof edge meet changed owner (tick 3202, 343 pixels, −0.0152, the worst frame of the judge's list); in the two rows looked at, the capture matches the old render. The outlines of one world decal slice are drawn after all of its fills, while an earlier slice's outline now lies under every later slice; which of the two moves these pixels is not attributed. `[Bounded Observation]`.
- **Overhangs:** a decal that overhangs its base writes no depth there, so a decal drawn later behind it can paint over the overhang. Not seen in a film.

_Source: [decals in stream order, no depth write, hardware depth bias](../../work/2026-11/489_ordered-decal-pass/depth-bias.md#2026-11-13-decals-in-stream-order-no-depth-write-hardware-depth-bias)._

Rejected ways to win the tie:
- Sinking the terrain by a constant: only right while the constant exceeds the depth step, which grows with the square of distance.
- A third pipeline with a slope bias on the terrain: 37 `INTRO` ticks lost.

Both are in [`world-scene.md`](../playone-exe/world-scene.md) section 6.3.

**Precision.** `Depth24Plus` with near 0.5 m resolves about z² / (0.5 × 2²⁴): 1 cm at 300 m, 12 cm at 1 km. The decal rules do not depend on it, because they make the surfaces coplanar and let the bias decide; a fixed geometric offset would (ruled out below). Renderer tests hold a snapped tile at 8 km. Reversed-Z with `Depth32Float` is the fallback if a non-coplanar case shows far away (ADR 0035).

## Ruled out

* **A painter's renderer of our own:** it would be the exact model, but [SPEC](../../docs/SPEC.md) section 2.1 rules out CPU painting, and the ties it would fix are handled by the decal rules and, on the ground plane, by the GPU's draw order (ADR 0045), at a cost of a few ticks.
* **A constant terrain sink, a biased terrain pass:** section 3 and [`world-scene.md`](../playone-exe/world-scene.md) section 6.3.
* **Moving decals off their facet** (`[I5]` before ADR 0046: 1 mm along the stored normal; PR #488: `k` mm per stacked level): the stored normal sinks clockwise ground decals; equal offsets tie stacked decals; per-level offsets do not separate past about 100 m, bury actor shadows and bake offsets into exports ([#489](https://github.com/neilsh/stunt-reel/issues/489)).
* **A stencil id per base, matched by its decals with no depth test** (prototype B): adopts too, with a worse worst target frame (−0.0071 against −0.0037) and twice the frames down by more than 0.005; [comparison](../../work/2026-11/489_ordered-decal-pass/comparison.md#2026-11-13-prototype-a-depth-bias-wins-the-comparison).

## Open questions

1. **Painter errors in the films.** No frame has been traced where `PLAYONE`'s walk order covers a nearer object. If one exists, the depth buffer draws that frame "better" than the capture.
2. **Actors in the walk.** Where film actors enter `PLAYONE`'s back-to-front order relative to the scenery, and whether an actor on the ground ties the terrain like a tile, is not traced.
3. **`SHADE*` light per actor.** The world light is in ([#221](https://github.com/neilsh/stunt-reel/issues/221), [`sod-vm.md`](../playone-exe/sod-vm.md) section 8.5); an actor's own light, turned by its rotation and the view each frame, would need shading after decode.
4. **`GVPOLY` ramp fraction.** The per-vertex index is interpolated ([#221](https://github.com/neilsh/stunt-reel/issues/221)); carrying each vertex's 8.8 fraction and flooring, as the filler does, is not tried.
5. **Edge pixels between coplanar decals.** Attribute `LOCATION` 3202's edge pixels to the outline order inside or between world decal slices, then decide whether per-fan outlines in the world mesh (per-polygon draws, or the edge buffer split per fan) bring them to the capture or away from it.
6. **`OP_ANIMATE` draw order.** The blit is drawn; it still loses to the depth test where `PLAYONE`'s painter's order puts it in front ([`sod-animate.md`](../playone-exe/sod-animate.md), Open questions).
