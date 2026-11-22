---
summary: "Lavapipe clips a line against the near plane but not the sides of the view, so an outline edge cut by the near plane beside the eye reaches its rasteriser tens of thousands of pixels off the page, five times farther at a 0.1 m near plane than at 0.5 m, and is drawn as a wedge (LAND 1025, 7,379 pixels). The outline line lists are clipped to a band 1.1 times the view through user clip distances, which lavapipe applies to lines: LAND's mean disagreement with the GPU falls from 309.4 to 5.2 pixels a tick, LOCATION's from 79.5 to 8.6."
---
# Parity: Lavapipe Draws Near-Cut Lines as Wedges

* **Scope**: why Mesa's lavapipe and a GPU draw an outline line that crosses the near plane differently, and how the renderer keeps them alike ([ADR 0055](../../docs/adr/0055-outline-lines-are-clipped-to-a-band-around-the-view.md)); lavapipe's other differences are in [`lavapipe.md`](lavapipe.md).

## 1. Mechanism

`[Supported Inference]`: Mesa source read, a pass-by-pass experiment and the frame's own outline geometry agree; the step inside Mesa's line rasteriser was not traced.
Mesa 25.2.8's llvmpipe, under lavapipe, sets `bypass_clip_points_lines` (`lp_context.c:339`) and lavapipe sets the rasterizer's `point_line_tri_clip` (`lvp_execute.c:5381`), so the gallium `draw` module clips lines through `clip_line_guard_xy` (`draw_pipe_clip.c:714-744`).
A line that leaves the view only through its sides reaches the rasteriser unclipped; one that crosses the near plane is clipped against it alone, the four side planes masked out of `do_clip_line`'s planes.
Triangles are still clipped against all six planes, with no guard band ([`lavapipe.md`](lavapipe.md) section 2).
An outline edge lying on the ground beside the eye and reaching behind it is cut where `w` equals the near distance, and that end projects to about `lateral / (near · tan(fov / 2))`: at LAND 1025 the asphalt prop edge (5136, 0, 6878)–(5200, 0, 6898) (shape 1868) ends at pixel (−61,040, 25,284), its other end at (280, 59).
`lp_setup_line` draws that line as a wedge from (280, 59) to the bottom right of the page, over ground the polygon never covers; the GPU draws the line.
At that camera 21 ground outline edges end more than 2,000 pixels off the page, the largest 202,601 pixels at the 0.1 m near plane and 40,281 at 0.5 m, so moving the near plane in from 0.5 m (#904) made the fault about five times likelier to show without causing it.
At LAND 1025 the wedge persists with the base and decal passes skipped, and goes when only the ground outlines are skipped; no asphalt fill triangle covers its pixels after Mesa's triangle clipper.
PLAYONE's capture at the nearest captured tick, 1024, shows the grass the GPU draws.
LOCATION 2407's wedge (6,566 pixels) goes with the same fix (section 2), so it is taken to be the same fault; its edge was not identified.
_Source: [Lavapipe draws a near-cut outline line as a wedge](../../work/2026-11/922_outline-clip-band/journal.md#2026-11-21-lavapipe-draws-a-near-cut-outline-line-as-a-wedge)._

## 2. The fix: clip the outline lines to a band around the view

The three line-list pipelines (the ground pass's, the base pass's and the decal pass's outlines) draw through `vs_edge` (`mode13h.wgsl`), which writes four user clip distances, `1.1·w − x`, `1.1·w + x`, `1.1·w − y` and `1.1·w + y`.
Lavapipe clips lines against user planes (they are not among the bits `clip_line_guard_xy` masks out), so every line reaches its rasteriser within 10% of the view; no pixel inside the view has a negative distance, so nothing on the page is cut.
The device requires `wgpu::Features::CLIP_DISTANCES`, which wgpu's DX12 backend, WARP included, does not offer; the adapter search passes over such adapters.
`[Bounded Observation]`, 2026-11-21, mesa-dist-win 25.2.8 against the RTX 4070, on `crates` `e76ec72b` with and without a prototype of the change; mean index-plane pixels differing per tick over every tick of each film, and the largest:

| Film | Without | With |
|---|---|---|
| CTRY | 45.6 / 4,157 | 3.1 / 14 |
| INTRO | 13.5 / 145 | 2.3 / 25 |
| LAND | 309.4 / 7,379 | 5.2 / 31 |
| BALLOON | 4.1 / 17 | 4.1 / 17 |
| TRAINTNL | 3.9 / 23 | 3.8 / 20 |
| BOMB | 9.3 / 321 | 8.4 / 77 |
| LOCATION | 79.5 / 6,566 | 8.6 / 584 |

LAND 416, the terrain-against-prop residue [`lavapipe.md`](lavapipe.md) section 5 names, falls from 152 to 7 pixels, so it was near-cut outlines too; LOCATION 3830 stays at 575.
The change moves the GPU's own render by at most 0.7 pixels a tick on any film and leaves every reference film's GPU score within 0.0007 of a frame.
_Source: [Lavapipe draws a near-cut outline line as a wedge](../../work/2026-11/922_outline-clip-band/journal.md#2026-11-21-lavapipe-draws-a-near-cut-outline-line-as-a-wedge)._

## Ruled out

- **A depth tie between the asphalt prop and the terrain**, which #922 first proposed (`near / w` steps five times coarser at 0.1 m): the ground pass that draws the wedge compares `Always`, and the wedge stays with the base and decal passes skipped ([journal](../../work/2026-11/922_outline-clip-band/journal.md#2026-11-21-lavapipe-draws-a-near-cut-outline-line-as-a-wedge)).
- **The prop's fill triangles, clipped by Mesa**: replaying `do_clip_tri` on every world triangle of the frame, none of the asphalt ones covers the wedge's pixels ([journal](../../work/2026-11/922_outline-clip-band/journal.md#2026-11-21-lavapipe-draws-a-near-cut-outline-line-as-a-wedge)).

## Open questions

1. Which step of `lp_setup_line` turns a line with one end tens of thousands of pixels off the page into a wedge; an upstream report is drafted, not filed. _Source: [the Mesa issue draft](../../work/2026-11/922_outline-clip-band/mesa-issue-draft.md)._
2. LOCATION 3830's 575 differing pixels, on water, which the band does not move.
