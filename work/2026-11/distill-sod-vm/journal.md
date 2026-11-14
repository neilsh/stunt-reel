# Journal: distilling `sod-vm.md`

The dated rounds of [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) as of commit `0a9cde7`, moved here verbatim when the note was distilled to current truth. Only relative link paths changed; a section number in the moved text names a section of the note as it stood at `0a9cde7` (`git show 0a9cde7:research/playone-exe/sod-vm.md`). Where an entry holds part of a paragraph, the rest of that paragraph is still in the note.

## 2026-11-01: GVPOLY polygons painted flat, and the triplane before the ramp word

From section 8.5 of the note, as it stood at `0a9cde7`:

The renderer first painted each such polygon flat at `base` plus the mean of its vertices' levels: grey-ramp pixels moved toward the capture's (`CTRY` 3.7k -> 33.8k against 52.4k, `INTRO` 120k -> 44.5k against 49.8k) but SSIM did not rise ([parity log](../../2026-10/parity-log/log.md)).

Before the ramp word was read, `INTRO.FLM` tick 1009 drew the triplane's fuselage grey and its wings bright pink where the capture has a red fuselage and dark red wings (capture above, ours below): [`intro-1009-gvpoly-running-colour.png`](../aircraft-render/images/intro-1009-gvpoly-running-colour.png).

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.5.

## 2026-11-05: the SHADE light swept with DBG_SHADE_LIGHT

From section 8.5 of the note, as it stood at `0a9cde7`:

Measured with `DBG_SHADE_LIGHT`, all shapes decoded under one light: the stand-in 0.8646 / 0.7986 (CTRY / INTRO), the world light 0.8641 / 0.8128, its negation `(-99, -32766, 17)` and the 180-degree-about-Z form `(-99, -32766, -17)` both 0.8646 / 0.7986 (the 99 and 17 move no shade across a ramp step, so only the sign of y matters). The world light for scenery with the stand-in for actors scored 0.8646 / 0.7986 exactly: no scenery shade that reaches the screen moves, and the whole gain is on the aircraft.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.5.

## 2026-11-06: OP_VECTORS turned, swept and adopted

From section 8.7 of the note, as it stood at `0a9cde7`:

**Adopted: `OP_VECTORS` turned the same way** (store `(−x, −y, z)`; measured first with the temporary switch `DBG_VECNEG`):

* **Aircraft.** All 14 inverted stock `0x7Fxx` aircraft stand upright, as do the two unclear ones (`0x7F18`, `0x7F21`); the 9 that were upright, and the `OP_IPG`-led aircraft, are unchanged.
* **Every other shape.** Of the 397 stock shapes holding the word `0x0075`, 229 export different geometry; the rest are unchanged, and 19 export nothing either way (terrain patches without anchors, empty shapes). In side views, none turns over and many are righted: the masts of the sailing ships `0x4114`..`0x4117`, `0x414D`, `0x414E` and `0x4153` (below the hull before), the conning tower of `0x3E19`, the antennas of `0x3D47`/`0x3D48`, the wheels of trucks and tanks, and the sign `0x063D`, which now reads "STUNT / ISLAND" top to bottom.
* **Parity** (sweep, RTX 4070): `CTRY.FLM` 0.8725 → 0.8986, `INTRO.FLM` 0.8273 → 0.8337, IoU unchanged. At `CTRY` tick 499 the biplane matches the capture, wing stripes included, which the hand-picked mirror culled ([log row](../../2026-10/parity-log/log.md)).

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.7.

## 2026-11-11: view-facing shapes adopted and scored

From section 8.8 of the note, as it stood at `0a9cde7`:

