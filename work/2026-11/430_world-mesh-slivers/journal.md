# Journal

## 2026-11-12: world-mesh slivers by conservative rasterization and by a line-list outline

- **Question**: Can the world mesh cover the pixels `PLAYONE`'s inclusive spans add to a polygon (`0x7571`, [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.11) at a cost `LOCATION` affords ([#430](https://github.com/neilsh/stunt-reel/issues/430))? #429's line-quad outlines took `LOCATION`'s world from 6.7 million to 32.4 million vertices, and one variant ran out of wgpu memory.
- **Method**: One temporary switch, `DBG_INCLUSIVE` with values 1 to 4, on `main` `dd9a22cf` (#429), each value scored with `mise run sweep` on all seven films (RTX 4070 Laptop, Vulkan), then reverted. `DBG_INCLUSIVE`: `1` draws the world through base and decal pipelines with `PrimitiveState::conservative` (the adapter reports `Features::CONSERVATIVE_RASTERIZATION`; a scratch print confirmed it on), with the world's line quads narrowed to a thousandth of their width so the over-estimate alone widens them; `2` does the same for the per-frame shapes too and drops their outline quads; `3` uploads with the world a line-list index buffer of every edge exactly one filled triangle of a mesh slice uses (`outline::boundary_edges`, the same edges #429 outlines) and draws it after the draw's triangles through a `LineList` pipeline with the slice's depth test (decal outlines compare `LessEqual` without the `[I5]` bias, which wgpu allows only on triangles); `4` is `3` without terrain and ocean triangles. A scratch script (`build/scratch/time_location.py`, not committed) rendered `LOCATION`'s whole captured span twice each with `0` and `4`, timing the process and polling `nvidia-smi` every 0.2 s for the whole GPU's peak memory use. `mise run frame -- --var` drew the pictures. Track: evidence-backed (`0x7571`).
- **Result**:

  | Film | Base | `1` conservative world | `2` conservative all | `3` edges, all world | `4` edges, props only |
  |---|---|---|---|---|---|
  | `CTRY` | 0.9022 | 0.8961 | 0.8946 | 0.9039 | 0.9048 |
  | `INTRO` | 0.8467 | 0.8480 | 0.8441 | 0.8479 | 0.8469 |
  | `LAND` | 0.8663 | 0.8653 | 0.8605 | 0.8655 | 0.8666 |
  | `BALLOON` | 0.8127 | 0.8127 | 0.7986 | 0.8114 | 0.8141 |
  | `TRAINTNL` | 0.8555 | 0.8545 | 0.8532 | 0.8570 | 0.8573 |
  | `BOMB` | 0.8151 | 0.8158 | 0.8133 | 0.8197 | 0.8202 |
  | `LOCATION` | 0.8092 | 0.8069 | 0.8064 | 0.8151 | 0.8142 |

  - With `4`, `LOCATION`'s world (6,703,537 vertices, 7,488,138 indices, one chunk) gains 12,863,762 edge indices: 6.4 million edges, 51.5 MB of index buffer, against about 1.25 GB of vertices and indices for #429's quads. The render took 184.7 s and 179.9 s without edges and 215.1 s and 207.2 s with them (about 16 % longer, upload and decode included). The whole GPU's polled peak went from 456 MiB to 763 MiB in both runs; the poll counts every process on the GPU, so the rise probably includes transient upload copies; the edges' resident size is 51.5 MB by index count.
  - Judged by eye: in `LOCATION` tick 4170 the derrick's legs draw a pixel wider, like the capture's; without edges they break into thin runs. In `CTRY` tick 672 the far fence line draws as an unbroken row, as in the capture.
- **Verdict**: conservative rasterization (`1`, `2`) rejected: with the world alone it fell on four of seven films (`CTRY` −0.006, `LOCATION` −0.0023; `BALLOON` level, `INTRO` and `BOMB` rose), and on every film with every shape; it likely over-covers, since it takes every pixel a triangle touches (not measured). Line-list edges on the world's props (`4`) adopted on the evidence-backed track: no film falls, `BOMB` rises 0.0051 and `LOCATION` 0.0050. Outlining terrain and ocean as well (`3`) moves `LAND` and `BALLOON` below the base (−0.0008, −0.0013) and is not adopted, though it scored highest on `LOCATION` and `INTRO`. The expected `gpu` tables in `references.toml` are updated from the committed change.
- **Lives in**: [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.11.
