# Ground-lying props are terrain decals

## Status

proposed 2026-11-04. Implements the change that
[`world-scene.md` section 6](../../research/playone-exe/world-scene.md#6-what-the-renderer-gets-wrong-and-the-change-it-licenses)
licenses, for [#69](https://github.com/neilsh/stunt-reel/issues/69); answers
[#176](https://github.com/neilsh/stunt-reel/issues/176). Applies `[I5]` to a class of props that
the SOD decode does not mark as decals.

## Context

`PLAYONE.EXE` has no depth buffer. It walks the scenery tree back to front, so a scenery tile laid
on the ground is painted after the ground leaf under it and always covers it. Our renderer has a
depth buffer, and the tiles tie the terrain exactly: measured against the `MAP.BIN` triangle under
each vertex, the 16 airfield and sand tiles sit within 8 mm of it, most within 1 mm
([`world-scene.md` section 6.1](../../research/playone-exe/world-scene.md#61-how-far-the-tiles-sit-from-the-terrain)).
The tile quads and the fan triangles of the patch are different triangulations of one plane, so
their depths differ by rounding and the terrain wins about half the pixels. The base pass draws
them all with `Less`, so the tile shows only where it happens to round in front. On the pixels the
render draws as terrain, 71% (`CTRY`) and 54% (`INTRO`) are the wrong colour.

Two candidates that need no change to the world were measured and kept as probes: sinking the
terrain by a constant (0.8649 / 0.7971 SSIM on `CTRY` / `INTRO`) and a third pipeline drawing the
terrain with a positive slope-scale bias (0.8640 / 0.7943).

## Decision

`build_world_ir` classifies each placed prop and treats a ground-lying one as a decal of the
terrain:

* **Rule.** A prop is ground-lying when its shape is flat (every vertex within 5 cm of one
  height), at least one vertex has terrain below it, and every vertex that does is within 10 cm of
  it. The data separate the groups widely: the largest offset of anything picked is 3.2 cm, the
  smallest of a flat prop left out is 22 cm.
* **Snap.** Each vertex over terrain takes the height of the terrain triangle at its `x, z`
  (the triangle nearest in height where patches overlap in plan). The tile then ties its patch in
  plane and depth instead of rounding either way.
* **Route.** Every mesh of a ground-lying prop goes to the `WORLD_DECAL` node, which the renderer
  draws after the base pass under `[I5]` (`LessEqual`, negative bias). The terrain is not moved.
  Terrain nearer the camera still hides a decal, because the decal pass keeps the depth test.

## Consequences

* `CTRY` 0.8298 to 0.8645 and `INTRO` 0.7745 to 0.7973 SSIM, mask IoU unchanged, no `CTRY` tick
  down by more than 0.002 and two `INTRO` ticks (1086 and 1317). It matches the terrain sink within
  0.0004 without that candidate range limit (a constant that shrinks as a fraction of the depth step
  the further the camera is) and without moving any mountain leaf. Ticks 2918-2973, which the biased
  terrain pass lost, are unchanged.
* The rule also takes flat markings and patches that lie on the ground (`0x03BE..0x03C3`, `0x064A`,
  `INTRO` `0x05CB..0x05D7` and others), which is the same kind of object. Flat props that hover
  (`INTRO` `0x0790..0x07B4`, 2 m up) stay in the base pass.
* Cost: one terrain-triangle scan per vertex of each flat instance when the world is built, nothing
  per frame.
* Depth precision: `Depth24Plus` with the existing bias held at 1, 1.5, 2, 4 and 8 km at a grazing
  angle in the renderer tests, for tiles snapped as above. Reversed-Z with `Depth32Float` was not
  adopted because nothing needed it; revisit it if a tile on a patch whose corners are not coplanar
  flickers far away.
* Open: `SCENERY3.RES` #1, 2, 5, 6 are not flat in our decode and are not covered (open question 4
  of the note).

## Considered Options

* **Sink the terrain by 5 cm.** Same score, but it moves every polygon, was not checked far from
  the camera, and loses `INTRO` tick 1086 as the prototype does.
* **Bias the terrain pass.** Loses 37 `INTRO` ticks, ticks 2918-2973 by up to 0.04.
* **Draw all terrain first without depth writes.** Would lose the occlusion of a prop by a nearer
  mountain leaf.
