# Journal

## 2026-11-21: Lavapipe draws a near-cut outline line as a wedge

- **Question**: why, after #905 put the near plane at 0.1 m, does lavapipe paint asphalt (index 13) where the GPU paints grass (195) at LAND 1025 (7,379 pixels) and LOCATION 2407 (6,566), and what fixes it without moving the near plane back?
- **Method**: on local-windows, `crates` = `e76ec72b`, the RTX 4070 (NVIDIA 610.88) against mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`), with temporary `DBG_*` switches, none committed:
  - `mise run frame -- --film land --ticks 1024,1025,1036` on each, then `mise run parity-residue`, and each differing pixel's layer and shape word read from the render store's planes;
  - `DBG_SKIP` dropping the base pass, the decal pass, the ground pass, the ground fills or the ground outlines;
  - a dump of every world triangle and of the tick's `rotation_proj`, replayed through a float32 port of Mesa's triangle clipper (`do_clip_tri`, no guard band), and the ground outline edges through its line clip with the z planes only;
  - Mesa 25.2.8's `lp_context.c`, `draw_context.c`, `draw_pipe_clip.c` and `lp_setup_line.c`, read at tag `mesa-25.2.8`;
  - a prototype: user clip distances `1.1·w ∓ x`, `1.1·w ∓ y` on the three line-list pipelines through a `vs_edge` entry, with `wgpu::Features::CLIP_DISTANCES` required; `mise run parity` on all seven films on each class with and without it, `parity-residue` between them, and `mise run judge` on the GPU pair.
- **Result**:
  - Local lavapipe reproduces the canonical figure exactly: 7,379 pixels at LAND 1025.
    7,211 of them are terrain (layer 2) on the GPU and prop shape 1868 (layer 3, index 13) on lavapipe; 166 are the other way round, on thin lines at the left.
  - The capture at the nearest captured tick, 1024, shows grass there, as the GPU does.
  - With the base pass skipped, the wedge is still there on lavapipe: the ground pass, which compares `Always`, draws it.
    With the ground fills skipped and the ground outlines kept, an outline-coloured wedge remains; with the ground outlines skipped, it is gone.
  - Replaying the clipper on every world triangle, no asphalt fill triangle covers the wedge's pixels.
  - `lp_context.c:339` calls `draw_set_driver_clipping(llvmpipe->draw, false, false, false, true)`, setting `bypass_clip_points_lines`, and lavapipe sets `point_line_tri_clip` (`lvp_execute.c:5381`), so `draw_context.c:286-289` turns on `guard_band_points_lines_xy` and lines go through `clip_line_guard_xy` (`draw_pipe_clip.c:714-744`).
    There a line outside only xy planes goes to the rasteriser unclipped, and one that crosses another plane is clipped by `do_clip_line` against `clipmask & 0xfffffff0`, the four xy bits masked out, unless both ends lie outside one plane.
  - The outline edge (5136, 0, 6878)–(5200, 0, 6898) of shape 1868 passes beside and behind the eye; cut at the near plane its end projects to pixel (−61,040, 25,284), its other end to (280, 59), the wedge's apex.
    21 ground outline edges at this camera reach more than 2,000 pixels off the page, the largest 202,601 at 0.1 m and 40,281 at 0.5 m.
  - Prototype, mean differing pixels per tick GPU against lavapipe / largest, without and with: CTRY 45.6 / 4,157 and 3.1 / 14; INTRO 13.5 / 145 and 2.3 / 25; LAND 309.4 / 7,379 and 5.2 / 31; BALLOON 4.1 / 17 and 4.1 / 17; TRAINTNL 3.9 / 23 and 3.8 / 20; BOMB 9.3 / 321 and 8.4 / 77; LOCATION 79.5 / 6,566 and 8.6 / 584.
    LAND 416 falls from 152 to 7 pixels, LAND 1025 to 2, LOCATION 2407 to 7; LOCATION 3830 stays at 575.
  - It moves the GPU's own render by at most 0.7 pixels a tick on any film, 17 at most on one tick (LOCATION 2069); `mise run judge`: mean SSIM 0.9038 on both, worst frame −0.0007, none down by more than 0.005.
- **Verdict**: adopted as designed with the owner on 2026-11-21 (clip distances required, adapters without them passed over, a new ADR); the committed change's measurement is the next entry.
- **Lives in**: [`lavapipe-line-clip.md`](../../../research/parity/lavapipe-line-clip.md).
