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
