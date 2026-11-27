# Sphere shapes are drawn in list order

## Status

accepted 2026-11-27 for [#1066](https://github.com/neilsh/stunt-reel/issues/1066); the owner chose to adopt it on 2026-11-27, after the bridge deck was kept out of it.
Amends the **No CPU Software Rasterizer** line of [`SPEC.md`](../SPEC.md) § 2.1: within a list-ranked shape, depth follows the display list instead of geometry.

## Context

`PLAYONE` paints a shape's polygons and `OP_SPHERE` discs in display-list order, so a later primitive covers an earlier one whatever its depth ([`render-model.md`](../../research/parity/render-model.md) § 2).
We draw a sphere as an icosahedron in the depth buffer, so the nearer primitive wins instead.
On `bomb`'s autumn trees that loses the capture's look: a later leaf cluster should cover the trunk and the earlier clusters, and a CPU painter in list order carries the capture's index on 0.85 to 0.91 of the trees' pixels against 0.59 to 0.69 for our render ([`prop-shape-loss.md`](../../research/parity/prop-shape-loss.md) § 2.3).

The prototypes and sweeps are in the [work folder's journal](../../work/2026-11/1066_sphere-list-order/journal.md).
Flattening every shape with a sphere to its placement's depth raised `bomb`'s target frames but let the ground cover the near half of `location`'s forest canopies; taking the depth from the shape's near side fixed that, and left `location`'s bridge deck (a slab holding one small sphere) covering the road's markings.

## Decision

* **Which shapes.**
  A shape is list-ranked when at least a tenth of its display-list places are spheres, an `OP_SPHERE`'s 20 faces counting as one place (`list_ranks` in `crates/stunt-core/src/sod/tessellate.rs`).
  The 131 shapes with a sphere that `bomb` and `location` decode at the ticks looked at fall into two groups: 120 at 12% or more, and 11 at 7% or less, with one to 13 spheres among 92 to 284 places; among the 11 are the bridge's deck slab and the two shapes whose bounds (20 m by 84 m by 8 m) are its towers.
* **Rank.**
  Each polygon of a ranked shape gets its place, from 1, in `SodVertex::list_rank`; a sphere's faces share one.
  Vertices of different places never weld.
  A `ZLINETO` line stays unranked.
* **Depth.**
  Each ranked shape gets one `RankSphere` (`SodModelIr::rank_spheres`): its vertices' bounding-box centre and the distance to the farthest of them.
  A world prop's is moved with its placement.
  The apex stream widens to four floats; a ranked filled vertex carries its sphere there.
  The vertex shader draws a ranked vertex at the depth of that sphere's point nearest the eye (no nearer than 5 cm), plus eight 24-bit depth steps per rank (`list_order_depth` in `mode13h.wgsl`).
  So the shape's primitives cover each other in list order and still depth-test against other objects.
  An outline corner of a ranked polygon carries no sphere; it takes the depth of the third vertex of the triangle its edge bounds, one step per rank.
  Shadow draws, orthographic views and collapsed corners keep their own depth.
* **`OP_SORT` is unchanged.**
  Our VM still runs a `SORT`'s inline branch first; running branches in facing order lowered every film as prototyped, so it is not part of this decision.

## Consequences

* On lavapipe, against `main` before the change, no film falls by the 0.002 film bar and no frame of any film by more than 0.005; `bomb` rises by 0.0027 and `balloon` by 0.0013, and the 21 scored frames of `bomb`'s target ranges all rise ([sweep](../../work/2026-11/1066_sphere-list-order/sweeps/lavapipe-sphere-share.toml)).
  The gains are near the sweep's noise floor of 0.002.
* `SodVertex` grows from 28 to 32 bytes and the apex stream from 12 to 16 bytes a vertex.
* Inside a ranked shape a polygon's depth no longer says where it is: an outline or a line of that shape can lose to its own flattened fill.
* The lavapipe expected scores are repinned with the change.

## Considered Options

* **Flatten to the placement's depth** (the first prototype): the ground covers the near half of wide canopies whose foot is the placement, and `location` falls.
* **A fixed pull toward the eye**: 5 m fixed the forest; 15 m drew far shapes over nearer ones and `bomb` fell on 51 frames.
* **Rank every shape with a sphere**: the bridge deck slab `MODEL_023D` (one sphere in 92 places) covers the deck's road markings, and `location` 6513 and 6689 fall by 0.025 and 0.050.
* **A CPU painter**: excluded by § 2.1; the depth buffer still orders everything between shapes.
* **`OP_SORT` in facing order**: fixes the `intro` aircraft's propeller (a shape this rule leaves unranked: 2 spheres among 139 places) but, as prototyped, lowers every film; left for later.
