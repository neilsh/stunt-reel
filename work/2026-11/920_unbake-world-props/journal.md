## 2026-11-22: loop time with the world's base and decal draws skipped

- **Question**: Does skipping the world's base and decal draws cut the whole `LOCATION` film's lavapipe loop by at least the 15% the owner set (step 1 of #920), with the skipped variant faster in all four pairs?
  The skip bounds what un-baking could save from above: un-baking still draws the visible placements.
- **Method**:
  - `main` at `dc9622ea` plus [`world-skip-and-vertex-probe.patch`](world-skip-and-vertex-probe.patch): #622's loop timer in `headless.rs` (`[probe] loop_ms`, from the first submit through `finish` and the last page write), and in `SceneRenderer::encode` an early return for every `Target::World` draw when `STUNT_PROBE_SKIP_WORLD` is set (read once).
    `encode` draws only base and decal slices, so the world's ground slices (ocean, flat terrain and each placement's flat-ground nodes) are still drawn, and the walk, `prepare` and readback still run.
  - One release `stuntreel.exe` for both variants (`cargo build --release -p stunt-cli`), on the owner's laptop (Ryzen 7 7745HX), no other render or build running.
  - `stuntreel --headless <data>/builds/patch3/VAULT/LOCATION.FLM --all <data>/captures/vault-location/archives/LOCATION.ALL --tick-range <span> --sidata <data>/corpus/siarchive/Developer/FreeFlight/SIDATA --out-dir <dir> --width 320 --height 200 --viewport-rows 185`, with `--software-only` and `VK_DRIVER_FILES` for mesa-dist-win 25.2.8, else on the GPU; every run's `render.json` names `llvmpipe (LLVM 21.1.7, 256 bits)` or the `NVIDIA GeForce RTX 4070 Laptop GPU`.
  - Four pairs per cell, base first in pairs 0 and 2 and skip first in 1 and 3, in the order: lavapipe whole film (`12..=8262`), lavapipe Span B (`3680..=3979`), RTX 4070 whole film, RTX 4070 Span B.
  - Whole-process wall clock from the runner's stopwatch; each run's `frames.zst`, `layers.zst`, `palettes.zst` and `shapes.zst` hashed.
- **Result**: Loop ms in pair order, then the median of four and the minimum:

  | Cell | Base | Skip | Skip faster | Median | Minimum |
  |---|---|---|---|---|---|
  | Lavapipe whole film | 27451, 28518, 29633, 27454 | 14209, 14222, 14417, 14323 | 4 of 4 | 27986 to 14272.5 (`-49.0%`) | 27451 to 14209 (`-48.2%`) |
  | Lavapipe Span B | 2466, 2503, 2864, 2814 | 686, 774, 816, 783 | 4 of 4 | 2658.5 to 778.5 (`-70.7%`) | 2466 to 686 (`-72.2%`) |
  | RTX 4070 whole film | 8781, 8775, 9774, 10322 | 8186, 8205, 9265, 10452 | 3 of 4 | 9277.5 to 8735 (`-5.8%`) | 8775 to 8186 (`-6.7%`) |
  | RTX 4070 Span B | 480, 464, 449, 416 | 378, 359, 366, 334 | 4 of 4 | 456.5 to 362.5 (`-20.6%`) | 416 to 334 (`-19.7%`) |

  - Whole-process wall-clock medians: lavapipe whole film 29671.5 to 16101.5 ms (`-45.7%`), Span B 5031 to 3023 (`-39.9%`); RTX 4070 whole film 11640 to 10617 (`-8.8%`), Span B 3032.5 to 3030.5 (`-0.1%`).
  - The RTX 4070's whole-film runs drifted upward through the cell (base `8,775..10,322 ms`), so its 3-of-4 pairs are not resolved; it does not gate.
  - Each variant's four stores hashed the same in all four of its runs in every cell; the skipped variant's `frames`, `layers` and `shapes` differ from base's and its `palettes` match.
- **Verdict**: control, passing the owner's gate (all four lavapipe whole-film pairs faster, median `-49.0%` against the 15% bar), so step 2 runs.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6, `#920`'s verdict.

## 2026-11-22: vertices a per-placement frustum test would remove

