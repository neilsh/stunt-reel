---
summary: "The SOD VM's lines and polygon spans: `MOVETO`/`ZLINETO`/`LINECOL` lines, polygon spans that include both ends, and the span test that culls an anticlockwise polygon with its outline."
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
The world instead draws the same edges, those exactly one filled triangle of a mesh slice uses, as a `LineList` index buffer over its own vertices, two indices an edge, after the world draw's triangles (a decal slice's outline right after that slice's triangles, [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)) and with their depth test (a decal slice's outline compares `LessEqual` without the `[I5]` bias, which wgpu allows only on triangles; [`mesh.rs`](../../crates/stunt-render/src/mesh.rs) `GpuModel::from_ir_outlined`).
Terrain and ocean triangles are not outlined.
The line list is drawn one pixel wide by the backend's line rules, which need not draw the end pixels a line quad does (not measured).
A slice split over chunks (a world over `max_buffer_size`; `LOCATION`'s is one chunk) gets the outline of the unsplit slice, its edges counted over all its runs, each run drawing its share ([#475](https://github.com/neilsh/stunt-reel/issues/475)).
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

## 10. Open questions

* **Back faces** (section 8.12).
  Open: how many pixels a back face draws at its apexes and along thin parts, and whether that is seen in a capture; what a back face clipped across a screen corner draws; whether a collinear polygon of three or more points draws with gaps.

* **Polygon outlines** (section 8.11).
  Open: how `0xC9D4` rounds a row's ends, so whether the outline matches the inclusive spans pixel for pixel; whether `PLAYONE` fills terrain through `0x7571` as well, since outlining terrain scored below the base on `LAND` and `BALLOON`; and whether the world's line-list outline drops end pixels a line quad draws.

* **Lines** (section 8.10).
  Open: a zero-length `ZLINETO` or two-vertex polygon, one pixel in `PLAYONE`, draws nothing here; `vm.rs` keeps the pen's point at `MOVETO` rather than reading the register at `ZLINETO`; whether anything resets `work:0x41EA`; whether the pen persists across `RETURN` and subobjects (`work:0x41EC` is global, `vm.rs` keeps one pen per decode); the clipping variant `0xBB83` and the Patch #3 image's line path.