**Adopted** (evidence-backed): a shape with header bit 0 is drawn turned about `+Y` so that its `+Z` lies along the camera's look direction seen from above. That heading is taken to equal the yaw of `Ry(−yaw)` (`[Supported Inference]`: the sign was checked only by the trees drawing rather than culling); past vertical pitch it is half a turn off, and a camera looking straight down gets heading 0 where `PLAYONE` keeps its yaw word. A view-facing prop also skips the per-placement `OP_TAP` decode and the ground-decal snap; the type-8 trees of the reference archives run no `OP_TAP`. Props with the bit leave the static world mesh and are drawn each frame as props, behind their `SP_1NODE` gates; actors with it drop the slot's rotation, while their shadow keeps it, since `0x1C0D` builds the shadow matrix from the slot's angles. At `INTRO.FLM` tick 2080 the hill pines, missing before, now stand facing the camera as in the capture; at tick 3301 the foreground pines still draw. `mean_ssim_scored` (RTX 4070 Laptop): CTRY 0.89960 → 0.89962 and INTRO 0.84177 → 0.84172, both under the 0.002 floor; of the other reference films only LOCATION moves by more than 0.0001, 0.80682 → 0.80800.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.8.

## 2026-11-12: thin polygons measured and outlines drawn

From section 8.11 of the note, as it stood at `0a9cde7`:

**What it does to thin polygons** (`[Bounded Observation]`, `INTRO.FLM` tick 3301, [#426](https://github.com/neilsh/stunt-reel/issues/426)). The pines `0x03A3` and `0x03A7` are a type-8 quad (section 8.8) whose `INTV` midpoints make two `POLYZ` triangles: the whole tree, and a sliver outside its right edge at most a sixth of its half-width across. The capture draws a six-pixel-wide pine's sliver as a strip of light green one to two pixels wide down 14 rows (21 pixels); our renderer, whose rasteriser fills only pixels whose centres a triangle covers, drew 2 pixels of it. Across the top-left 100 × 100 pixels the four tree colours covered 1,471 pixels in the capture and 815 in ours, with every tree checked in a 60 × 60 part of the crop at the same place in both. `[Supported Inference]` that the inclusive spans are why the sliver measured is drawn.

The renderer follows it in part. `stunt-render` draws every edge that exactly one filled triangle of a mesh node uses as a one-pixel screen line (section 8.10), in its end vertices' colours, after the node's triangles ([`outline.rs`](../../../crates/stunt-render/src/outline.rs)), so a polygon also covers the pixels its outline crosses. It does this as line quads for the shapes drawn per frame (actors and view-facing props such as these pines), and as a line list for the world mesh's props (below). With it, the pine's sliver draws 23 pixels and the crop's tree colours 1,188. Every reference film's score rose but `LOCATION`'s, which fell; the journal entry cited below has each film's scores. The outline lines are wound both ways, like every line here, so a back-facing polygon's outline still draws where nothing hides it, which `PLAYONE` does not do.

**The world mesh.** Line quads cost four vertices and twelve indices an edge: outlining `LOCATION`'s world that way grew it from 6.7 million vertices and 7.5 million indices to 32.4 million and 84.7 million, and with terrain excluded its render failed with a wgpu out-of-memory error. The world now draws the same edges, those exactly one filled triangle of a mesh slice uses, as a `LineList` index buffer over its own vertices, two indices an edge, after the world draw's triangles and with their depth test (a decal slice's outline compares `LessEqual` without the `[I5]` bias, which wgpu allows only on triangles; [`mesh.rs`](../../../crates/stunt-render/src/mesh.rs) `GpuModel::from_ir_outlined`). Terrain and ocean triangles are not outlined. The line list is drawn one pixel wide by the backend's line rules, which need not draw the end pixels a line quad does (not measured). A slice split over chunks (a world over `max_buffer_size`; `LOCATION`'s is one chunk) is outlined per run, so its cut is outlined too. On `LOCATION` the outline is 6.4 million edges, 51.5 MB of indices, and a whole-film render took about 16 % longer (two runs each). Every reference film's score rose; the journal entry cited below has each film's scores. In `LOCATION` tick 4170 the derrick's legs draw a pixel wider, as in the capture (judged by eye).

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.11.

The "journal entry cited below" in the moved text is, for line quads, [polygon outlines scored on the seven reference films](../426_intro-conifers/journal.md#2026-11-12-polygon-outlines-scored-on-the-seven-reference-films), and for the world's line list, [world-mesh slivers by conservative rasterization and by a line-list outline](../430_world-mesh-slivers/journal.md#2026-11-12-world-mesh-slivers-by-conservative-rasterization-and-by-a-line-list-outline).