- **Question**: Over the whole `LOCATION` film, would frustum-testing each placement on its own box, beside `VisibleWalk`'s node-box cull, remove at least 30% of the world's drawn vertices (step 2 of #920)?
- **Method**:
  - The same patch's CPU probe (`DBG_PROBE_WORLD_VERTS_FILE=<out>` on the step 1 command, without `--out-dir`), which returns before the renderer opens: `GpuModel::probe_cpu` gives each mesh node of `world.ir` one slice with its box and disc flag, as the upload does, and `probe_world_vertices` walks it with `collect_world_meshes` on each frame's camera, as `SceneRenderer::prepare` does (`projection_y_scale` from `--viewport-rows 185`).
  - Per frame it sums the vertices (each emitted node's mesh vertex count) and indices of the ground, base and decal slices, and, for each placement record whose `MeshSpans` hold base or decal indices in the `WORLD_BASE` or `WORLD_DECAL` run, the distinct vertices of a placement whose own box `frustum_keeps` rejects (kept when its disc rim can be squeezed, as the walk keeps a node).
  - Check: a throwaway print in `SceneRenderer::prepare` on the step 1 command, `3680..=3682` on the GPU, gave the same base slice, base index and decal slice counts as the probe on those ticks (`272`, `2,697`, `59`; `270`, `2,682`, `59` on `3682`).
  - Whole film `12..=8262`, Span B, and `INTRO` Span C (`2500..=2949`, `<data>/builds/patch3/VAULT/INTRO.FLM` with `captures/vault-intro/archives/INTRO.ALL`) for the structure only.
- **Result**:
  - On `LOCATION` the world IR holds `228,159` nodes, `6,704,202` vertices and `7,493,034` indices; `WORLD_BASE`'s own slice is indices `0..342` (raised terrain) and `WORLD_DECAL`'s `342..360`.
    Of `56,585` placement records, `35,479` have mesh spans, and none holds an index in either run: each placement's geometry lies in nodes made for it alone (`MeshSpans::nodes`, built by `push_gated_props`), which the walk already culls on their own boxes.
    `push_props` puts nothing of a placement behind an `SP_1NODE` chain or a distance cut (`Placement::reach`) in those runs; why no placement is left for them was not traced further.
    `INTRO` is the same: `26,386` records, `10,723` with mesh spans, none in `WORLD_BASE` (`0..342`) or `WORLD_DECAL` (`342..360`).
  - Whole film (`8,251` frames): the walk draws `35,456,495` base and decal vertices (`33,067,366` base, `2,389,129` decal; `38,389,803` and `6,436,035` indices), a mean of `4,297.2` and a median of `1,000` a frame, beside at least `22,414,120` ground vertices (a lower bound: the probe counts a ground slice's vertices only when it starts its node's mesh); the per-placement test removes `0` (`0%`).
  - Span B (`300` frames): `1,319,915` base and decal vertices, median `4,423` a frame, from a median of `585.5` base and `327` decal slices; the test removes `0`.
- **Verdict**: rejected by the owner's 30% gate, cleanly: the test removes `0%` of the drawn vertices, since the walk already culls each placement on its own box.
  Step 1's saving is not fill-vertex work: the skipped draws carry about `4,400` base and decal vertices a frame on Span B against the `6.7` million the baked mesh holds; their outline indices were not counted.
  Step 3 (memory) gives no go and was measured afterwards as a control, in the next entry.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6 and its Ruled out.

## 2026-11-22: memory with and without the world uploaded

- **Question**: What are `LOCATION`'s peak and post-upload resident memory per worker with and without the world's geometry uploaded (step 3 of #920)?
  The owner asked for it as a control, recorded only: memory gives no go.
- **Method**:
  - `main` at `636ee2f4` plus [`world-upload-skip.patch`](world-upload-skip.patch): when `STUNT_PROBE_NO_WORLD_UPLOAD` is set, `SceneRenderer::new` does not call `GpuModel::from_ir_outlined` for the world, so its `world` is `None` and `prepare` draws no world, as the skip of step 1 did for the base and decal draws and more.
    Nothing else changes: the CPU-side `world.ir` is still built with the scene, `WorldPlacements::new` still runs, and the shapes and sprites are still uploaded.
    The CLI's `release_world_mesh` still frees `world.ir` as usual, so the peak without the upload still includes the CPU world mesh; the same code runs to `scene built` in both variants, and its readings there differ by up to `12.1` MiB (lavapipe), so that column's `fall` is run-to-run noise, not a saving.
  - One release `stuntreel.exe` for both variants, on the owner's laptop (Ryzen 7 7745HX), with no other stuntreel, cargo or rustc process running.
  - #622's method and span: `stuntreel --headless <data>/builds/patch3/VAULT/LOCATION.FLM --all <data>/captures/vault-location/archives/LOCATION.ALL --tick-range 12..=300 --sidata <data>/corpus/siarchive/Developer/FreeFlight/SIDATA --out-dir <dir> --width 320 --height 200 --viewport-rows 185 --report-memory` (Span A), with `--software-only` and `VK_DRIVER_FILES` for mesa-dist-win 25.2.8 on lavapipe, else on the GPU; every run's `render.json` names `llvmpipe (LLVM 21.1.7, 256 bits)` or the `NVIDIA GeForce RTX 4070 Laptop GPU`.
  - One run per cell, no noise estimate.
- **Result**: Resident set in MiB at each `--report-memory` stage, then the peak line:

  | Adapter | World uploaded | scene built | renderer opened | world mesh released | frames rendered | peak |
  |---|---|---|---|---|---|---|
  | Lavapipe | yes | 307.4 | 767.0 | 499.4 | 672.0 | 910.5 |
  | Lavapipe | no | 295.3 | 354.8 | 86.0 | 104.1 | 354.8 |
  | Lavapipe | fall | 12.1 | 412.2 | 413.4 | 567.9 | 555.7 |
  | RTX 4070 | yes | 297.0 | 537.2 | 267.8 | 272.9 | 732.4 |
  | RTX 4070 | no | 295.9 | 431.4 | 161.7 | 169.1 | 431.4 |
  | RTX 4070 | fall | 1.1 | 105.8 | 106.1 | 103.8 | 301.0 |

  - The uploaded runs' peaks (`910.5`, `732.4` MiB) and post-release figures (`499.4`, `267.8`) compare with #622's `904.1..915.6` and `697.5..809.8` MiB peaks and `493.4..495.1` and `234.3..276.8` MiB after release: three sit inside, and lavapipe's `499.4` sits `4.3` MiB above its range, a gap one run per cell cannot resolve.
  - Without the upload the peak is the `renderer opened` stage on both adapters, so the peak includes the scene, the CPU world mesh, the shapes and sprites uploaded, and the device and driver's own memory, not separated here.
  - On lavapipe the world's device buffers are system memory, so they are in the resident set; on the RTX 4070 the resident set holds the driver's host-side share of them.
- **Verdict**: control, recorded only; memory gives no go.
  Against the issue's hypothetical bar, a post-upload fall of at least 200 MiB a worker: removing the whole upload falls the post-upload resident set `413.4` MiB on lavapipe, above the bar, and `106.1` MiB on the RTX 4070, below it.
  These are upper bounds on what un-baking could save, since un-baking still uploads each shared shape once and still builds per-placement data, and nothing here measures that.
  The peak fell `555.7` and `301.0` MiB, but a saving at the peak alone would be a chunked world upload issue, not this one.
  `[Bounded Observation]`: one run per cell, on one machine.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6, `#920`'s verdict.

## 2026-11-22: what un-baking would keep baked

- **Question**: Of the world's uploaded GPU bytes, how many would un-baking (the issue's candidate design) keep baked and how many would it drop, and what would it add, on `LOCATION` and `INTRO`?
  Step 3's `413.4` and `106.1` MiB are upper bounds, since they remove the whole upload.
- **Method**:
  - The branch at `68ac0d18` plus [`baked-share-probe.patch`](baked-share-probe.patch): a CPU-only count that returns from `run_headless` before the renderer opens (`DBG_PROBE_WORLD_BYTES=1`), with no GPU and no device.
    It calls the uploader's own planning code on the world IR: `plan_upload` (with the 256 MiB buffer limit of the `downlevel_defaults` that `request_device` asks for; one chunk, as #645 found) and `plan_edges` with `outlines_in_world`, the filter `SceneRenderer::new` passes `GpuModel::from_ir_outlined`.
  - Bytes per element are the sizes in `GpuChunk::upload`: vertex `28` B (`size_of::<SodVertex>()`), apex `12` B a vertex (`[f32; 3]`, the second stream), index `4` B, outline `4` B an outline index (two per edge: `8` B an edge), prop-runs table `12` B a run (`[u32; 3]`, `chunk_prop_runs`).
  - Each mesh node's vertex window (`NodeKind::Mesh`'s `vertex_offset` and `vertex_count`), its indices and its slices' `edge_count` go to one class; a run's class is that of its first vertex.
    Every one of the `6,704,202` vertices fell in some node's window.
  - A node's class is recognised in the code as:
    - **terrain and ocean**: a node of no placement (`WORLD_BASE`, `WORLD_DECAL`, and the `GROUND_NODE` quads `push_mesh_node` makes for the ocean and the flat terrain), `4` nodes;
    - **flat ground**: a `GROUND_NODE` node `push_gated_props` makes for a placement, which is in its `MeshSpans::nodes` run;
    - **ground-snapped decal**: that function's `WORLD_GATED` node of a placement whose `grounded` entry is `Some` (`ground_decal_vertices`, ADR 0035; a node's `is_decal` is also true for an unsnapped decal mesh, so `is_decal` does not tell them apart);
    - **`OP_TAP` shape**: its `WORLD_GATED` node, when the shape is one `decode_chunks` found stopping at `MissingAnchors` on a decode without anchors, the shapes `World` decodes per placement (`anchored_shapes`, `anchored_models`);
    - **dropped**: every other `WORLD_GATED` node.

    A node is classed in that order, so a tapped shape's flat-ground nodes count as flat ground.
  - What un-baking adds: the shapes the renderer does not upload today.
    `FilmScene::drawn_only` keeps only the actors', view-facing props' and origin shapes, so no baked prop's shape is in `SceneRenderer::shapes` (the probe checked: none of the dropped placements' shapes is there).
    The probe sizes each dropped placement's distinct shape uploaded two ways, since the issue leaves the outline open: as `outlined()` quads, as `self.shapes` uploads (vertices at `40` B with the apex, indices at `4` B), and as a line list, as the world does (the same, plus `4` B an outline index from `plan_edges`).
    The per-placement entry is the issue's `shape_id` and a transform, at `68` B (a `64` B matrix and a `4` B id), and at `16` B (an eye-relative position and the id) for comparison.
    A placement counts once if any of its nodes is dropped.
  - One run each, release build, on the owner's laptop, with step 1's command for `LOCATION` (`--tick-range 12..=300`, no `--out-dir`) and for `INTRO` (`<data>/builds/patch3/VAULT/INTRO.FLM` with `captures/vault-intro/archives/INTRO.ALL`); the world does not depend on the tick range.
