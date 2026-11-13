# Journal: distilling `sod-vm.md`

The dated rounds and scored results of [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) as of commit `f7e9c55`, moved here verbatim when the note was distilled to current truth. Only relative link paths changed; a section number in the moved text names a section of the note as it stood at `f7e9c55` (`git show f7e9c55:research/playone-exe/sod-vm.md`). An entry whose text carries no date is dated by the parity-log row or work journal that records it.

## 2026-11-01: SHADE ramps painted flat, and the triplane's running colour

From section 8.5 of the note, as it stood at `f7e9c55`:

The renderer first painted each such polygon flat at `base` plus the mean of its vertices' levels: grey-ramp pixels moved toward the capture's (`CTRY` 3.7k -> 33.8k against 52.4k, `INTRO` 120k -> 44.5k against 49.8k) but SSIM did not rise ([parity log](../../2026-10/parity-log/log.md)).

Before the ramp word was read, `INTRO.FLM` tick 1009 drew the triplane's fuselage grey and its wings bright pink where the capture has a red fuselage and dark red wings (capture above, ours below): [`intro-1009-gvpoly-running-colour.png`](../aircraft-render/images/intro-1009-gvpoly-running-colour.png).

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.5.

## 2026-11-05: the shade light

From section 8.5 of the note, as it stood at `f7e9c55`:

