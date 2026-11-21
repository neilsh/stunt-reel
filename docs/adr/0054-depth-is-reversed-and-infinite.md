# Depth is reversed and infinite

## Status

accepted 2026-11-20 for [#637](https://github.com/neilsh/stunt-reel/issues/637).
#637 proposed reversed depth in `Depth32Float`; this ADR departs from that proposal and keeps `Depth24Plus` (Considered Options), and the owner has not yet signed off on the departure.
Amends the compare functions and the sign of the depth bias of [ADR 0046](0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) (`LessEqual`, `constant: -2, slope_scale: -2.0`); its other decisions stand.

## Context

The renderer stored standard depth (near plane 0, far plane 1) in `Depth24Plus`, with a DirectX perspective from 0.5 m to 25 km.
Its clip z came from the projection's third row, `A·z + B`, a sum whose rounding the vertex stage could do differently on each backend.
After eye-relative transforms (#636), lavapipe and the RTX 4070 still drew different pixels at near-coplanar ties ([`lavapipe.md`](../../research/parity/lavapipe.md) section 5).
Under a reversed, infinite perspective clip z is the constant `near`, so depth is `near / w` and rounds only through `w` and the division.

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

## Considered Options

* **`Depth32Float`, which #637 proposed.**
  In f32, `near / w` keeps 24 significant bits at every distance.
  Measured on the same films against `main` `5fbfe844` (the Backend agreement figures under Consequences hold on `b028f7d3` too), it made the backends disagree on more pixels than standard depth did (LOCATION 62.0 to 92.7 per tick, BALLOON 19.9 to 44.6, TRAINTNL 20.7 to 30.9; CTRY and INTRO 0.2 and 0.7 lower), and at 13 sampled ticks of five films the decal bias did not explain it: a constant of 0 or 1,024 in place of that variant's 32 moved the disagreement by at most 2 pixels a tick, a slope of 8 in place of 2 by at most 7, and a slope of 0 raised it.
  The same projection in `Depth24Plus` lowered it at 12 of those 13 ticks, by up to 18 times (LOCATION 3820 2,856 to 182, BALLOON 1130 191 to 37).
  `[Supported Inference]`: rounding the interpolated depth to a 24-bit step absorbs differences between the two rasterizers' depth interpolation that f32 keeps, so a tie between coplanar polygons resolves by the compare function alike on both.
* **A reversed, finite far plane at 25 km.**
  Not measured: the infinite form was chosen because its clip z is exactly `near`.

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
