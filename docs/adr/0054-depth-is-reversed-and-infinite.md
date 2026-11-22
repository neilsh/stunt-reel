# Depth is reversed and infinite

## Status

accepted 2026-11-20 for [#637](https://github.com/neilsh/stunt-reel/issues/637).
#637 proposed reversed depth in `Depth32Float`; this ADR departs from that proposal and keeps `Depth24Plus` (Considered Options), and the owner has not yet signed off on the departure.
Amends the compare functions and the sign of the depth bias of [ADR 0046](0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) (`LessEqual`, `constant: -2, slope_scale: -2.0`); its other decisions stand.
Amended 2026-11-21 for [#922](https://github.com/neilsh/stunt-reel/issues/922): the outline line lists are clipped to a band around the view, and the device requires clip distances (the last two Decision bullets, and the Considered Options and Consequences marked #922).

## Context

The renderer stored standard depth (near plane 0, far plane 1) in `Depth24Plus`, with a DirectX perspective from 0.5 m to 25 km.
Its clip z came from the projection's third row, `A·z + B`, a sum whose rounding the vertex stage could do differently on each backend.
After eye-relative transforms (#636), lavapipe and the RTX 4070 still drew different pixels at near-coplanar ties ([`lavapipe.md`](../../research/parity/lavapipe.md) section 5).
Under a reversed, infinite perspective clip z is the constant `near`, so depth is `near / w` and rounds only through `w` and the division.

The world's polygon outlines are line lists, drawn in the ground, base and decal passes.
Lavapipe clips a line against the near plane but not against the sides of the view ([`lavapipe-line-clip.md`](../../research/parity/lavapipe-line-clip.md) section 1).
An outline edge that passes beside the eye and reaches behind it is cut where `w` equals `near`, and that end lands tens of thousands of pixels off the page; lavapipe's line rasteriser draws such a line as a wedge, which the GPU does not.
Moving the near plane from 0.5 m to 0.1 m (#904) put those ends five times farther out, and LAND's mean disagreement between lavapipe and the GPU rose from 26.20 to 309.42 pixels a tick (#922).

## Decision

* **Reversed, infinite perspective.**
  `compute_proj_matrix` builds glam's `perspective_infinite_reverse`: clip z is the constant `near` (0.5 m when accepted, 0.1 m since [#904](https://github.com/neilsh/stunt-reel/issues/904)) and clip w the distance along the view axis, so depth is `near / w`, 1 at the near plane and falling toward 0 at infinity.
  Nothing is clipped far away; `far_clip` is used by the orthographic projection only.
* **Reversed orthographic.**
  The orthographic projection swaps its near and far planes, so it too maps near to 1 and far to 0, and every pipeline uses one compare direction.
* **`Depth24Plus`, cleared to 0.**
  The buffer stays fixed-point (see Considered Options for `Depth32Float`).
* **Compare directions.**
  The base pass compares `Greater`, the decal pass and the decal outlines `GreaterEqual`.
  The ground pass (`Always`, depth write, ADR 0045), the sky and the bars ignore depth.
* **The decal bias.**
  The `[I5]` bias is `constant: 2, slope_scale: 2.0`, ADR 0046's magnitudes with the sign flipped: toward the viewer is now positive, because nearer is larger.
  In a fixed-point buffer the constant's unit is one step of the buffer, as before, and the slope term is still two pixels of the decal's own depth gradient.
* **Sky.**
  The sky pass draws its bands and sun disc from the pixel's raster position (#617), so it unprojects nothing, and depth 0 lying at infinity (`w = 0`) does not reach it.
* **A clip band on the line lists** (#922).
  The three line-list pipelines draw through the vertex entry `vs_edge`, which writes four user clip distances, `1.1·w ∓ x` and `1.1·w ∓ y` (`EDGE_CLIP_BAND` in `mode13h.wgsl`).
  Lavapipe applies user planes to lines, so every line reaches its rasteriser within a tenth of the view's half-width or half-height beyond its edge; nothing inside the view is cut.
  Triangle pipelines keep `vs_main`: lavapipe clips triangles against the view's sides already, and the band would add a clip step there for nothing.
  The near plane stays at 0.1 m, so what #904 fixed (the police car's door on BOMB, the tunnel wall on TRAINTNL) is kept.
* **The device requires `wgpu::Features::CLIP_DISTANCES`** (#922).
  The adapter search chooses among the adapters that offer it, so a machine with none fails with `NoGpuAdapter` rather than rendering without the band.
  wgpu's DX12 backend, WARP included, does not offer it (wgpu-hal 30.0.1 sets the feature in its Vulkan, Metal and GL adapters, never in DX12's); the RTX 4070 and lavapipe, the two renderer classes with pinned scores, do.

## Considered Options

* **`Depth32Float`, which #637 proposed.**
  In f32, `near / w` keeps 24 significant bits at every distance.
  Measured on the same films against `main` `5fbfe844` (the Backend agreement figures under Consequences hold on `b028f7d3` too), it made the backends disagree on more pixels than standard depth did (LOCATION 62.0 to 92.7 per tick, BALLOON 19.9 to 44.6, TRAINTNL 20.7 to 30.9; CTRY and INTRO 0.2 and 0.7 lower), and at 13 sampled ticks of five films the decal bias did not explain it: a constant of 0 or 1,024 in place of that variant's 32 moved the disagreement by at most 2 pixels a tick, a slope of 8 in place of 2 by at most 7, and a slope of 0 raised it.
  The same projection in `Depth24Plus` lowered it at 12 of those 13 ticks, by up to 18 times (LOCATION 3820 2,856 to 182, BALLOON 1130 191 to 37).
  `[Supported Inference]`: rounding the interpolated depth to a 24-bit step absorbs differences between the two rasterizers' depth interpolation that f32 keeps, so a tie between coplanar polygons resolves by the compare function alike on both.
* **A reversed, finite far plane at 25 km.**
  Not measured: the infinite form was chosen because its clip z is exactly `near`.
* **Request clip distances only where the adapter has them, and draw the outlines through `vs_main` elsewhere** (#922).
  Keeps WARP, drawing the outlines through `vs_main` unclipped (WARP's line drawing was not measured), at the cost of a second shader path that no machine with pinned scores runs.
* **Clip the ground outlines at 0.5 m** (#922).
  Returns only to the pre-#904 level, needs a second clip depth kept consistent with the fill's, and leaves the base and decal outlines exposed.
* **Draw the world's outlines as triangle quads**, as the actors' are, which lavapipe clips against the view's sides (#922).
  About five times the world's outline vertices.
* **A depth bias or a reordered pass** (#922).
  Does not apply: the wedge is coverage, not a depth tie.

## Consequences

* **Backend agreement.**
  Over every tick of the seven reference films, the mean index-plane pixels per tick on which lavapipe (mesa-dist-win 25.2.8) and the RTX 4070 differ fell on every film: CTRY 12.2 to 6.3, INTRO 12.8 to 8.9, LAND 35.7 to 26.2, BALLOON 19.9 to 8.9, TRAINTNL 20.7 to 5.2, BOMB 14.7 to 11.6 and LOCATION 62.0 to 29.8 ([journal](../../work/2026-11/637_reversed-z/journal.md)).
* **GPU parity.**
  No reference film's score falls by the adoption rule's 0.002 and no frame by more than 0.005; no film rises enough to adopt on score (same journal entry).
* **Precision.**
  Reversed depth in a fixed-point buffer resolves what standard depth did: a step of `2^-24` in `near / w` is `w² × 2^-24 / near` in distance, about 12 cm at 1 km with the 0.5 m near plane this ADR was accepted with, 60 cm at 0.1 m ([#904](https://github.com/neilsh/stunt-reel/issues/904)).
* **Actor shadows.**
  The actor shadow, flattened 1 mm above the ground, keeps going through the decal pass.
* **Decal outlines.**
  The world's decal outlines are a line list, which wgpu cannot bias; they compare `GreaterEqual` unbiased and still lose pixels to a base exactly in their plane, as under ADR 0046.
* **The far plane.**
  The ocean quad (32 km half-width, `WORLD_EXTENT`) is no longer cut at 25 km.
* **CPU frustum tests.**
  `CameraController::world_view_proj()`, which CPU-side tests use for world points, is reversed: the near plane is `z = w` and there is no far plane.
  The world's view-frustum cull (`frustum_keeps` in `mesh.rs`) keeps its six planes: depth still runs over `[0, w]`, so `z ≥ 0` and `w - z ≥ 0` bound it, now as the far and near planes.
  Under the perspective, clip z is the constant `near`, so the far plane keeps every box in front of the eye.
* **Class agreement after the clip band** (#922).
  Over every tick of the seven reference films, the mean differing pixels per tick between the canonical lavapipe and the RTX 4070 fell on six and held on BALLOON, and every film ended below its pre-#904 level (CTRY 22.37 to 3.09, LAND 309.42 to 5.23, LOCATION 79.24 to 8.60; [`lavapipe-line-clip.md`](../../research/parity/lavapipe-line-clip.md) section 2).
* **GPU parity after the clip band** (#922).
  The GPU's own render moves by at most 0.7 pixels a tick, and no reference film's score falls by the adoption rule's 0.002.
* **CI and adapters** (#922).
  The Windows job's GPU tests ran on a runner with no Vulkan driver, so on WARP, which lacks clip distances, and they are expected to skip there from #922 on; the Linux jobs run them on lavapipe.
  A software render without lavapipe no longer falls back to WARP: it fails to find an adapter.
* **Edge shader** (#922).
  `EdgeVertexOutput` repeats `VertexOutput`'s varyings, since a fragment input cannot hold clip distances; the two must change together.
