# Coplanar decals are drawn in an ordered pass

## Status

accepted 2026-11-14 for [#489](https://github.com/neilsh/stunt-reel/issues/489). Supersedes the
**What is flat ground** clause of [ADR 0045](0045-flat-ground-is-painted-in-walk-order.md) where
it removes "any `[I5]` lift the decoder gave a decal": decals have no lift left to remove. ADR
0045's other decisions stand.

## Context

`PLAYONE.EXE` paints with no depth buffer, so a polygon later in a shape's stream covers an
earlier coplanar one ([`render-model.md`](../../research/parity/render-model.md) section 1).
`[I5]` imitated that by moving each decal 1 mm along its stored normal and drawing it with a
depth bias. That failed three ways (#489): the stored normal points down on clockwise ground
faces, so ground decals sank below their base (#449); decals stacked on one facet all got the
same 1 mm and tied each other (BOMB truck `0x4142`); and PR #488's fix, `k` mm per stacked
level, did not separate levels past about 100 m with `Depth24Plus`, buried actor shadows under
level-2 decals and baked offsets of up to 15 mm into the model and its glTF export.

## Decision

* **No geometric offset.** The decoder flags a polygon as a decal when it is coplanar with an
  earlier polygon of the stream, by front normal (the side `FrontFace::Cw` keeps, from the
  winding) against the earlier polygons as decoded, and leaves it where it is. `SodModelIr`
  and the renderer carry no decal offset.
* **An ordered pass.** Decals draw after all base geometry, in stream order, with `LessEqual`,
  a hardware depth bias toward the viewer (`constant: -2, slope_scale: -2.0`) and no depth
  write. Each decal is tested against the base geometry's depth, not against other decals, so
  a later coplanar decal covers an earlier one. Actor shadows, flattened 1 mm above the
  ground, use the same state. Outlines follow the fill they belong to: per fan in a shape's
  decal node, per draw slice in the world. Ungated world decals share one `WORLD_DECAL` node,
  so within each of its draw slices the outlines still follow all of the fills. The world's
  decal outlines are a line list, and wgpu allows depth bias only on triangles, so they
  compare `LessEqual` with no bias and can lose pixels to a base exactly in their plane.
* **The exporter alone lifts.** glTF has no depth bias or draw order, so `stunt-gltf` moves
  decal vertices 1 mm (`EPSILON_DISPLACEMENT`) toward their front on export.

## Consequences

* Against `main` (`3d680420`), no reference film's mean falls and CTRY, TRAINTNL and BOMB
  rise by more than 0.002; BOMB's target frames rise by +0.0190
  in SSIM (+0.0141 in index agreement), and the worst target frame is LOCATION 4775 at
  −0.0037
  ([comparison](../../work/2026-11/489_ordered-decal-pass/comparison.md)).
* The bias is in depth-buffer units, so unlike a fixed offset it does not shrink below the
  depth step with distance (inferred, not measured past the films' ranges). The flip side is
  that a decal also beats any other surface within a few depth steps of it: with
  `Depth24Plus`, near plane 0.5 m and far plane 25 km, two steps are about 24 cm at 1 km by
  arithmetic, more at grazing angles through the slope term.
* A decal that overhangs its base writes no depth there, so a decal drawn later behind it can
  paint over the overhang.
* On LOCATION's facades, pixels where coplanar bands and a roof edge meet changed owner
  (tick 3202, 343 pixels, −0.0152, the worst frame of the judge's list); in the two rows
  looked at, the capture matches `main`. Between world decal slices the outline order
  changed; inside a slice the outlines still follow all the fills, which no longer write
  depth. Which of the two moves these pixels is not attributed.

## Considered Options

* **Per-level offsets** (PR #488, `k × 1 mm`). Closed: the failures in Context.
* **A stencil id per base, matched by its decals with no depth test** (prototype B). Passed
  the adoption rule too, with a worse worst target frame (−0.0071), and needs a seam-contract
  field, a stencil format, per-group draws and ids that wrap at 255
  ([comparison](../../work/2026-11/489_ordered-decal-pass/comparison.md)).