**The light** (2026-11-05, [#221](https://github.com/neilsh/stunt-reel/issues/221)). `SHADES` dots `L` with the shape's raw normal words, and an unrotated object is handed the world light as stored, so `L` is in the raw model frame and needs no game-to-`[I1]` axis mapping: the decoder keeps the normals in that frame too. The mapping is derived, not chosen by score. The decoded model frame is +Y up ([`coordinates-and-units.md` § 1.2](../../../research/formats/concepts/coordinates-and-units.md#12-right-handed-metric-basis-i1)), so `(99, 32766, -17)` points up, and `s = -(N . L)` leaves an upward face at its ramp base and lifts a downward one. The old stand-in `SHADE_LIGHT = (0, -32767, 0)` had the opposite sign. Both films set film variable 13 to `0x2D` at tick 0 (`mise run flm-events`), the value `0x196C` was seen with on both, so both get `(99, 32766, -17)` ([`ShadeLight`](../../../crates/stunt-core/src/sod/light.rs)); how `0x196C` maps other values is open ([`terrain-shade.md`](../../../research/playone-exe/terrain-shade.md), open question 1). Measured with `DBG_SHADE_LIGHT`, all shapes decoded under one light: the stand-in 0.8646 / 0.7986 (CTRY / INTRO), the world light 0.8641 / 0.8128, its negation `(-99, -32766, 17)` and the 180-degree-about-Z form `(-99, -32766, -17)` both 0.8646 / 0.7986 (the 99 and 17 move no shade across a ramp step, so only the sign of y matters). The world light for scenery with the stand-in for actors scored 0.8646 / 0.7986 exactly: no scenery shade that reaches the screen moves, and the whole gain is on the aircraft. Actors are therefore decoded under the world light unrotated, the light `PLAYONE` would hand a level, unrotated object. Their own light turns with their rotation and the view every frame, and shapes are decoded once, so it is not modelled.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.5.

## 2026-11-05: facing flags scored

From section 8.6 of the note, as it stood at `f7e9c55`:

`SORTON` (`0x9183`) reads the same table (`js` on the flag byte) to order its two branches. The renderer keeps each `REJ` face as `VisibilityCondition::FacesEye { point: b, normal: n }` in model space and draws the section while `n · (b - eye) < 0`, with the eye taken into each actor's space, and into the world's for scenery props, every frame. Measured 2026-11-05 ([parity log](../../2026-10/parity-log/log.md)): CTRY 0.8645 -> 0.8646, INTRO 0.7973 -> 0.7986; the opposite sign gives 0.8061 / 0.7366, which fixes the sign. The old reading (condition 1 as `D^2 <= 1000 m^2`, everything else drawn) had no binary basis.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.6.

## 2026-11-06: OP_VECTORS turned like the cube

From section 8.7 of the note, as it stood at `f7e9c55`:

**Adopted: `OP_VECTORS` turned the same way** (store `(−x, −y, z)`; measured first with the temporary switch `DBG_VECNEG`):

* **Aircraft.** All 14 inverted stock `0x7Fxx` aircraft stand upright, as do the two unclear ones (`0x7F18`, `0x7F21`); the 9 that were upright, and the `OP_IPG`-led aircraft, are unchanged.
* **Every other shape.** Of the 397 stock shapes holding the word `0x0075`, 229 export different geometry; the rest are unchanged, and 19 export nothing either way (terrain patches without anchors, empty shapes). In side views, none turns over and many are righted: the masts of the sailing ships `0x4114`..`0x4117`, `0x414D`, `0x414E` and `0x4153` (below the hull before), the conning tower of `0x3E19`, the antennas of `0x3D47`/`0x3D48`, the wheels of trucks and tanks, and the sign `0x063D`, which now reads "STUNT / ISLAND" top to bottom.
* **Parity** (sweep, RTX 4070): `CTRY.FLM` 0.8725 → 0.8986, `INTRO.FLM` 0.8273 → 0.8337, IoU unchanged. At `CTRY` tick 499 the biplane matches the capture, wing stripes included, which the hand-picked mirror culled ([log row](../../2026-10/parity-log/log.md)).

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.7.

## 2026-11-05: per-vertex shade interpolation scored

From section 8.5 of the note, as it stood at `f7e9c55`:

**Interpolation.** The `GVPOLY` handlers write `(index << 8) | fraction` per vertex and the filler `0x75DB` interpolates it linearly in screen space ([`terrain-shade.md`](../../../research/playone-exe/terrain-shade.md) sections 5-6). The renderer now gives each vertex its own index (`base` plus that vertex's level, the fraction dropped) and interpolates it in screen space (`@interpolate(linear)`), rounding to a whole index per fragment (`[I3]`): CTRY 0.8641 -> 0.8642, INTRO 0.8128 -> 0.8166 (`DBG_GVPOLY_INTERP`). Rounding stands in for the dropped fraction: `PLAYONE` floors the interpolated 8.8 value, and an average fraction of one half makes that a rounding of the whole indices.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.5.

## 2026-11-11: view-facing type-8 shapes scored

From section 8.8 of the note, as it stood at `f7e9c55`:

**Adopted** (evidence-backed): a shape with header bit 0 is drawn turned about `+Y` so that its `+Z` lies along the camera's look direction seen from above. That heading is taken to equal the yaw of `Ry(−yaw)` (`[Supported Inference]`: the sign was checked only by the trees drawing rather than culling); past vertical pitch it is half a turn off, and a camera looking straight down gets heading 0 where `PLAYONE` keeps its yaw word. A view-facing prop also skips the per-placement `OP_TAP` decode and the ground-decal snap; the type-8 trees of the reference archives run no `OP_TAP`. Props with the bit leave the static world mesh and are drawn each frame as props, behind their `SP_1NODE` gates; actors with it drop the slot's rotation, while their shadow keeps it, since `0x1C0D` builds the shadow matrix from the slot's angles. At `INTRO.FLM` tick 2080 the hill pines, missing before, now stand facing the camera as in the capture; at tick 3301 the foreground pines still draw. `mean_ssim_scored` (RTX 4070 Laptop): CTRY 0.89960 → 0.89962 and INTRO 0.84177 → 0.84172, both under the 0.002 floor; of the other reference films only LOCATION moves by more than 0.0001, 0.80682 → 0.80800.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.8.

## 2026-11-11: one-pixel screen lines scored

From section 8.10 of the note, as it stood at `f7e9c55`:

The change was adopted, every reference film's score rising, measured against main's ribbons restored by a temporary switch on the same commit: `CTRY` 0.8996 to 0.9015, `INTRO` 0.8418 to 0.8437, `LAND` 0.8654 to 0.8662, `BALLOON` 0.8030 to 0.8097, `TRAINTNL` 0.8518 to 0.8548, `BOMB` 0.8101 to 0.8129, `LOCATION` 0.8068 to 0.8088. Each of `INTRO` camera 1's scored ticks gains 0.0034 to 0.0060: its power line about 437 m away, drawn by `ZLINETO` spans, is two continuous one-pixel cables, as the capture shows, where the 0.03 m ribbons came to scattered dots.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.10.

## 2026-11-12: OP_PERFDISK's radius against a BOMB capture

From section 8.8 of the note, as it stood at `f7e9c55`:

`vm.rs` draws the disc as a 16-gon (16 is a guess at roundness; the radius is checked, below) in the plane perpendicular to the raw register difference `regs[centre] − regs[axis]`, one face for each side, in the current colour, with `radius` in register units. **Scale checked against a same-camera capture** ([#425](https://github.com/neilsh/stunt-reel/issues/425)). `OP_SPHERE` shifts the radius product by 8 and divides by depth; this handler shifts by 16 (`0xA0A2..0xA0A6`: `imul [0x8070]`, high word) and leaves the perspective to the conic it builds, so the two shifts do not by themselves say the disc is 256 times smaller. `BOMB` tick 2058 has a capture and a render from the same camera (the car body's left edge and the disc's centre column agree to 2 px), and the wheel disc's width agrees with `radius` in register units to about 2 px (one shape, ticks 2058 and 2070; other shapes and depths unchecked): at the rows 172 and 184 the capture is 77 and 91 px wide, the 16-gon 72 and 87 px, and a 64-gon 1 to 2 px under the capture; at tick 2070 the capture and the 64-gon differ by 1 to 2 px over four rows (`[Bounded Observation]`: two ticks, one shape, widths read off the palette index of the disc's flat colour). The 16-gon is 4 to 6 % narrow and the 64-gon closes most of that gap; the remainder is unexplained, perhaps the stepped ellipse of `0xD11D`. A 32-gon moved no film by more than 0.00015 SSIM and BOMB, LOCATION, LAND and INTRO fell (BOMB -0.00014), so it is not adopted and 16 stays. The `work:0x8108` rescale of the normal's depth difference (`0xA0DB..0xA0E8`) is `dz · 0x8108 · 2^(0x810C+1) >> 16`; with the view matrix's two screen rows scaled by `0x8108` in Q15 and the depth row shifted right by `0x810C` ([`memory-map.md`](../../../research/playone-exe/memory-map.md)), that makes the normal's three components share one scale, which `vm.rs` already has because it keeps the normal in the model frame, so no rescale is added (`[Supported Inference]`: read from the two sites, not verified live; the tilt looks similar, and a 2 px height gap at tick 2058 is unexplained). The near-depth cut, the shadow-pass skip and the early exits are not reproduced. Scored against the seven reference films with `mise run parity` (RTX 4070). _Source: [the handler read and the scores](../392_perfdisk/journal.md#2026-11-12-the-handler-read-to-its-end-and-drawn)._

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.8.

## 2026-11-12: polygon outlines for thin polygons and the world mesh

From section 8.11 of the note, as it stood at `f7e9c55`:

**What it does to thin polygons** (`[Bounded Observation]`, `INTRO.FLM` tick 3301, [#426](https://github.com/neilsh/stunt-reel/issues/426)). The pines `0x03A3` and `0x03A7` are a type-8 quad (section 8.8) whose `INTV` midpoints make two `POLYZ` triangles: the whole tree, and a sliver outside its right edge at most a sixth of its half-width across. The capture draws a six-pixel-wide pine's sliver as a strip of light green one to two pixels wide down 14 rows (21 pixels); our renderer, whose rasteriser fills only pixels whose centres a triangle covers, drew 2 pixels of it. Across the top-left 100 × 100 pixels the four tree colours covered 1,471 pixels in the capture and 815 in ours, with every tree checked in a 60 × 60 part of the crop at the same place in both. `[Supported Inference]` that the inclusive spans are why the sliver measured is drawn.

The renderer follows it in part. `stunt-render` draws every edge that exactly one filled triangle of a mesh node uses as a one-pixel screen line (section 8.10), in its end vertices' colours, after the node's triangles ([`outline.rs`](../../../crates/stunt-render/src/outline.rs)), so a polygon also covers the pixels its outline crosses. It does this as line quads for the shapes drawn per frame (actors and view-facing props such as these pines), and as a line list for the world mesh's props (below). With it, the pine's sliver draws 23 pixels and the crop's tree colours 1,188. Scores (`mean_ssim_scored`, RTX 4070 Laptop) before and after: `CTRY` 0.9015 to 0.9022, `INTRO` 0.8437 to 0.8460, `LAND` 0.8662 to 0.8666, `BALLOON` 0.8097 to 0.8127, `TRAINTNL` 0.8548 to 0.8558, `BOMB` 0.8129 to 0.8134, `LOCATION` 0.8098 to 0.8089. Merged with the `OP_PERFDISK` discs and SOD gates of [#424](https://github.com/neilsh/stunt-reel/pull/424) and [#427](https://github.com/neilsh/stunt-reel/pull/427), against `main`'s pins: `CTRY` 0.9015 to 0.9022, `INTRO` 0.8443 to 0.8467, `LAND` 0.8658 to 0.8663, `BALLOON` 0.8097 to 0.8127, `TRAINTNL` 0.8550 to 0.8555, `BOMB` 0.8143 to 0.8151, `LOCATION` 0.8103 to 0.8092. The outline lines are wound both ways, like every line here, so a back-facing polygon's outline still draws where nothing hides it, which `PLAYONE` does not do.

**The world mesh.** Line quads cost four vertices and twelve indices an edge: outlining `LOCATION`'s world that way grew it from 6.7 million vertices and 7.5 million indices to 32.4 million and 84.7 million, and with terrain excluded its render failed with a wgpu out-of-memory error. The world now draws the same edges, those exactly one filled triangle of a mesh slice uses, as a `LineList` index buffer over its own vertices, two indices an edge, after the world draw's triangles and with their depth test (a decal slice's outline compares `LessEqual` without the `[I5]` bias, which wgpu allows only on triangles; [`mesh.rs`](../../../crates/stunt-render/src/mesh.rs) `GpuModel::from_ir_outlined`). Terrain and ocean triangles are not outlined. The line list is drawn one pixel wide by the backend's line rules, which need not draw the end pixels a line quad does (not measured). A slice split over chunks (a world over `max_buffer_size`; `LOCATION`'s is one chunk) is outlined per run, so its cut is outlined too. On `LOCATION` the outline is 6.4 million edges, 51.5 MB of indices, and a whole-film render took about 16 % longer (two runs each). Scores (`mean_ssim_scored`, RTX 4070 Laptop) before and after: `CTRY` 0.9022 to 0.9048, `INTRO` 0.8467 to 0.8469, `LAND` 0.8663 to 0.8666, `BALLOON` 0.8127 to 0.8141, `TRAINTNL` 0.8555 to 0.8573, `BOMB` 0.8151 to 0.8202, `LOCATION` 0.8092 to 0.8142. In `LOCATION` tick 4170 the derrick's legs draw a pixel wider, as in the capture (judged by eye).

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.11.