- **Result**: The world holds `LOCATION`'s `228,159` nodes (`158,362` with a mesh), `6,704,202` vertices, `7,493,034` indices, `12,861,070` outline indices and `31,441` runs, and `INTRO`'s `128,768`, `819,265`, `1,002,423`, `1,513,630` and `9,815`.
  `LOCATION` in MiB (`1,048,576` B), by class and by buffer:

  | Class | Vertex | Apex | Index | Outline | Runs | Total |
  |---|---|---|---|---|---|---|
  | Terrain and ocean | 0.01 | 0.01 | 0.00 | 0.00 | 0.00 | 0.02 |
  | Flat ground (`309,901` vertices) | 8.28 | 3.55 | 2.61 | 1.18 | 0.06 | 15.67 |
  | Ground-snapped decals (`177` vertices) | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.01 |
  | `OP_TAP` shapes (`84` vertices) | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
  | Kept baked | 8.30 | 3.55 | 2.61 | 1.18 | 0.06 | 15.71 |
  | Dropped (`6,393,484` vertices, `95.4%`) | 170.72 | 73.17 | 25.97 | 47.88 | 0.30 | 318.04 |
  | World total | 179.02 | 76.72 | 28.58 | 49.06 | 0.36 | 333.75 |

  - Added by un-baking on `LOCATION`: the dropped placements are `28,434` records of `823` distinct shapes, none already uploaded (`drawn_only` removes a baked prop's shape from the renderer's shapes); the probe's count of shapes absent from the scene, which it prints, was not recorded, so if any were absent the shape costs below are low.
    The shapes cost `34.72` MiB as `outlined()` quads or `8.07` MiB as a line list; the per-placement entries `1.84` MiB at `68` B (`0.43` at `16` B).
    So the dropped bytes less what un-baking adds are `281.48` MiB with quad outlines and `308.13` MiB with line-list outlines (`282.89` and `309.54` at `16` B).
    The CPU side of the per-placement data is the same entries, `1.84` MiB, beside the `PlacementRecord`s that already exist (`76` B each, `56,585` of them).
  - `INTRO` in MiB, for comparison: kept `0.84` (`0.81` of it flat ground, `15,919` vertices); dropped `40.12` (`802,706` vertices, `98.0%`: vertex `21.43`, apex `9.19`, index `3.71`, outline `5.69`, runs `0.10`); total `40.96`.
    Un-baking adds `3.57` (quads) or `0.77` (line list) for `76` shapes and `0.61` for `9,405` placements, so it would save `35.94` or `38.74` MiB.
  - Records: of `LOCATION`'s `35,479` placements with a mesh, `8,424` have a flat-ground node, `10` a snapped decal, `14` an `OP_TAP` shape and `28,434` a dropped node (a placement can be in more than one).
  - Sanity check against step 3: the world's buffers total `333.75` MiB, against lavapipe's measured fall of `413.4` MiB (`499.4` to `86.0`), a gap of `79.7` MiB.
    The skipped variant also did not build the world's `GpuModel` node arena: `228,159` `GpuNode`s at `240` B and `158,362` slices at `28` B are `56.5` MiB inline (`size_of`), before their name, child-list and slice heap allocations.
    That leaves about `23` MiB, or less once those allocations are counted; allocator and driver granularity and staging copies are candidates, but none was measured.
    On the RTX 4070 the buffers are in device memory, so the `106.1` MiB fall is the driver's host-side share plus that node arena, and the split between them was not measured.
