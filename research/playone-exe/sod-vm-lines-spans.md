---
summary: "The SOD VM's lines and polygon spans: `MOVETO`/`ZLINETO`/`LINECOL` lines, polygon spans that include both ends, and the span test that culls an anticlockwise polygon with its outline, the polygon clipper, which cuts at the view pyramid's sides and has no near plane, and the register projectors and anchor transform, which truncate an unclipped vertex's screen offset toward the projection centre."
sidebar_label: "SOD VM lines & spans"
---

# `PLAYONE.EXE`: SOD VM Lines and Polygon Spans

Part of the SOD VM notes: [`sod-vm.md`](sod-vm.md) lists the files and states the binary and method; section numbers run across the files.
The model frames and two-vertex polygons (sections 8.8 and 8.9) are in [`sod-vm-generators.md`](sod-vm-generators.md).

### 8.10 Lines: `MOVETO`, `ZLINETO` and `LINECOL`

`[Established]` for the instructions, static, in the unpatched image (not run; the Patch #3 image not read).
The dispatch slots ([section 1](sod-vm.md#1-dispatch)) send `MOVETO` (`0x00A2`) to `0x968D`, `ZLINETO` (`0x00BD`) to `0x9696` and `LINECOL` (`0x00B4`) to `0x9BAA`.

| Image offset | Role |
|---|---|
| `0x968D` | `MOVETO`: stores its operand, a register's byte offset, at `work:0x41EC` (the pen). |
| `0x9696` | `ZLINETO`: `BX` = the pen, the pen = its operand, then `call [0x807E]`. |
| `0x9BAA` | `LINECOL`: stores its word at `work:0x41EA`, the line colour. |
| `0xBBD4`, `0xBB83` | Line routines that `0x9100` puts in `work:0x807E` (at `0x914F` and `0x9167`, beside `work:0x8080`'s polygon routines). `0xBBD4` reads both registers' screen words (`+6`, `+8`), clips the segment to the rectangle at `work:0x41C0..0x41C6` and calls `0:7FD2`. `0xBB83`, the clipping variant, was not read line by line. |
| `0x7FD2` | Line gateway: `DI` = `work:0x41EA`, or 0 when `work:0x806C` is set (the shadow draw, [section 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)), then the driver slot `DS:[0x2244]`. |
| `0x7511` | The driver's line (third word of the table at `DS:0x10A4`): a Bresenham line over the 320-byte page rows, endpoints ordered by column. When `\|dx\| >= \|dy\|` it stores `\|dx\| + 1` pixels, one per column; otherwise `\|dy\| + 1`, one per row. Both ends are drawn, in the low byte of `DI`, with no depth test. |

So a `ZLINETO` line is one pixel wide at any distance, from the pen register's screen point to the operand's, in the `LINECOL` colour.
The pen is a register, so the line uses that register's value when `ZLINETO` runs.
`0x7511` draws one pixel for coincident endpoints; whether the clipper `0xBBF3` passes such a segment was not read.

The renderer follows it.
`vm.rs` emits each line, and each two-vertex polygon (section 8.9), as one polygon of its two endpoints.
Tessellation turns it into a quad of zero world width whose corners are flagged as line vertices (`SodVertex::flags` bits 3 to 5) and carry the vector to the other endpoint, and the vertex shader moves each corner half a pixel across the line's minor screen axis and half a pixel past its endpoint along the major one.
The quad is meant to cover one pixel per column when `|dx| >= |dy|` and one per row otherwise, both ends included (a GPU test checks this for a steep and a shallow line at 200 m and 1000 m; it is not compared with `0x7511` pixel for pixel), at the endpoints' depth, so lines are depth-tested like every other polygon here.
A shadow draw puts lines in index 0, as `0x7FD2` does.
`vm.rs` still takes the pen's point at `MOVETO` time, draws nothing for a zero-length line, and leaves the colour at `OP_COLOR`'s until a `LINECOL` (whether `PLAYONE` resets `work:0x41EA` is not read).

The change was adopted, every reference film's score rising, measured against main's ribbons restored by a temporary switch on the same commit; the journal entry cited below has each film's scores.
Each of `INTRO` camera 1's scored ticks gains 0.0034 to 0.0060: its power line about 437 m away, drawn by `ZLINETO` spans, is two continuous one-pixel cables, as the capture shows, where the 0.03 m ribbons came to scattered dots.

_Source: [the ZLINETO draw path read statically](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-the-zlineto-draw-path-read-statically)._ _Source: [one-pixel screen lines scored](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-one-pixel-screen-lines-scored-on-the-seven-reference-films)._

### 8.11 Polygon Spans Include Both Ends

`[Established]` for the instructions, static, in the unpatched image (`mise run re-tool -- disasm 0x7571 0x75DB`; the Patch #3 image not read).
The flat filler `0x7571`, which `POLYZ` reaches through the gateway (section 8.9), fills both ends of a polygon on both axes:

* **Rows.**
  It takes the bottom row minus the top row as a count, stores it at `DS:0x10C6`, and after each row runs `dec word [0x10C6]; jns` (`0x75BE`), so it fills the top row, the bottom row and every row between.
* **Spans.**
  Per row it reads the left and right ends, clips them to `[0x2294]` and `[0x2296]`, skips a row whose right end is left of its left (`sub ax,cx; jl` at `0x75A1`), and fills `right − left + 1` pixels (`inc ax` at `0x75A5`).

So every row from top to bottom whose right end is not left of its left is drawn, a row with left equal to right as one pixel, however narrow the polygon.
Which end of an edge's run of pixels each row takes is in section 8.12; the pixel-for-pixel extent of a wide polygon was not compared with ours.

**What it does to thin polygons** (`[Bounded Observation]`, `INTRO.FLM` tick 3301, [#426](https://github.com/neilsh/stunt-reel/issues/426)).
The pines `0x03A3` and `0x03A7` are a type-8 quad (section 8.8) whose `INTV` midpoints make two `POLYZ` triangles: the whole tree, and a sliver outside its right edge at most a sixth of its half-width across.
The capture draws a six-pixel-wide pine's sliver as a strip of light green one to two pixels wide down 14 rows (21 pixels); our renderer, whose rasteriser fills only pixels whose centres a triangle covers, drew 2 pixels of it.
Across the top-left 100 × 100 pixels the four tree colours covered 1,471 pixels in the capture and 815 in ours, with every tree checked in a 60 × 60 part of the crop at the same place in both.
`[Supported Inference]` that the inclusive spans are why the sliver measured is drawn.

The renderer follows it in part.
`stunt-render` draws every edge that exactly one filled triangle of a mesh node uses as a one-pixel screen line (section 8.10), in its end vertices' colours, after the node's triangles, or in a decal node after each fan's triangles ([`outline.rs`](../../crates/stunt-render/src/outline.rs)), so a polygon also covers the pixels its outline crosses.
It does this as line quads for the shapes drawn per frame (actors and view-facing props such as these pines), and as a line list for the world mesh's props (below).
With it the pine's sliver draws 23 pixels and the crop's tree colours 1,188.
The outline lines are wound both ways, like every line here, so a back-facing polygon's outline still draws where nothing hides it.
`PLAYONE` has no outline apart from the spans, so a back-facing polygon's ends go with its fill, except on the rows section 8.12 names.

**The world mesh.**
Line quads cost four vertices and twelve indices an edge, and outlining `LOCATION`'s world that way grew it from 6.7 million vertices and 7.5 million indices to 32.4 million and 84.7 million and made its render, with terrain excluded, fail with a wgpu out-of-memory error.
The world instead draws the same edges, those exactly one filled triangle of a mesh slice uses, as a `LineList` index buffer over its own vertices, two indices an edge, after the world draw's triangles (a decal slice's outline right after that slice's triangles, [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)) and with their depth test (a decal slice's outline compares `GreaterEqual`, depth being reversed, without the `[I5]` bias, which wgpu allows only on triangles; [`mesh.rs`](../../crates/stunt-render/src/mesh.rs) `GpuModel::plan_outlined`).
Terrain and ocean triangles are not outlined.
The line list is drawn one pixel wide by the backend's line rules, which need not draw the end pixels a line quad does (not measured).
On `LOCATION` the outline is 6.4 million edges, 51.5 MB of indices, and a whole-film render took about 16 % longer (two runs each).
With line quads on the per-frame shapes every reference film's score rose but `LOCATION`'s, which fell; with the world's line list added every film's rose, and at `LOCATION` tick 4170 the derrick's legs draw a pixel wider, as in the capture (judged by eye).
_Source: [thin polygons measured and outlines drawn](../../work/2026-11/distill-sod-vm/journal.md#2026-11-12-thin-polygons-measured-and-outlines-drawn)._

_Source: [what thins the INTRO conifer field](../../work/2026-11/426_intro-conifers/journal.md#2026-11-12-what-thins-the-intro-conifer-field)._ _Source: [polygon outlines scored](../../work/2026-11/426_intro-conifers/journal.md#2026-11-12-polygon-outlines-scored-on-the-seven-reference-films)._ _Source: [world-mesh slivers](../../work/2026-11/430_world-mesh-slivers/journal.md#2026-11-12-world-mesh-slivers-by-conservative-rasterization-and-by-a-line-list-outline)._

### 8.12 Back Faces: the Span Test

`[Established]`, static, for the row test, the walk order and the instructions the three bullets below cite, in the unpatched image (`mise run re-tool -- disasm 0xC50E 0xD000`, `0x995C 0x9B78` and `0x7571 0x7700`; the Patch #3 image not read, nothing traced live).
Of the routines read, none computes a normal, a cross product or a signed area: the handlers `POLYZ` (`0x9B78`), `OP_GVPOLY` (`0x995C`) and `GVPOLY16` (`0x9A24`), the vertex copiers `0xC9D4` and `0xC50E`, the span-table builder `0xCA5D`, the gateway `0x8010` and the fillers.
The vertex transform and projection that fill the registers' screen words were not read for this.
The cull is the fillers' row test, applied to a table whose two columns come from walking the vertex list in opposite directions.

* **The span table.**
  `0xC9D4` and the clipper `0xC50E` copy the polygon's screen points, in stream order, into `work:0x4250` (row word, then column word), and both run on into the span-table builder `0xCA5D`.
  From the first topmost vertex it walks the list backward (`sub si,4`) into each row's left word (`[work:0x1952] + 0x0A`, stride 4) and forward (`add si,4`) into its right word (`+0x0C`), skipping horizontal edges, until each walk reaches the bottom row.
* **The test.**
  The flat filler `0x7571` skips a row whose right word is less than its left (`sub ax,cx; jl` at `0x75A1`, section 8.11); the Gouraud filler `0x75DB` does the same with `inc ax; jg` (`0x7612`, and `0x76DC` on its other route).
  So a polygon fills where its vertices run clockwise on the screen (rows counting down), and a polygon whose vertices run anticlockwise has its left walk on its right-hand edge and skips every row where its two edges are apart.
* **Which end of a run.**
  In the `POLYZ` walks (`0xCC53`, `0xCDAE`, which flat `GVPOLY` routes use too) the backward walker writes the leftmost pixel of each row's run along a shallow edge and the forward walker the rightmost, each half a step from the edge's line (`sar bx,1` at `0xCCBB`, `0xCD40`, `0xCE17`, `0xCEA2`); steep edges step by a midpoint error term (`0xCCF5`, `0xCD76`, `0xCE4E`, `0xCEE4`).
  A Gouraud `GVPOLY` walks its left edge with its own stepper (`0xCB18`), and its right edge with the `POLYZ` forward walk (`jmp 0xCDE6` at `0xCBA6`) unless its top row is clipped.

What this does is `[Hypothesis]`: a static reading of the instructions above, not traced live or seen in a capture.

* **Fill and outline go together.**
  The spans' ends are the only edge pixels `PLAYONE` draws for a polygon, so a back face loses its "outline" with its fill.
  A row still draws where the right-end walker's column reaches the left-end walker's: the row of a lone top or bottom vertex (the left walk's column there is at most the vertex's and the right walk's at least, so at least that pixel draws) and any row where the face is narrower than the runs of its two edges.
* **Zero area.**
  A polygon on one screen row (`[0x41D0] == [0x41D2]`) is drawn by `0xCAB4` as one span from its least to its greatest column, whatever its order.
  A polygon whose points lie on one slanted line is drawn along it by both walks, so it has no facing; whether two walks over different edges of the line round a row a column apart was not worked out.
* **Two vertices** (section 8.9).
  Both walks follow the same edge, the left walker taking each row's left end and the right walker its right end, so the line draws whatever its vertex order: a two-vertex polygon has no facing test.
* **Clipping.**
  `0xC50E` keeps the stream's order and joins the builder at `0xCA5E`, so a clipped polygon is tested the same way.
  The screen corners it inserts where a polygon leaves one side and enters another run only clockwise (`0xC65A` steps the side index up); for a back face clipped across a corner the result was not worked out.
  A polygon it finds covering the whole view (`0xC88E`, reached at `0xC5E1` once the vertices' clip flags OR to at least `0x1E`) becomes the four screen corners in clockwise order, so it fills the view whatever its own order.
* **Vertex rejection.**
  `0xC9D4` gives up on a polygon with any vertex whose clip-flag byte (register `+0x0A`, `work:0x445A`) is set (`0xC9CB`, carry): `POLYZ` draws nothing, and the Gouraud route of `GVPOLY` and `GVPOLY16` retries it through the flat route (`0x99BB`, `0x9A8A`).
  It is a clip test, not a facing test.

The renderer culls whole triangles by their clip-space winding (`FrontFace::Cw`, [`attribution.md` § 6](../parity/attribution.md#6-back-faces)), the same side.
It draws a back face's outline (section 8.11) and none of its rows.
_Source: [the polygon span builder read for a facing test](../../work/2026-11/850_playone-back-face-cull/journal.md#2026-11-20-the-polygon-span-builder-read-for-a-facing-test)._

### 8.13 The Clip Volume Has No Near Plane

`[Established]`, static, for the instructions, in the unpatched image (`mise run re-tool -- disasm 0x9CF1 0x9DB5` and `0xC50E 0xC9D4`; the Patch #3 image not read, nothing traced live).
`[Supported Inference]` for the clip volume they make: read statically, not traced, and consistent with the `bomb` capture drawing the police car's door nearer the eye than 0.5 m ([`attribution.md` § 2](../parity/attribution.md#2-current-breakdown)).
`PLAYONE`'s polygon clipper cuts only against the four side planes of the view pyramid, which meet at the eye.
It has no near plane: the depth it cuts at is 0, the eye itself, at every `scale_index` and lens.

* **The outcode.**
  The clipping projector (`0x9D3A`, which `0x9100` selects at `0x9173`) adds the origin words `work:0x8084..0x8088` to a register to get its view point `(x', y', z')`.
  It sets bit 0 when `z' ≤ 0` (`jle` at `0x9D50`), bit 1 when `x' ≥ z'`, bit 2 when `x' < −z'`, and bits 3 and 4 likewise for `y'` (`0x9D52..0x9D60`, or `0x9D91..0x9DA9` behind the eye), and projects an unflagged register to `(x' · 256 / z' + work:0x41C8, y' · 256 / z' + work:0x41CA)`.
  When `z' ≤ 0`, `x' ≥ z'` or `x' + z' < 0` holds for every `x'`, and the same for `y'`, so a register behind the eye always has a side bit of each axis as well as bit 0.
* **The edge clip.**
  The clipping vertex copier `0xC50E` copies an unflagged vertex's screen words and hands each edge with a flagged end to `0xC6AF`, unless both ends share an outcode bit, bit 0 included (`test` at `0xC596`), which drops the edge.
  `0xC6AF` shifts the outside end's outcode right by 2 (`0xC6BF`), discarding bit 0.
  For each side bit set it finds where the edge meets that plane (`x' = z'`, `x' = −z'`, `y' = z'`, `y' = −z'`) as a 16-bit fraction of the edge from its outside end (`div si` at `0xC6ED`, `0xC729`, `0xC764`, `0xC7A1`) and keeps the largest.
  It interpolates the crossing's depth and other coordinate (`0xC7B2..0xC7E3`, `0xC81B..0xC84C`), rejects it when the edge's other end is flagged too and the crossing lies outside the other pair of planes (`0xC7E7..0xC7F6`, `0xC850..0xC85F`), and writes it as a point on a screen edge 256 pixels from the centre (`0xC802..0xC80F`, `0xC86B..0xC87B`).
  No instruction in `0xC50E..0xC9D4` compares a depth with a positive constant: depth enters through the side-plane distances `x' ∓ z'` and `y' ∓ z'` and the whole-view test's sign tests below.
* **The whole-view test.**
  When no edge survives and the outcodes of the edges' outside ends OR to at least `0x1E` (`0xC5DA`), `0xC88E` takes the two edges where `x'` changes sign and each one's `y'` and `z'` where it does (`0xC906`).
  It fills the view only when the segment between those points crosses `y' = 0` at `z' ≥ 0` (`0xC8E2..0xC901`): when the polygon meets the view's centre line in front of the eye.

So, in exact arithmetic, the clip volume is the pyramid `−z' ≤ x' < z'`, `−z' ≤ y' < z'`, whose only point at `z' = 0` is the eye.
A polygon crossing the eye plane is cut where it leaves the pyramid's sides, and a polygon however near the eye is drawn where it lies inside them.
Units cannot move that apex: every plane passes through the eye whatever the shift `work:0x806F` or the lens's zoom of `x'` and `y'` and shift of `z'` (section 8.6, `REJVEC`), which change the pyramid's angle, not where it meets.
`[Supported Inference]` for the lens: that the zoom scales `x'` and `y'` and shifts `z'` before the projector sees them is read from `0x12DC` scaling the view matrix's first six words by `work:0x8108` and shifting its depth row by `work:0x810C` ([`lod.md`](lod.md)), not traced; scaling each axis by its own factor keeps every plane `x' = ±z'`, `y' = ±z'` through `(0, 0, 0)`.
What is quantised is the depth: a vertex is in front once `z'` is at least one register unit, and a register unit is set by how far the object lies, not by `scale_index` (the origin words are the object's 16.16 view position shifted right by `0x31CF`'s `s`, [`sod-vm.md` § 4](sod-vm.md#4-register-side-effects)).
For an object whose coordinates relative to the eye are each under 16 m, `s` is at most 5 and the origin's unit, `2^(s − 16)` m, at most `2^-11` m (0.49 mm), before any halving in the rotation `0x0824:06B0` and the lens's depth shift `work:0x810C` (1 on `BALLOON`, [`palette-fade.md`](palette-fade.md)); `[Supported Inference]` for the unit, read from the writers (`0x31CF`'s magnitude and table lookup, `0x31D5..0x3217`), not traced.

The renderer cannot clip at the eye: a perspective projection needs a near distance above 0, and with reversed infinite depth in `Depth24Plus` ([ADR 0054](../../docs/adr/0054-depth-is-reversed-and-infinite.md)) the depth step at distance `z` is `z² / (near × 2²⁴)`.
That is 0.6 m at 1 km for the 0.1 m default, and 6 m at 1 km for 0.01 m.
So the evidence-backed value is the least near distance the depth buffer tolerates.
On the evidence track 0.05 m's largest film-mean change against 0.1 m was `balloon`'s +0.0002, from depth ties rather than cut geometry, and 0.01 m lowered all seven; the default stays 0.1 m, and whether to lower it is [#955](https://github.com/neilsh/stunt-reel/issues/955) ([`attribution.md` § 2](../parity/attribution.md#2-current-breakdown)).
_Source: [the polygon clipper read for a near plane](../../work/2026-11/907_playone-near-plane/journal.md#2026-11-22-the-polygon-clipper-read-for-a-near-plane), [near planes nearer than 0.1 m](../../work/2026-11/907_playone-near-plane/journal.md#2026-11-22-near-planes-nearer-than-01-m-on-the-evidence-track)._

### 8.14 Projected Points Are Truncated Toward the Centre

`[Established]`, static, for the instructions, in the unpatched image (`mise run re-tool -- disasm 0x9CF1 0x9DB5`, `0xAE67 0xB011` and `0xB80E 0xB83A`; the Patch #3 image not read, nothing traced live).
Both register projectors (section 8.13) form a screen word the same way: `DX:AX` is the view coordinate shifted left 8, `idiv bp` divides it by the depth `z'`, and the projection centre is added to the quotient with nothing in between (`0x9CF1`: column `0x9D05..0x9D13`, row `0x9D16..0x9D2B`; `0x9D3A`: column `0x9D69..0x9D77`, row `0x9D7A..0x9D88`).
`idiv` truncates toward zero, so a register's screen point is `(trunc(256 · x' / z') + work:0x41C8, trunc(256 · y' / z') + work:0x41CA)`: its offset from the centre (160, 92) truncated toward that centre, as the disc generator does ([`sod-vm-generators.md`](sod-vm-generators.md) section 8.8).
The anchor transform `0xAE67`, which projects the anchors a ground leaf (`0xBF23`, [`world-scene.md`](world-scene.md) section 2) and `OP_TAP` ([`sod-vm.md`](sod-vm.md) section 4) read, ends the same way when the anchor's outcode is 0: `0xB80E` shifts the 32-bit `z'` right by the fewest bits `n` that leave it under 2^15, `x'` and `y'` are shifted left `8 − n` bits (right `n − 8`, arithmetically, for `n ≥ 8`), and `idiv` divides each, the centre added to the quotient (`0xAFA7`, `0xAFC5`, `0xAFE8`, `0xB006`).
With `z' < 2^15` that is `trunc(256 · x' / z')` exactly; a deeper point first loses `z'`'s low bits, and for `n > 8` those of `x'` and `y'`, floored, before the same truncation.
So every vertex that reaches the fillers unclipped, of a SOD VM polygon or a ground leaf, sits on its offset truncated toward the centre; where the clippers (`0xC6AF`, and `0xBF82` for a ground leaf) put a crossing on a side of the view was not read.
The polygon walks and line routines read these words as pixel indices, and the flat filler fills a vertex's own row and column (section 8.11).

`[Supported Inference]` for what that means against our renderer, which samples pixel centres and puts the optical axis at (160, 92.5) pixels from the 320 × 185 view's top left: a vertex `o` pixels off the axis lies at `160 + trunc(o.x) + 0.5`, `92 + trunc(o.y) + 0.5` in `PLAYONE` and at `160 + o.x`, `92.5 + o.y` in ours.
Below the centre `PLAYONE`'s vertex is up to a row higher, above it up to a row lower, which fits the one-row backdrop shift of [`framing-and-actors.md` § 4](../parity/framing-and-actors.md#4-background-misregistration-is-neither-one-time-offset-nor-one-page-shift); across, it is half a column right of ours on the axis, within half a column of ours right of the centre, and half a column to a column and a half right of ours left of it.
The centre alone moves nothing vertically: row 92's centre is our 92.5.

`[Bounded Observation]` for the measurement, on the GPU over every reference film.
Drawing each vertex at that pixel raised all seven films by 0.005 to 0.011 SSIM when each vertex slid to the pixel along the horizontal world plane through it, so that the ground and the ocean stayed coplanar, and a vertex whose ray missed that plane kept its own projection.
The renderer follows the rule: `playone_vertex` in `mode13h.wgsl` draws each vertex at that pixel's centre, sliding it along the ray through the pixel to a plane through the vertex, so the surfaces that shared a plane still do.
That plane is the horizontal one for a world-mesh vertex and for a shape facet within about 26 degrees of horizontal, and the facet's own for a steeper facet and for a world prop's polygon in a decal tie (below; Ruled out gives the forms that failed).
Terrain in the world's base slice (every `MAP.BIN` patch drawn there; flat ground is drawn in its own slices) is the exception: `vs_terrain` moves its vertices only in x and y, to the same pixel, and `fs_terrain` writes each fragment's depth from the patch's own plane, no farther than the ground plane's along the pixel's ray ([ADR 0059](../../docs/adr/0059-terrain-takes-its-depth-per-fragment-from-its-own-plane.md); the limit below is why).
`[Bounded Observation]` for the score, on the GPU against `main`: every film's SSIM rises, `balloon` by 0.0009 and the other six by 0.0054 (`ctry`) to 0.0132 (`intro`); mask IoU falls by 0.0001 to 0.0013 on four (`ctry`, `intro`, `land`, `location`) and rises on three.
The worst frame of each film (seven of the 297 down by more than 0.005; the other 290 were not examined) differs mostly by pixels a pixel off along edges and lines; `location` 3334 (−0.0716) and `land` 617 (−0.0334) also lose a region: a wedge along `location`'s horizon ridge, and the band of a `land` hangar's wall that the capture draws and the PR covers; `location`'s cause was not found, and `land`'s is below.
The depth ties are pinned by the decal tests of `draw_order.rs` on a steep and a near-horizontal facet of a single shape and on a steep facet of a world prop, by its tile-on-terrain and actor-on-scenery tests, and by `lines.rs`'s one-pixel polygon.
Sliding every world-mesh vertex horizontally loses a decal's tie on a steep facet of a world prop, the failure of #1027's horizontal-plane form.
`[Bounded Observation]`, one frame on lavapipe: `land` 617's band is that case: the hangar is world prop shape 522 (its pixels lie on the props layer with that shape word), and the band is the lower of two stripes in index 162 that its decode flags decal on each vertical long wall, which ours covers with the wall's 149; a synthetic decal on a steep world-prop facet loses to its base the same way on `main`.
The renderer slides a world prop's polygon in its facet's plane when it is in a decal tie: the decoder marks a filled decal and each earlier coplanar filled polygon it overlaps within their plane (`SodVertex::decal_tie`, from `decal_ties` in `decal.rs`), not one whose bounds only touch the decal's.
`[Bounded Observation]` for the score, on lavapipe against `main`: `land` rises by 0.0030 with the band back, `location` by 0.0008, `bomb` and `ctry` by 0.0002, but `traintnl` falls by 0.0004 and `intro` by 0.00002, falls the owner accepted (#1127).
The limit: a tied polygon's corners slide to other depths than the untied facets sharing them, so on `traintnl` 1145 a decorated wall's undecorated side walls cover its edges; every other form tried lowered some film more (Ruled out).
A second limit: a steep `MAP.BIN` patch's corner slides in the horizontal plane too, and where it lies just below the eye's height far off, the snapped pixel's ray grazes that plane and meets it kilometres beyond the corner.
`[Bounded Observation]`, lavapipe: on `CTRY` ticks 286 to 366 that slide pushes a foot corner of the hill of records 107 to 109 (5 km off, 6 m below the eye) behind the mountain face of record 12 on some ticks and not others, so the hill flickers where the capture keeps it (#1197).
Sliding steep terrain in its own plane keeps the hill but draws a mountain on `land` 551 that the capture lacks: records 46 and 50, 7 to 10 km off, behind record 2, a nearer face that covers the frame above the horizon in the capture and on `main`.
They slope at 25 and 24 degrees, under the threshold, so their feet, 3 m below the eye, slide in the horizontal plane; the pixel they truncate to lies toward the centre row, below the horizon, so the slide pulls them to about 3.4 km, in front of record 2 once it slides in its own plane.
So a horizontal slide misplaces a far foot either way, pushed back or pulled in, and no distance cut reaches records 46 and 50 (section 6.4 of [`world-scene-residuals.md`](world-scene-residuals.md) holds its scenery cut, which ground leaves do not reach; [`world-scene.md`](world-scene.md) section 2).
Sliding every raised patch in its own plane keeps the hill and `land` 551 but draws ocean along the foot of far raised terrain, where the ocean takes the face's pixels at its foot (`[Hypothesis]`: the foot's own-plane depth lies beyond the ocean's, which slides horizontally with the ground) (Ruled out).
Sliding a raised patch's ground-plane corners horizontally while that changes their distance from the eye by at most 5% or 20% (own plane otherwise) removes the strip where it holds and keeps the hill, but gains about what that slide does and leaves a row of ocean at a far foot on `land` 199 (Ruled out).
`[Bounded Observation]`, lavapipe: a terrain patch that moves only its edges to the snapped pixel and takes each fragment's depth from its own plane, no farther than the ground plane's along the pixel's ray, keeps the hill without the ocean strip on the frames scored (`land` level; `land` 551 not examined): `ctry` +0.0018, `intro` +0.0016, `location` +0.0011, `balloon` −0.0002, one frame of 297 down more than 0.005 in the prototype.
It is short of the adoption bar, which the owner waived in [ADR 0059](../../docs/adr/0059-terrain-takes-its-depth-per-fragment-from-its-own-plane.md), and the renderer draws terrain that way (above).
The same depth per fragment without the clamp loses the strip as the plain raised slide does (`land` and `balloon` match it).
_Source: [the register projectors truncate toward the centre](../../work/2026-11/1027_projection-truncation/journal.md#2026-11-24-the-register-projectors-truncate-toward-the-centre), [with an unsnapped fallback](../../work/2026-11/1027_projection-truncation/journal.md#2026-11-24-the-projector-rounding-with-an-unsnapped-fallback), [the world mesh slides horizontally](../../work/2026-11/1064_projector-vertex-truncation/journal.md#2026-11-25-the-world-mesh-slides-in-the-horizontal-plane-shapes-in-their-facets), [facets near horizontal](../../work/2026-11/1064_projector-vertex-truncation/journal.md#2026-11-25-facets-near-horizontal-slide-horizontally), [the world mesh and near-horizontal shape facets together](../../work/2026-11/1064_projector-vertex-truncation/journal.md#2026-11-25-the-world-mesh-and-near-horizontal-shape-facets-together), [the hangar is a world prop and the band a decal on its wall](../../work/2026-11/1100_land-617-hangar-decal/journal.md#2026-11-26-the-hangar-is-a-world-prop-and-the-band-a-decal-on-its-wall), [#1100's variant `3` as the renderer's own rule](../../work/2026-11/1127_land-617-decal-fix/journal.md#2026-11-26-1100s-variant-3-as-the-renderers-own-rule), [the hill's foot slides along a grazing ray](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-27-the-hills-foot-slides-kilometres-along-a-grazing-ray), [`land` 551's mountain is hidden by a nearer face](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-27-land-551s-mountain-is-hidden-by-a-nearer-face-not-left-out), [every raised patch in its own plane](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-27-every-raised-terrain-patch-slides-in-its-own-plane), [the ocean strip](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-28-the-ocean-strip-is-the-raised-faces-foot-losing-to-the-ocean), [a mixed slide](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-28-a-mixed-slide-raised-patches-in-their-plane-except-on-the-ground), [per-fragment depth](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-28-per-fragment-depth-from-the-polygons-own-plane)._

## Ruled out

* **Conservative rasterization for the world mesh's slivers** (section 8.11).
  It likely over-covers, taking every pixel a triangle touches (inferred): with the world drawn that way `CTRY` fell 0.006 and `LOCATION` 0.0023 (`INTRO` and `BOMB` rose), and every film fell with the per-frame shapes drawn that way too ([world-mesh slivers](../../work/2026-11/430_world-mesh-slivers/journal.md#2026-11-12-world-mesh-slivers-by-conservative-rasterization-and-by-a-line-list-outline)).

* **Outlining the world's terrain and ocean** (section 8.11).
  With the line-list outline, adding them moved `LAND` and `BALLOON` below the base without world outlines (−0.0008 and −0.0013), where props alone raised both; `LOCATION` and `INTRO` still rose ([world-mesh slivers](../../work/2026-11/430_world-mesh-slivers/journal.md#2026-11-12-world-mesh-slivers-by-conservative-rasterization-and-by-a-line-list-outline)).

* **SOD lines as 0.03 m world ribbons** (section 8.10).
  They vanish far away and swell up close; one-pixel screen lines score higher on all seven reference films ([one-pixel screen lines scored](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-one-pixel-screen-lines-scored-on-the-seven-reference-films)).

* **Missing placements as the cause of `INTRO`'s faint conifer field at tick 3301** (section 8.11).
  In a 60 × 60 crop of that tick the pines match the capture's in position, judged by eye at 8×; the slivers explain part of the gap (the crop's tree pixels go from 815 to 1,188 of the capture's 1,471).
  Tick 3290, whose camera sits a few pixels off the capture's, was not compared ([what thins the INTRO conifer field](../../work/2026-11/426_intro-conifers/journal.md#2026-11-12-what-thins-the-intro-conifer-field)).

* **A per-polygon facing test in `PLAYONE`** (section 8.12).
  None of `0x9B78`, `0x995C`, `0x9A24`, `0xC9D4` with its rejection exit `0xC9CB`, `0xC50E` with `0xC6AF`, `0xC65A` and `0xC88E`, `0xCA5D`, `0x8010`, `0x7571` or `0x75DB` computes a normal or a signed area; the authored facing flags `REJ`, `REJVEC` and `REJ2D` (section 8.6) gate sections, and the scenery walker's ground-leaf test `CS:0x23BF` gates a ground leaf, not a shape polygon ([the span builder read](../../work/2026-11/850_playone-back-face-cull/journal.md#2026-11-20-the-polygon-span-builder-read-for-a-facing-test)).

* **A near plane at a fixed depth in the polygon clipper** (section 8.13).
  `0xC6AF` discards the outcode's depth bit and cuts only at the four side planes; no instruction in `0xC50E..0xC9D4` compares a depth with a positive constant ([the polygon clipper read](../../work/2026-11/907_playone-near-plane/journal.md#2026-11-22-the-polygon-clipper-read-for-a-near-plane)).

* **Drawing truncated vertices at their own view depth** (section 8.14).
  It breaks the tie between coplanar meshes: the ocean, painted on the ground plane first, wins six rows of `balloon` 540's grass, which fell 0.0528 SSIM, past the target bound ([projector rounding on the evidence track](../../work/2026-11/1027_projection-truncation/journal.md#2026-11-24-playones-projector-rounding-on-the-evidence-track)).
  Keeping that depth only where a vertex's ray misses its horizontal plane still drew the grass of `bomb`'s opening shot as ocean (22 frames, mask IoU −0.328 each) ([with coplanar ground kept coplanar](../../work/2026-11/1027_projection-truncation/journal.md#2026-11-24-the-projector-rounding-with-coplanar-ground-kept-coplanar)).

* **Drawing truncated vertices slid within their own facet's plane** (section 8.14).
  It keeps a decal on a facet tilted about the vertical, which the horizontal-plane form loses near the eye (`draw_order::a_decal_wins_over_its_base_near_and_far`), but lowers `balloon` by 0.0043 while the other six films rise, so it did not adopt; the river, a flat prop snapped onto sloped terrain, was the suspect, not tested alone ([the shipped projector rounding](../../work/2026-11/1027_projection-truncation/journal.md#2026-11-24-the-shipped-projector-rounding-against-main)).
  Re-measured on `main` it lowered `balloon` by 0.0043 again ([the world mesh slides horizontally](../../work/2026-11/1064_projector-vertex-truncation/journal.md#2026-11-25-the-world-mesh-slides-in-the-horizontal-plane-shapes-in-their-facets)).

* **Drawing truncated vertices slid horizontally for the world mesh and within their facet's plane for every shape** (section 8.14).
  The river's plane explained part of that fall: `balloon` still fell 0.0024, past the 0.002 the evidence track allows, while the other six films rose by 0.0055 to 0.0132 ([the world mesh slides horizontally](../../work/2026-11/1064_projector-vertex-truncation/journal.md#2026-11-25-the-world-mesh-slides-in-the-horizontal-plane-shapes-in-their-facets)).

* **Drawing truncated vertices slid horizontally for every facet within 26 degrees of horizontal, in the world mesh and in shapes alike, with no rule for the world mesh as a whole** (section 8.14, variant `3`).
  It adopted in its own sweep (`balloon` −0.0007, inside the 0.002 the evidence track allows), but the shipped form, which also slides every world-mesh facet horizontally, scored a mean of 0.9158 against its 0.9153 (+0.0005, inside the ±0.002 noise floor) and `balloon` +0.0009, and was the committed shader.
  Per film (GPU, SSIM; `main` in brackets): `ctry` 0.9452 (0.9385), `intro` 0.9066 (0.8937), `land` 0.9314 (0.9248), `balloon` 0.9052 (0.9059), `traintnl` 0.9171 (0.9107), `bomb` 0.9073 (0.8957), `location` 0.8945 (0.8863); the mean 0.9153 against `main`'s 0.9079 ([facets near horizontal](../../work/2026-11/1064_projector-vertex-truncation/journal.md#2026-11-25-facets-near-horizontal-slide-horizontally)).

* **Drawing truncated vertices slid horizontally for every facet within 60 degrees of horizontal, without the world-mesh rule** (section 8.14, variant `4`).
  It scored a mean of 0.9166 against the shipped form's 0.9158 (+0.0008) and 0.9153 for `3` (+0.0013), both inside the ±0.002 noise floor, and `balloon` +0.0048 against `main` (+0.0039 against the shipped form), but `bomb` 0.9066 against 0.9085 shipped and 0.9073 for `3`, and `ctry` and `bomb` below `3`.
  Per film (GPU, SSIM): `ctry` 0.9447, `intro` 0.9069, `land` 0.9349, `balloon` 0.9107, `traintnl` 0.9173, `bomb` 0.9066, `location` 0.8952; it was not combined with the world-mesh rule, so it is an open threshold question (section 10), not a ruled-out one ([facets near horizontal](../../work/2026-11/1064_projector-vertex-truncation/journal.md#2026-11-25-facets-near-horizontal-slide-horizontally)).

* **The projection centre alone** (section 8.14).
  Moving the axis half a column right, to the centre of column 160, lowered six films (`intro` by 0.0056) ([projector rounding on the evidence track](../../work/2026-11/1027_projection-truncation/journal.md#2026-11-24-playones-projector-rounding-on-the-evidence-track)).

* **Every steep facet of a world prop sliding in its own plane** (section 8.14).
  It brings back `land` 617's hangar band (`land` +0.0033 on lavapipe) but lowers `location` by 0.0022, past the 0.002 guard, and `bomb` by 0.0012; on `location` 2059 the pixels it loses lie along prop edges, the town lots' the most, fitting a steep facet's foot no longer lying in the horizontal plane its ground-level neighbours slid in ([a world prop's steep facet slides in its own plane](../../work/2026-11/1100_land-617-hangar-decal/journal.md#2026-11-26-a-world-props-steep-facet-slides-in-its-own-plane)).

* **A world prop's decal and every earlier facet coplanar with it sliding in their plane** (section 8.14).
  It adopts by the rule (`land` +0.0029, `location` +0.0003 on lavapipe) but lowers `bomb` by 0.0008, `traintnl` by 0.0003 and `intro` by 0.00002: on `bomb`'s opening shot shape 1651 loses a row of pixels where one of its decals only touches its wall along an edge and meets a flat polygon at its foot, which fits the decal's foot no longer lying in that polygon's horizontal plane ([only a decal's plane slides in its own plane](../../work/2026-11/1100_land-617-hangar-decal/journal.md#2026-11-26-only-a-decals-plane-slides-in-its-own-plane)).

* **Every steep facet of a decorated world prop sliding in its own plane** (section 8.14).
  A decorated prop being one whose shape holds a filled decal, or one where such a decal overlaps a coplanar earlier polygon: either brings back `land` 617's band (`land` +0.0033 and +0.0028 on lavapipe) and raises `traintnl`, but lowers `bomb` by 0.0016 and `location` by 0.0016 or 0.0013, `intro` by 0.0001 and `balloon` by 0.000005; `location`'s worst frames are a run of its stadium, not traced to pixels ([every steep facet of a decorated world prop](../../work/2026-11/1127_land-617-decal-fix/journal.md#2026-11-26-every-steep-facet-of-a-decorated-world-prop-slides-in-its-own-plane)).

* **A world prop's steep decal pulled toward the eye in the decal pass** (section 8.14).
  The base keeps the horizontal slide; the decal slides in its plane and moves toward the eye along its ray by a margin for the depth a horizontal slide one row off could move its base.
  At one or two times that margin it lowers `ctry`, `traintnl` and `bomb` (`ctry` 848: a decal shows through the slope in front of it) ([the decal pass pulls](../../work/2026-11/1127_land-617-decal-fix/journal.md#2026-11-26-the-decal-pass-pulls-a-world-props-steep-decal-toward-the-eye)); at a quarter of it, or capped at 2% of the distance, `traintnl` still falls by 0.0006 or 0.0007 and `bomb` by 0.0007 or 0.0001, while `land` rises by 0.0030 or 0.0032 ([a smaller margin](../../work/2026-11/1127_land-617-decal-fix/journal.md#2026-11-26-a-smaller-decal-pass-margin)).

* **Bounding or clamping the world-mesh slide** (section 8.14, #1197).
  Keeping a vertex's own projection when its slide would change its distance by more than 30%, 10% or 3% keeps `CTRY`'s hill on the ticks checked (at 30% not on every tick) but none adopts: at 10% five films rise by 0.0005 to 0.0020 and `traintnl` falls by 0.0001, short of the heuristic bar; giving that vertex the snapped pixel at its own depth costs `balloon` 0.0057 and `bomb`'s mask IoU 0.021; clamping the slid distance to within 1% to 10% costs `balloon` 0.0044 to 0.0052, the ocean showing through the far edge of its ground.
  A far surface lying in the horizontal plane needs the whole slide; only a vertex slid in a plane it does not lie along goes wrong ([bound](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-27-the-hills-foot-slides-kilometres-along-a-grazing-ray), [snapped or clamped](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-27-a-bounded-slide-that-keeps-the-snapped-pixel-or-clamps), [clamped, misses untouched](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-27-a-clamped-slide-misses-untouched)).

* **Steep terrain sliding in its own plane** (section 8.14, #1197).
  A raised patch steeper than about 26 degrees sliding in its own plane, as a shape facet does, keeps the hill on every captured tick of the window (`ctry` +0.0010) but lowers `land` by 0.0033 and `balloon` by 0.0017: on `land` 551 it draws records 46 and 50, which a nearer face covers in the capture, because their gentler facets still slide horizontally and come forward ([steep terrain](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-27-steep-terrain-slides-in-its-own-facets-plane)).

* **A far-terrain rule for `land` 551** (section 8.14, #1206).
  `SP_GLEAF` (`0x23BF`) calls no distance cut, records 46 and 50 face the eye and stand under no gate, and the capture's pixels there are record 2's colour: a nearer face hides them ([`land` 551](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-27-land-551s-mountain-is-hidden-by-a-nearer-face-not-left-out)).

* **Every raised terrain patch sliding in its own plane** (section 8.14, #1197).
  It keeps the hill (`ctry` +0.0016) and draws `land` 551 as the capture does, but shows ocean along the foot of far raised terrain and lowers `balloon` by 0.0018 and `land` by 0.0012, so it does not adopt ([every raised patch](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-27-every-raised-terrain-patch-slides-in-its-own-plane)).

* **A mixed slide for raised terrain** (section 8.14, #1197).
  A raised patch slid in its own plane, except its ground-plane corners, which slid horizontally while that changes their distance by at most 5% or 20%: `ctry` +0.0016, `intro` +0.0016 to +0.0018, `location` +0.0001 to +0.0005, `land` −0.0012 to −0.0009, `balloon` −0.0010 to −0.00001; the hill holds and `balloon` 1156 scores as `main` at 20%, but `land` 199 keeps a row of ocean at a far foot, and the gain misses the bar, so it does not adopt ([a mixed slide](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-28-a-mixed-slide-raised-patches-in-their-plane-except-on-the-ground)).

## 10. Open questions

* **A raised terrain patch's slide plane** (section 8.14, #1197).
  Open: a far foot beyond the bound appears to need its own plane on `ctry` (the hill) and the ground's on `land` 199 (the ocean), which a distance bound cannot tell apart; per-fragment depth is untried.

* **A world prop's decal tie** (section 8.14).
  Open: a slide that keeps a decal on a steep world-prop facet without the corners it shares with untied facets sliding apart, which costs `traintnl` 0.0004 under the shipped rule.

* **Projected points** (section 8.14).
  Open: where the clippers `0xC6AF` and `0xBF82` put a vertex at an edge's crossing, and whether it is truncated too; whether a slide threshold other than 26 degrees from horizontal scores better: 60 degrees, tried without the world-mesh rule (Ruled out, variant `4`), gave a film mean of 0.9166 against the shipped form's 0.9158 (+0.0008, +0.0013 against `3`, inside the ±0.002 noise floor) and raised `balloon` by 0.0048 against `main` (+0.0039 against the shipped form), but left `bomb` at 0.9066 (shipped 0.9085); the two were not combined.
  On `location`'s stadium the lines' and outlines' mismatched pixels lie mostly a pixel toward the centre in the capture, and the prototype cuts the stadium's loss by about a third ([`prop-shape-loss.md` § 2.5](../parity/prop-shape-loss.md#25-one-tick-phase-and-lines)).

* **Back faces** (section 8.12).
  Open: how many pixels a back face draws at its apexes and along thin parts; what a back face clipped across a screen corner draws; whether a collinear polygon of three or more points draws with gaps.
  The 13 frames searched, in `intro`, `balloon` and `bomb`, show a thin part drawn by neither test consistently; the apexes and the other four films' frames were not searched pixel by pixel ([`attribution.md` § 6](../parity/attribution.md#6-back-faces)), so telling the tests apart needs a trace or a capture made for it.

* **Polygon outlines** (section 8.11).
  Open: how `0xC9D4` rounds a row's ends, so whether the outline matches the inclusive spans pixel for pixel; whether `PLAYONE` fills terrain through `0x7571` as well, since outlining terrain scored below the base on `LAND` and `BALLOON`; and whether the world's line-list outline drops end pixels a line quad draws.
  On `location`'s stadium, #1027's truncation prototype lowers the index disagreement of the pixels beside the outlines but raises that of the outline pixels themselves ([`prop-shape-loss.md` § 2.5](../parity/prop-shape-loss.md#25-one-tick-phase-and-lines)), so these questions are what that rule leaves at a polygon's edge.

* **Lines** (section 8.10).
  Open: a zero-length `ZLINETO` or two-vertex polygon, one pixel in `PLAYONE`, draws nothing here; `vm.rs` keeps the pen's point at `MOVETO` rather than reading the register at `ZLINETO`; whether anything resets `work:0x41EA`; whether the pen persists across `RETURN` and subobjects (`work:0x41EC` is global, `vm.rs` keeps one pen per decode); the Patch #3 image's line path.
  The clipping variant `0xBB83`, which `0x9100` puts in `work:0x807E` beside the polygon clipper, was not read, so whether it too cuts only at the side planes (section 8.13) is open.
