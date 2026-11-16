# Depth is reversed and infinite, in f32

## Status

accepted 2026-11-16 for [#637](https://github.com/neilsh/stunt-reel/issues/637). Amends the
depth-bias values of [ADR 0046](0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)
(`constant: -2, slope_scale: -2.0` under `LessEqual`); its other decisions stand.

## Context

The renderer stored standard depth (near plane 0, far plane 1) in `Depth24Plus`, with a DirectX
perspective from 0.5 m to 25 km. Standard depth is `A - B / w`, so nearly all its resolution
sits by the near plane: at 80 m, where the ties of
[`lavapipe.md` section 5](../../research/parity/lavapipe.md#5-what-still-differs) sit, depth is
about 0.994 and one step of the 24-bit buffer is about 1.5 mm. A near-coplanar tie there goes
to whichever backend rounds nearer, and lavapipe and the RTX 4070 broke such ties in opposite
directions.

## Decision

* **Reversed, infinite perspective.** `compute_proj_matrix` builds glam's
  `perspective_infinite_reverse`: clip z is the constant `near` (0.5 m), clip w the distance
  along the view axis, so depth is `near / w`, 1 at the near plane and falling toward 0 at
  infinity. Nothing is clipped far away; `far_clip` is used by the orthographic projection
  only.
* **Reversed orthographic.** The orthographic projection swaps its near and far planes, so it
  too maps near to 1 and far to 0, and every pipeline can use one compare direction.
* **`Depth32Float`, cleared to 0.** In f32, `near / w` keeps 24 significant bits at every
  distance, so its resolution is a fixed fraction of the distance (about 6e-8 to 1.2e-7 of it)
  instead of shrinking with the square of the distance.
* **Compare directions.** The base pass compares `Greater`, the decal pass and the decal
  outlines `GreaterEqual`. The ground pass (`Always`, depth write, ADR 0045), the sky and the
  bars ignore depth.
* **Sky.** The sky pass draws its bands and sun disc from the pixel's raster position
  (#617), so it unprojects nothing and depth 0 lying at infinity (`w = 0`) does not reach it.

### The decal bias

The `[I5]` bias is now `constant: 32, slope_scale: 2.0` toward the viewer, positive because
nearer is now larger.

* **Slope term.** The slope term is `slope_scale × m`, `m` the triangle's largest depth change
  per pixel, in depth units for either format. `2.0` keeps its meaning: two pixels of the
  decal's own depth gradient, so only the sign changes.
* **Constant term.** For a float depth format the unit is `r = 2^(e - 23)`, `e` the exponent
  of the triangle's largest depth, so `r` is more than `2^-24` of that depth and the constant
  is a fraction of the distance at every pixel of the triangle (for `Depth24Plus` it was a
  fixed `2^-24` of depth, about 24 cm at 1 km). The constant must cover the rounding by which
  two coplanar triangles' depths disagree where the slope term is near 0 (a face seen
  head-on). With `u = 2^-24`, each vertex's eye-relative position rounds by up to about `3u`
  of its distance per component (a matrix row: three products and the translation), the dot
  product giving `w` adds `3u`, carrying the position's error through adds about `3√3 u`, and
  the division `near / w` adds `u`: about `9u` a vertex, and twice that, `18u` to `20u`,
  between two triangles whose roundings fall opposite ways. 32 is the next power of two that
  covers it.
* **What it costs.** A decal also beats any surface within the bias of it. With the constant
  at most `32 × 2^-23` of the distance, that is under 4 mm at 1 km and 0.3 mm at 80 m, against
  about 24 cm and 1.5 mm for `-2` in `Depth24Plus`.
* **What it moved.** On twelve single ticks of LAND, BOMB and CTRY, the constants tried (0 and
  16 on eight ticks, 2, 16 and 64 on six) drew the same index planes as each other on each
  backend: on those frames the slope term and the compare's equality settle the ties, and the
  constant is a guard for the head-on case
  ([journal](../../work/2026-11/637_reversed-z/journal.md)).

## Consequences

* The actor shadow, flattened 1 mm above the ground, stays in front of the ground by about
  `1 mm / h` of its distance for a camera `h` metres up, far above the bias.
* The world's decal outlines are a line list, which wgpu cannot bias; they compare
  `GreaterEqual` unbiased and still lose pixels to a base exactly in their plane, as under
  ADR 0046.
* The ocean quad reaches 32 km from the island's centre and is no longer cut at 25 km, so a
  high camera can see a few more rows of ocean at the horizon.
* A CPU frustum test of world points uses `CameraController::world_view_proj()`, whose depth
  is reversed: the near plane is `z = w` and there is no far plane.
* The world's view-frustum cull (`frustum_keeps` in `mesh.rs`) keeps its six planes: depth
  still runs over `[0, w]`, so `z ≥ 0` and `w - z ≥ 0` bound it, now as the far and near
  planes. Under the perspective clip z is the constant `near`, so the far plane keeps every
  box in front of the eye.

## Considered Options

* **Reversed Z in `Depth24Plus`.** A fixed-point buffer gains nothing from reversing:
  `near / w` would then have the same absolute resolution everywhere, coarse far away.
* **A reversed, finite far plane at 25 km.** Depth is then about `near / w - near / far`, with
  nearly the same precision, and the 25 km far clip stays. Not measured: the infinite form
  was chosen because its clip z is exactly `near`, so the depth rounds only through `w` and the
  division.
