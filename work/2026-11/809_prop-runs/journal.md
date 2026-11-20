# Journal: move the prop-shape attribution slot out of SodVertex

## 2026-11-19: Can `primitive_index` or `vertex_index` give a world fragment its prop?

- **Question**: can the plane's shape word find a world prop's shape from `@builtin(primitive_index)` and a table of index ranges per placement, on lavapipe and this repo's wgpu (30.0.1), so that `SodVertex` carries no slot?
- **Method**: a throwaway probe on `main` `6ee17e0`, not committed.
  `stunt-core` recorded each `push_prop_mesh` call's index and vertex range with its placement and shape.
  An env-gated pipeline, drawn at the end of the real scene pass, drew the frame's prepared world slices (ground, base, decals) one `draw_indexed` per slice as the renderer does, with `first_instance = index_offset / 3`, depth `Always`, no culling and no colour writes, and the outlines the same way with `first_instance = edge_offset / 2`.
  Its vertex shader looked `vertex_index` up in a vertex-range table and passed the result flat; its fragment shader read the index and edge buffers as storage and counted with atomics:
  - whether `base + primitive_index` lands on the triangle whose first index is the provoking `vertex_index`;
  - whether `primitive_index` without the base does;
  - whether the triangle-range and vertex-range tables find the same push;
  - whether a fragment of scenery class prop lies outside the table, or one of another class inside it.

  Every 25th film tick of each reference film, `--software-only`, `VK_DRIVER_FILES` set to the lavapipe ICD; adapter `llvmpipe (LLVM 20.1.2, 256 bits)`, Mesa 25.2.8.
- **Result**: llvmpipe reports `Features::PRIMITIVE_INDEX` (wgpu enables it on Vulkan with `geometryShader`), and the shader needs `enable primitive_index;`.
  The index restarts at 0 for every draw call: with the draw's first triangle added it matched on every one of 99,295,981 triangle fragments over 828 frames, and without it on 0 of the 90,355,174 fragments of draws whose first index is not 0.
  Outline draws number edges in the edge buffer, not triangles: `edge_offset / 2 + primitive_index` matched on all 9,996,141 edge fragments.
  Each push appends its triangles as one index run and its own new vertices as one vertex run, and no push's indices reach another's vertices, so a table keyed by triangle or by vertex names the same push on every one of 25,965,967 prop fragments; no prop fragment fell outside the table and no other fragment inside it.
  Every world uploads as one chunk, so `vertex_index` is the world's own vertex number; LOCATION's 6,702,496 vertices take 187.7 MB of the 256 MiB `max_buffer_size`.

  | World | Frames | Vertices | Table entries | Placements | Shapes | Triangle fragments | Prop fragments | Edge fragments | Mismatches |
  |---|---|---|---|---|---|---|---|---|---|
  | CTRY | 53 | 20,044 | 775 | 306 | 119 | 7,896,920 | 2,593,077 | 438,948 | 0 |
  | INTRO | 153 | 819,169 | 100,868 | 10,723 | 161 | 11,374,587 | 2,557,784 | 1,240,486 | 0 |
  | LAND | 45 | 32,055 | 1,858 | 834 | 159 | 6,279,274 | 1,428,048 | 193,826 | 0 |
  | BALLOON | 48 | 569,348 | 6,982 | 1,589 | 50 | 3,476,231 | 71,688 | 24,661 | 0 |
  | TRAINTNL | 49 | 112,145 | 2,341 | 1,049 | 60 | 5,021,603 | 928,134 | 288,462 | 0 |
  | BOMB | 149 | 244,829 | 5,196 | 970 | 163 | 16,403,752 | 5,118,654 | 3,595,144 | 0 |
  | LOCATION | 331 | 6,702,496 | 152,754 | 35,479 | 1,062 | 48,843,614 | 13,268,582 | 4,214,614 | 0 |

  Shapes counts distinct shape ids over every push, empty pushes included; mismatches sums the checks above.
- **Verdict**: both tables work on lavapipe; the vertex-keyed one is adopted (owner decision on #809, 2026-11-19).
  The primitive-index table is rejected not by score but by cost: it needs a wgpu feature and a second shader module, every world draw would have to pass its first triangle, and outlines would need a second, edge-keyed table.
  The local-windows GPU was not tested; the vertex-keyed table uses only core WGSL.
- **Lives in**: [`attribution.md`](../../../research/parity/attribution.md) § 1 and its Ruled out list.
