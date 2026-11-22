# Draft: llvmpipe draws a line cut by the near plane beside the eye as a wedge

Not filed; filing is the owner's call.

## Summary

With `bypass_clip_points_lines` set (`lp_context.c:339`) and lavapipe's `point_line_tri_clip` (`lvp_execute.c:5381`), the draw module clips a line against the z planes but not x and y (`clip_line_guard_xy`, `draw_pipe_clip.c:714-744`).
A line from a point in view to a point behind the eye and well to one side is cut at the near plane, and that end projects tens of thousands of pixels outside the viewport.
`lp_setup_line` then covers a large wedge of the viewport instead of a one-pixel line; a GPU draws the line.

## Observed (Mesa 25.2.8)

- mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) on Windows and Ubuntu 24.04's `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`) under WSL 2.
- Reversed, infinite perspective (clip z = 0.1, w = view depth), a 320x240 target, outline lines of one triangle lying on the ground beside and behind the eye; one edge ends in view and is cut at the near plane, where it projects far outside the viewport (at the same film camera on a 320x185 view, at pixel (−61,040, 25,284)).
- On lavapipe (the Ubuntu package) 6,171 pixels of the line's colour have no point within 1.5 pixels on each axis whose view ray meets the triangle (`a_near_cut_ground_outline_draws_only_beside_its_polygon` in `crates/stunt-render/tests/gpu/lines.rs`); on an NVIDIA RTX 4070, none.
- Writing user clip distances that bound the line to 1.1 times the viewport makes lavapipe draw the line.

## Not yet done

- A standalone Vulkan repro, as `work/2026-11/lavapipe-clip-nan/repro` is for the clipper's NaN.
- Which step of `lp_setup_line` (fixed-point snapping, the bounding box, or the 32- or 64-bit plane setup) produces the wedge.
