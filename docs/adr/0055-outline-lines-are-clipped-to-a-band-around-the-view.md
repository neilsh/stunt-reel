# Outline lines are clipped to a band around the view

## Status

accepted 2026-11-21 for [#922](https://github.com/neilsh/stunt-reel/issues/922).

## Context

The world's polygon outlines are drawn as line lists, in the ground, base and decal passes.
Mesa's lavapipe clips a line against the near plane but not against the sides of the view ([`lavapipe-line-clip.md`](../../research/parity/lavapipe-line-clip.md) section 1).
An outline edge that passes beside the eye and reaches behind it is cut where `w` equals the near distance, and that end lands tens of thousands of pixels off the page; lavapipe's line rasteriser draws such a line as a wedge, which the GPU does not.
Moving the near plane from 0.5 m to 0.1 m (#904, [ADR 0054](0054-depth-is-reversed-and-infinite.md)) put those ends five times farther out, and LAND's mean disagreement between lavapipe and the GPU rose from 26.20 to 309.42 pixels a tick.

## Decision

* **A clip band on the line lists.**
  The three line-list pipelines draw through the vertex entry `vs_edge`, which writes four user clip distances, `1.1·w ∓ x` and `1.1·w ∓ y` (`EDGE_CLIP_BAND` in `mode13h.wgsl`).
  Lavapipe applies user planes to lines, so every line reaches its rasteriser within a tenth of the view's half-width or half-height beyond its edge; nothing inside the view is cut.
  Triangle pipelines keep `vs_main`: lavapipe clips triangles against the view's sides already, and the band would add a clip step there for nothing.
* **The device requires `wgpu::Features::CLIP_DISTANCES`.**
  The adapter search passes over an adapter without it, so a machine with none fails with `NoGpuAdapter` rather than drawing wedges.
  wgpu's DX12 backend, WARP included, does not offer it; the RTX 4070 and lavapipe, the two renderer classes with pinned scores, do.
* **The near plane stays at 0.1 m**, so what #904 fixed (the police car's door on BOMB, the tunnel wall on TRAINTNL) is kept.

## Considered Options

* **Request the feature where the adapter has it, and draw the outlines through `vs_main` elsewhere.**
  Keeps WARP, with its wedges, at the cost of a second shader path that no machine with pinned scores runs.
* **Clip the ground outlines at 0.5 m.**
  Returns only to the pre-#904 level, needs a second clip depth kept consistent with the fill's, and leaves the base and decal outlines exposed.
* **Draw the world's outlines as triangle quads**, as the actors' are, which lavapipe clips against the view's sides.
  About five times the world's outline vertices.
* **A depth bias or a reordered pass.**
  Does not apply: the wedge is coverage, not a depth tie.

## Consequences

* **Class agreement.**
  Over every tick of the seven reference films, the mean differing pixels per tick between the canonical lavapipe and the RTX 4070 fell on six and held on BALLOON, and every film ended below its pre-#904 level (CTRY 22.37 to 3.09, LAND 309.42 to 5.23, LOCATION 79.24 to 8.60; [`lavapipe-line-clip.md`](../../research/parity/lavapipe-line-clip.md) section 2).
* **GPU parity.**
  The GPU's own render moves by at most 0.7 pixels a tick, and no reference film's score moves by the adoption rule's margin.
* **CI.**
  The Windows job's GPU tests ran on WARP, which lacks the feature, so they are expected to skip there from this change on; the Linux jobs run them on lavapipe.
* **Adapters.**
  A software render without lavapipe no longer falls back to WARP: it fails to find an adapter.
* **Shader.**
  `EdgeVertexOutput` repeats `VertexOutput`'s varyings, since a fragment input cannot hold clip distances; the two must change together.
