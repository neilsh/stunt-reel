# Journal: walk-order world base indices (#622)

## 2026-11-22: the median-frame gate after #644 and #914

- **Question**: Can coalescing the world's base draws remove 25% of a median LOCATION frame's `draw_indexed` calls, the gate #622 set when the median frame held 127,910 calls?
- **Method**: Arithmetic on the per-category draw counts already recorded, no new run: the #918 CPU scan on `6955e159` and #931's rescan on `682f74c` after #914 ([`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 2).
- **Result**: On Span A (`LOCATION 12..=300`, the issue's range) the median frame holds 191 draws after #914, 29 of them world draws, so removing every world draw would save at most 15%.
  Over the whole LOCATION film the median frame held base fill and outline draws `80 + 75 = 155` of 648 before #914 (24%); #914 left the world draws unchanged and cut the others, and the whole film's median total after it is not recorded.
  Span B (`LOCATION 3680..=3979`, the elevated overview) is dominated by base draws: `596 + 595 = 1,191` of 1,989 (60%).
  The issue's ground and decal `set_pipeline` switches (about 29k a frame) were counted before the cull; those loops now draw medians of `23 + 13` ground and `12 + 12` decal slices over the whole film.
- **Verdict**: rejected as a gate: no count can pass it on Span A, the issue's range, and a median frame's share of draws says little about render time, which sums over frames; the next entry measures the loop instead.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6, `#622`'s verdict.

## 2026-11-22: skipping Span B's base outlines on lavapipe

- **Question**: How much of Span B's loop time do the world's base outline draws (595 a frame by median) cost on lavapipe?
  Outlines cover few pixels, so their cost is close to their per-draw overhead, an upper bound on what merging base draws could save.
- **Method**:
  - `main` at `5ba6b056`, with two throwaway edits, both reverted: `SceneRenderer`'s world base outline block (`set_pipeline(edge_pipeline)` and `draw_edges`) skipped when `STUNT_PROBE_SKIP_BASE_EDGES` is set (read once), and a loop timer in `headless.rs` around the submit loop through `finish` and the last page write.
  - One release `stuntreel.exe` for both variants, on mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`, `VK_DRIVER_FILES` and `--software-only`) on the owner's laptop (Ryzen 7 7745HX), no other render or build running.
  - `--headless --tick-range 3680..=3979 --width 320 --height 200 --viewport-rows 185` on `corpus/stuntisl/VAULT/LOCATION.FLM` with `captures/vault-location/archives/LOCATION.ALL`, eight runs per variant, strictly interleaved.
  - Sanity: the base variant's four stores are byte-identical between its first and eighth runs; the skip variant's `frames`, `layers` and `shapes` differ from base and its `palettes` match.
- **Result**: Loop ms, minimum / median of the four fastest / median of all eight:

  | Variant | Min | Four fastest | All eight | Max |
  |---|---|---|---|---|
  | Outlines drawn | 2485 | 2547 | 2627 | 2842 |
  | Outlines skipped | 2182 | 2260.5 | 2325 | 2692 |
  | Change | -12.2% | -11.2% | -11.5% | |

  Raw, drawn: 2506, 2485, 2588, 2703, 2842, 2645, 2609, 2645; skipped: 2255, 2182, 2266, 2608, 2692, 2298, 2354, 2352.
  Skipping was faster in all eight pairs, and the gap (about 290 ms) exceeds the spread of each variant's four fastest runs (124 ms drawn, 116 ms skipped).
  Whole-process wall clock fell 7.6% / 6.8% / 8.2% (drawn 4150 / 4205.5 / 4333.5 ms, skipped 3835 / 3920.5 / 3979.5 ms).
  The skipped draws were not counted per frame; 595 is the recorded median.
- **Verdict**: control, above the 5% bar the owner set, so #622 goes on, gated on loop time.
  The figure bounds the saving from above three ways: it removes draws a walk-order layout would only merge where visible nodes are walk-neighbours, it removes their pixels and a `set_pipeline` per model too, and it holds on Span B, 300 of LOCATION's 8,251 ticks.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6, `#622`'s verdict.

## 2026-11-22: base draws a walk-order layout would merge

- **Question**: If the world's base fill indices, and separately its edge indices, were laid out in walk order, how many of each frame's base draws would merge, and does the estimate reach the 5%-of-Span-B's-loop gate?
- **Method**:
  - `main` at `5ba6b056` plus [`merge-count.patch`](merge-count.patch), reverted after the run: a CPU-only scan (no device) that builds the world model's slice metadata, runs the real `collect_world_meshes` per tick with the offscreen camera, and compares each frame's emitted base list with the full ungated walk.
  - `DBG_PROBE_WALK_SCAN_FILE=<out> stuntreel --headless --tick-range <span> --width 320 --height 200 --viewport-rows 185 --sidata <data>/corpus/siarchive/Developer/FreeFlight/SIDATA <data>/builds/patch3/VAULT/LOCATION.FLM <data>/captures/vault-location/archives/LOCATION.ALL`.
  - Rule: emitted ranges i then j merge when j immediately follows i in the fixed walk (for edges, the walk filtered to slices with `edge_count > 0`) and both lie in the same chunk at the same `vertex_offset`; ground and decal passes are excluded.
    The scan keeps today's chunk assignment, which a rebuilt layout could change.
- **Result**:
  - The premise holds: `VisibleWalk::walk` (`crates/stunt-render/src/mesh.rs`) is a pre-order depth-first walk that pushes children in arena order, and the camera only prunes (frustum, LOD branch, facing, depth, reach), so on all 8,251 LOCATION frames every emitted base sequence is a subsequence of one fixed walk (0 out-of-order pairs, fills and edges), and today no emitted pair is adjacent in index order (#603's zero reproduces).
    LOCATION places no sprite, so no frame splits the world base at a placement mark; a film that does would break more runs.
  - Base counts match the recorded medians on the whole film (`80 + 75`) and Span A (`11 + 10`); Span B now draws `585.5 + 584.5` against `596 + 595`, with decals `327 + 327` against `317 + 317` and base plus decal conserved, which fits #969 drawing a flat prop lying on an earlier one as its decal (not confirmed by rebuilding the older commit).
  - Base draws per frame, fills and edges together, median before to after: Span A 21 to 13, Span B 1,170 to 197 (p95 after 289), the whole film 156 to 78.
    Merged draws per frame, median / mean / p95 / max: Span A 8 / 15.7 / 46 / 54, Span B 960 / 589.9 / 1,040 / 1,046 (480 fills and 480 edges at the median), the whole film 75 / 111.6 / 304 / 1,046.
  - Span B is bimodal (recounted from the next entry's scan, which gives the same per-frame counts): ticks 3812 to 3970 (159 frames) hold 582 to 612 fills and about as many edges (1,163 to 1,223 base draws, 1,010 merged a frame by median), and the other 141 frames 27 to 553 base draws.
  - Base fill plus edge indices per frame, for a compacted per-frame index buffer instead: Span A median 432, Span B median 10,066 (mean 10,893, max 138,644), the whole film median 2,066 (mean 11,631, p95 90,386, max 174,410); the outliers are frames that draw the `WORLD_BASE` node's large slice.
- **Verdict**: adopted for implementation: `960 / 595 × 11.5% = 18.6%` of Span B's loop, and edges alone `480 / 595 × 11.5% = 9.3%`, both above the 5% gate.
  Both are upper bounds: the 11.5% came from skipping outline draws with their pixels and a `set_pipeline`, which merging keeps, and fills, which cover more pixels, likely spend a smaller share of their time on per-draw overhead than outlines do.
  The gain falls on Span B's ticks 3812 to 3970 (159 frames) and on similar overview frames; Span A gains 8 draws a frame.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6 and its Ruled out.

## 2026-11-22: the walk-order layout's draws and stores

- **Question**: Does the static walk-order layout, built into the world upload, merge the base draws the CPU count predicted, and does it leave every render store byte-identical?
- **Method**:
  - The layout is [`walk-order-layout.patch`](walk-order-layout.patch) on `main` at `566977a6`, built as commit `f77fd073` (never merged): `GpuModel::from_ir_outlined` copies a one-chunk world's base slices' indices, and separately their outlines, into one buffer in the order `VisibleWalk::walk` visits the nodes with no gate (`lay_out_in_walk_order` in `crates/stunt-render/src/mesh.rs`), then every ground and decal slice in arena order; `draw_slices` and `draw_edges` draw each run of slices that continue one another's range in one chunk at one base vertex with one `draw_indexed` (`for_each_run`).
    `GpuModel::cut` now maps a placement's arena offsets to the moved slice's buffer offsets through its marks.
  - Count: [`run-count.patch`](run-count.patch) on `f77fd073`, reverted after the run, builds the world's layout under the device's 256 MiB buffer limit (asserting one chunk), runs `collect_world_meshes` per tick as `prepare` does, and counts the base fill and outline runs `for_each_run` draws.
    `DBG_PROBE_WALK_SCAN_FILE=<out> stuntreel --headless --tick-range <span> --width 320 --height 200 --viewport-rows 185 --sidata <data>/corpus/siarchive/Developer/FreeFlight/SIDATA <data>/builds/patch3/VAULT/LOCATION.FLM <data>/captures/vault-location/archives/LOCATION.ALL`, over Span A (`12..=300`), Span B (`3680..=3979`) and the whole film (`12..=8262`).
  - Stores: `mise run parity -- --no-build` over the seven reference films with `566977a6`'s release binary, then `f77fd073`'s, each copied over `target/release/stuntreel.exe` (both built by `mise run build-at`), on the RTX 4070 and on mesa-dist-win 25.2.8 (`VK_DRIVER_FILES` and `--software-only`), comparing each film's `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` with `cmp`.
- **Result**:
  - Base draws per frame, fills and outlines together, median before to after: Span A `21` to `13`, Span B `1,170` to `197` (p95 after `289`), the whole film `156` to `78`.
    Merged draws per frame, median / mean / p95 / max: Span A `8 / 15.7 / 46 / 54`, the whole film `75 / 111.6 / 304 / 1,046`; Span B's median is `960` and its mean `589.9`, and its median frame draws `585.5` fills in `99` runs and `584.5` outlines in `98`.
    These are the previous entry's figures, so the layout merges what the fixed walk promised; no frame of the three ranges places a sprite, so no run is cut at a placement.
  - Stores: `28` of `28` files byte-identical between the two binaries on the RTX 4070, and `28` of `28` on lavapipe (`llvmpipe (LLVM 21.1.7, 256 bits)` in every report), with the same summary lines for both binaries on each adapter:

    ```text
    ctry  ssim 0.9385  iou 0.9955  idx 0.961  scored 114/121
    intro ssim 0.8833  iou 0.9879  idx 0.917  scored 209/347
    land  ssim 0.9245  iou 0.9869  idx 0.946  scored 97/103
    balloon ssim 0.9059  iou 0.9504  idx 0.911  scored 107/108
    traintnl ssim 0.9107  iou 0.9716  idx 0.948  scored 112/112
    bomb  ssim 0.8949  iou 0.9660  idx 0.929  scored 316/339
    location ssim 0.8727  iou 0.9820  idx 0.906  scored 732/745
    ```

    On lavapipe the `location` line reads `ssim 0.8728`.
- **Verdict**: control: the layout merges what the count said and changes no pixel; whether it lands is the next entry's timing.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6, `#622`'s verdict.

## 2026-11-22: loop time before and after on lavapipe and the RTX 4070

- **Question**: Does the walk-order layout cut Span B's lavapipe loop by at least the 5% the owner set, and leave Span A no slower?
- **Method**:
  - The patch also joins contiguous slices in every model's `draw_slices` and `draw_edges`, not only the world's base draws; ground and world decal slices are drawn one at a time, so they are unaffected, and the timing measures the whole patch.
  - [`loop-timer.patch`](loop-timer.patch) (an `eprintln!` of the milliseconds from the first submit through `finish` and the last page write in `headless.rs`) applied to `566977a6` (before) and to `f77fd073` (after), each built by `mise run build-at`.
  - `stuntreel --headless <data>/builds/patch3/VAULT/LOCATION.FLM --all <data>/captures/vault-location/archives/LOCATION.ALL --tick-range <span> --sidata <data>/corpus/siarchive/Developer/FreeFlight/SIDATA --out-dir <dir> --width 320 --height 200 --viewport-rows 185`, with `--software-only` and `VK_DRIVER_FILES` for lavapipe (mesa-dist-win 25.2.8), else on the GPU; each round's first run's `render.json` names `llvmpipe (LLVM 21.1.7, 256 bits)` or the `NVIDIA GeForce RTX 4070 Laptop GPU`.
    The owner's laptop (Ryzen 7 7745HX), no other render or build running, other agents' desktop apps open.
  - Eight rounds; each round runs every span and adapter's two variants back to back, before first in even rounds and after first in odd ones.
    Eight more rounds of the two cells nearest a threshold (lavapipe Span B, RTX 4070 Span A) followed straight after.
  - Each run's four stores hashed together.
- **Result**: Loop ms, minimum / median of the four fastest / median of all / maximum, and the change in the first three:

  | Cell | Runs | Before | After | Change |
  |---|---|---|---|---|
  | Lavapipe Span A | 8 | 938 / 974.5 / 994 / 1063 | 933 / 944.5 / 1008 / 1057 | -0.5% / -3.1% / +1.4% |
  | Lavapipe Span B | 16 | 2758 / 2773.5 / 2904 / 3493 | 2626 / 2648 / 2775 / 3071 | -4.8% / -4.5% / -4.4% |
  | RTX 4070 Span A | 16 | 424 / 431.5 / 487.5 / 720 | 434 / 445 / 512 / 620 | +2.4% / +3.1% / +5.0% |
  | RTX 4070 Span B | 8 | 433 / 460 / 483.5 / 695 | 421 / 435.5 / 452 / 610 | -2.8% / -5.3% / -6.5% |

  - Raw, in round order, lavapipe Span B before: 2926, 2856, 2782, 3014, 3414, 2792, 2758, 2791, 3001, 2837, 2906, 2765, 2902, 3493, 2964, 2933; after: 2701, 2812, 2999, 2884, 3071, 2653, 2858, 2679, 2778, 2791, 2643, 2772, 2888, 2701, 2626, 2690.
    After was faster in 13 of 16 pairs; the first eight rounds alone gave `-3.8% / -3.5% / +0.4%`, the second eight `-5.0% / -7.1% / -6.3%`.
  - RTX 4070 Span A before: 440, 547, 427, 720, 605, 443, 424, 436, 637, 438, 517, 472, 549, 641, 494, 481; after: 435, 514, 530, 510, 593, 470, 508, 434, 620, 545, 467, 528, 455, 506, 530, 531.
    After was faster in 9 of 16 pairs, and each variant's runs span about 200 ms.
  - Lavapipe Span A before: 1063, 1040, 974, 1008, 1018, 975, 980, 938; after: 1024, 947, 999, 1057, 1046, 1017, 942, 933 (after faster in 4 of 8).
    RTX 4070 Span B before: 477, 569, 461, 490, 695, 433, 497, 459; after: 441, 456, 585, 610, 550, 448, 421, 430 (after faster in 5 of 8).
  - Whole-process wall clock on lavapipe Span B: before `4416 / 4464 / 4594` ms, after `4358 / 4403 / 4548` (`-1.3% / -1.4% / -1.0%`).
  - Every run exited 0, and within each cell every run of both variants has one store digest.
- **Verdict**: rejected by the owner's 5% gate: Span B's lavapipe loop fell `4.4%..4.8%` over 16 interleaved pairs, about 130 ms, or about 0.4 ms of a frame's 9.2 to 9.7 ms, well under the count's `9.3%..18.6%` bound.
  Merging about 960 draws a frame therefore costs less than the bound assumed, which suggests that most of the 11.5% the outline-skip probe removed was the outlines' pixels and pipeline switch rather than their per-draw cost; this was not measured apart.
  No other cell resolves from its noise: the RTX 4070's Span A reads `2.4%..5.0%` slower with after faster in 9 of 16 pairs and each variant spread over about 200 ms, so it is shown neither slower nor not slower.
  The task said to report and stop under 5% rather than land, so the owner took the decision; the next entry settles it.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6 and its Ruled out, with the next entry's decision.

## 2026-11-22: the whole film, Span A on the RTX 4070, peak memory, and the decision

- **Question**: Under 5%, should the layout land anyway?
  Before measuring, the owner set three bars: the whole `LOCATION` film on lavapipe must be faster in all four interleaved pairs, by a median of at least 1%; 16 more RTX 4070 Span A pairs must show no consistent slowdown; and peak memory must rise by no more than about 10 MB, since the upload holds a second copy of the world's indices (about 30 MB) and outlines (about 51 MB) while it reorders them.
- **Method**:
  - The previous entry's timer binaries and command, at `--tick-range 12..=8262` on lavapipe, four pairs alternating which variant runs first; then 16 more pairs of RTX 4070 Span A the same way.
  - Memory: `566977a6`'s and `f77fd073`'s release binaries with `--report-memory` over Span A, before, after, before, after on each adapter, reading the `memory peak` line and the resident set after `world mesh released`.
  - The machine as before, nothing else rendering or building.
- **Result**:
  - Whole film on lavapipe, loop ms in pair order, before: 30683, 27538, 31274, 32055; after: 26251, 26512, 31589, 31371.
    After was faster in 3 of 4 pairs; minimum `-4.7%`, median `30978.5` to `28941.5` (`-6.6%`); whole-process wall clock before 32470, 29122, 33033, 33746, after 27959, 28125, 33359, 33180 (median `-6.4%`).
    The runs fall in two groups, 26.3 to 27.5 s and 30.7 to 32.1 s, whichever variant ran, so four pairs do not resolve the about 2% the count predicts (Span B's `0.7 µs` saved per merged draw, at the whole film's mean of `111.6` merged draws a frame over `8,251` frames, is about `0.67 s`, `2.1%..2.6%` of these loops); of the pairs whose two runs fell in one group, two favour after (`-3.7%`, `-2.1%`) and one before (`+1.0%`).
    All eight runs share one store digest.
  - RTX 4070 Span A, 16 more pairs, before: 430, 444, 432, 440, 547, 443, 449, 428, 430, 405, 412, 408, 392, 423, 423, 452; after: 435, 439, 452, 422, 477, 495, 439, 416, 436, 430, 436, 392, 461, 560, 424, 565.
    After was faster in 6 of these 16 and in 15 of all 32 pairs; over all 32 the minimum is `392` on both, the median of the four fastest `406.5` to `419` (`+3.1%`, as in the first 16), and the median `441.5` to `468.5` (`+6.1%`).
  - Peak resident set over Span A, before then after: RTX 4070 `741.2` to `809.8` MiB and `697.5` to `773.5` MiB (`+68.6`, `+76.0`); lavapipe `904.1` to `915.6` and `904.8` to `916.2` MiB (`+11.5`, `+11.4`).
    After `world mesh released` the resident set matches within `5.2` MiB on each adapter (RTX 4070 `276.8`/`271.6` and `234.5`/`234.3`, lavapipe `495.1`/`493.4` and `494.5`/`494.3`), so the rise is transient, during the upload; it is attributed to the upload's second copy of the indices and outlines, which was not measured apart, and on lavapipe it is well under the copies' size.
- **Verdict**: rejected: the whole film was faster in 3 of 4 pairs, not 4, and peak memory rose by `11.4..11.5` MiB on lavapipe and `68.6..76.0` MiB on the RTX 4070, both against bars set before measuring.
  The RTX 4070's Span A passed its bar (after faster in 15 of 32 pairs), though its four-fastest median read `+3.1%` in both batches.
  Even the expected 2% or so over the whole film, plus the code to build the outlines in walk order without a second copy, would not justify the layout, so #622 closes as not planned.
  The layout is kept as [`walk-order-layout.patch`](walk-order-layout.patch) on `566977a6`; reviving it needs the copy-free upload first.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6 and its Ruled out.