- **Verdict**: control, recorded only; memory gives no go.
  Against the issue's hypothetical bar of a 200 MiB fall a worker, the bytes un-baking would drop net of what it adds, `281` to `308` MiB of buffers on `LOCATION`, are above it on lavapipe, though as buffer bytes, not a measured fall; on the RTX 4070 the whole upload's fall in one run is `106.1` MiB, so any un-baking saving there is at most about that, below the bar.
  The dropped class includes the placements of shapes with internal `FacesEye`/`BeyondDepth` gates, whose routing #920 leaves open; their share of the bytes was not counted.
  If that fall scaled with bytes, un-baking's share would be about `89` MiB (`106.1 × 281.48 / 333.75`); the scaling is an assumption, not a measurement.
  The dropped nodes' share of the `GpuNode` arena, about `36` MiB inline (`141,258` mesh nodes), is not in the `281` to `308` MiB, and whether un-baking would keep those nodes (they carry the placements' gates) was not examined.
  The probe counts bytes; no un-baked renderer was run, so the figure holds for the candidate design as the issue states it.
  `[Bounded Observation]`: one run per film on one machine, a 256 MiB buffer limit assumed from the code, and a byte count that the sanity check matches only to within the node arena and about `23` MiB.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6, `#920`'s verdict.

## 2026-11-22: what the world's base and decal draws cost on lavapipe

