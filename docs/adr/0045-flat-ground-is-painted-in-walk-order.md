# Flat ground is painted in walk order

## Status

accepted 2026-11-13 for [#446](https://github.com/neilsh/stunt-reel/issues/446). Supersedes the
**Route** decision of [ADR 0035](0035-ground-lying-props-are-terrain-decals.md) for geometry flat
on the ground plane; ADR 0035's **Rule** and **Snap** stand, and its **Route** still applies to a
ground-lying prop off that plane, such as a tile on a hill. The `[I5]` lift that **What is flat
ground** subtracts is gone under [ADR 0046](0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)
(proposed).

## Context

`PLAYONE.EXE` has no depth buffer. It paints the scenery in its walk order, the later polygon over
the earlier, and `SP_2NODE` (`0x1EC0..0x1EEE`) visits its first child and then its second without
testing which side the eye is on
([`world-scene.md` section 6.6](../../research/playone-exe/world-scene.md#66-ocean-coloured-tile-polygons-over-land)).

Our renderer resolved the flat ground by depth. ADR 0035 routed ground-lying props to the
`WORLD_DECAL` node, drawn under `[I5]`'s biased `LessEqual` pass. Every polygon in the plane
`y = base_y` (the `MAP.BIN` patches, the tiles, roads and lawns on them, stacked decals) then ties
every other one, and which wins depends on how each triangulation rounds its depth, or on which
pass it landed in, not on `PLAYONE`'s order. Unbiased flat props such as `LOCATION`'s lawns lost to
the terrain under them, and roads tied biased decals by one ULP.

A prototype painted the flat ground first, in walk order, through a pass that writes depth and
replaces whatever is there. It scored up on six films and down on `TRAINTNL`, whose distant track
turned into a solid band. Its outlines were drawn after all of a mesh's triangles, so a tie's
outline could cover the one-pixel rail drawn after the tie; the tie's own fill, in the later
`SOD_DECAL` mesh, covers the rails too.

## Decision

* **What is flat ground.** The ocean, every `MAP.BIN` patch whose corners all lie on the plane
  `y = base_y` (within 0.1 mm), and every prop triangle whose three corners lie on it, less any
  `[I5]` lift the decoder gave a decal. Raised terrain and the rest of each prop stay in the base and
  decal passes, so a nearer mountain still hides what lies behind it.
* **Where it goes.** `build_world_ir` puts that geometry in `WORLD_GROUND` nodes
  (`stunt_core::world::GROUND_NODE`): the ocean, the flat patches in `MAP.BIN` order, then each
  placement's flat triangles in placement order, under the placement's `SP_1NODE` groups and with
  its mesh's gate; placements sharing a group are painted together where its first one is.
* **How it is drawn.** The renderer collects those slices in a forward walk and draws them first,
  through a pipeline with `CompareFunction::Always` and depth write, each slice's outline right
  after it.
* **Lines.** A prop mesh's flat triangles are split into runs of filled and line
  (`VERTEX_FLAG_LINE`) triangles, one node per run, so no outline is drawn over a line that
  follows it in the mesh (a renderer test shows it). No score separates this from one node per
  mesh: the sweep that preferred it ran with a bug since fixed (journal).
* **Not a CPU sort.** This is the GPU's draw order over a fixed walk, not a sort by depth, so
  `SPEC.md` section 2.1's non-goal on CPU painter sorting stands.

## Consequences

* All seven reference films were scored; six rise and `TRAINTNL` falls by 0.0005, inside the
  evidence-backed track's guard: the scores are in the
  [journal entry](../../work/2026-11/446_world-ground-pass/journal.md#2026-11-13-snapped-decals-lost-their-lift-twice-and-missed-the-ground-pass).
* `TRAINTNL`'s distant opening shot still falls. The decoder puts the track's rail lines in
  `SOD_BASE` and its tie in `SOD_DECAL`, so the tie, painted with the later mesh, still covers
  the rails; how `tessellate.rs` splits a shape into those meshes is
  [#448](https://github.com/neilsh/stunt-reel/issues/448).
* Flat patches are painted in `MAP.BIN` order and all of them before any prop. `PLAYONE`'s tree
  interleaves terrain leaves and props, and its order was checked against `MAP.BIN`'s for three
  records only (`world-scene.md` section 6.5), so a patch painted over a prop, or the other way
  round, can still come out wrong.
* In the static world, `[I5]`'s depth bias now separates only decals off the ground plane; actor
  decals keep it everywhere.
* Cost: one more pipeline pair and one or two draws (fill, outline) per ground slice; a placement
  of a flat prop adds a node per run.

## Considered Options

* **Keep resolving by depth** (ADR 0035's **Route**). Leaves the ties to rounding.
* **Draw the outlines before a slice's triangles.** Keeps outlines off the lines, but the fill of
  a polygon earlier in the same slice would then cover the outline of every polygon after it,
  such as a distant tie's under the track bed drawn before it. Not measured.
* **Mask the outlines off the pixels a line drew** (a stencil). Needs a stencil attachment and
  per-shape clears for the same result as splitting the runs.
