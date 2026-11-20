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

## 2026-11-20: Every prop shape attributed on the seven references

- **Question**: does looking a world prop's shape up in its vertex run leave the index plane and the scores unchanged, and how does the shape split change once no shape is capped?
- **Method**: `mise run parity -- --software-only` on lavapipe (`llvmpipe`, Mesa 25.2.8): the branch at `2e18ca0` (`crates/` tree `b228018`), and `main` at `581d811` from its own worktree and release binary.
  `mise run parity-residue` between the two render trees, and the two runs' `report.json` compared field by field.
- **Result**: the index plane is unchanged: 0 differing ticks of 1320 (`ctry`), 3807 (`intro`), 1123 (`land`), 1179 (`balloon`), 1222 (`traintnl`), 3719 (`bomb`) and 8251 (`location`).
  Every film's `mean_ssim_scored`, `mean_iou_scored` and `mean_loss_by_class_scored` equal `main`'s exactly (`ctry` 0.9188, `intro` 0.8621, `land` 0.8944, `balloon` 0.8172, `traintnl` 0.8635, `bomb` 0.8461, `location` 0.8383).
  On the six films that place fewer than 511 shapes, `mean_loss_by_shape_scored` equals `main`'s exactly.
  On `location`, the 532 shapes `main` attributed keep their figures, and 482 more carry the 0.0476714 that `main` left `unattributed` (56.8% of its `props` loss 0.0839), within 6e-10; no film has an `unattributed` key.
  Each split sums to its `props` loss within 2e-7 (largest difference 1.03e-7, `ctry`).
  `location`'s worst shape is now 1610 at 0.0035 (4.2%), and its ten worst hold 0.0161 (19.2%), against 0.0090 (10.7%) of the shapes `main` attributed; eight of the ten (1610, 1145, 1150, 613, 996, 1164, 1179, 1162) were among those `main` left out.
- **Verdict**: adopted: the attribution changes and no pixel or score does.
- **Lives in**: [`attribution.md`](../../../research/parity/attribution.md) § 2.