`[Bounded Observation]`

- **Question**: Which part of the world's base and decal draws makes up the half of the lavapipe loop that step 1's skip removed: their pixels, their outlines, the decal slices' per-slice pipeline switches, or the draws' own overhead?
  And what does the 172.6 MiB resident-set rise between `world mesh released` and `frames rendered` follow?
- **Method**:
  - `main` at `67f409b7` plus [`draw-cost-split.patch`](draw-cost-split.patch) (`git diff -- crates`, so it also holds step 1's [`world-skip-and-vertex-probe.patch`](world-skip-and-vertex-probe.patch): the loop timer and the vertex probe).
    In `SceneRenderer::encode`, for `Target::World` draws only, `STUNT_PROBE_WORLD` (read once) is a bit mask over the base and decal draws; the ground draws are not touched.
  - The variants, each one switch:
    - `base`: no switch.
    - `a`: skip base fills.
    - `b`: skip base outlines.
    - `c`: skip decal fills.
    - `d`: skip decal outlines.
    - `e`: skip all four (step 1's skip).
    - `f`: issue every draw, with its pipeline switch and vertex fetch, but with the scissor rect set to `0,0,1,1` for those draws and restored to `0,0,320,200` after each; `wgpu` accepted it.
    - `g`: skip nothing, but encode a world draw's decal fills together, then its decal outlines together: two pipeline switches a draw instead of two a slice.
      It changes the picture where decals overlap, so it is a timing probe only.
  - One release binary (`mise exec -- cargo build --release -p stunt-cli`) copied to the scratchpad as `stuntreel-split.exe`, every variant run from it, no other `stuntreel`, `cargo` or `rustc` process running.
    An earlier build of the same switches without `g` ran the Span B set once too; its medians are under Result.
  - Same command line as step 1 (`--headless ... LOCATION.FLM --all ... --width 320 --height 200 --viewport-rows 185`, with `--software-only` and `VK_DRIVER_FILES` for mesa-dist-win 25.2.8 on lavapipe); every run's `render.json` names `llvmpipe (LLVM 21.1.7, 256 bits)` or `NVIDIA GeForce RTX 4070 Laptop GPU`.
  - Order: lavapipe Span B (`3680..=3979`), 4 rounds of all 8 variants, the order rotated one place a round.
    Lavapipe whole film (`12..=8262`), 2 rounds of `base`, `b`, `f`, `e`, `g`, reversed in round 2.
    RTX 4070 Span B, 4 rounds of `base`, `b`, `f`, `e`, `g`, rotated.
    Memory: one `--report-memory` run each of `base`, `b`, `f` and `e` on lavapipe Span A (`12..=300`), run twice, with the earlier build and with this one.
- **Result**:
  - Loop ms, lavapipe Span B, in round order (rounds 0 to 3), the median and its change against `base`'s median:

    | Variant | Rounds | Median | Min..max | Change |
    |---|---|---|---|---|
    | `base` | 2466, 2340, 2335, 2414 | 2377.0 | 2335..2466 | |
    | `a` base fills | 2461, 2244, 2256, 2159 | 2250.0 | 2159..2461 | -5.3% |
    | `b` base outlines | 2205, 2080, 2043, 2146 | 2113.0 | 2043..2205 | -11.1% |
    | `c` decal fills | 1375, 1365, 1331, 1348 | 1356.5 | 1331..1375 | -42.9% |
    | `d` decal outlines | 1318, 1254, 1247, 1247 | 1250.5 | 1247..1318 | -47.4% |
    | `e` all four | 661, 644, 640, 642 | 643.0 | 640..661 | -72.9% |
    | `f` 1-pixel scissor | 2149, 2149, 2045, 2043 | 2097.0 | 2043..2149 | -11.8% |
    | `g` decals grouped | 1427, 1424, 1420, 1406 | 1422.0 | 1406..1427 | -40.2% |

  - Change round by round against that round's `base`: `a` -0.2, -4.1, -3.4, -10.6%; `b` -10.6, -11.1, -12.5, -11.1%; `c` -44.2, -41.7, -43.0, -44.2%; `d` -46.6, -46.4, -46.6, -48.3%; `e` -73.2, -72.5, -72.6, -73.4%; `f` -12.9, -8.2, -12.4, -15.4%; `g` -42.1, -39.1, -39.2, -41.8%.
    Every variant but `a` is faster than `base` in all four rounds: `b`'s and `f`'s maxima (2205, 2149) are under `base`'s minimum (2335), while `a`'s maximum (2461) is inside `base`'s range, so `a`'s `-5.3%` does not resolve.
    `b` and `f` (2113.0 and 2097.0) lie inside each other's ranges, so they do not resolve against each other.
  - The earlier build's Span B set, loop ms in round order and the median: `base` 2431, 2407, 2275, 2433 (2419.0); `a` 2340, 2340, 2341, 2277 (2340.0, -3.3%); `b` 2152, 2056, 2192, 2022 (2104.0, -13.0%); `c` 1350, 1354, 1348, 1371 (1352.0, -44.1%); `d` 1316, 1280, 1275, 1290 (1285.0, -46.9%); `e` 639, 661, 679, 648 (654.5, -72.9%); `f` 2142, 2098, 2207, 2224 (2174.5, -10.1%).
  - Loop ms, lavapipe whole film, round 0 and round 1:

    | Variant | Round 0 | Round 1 | Median | Change |
    |---|---|---|---|---|
    | `base` | 27368 | 26757 | 27062.5 | |
    | `b` | 21088 | 20531 | 20809.5 | -23.1% |
    | `f` | 19815 | 20197 | 20006.0 | -26.1% |
    | `e` | 13972 | 14200 | 14086.0 | -48.0% |
    | `g` | 24918 | 25052 | 24985.0 | -7.7% |

    Each variant is faster than `base` in both rounds with its two values clear of `base`'s two, and `f`'s clear of `b`'s, but two rounds give no spread estimate.
  - Loop ms, RTX 4070 Span B, in round order:

    | Variant | Rounds | Median | Min..max | Change |
    |---|---|---|---|---|
    | `base` | 437, 415, 440, 469 | 438.5 | 415..469 | |
    | `b` | 418, 409, 424, 418 | 418.0 | 409..424 | -4.7% |
    | `f` | 406, 401, 442, 431 | 418.5 | 401..442 | -4.6% |
    | `e` | 323, 336, 314, 319 | 321.0 | 314..336 | -26.8% |
    | `g` | 390, 374, 414, 457 | 402.0 | 374..457 | -8.3% |

    Only `e` resolves (its maximum, 336, is under `base`'s minimum, 415); the ranges of `b`, `f` and `g` overlap `base`'s.
  - Memory on lavapipe Span A, rss in MiB at each stage, this build:

    | Variant | Scene built | Renderer opened | World mesh released | Frames rendered | Rise, released to rendered | Peak |
    |---|---|---|---|---|---|---|
    | `base` | 295.5 | 758.5 | 491.6 | 663.8 | 172.2 | 902.0 |
    | `b` | 295.4 | 758.6 | 490.9 | 663.6 | 172.7 | 902.0 |
    | `f` | 295.3 | 758.5 | 491.9 | 663.4 | 171.5 | 902.0 |
    | `e` | 296.0 | 759.0 | 491.0 | 664.0 | 173.0 | 902.3 |

    The earlier build's run, in the same stage order then the rise and the peak: `base` 305.8, 766.0, 498.9, 670.6, 171.7, 909.5; `b` 295.1, 758.0, 490.1, 663.1, 173.0, 901.4; `f` 295.5, 757.8, 491.1, 662.4, 171.3, 901.3; `e` 295.3, 757.8, 489.7, 661.7, 172.0, 901.2.
    The rise is 171.3 to 173.0 MiB in all eight runs, whichever world draws run, against step 3's 172.6 MiB (18.1 MiB with the world not uploaded).
    The earlier `base` run's `scene built` and peak are 10 and 8 MiB above the others'; this entry does not explain that.
  - The same Span A runs' loop ms, earlier build then this one: `base` 837 and 846, `b` 782 and 795, `f` 819 and 849, `e` 720 and 725.
- **Verdict**: control.
  On lavapipe Span B, the span step 1 cut 70.7%:
  - Pixels are not the main part.
    The 1-pixel scissor keeps every draw, pipeline switch and vertex fetch and removes nearly all fragment work, and it recovers `280 ms` of the `1,734 ms` that `e` saves (16.1%); `1,454 ms` of the saving is left with the pixels gone.
  - Base outlines are not the main part: `b` takes `264 ms` (-11.1%), as #622 found (11.2% to 12.2%), and `a`'s base fills do not resolve.
  - The decal slices' fill-and-outline alternation is the main part.
    `c` and `d` each cut about `1,000 ms` (-42.9% and -47.4%) though the decals carry a third of the two kinds' indices (a median 2,391 of 7,161), and they are not additive: `1,020.5 + 1,126.5` exceeds `e`'s `1,734.0`, as it would if skipping either removes the alternation of the two decal pipelines.
    `g` keeps every draw and every pixel and only groups the decal fills and outlines: `-955 ms` (-40.2%), 55.1% of `e`'s saving and within about 100 ms of `c`'s and `d`'s.
    The remaining `779 ms` of `e`'s saving is draw cost that grouping does not remove, to which the pixels contribute up to the `280 ms` that `f` recovers (the two probes need not add); the base draws' own overhead is part of it, not separated.
    The mechanism inside lavapipe (a state or binning flush at each switch) is not examined.
  - The mix differs by span: on the whole film `b` takes -23.1%, `f` -26.1% and `g` only -7.7%, so there the outlines and pixels weigh more and the decal alternation less (2 rounds).
  - On the RTX 4070 only `e` (-26.8%) resolves from the noise.
  - The memory rise does not follow the world's base or decal draws: skipping all four, the outlines or the fragments leaves it at 171.3 to 173.0 MiB.
    It follows the world's upload (18.1 MiB without it, step 3) and something that runs with it in every variant, the ground draws or the walk; which of them, or whether lavapipe maps the buffer lazily, is not tested here.
  - `g` changes the picture where decals overlap, so it names a cost, not a change to adopt.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3 and its Open questions item 1.
