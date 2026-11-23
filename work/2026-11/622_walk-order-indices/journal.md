# Journal: walk-order world base indices (#622)

## 2026-11-22: the median-frame gate after #644 and #914

- **Question**: Can coalescing the world's base draws remove 25% of a median LOCATION frame's `draw_indexed` calls, the gate #622 set when the median frame held 127,910 calls?
- **Method**: Arithmetic on the per-category draw counts already recorded, no new run: the #918 CPU scan on `6955e159` and #931's rescan on `682f74c` after #914 ([`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 2).
- **Result**: On Span A (`LOCATION 12..=300`, the issue's range) the median frame holds 191 draws after #914, 29 of them world draws, so removing every world draw would save at most 15%.
  Over the whole LOCATION film the median frame held base fill and outline draws `80 + 75 = 155` of 648 before #914 (24%); #914 left the world draws unchanged and cut the others, and the whole film's median total after it is not recorded.
  Span B (`LOCATION 3680..=3979`, the elevated overview) is dominated by base draws: `596 + 595 = 1,191` of 1,989 (60%).
  The issue's ground and decal `set_pipeline` switches (about 29k a frame) were counted before the cull; those loops now draw medians of `23 + 13` ground and `12 + 12` decal slices over the whole film.
- **Verdict**: rejected as a gate: no count can pass it on Span A, the issue's range, and a median frame's share of draws says little about render time, which sums over frames; the next entry measures the loop instead.
- **Lives in**: not yet; `research/parity/lavapipe-render-time.md` takes it with the implementation.

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
  Skipping was faster in all eight pairs, and the gap (about 290 ms) exceeds the spread of each variant's four fastest runs (about 100 ms).
  Whole-process wall clock fell 7.6% / 6.8% / 8.2% (drawn 4150 / 4205.5 / 4333.5 ms, skipped 3835 / 3920.5 / 3979.5 ms).
  The skipped draws were not counted per frame; 595 is the recorded median.
- **Verdict**: control, above the 5% bar the owner set, so #622 goes on, gated on loop time.
  The figure bounds the saving from above three ways: it removes draws a walk-order layout would only merge where visible nodes are walk-neighbours, it removes their pixels and a `set_pipeline` per model too, and it holds on Span B, 300 of LOCATION's 8,251 ticks.
- **Lives in**: not yet; `research/parity/lavapipe-render-time.md` takes it with the implementation.

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
  - Span B is bimodal: ticks 3680 to 3814 hold 27 to 272 base draws, and ticks 3815 to 3979 about 590 to 612 fills and as many edges (986 merged a frame by median).
  - Base fill plus edge indices per frame, for a compacted per-frame index buffer instead: Span A median 432, Span B median 10,066 (mean 10,893, max 138,644), the whole film median 2,066 (mean 11,631, p95 90,386, max 174,410); the outliers are frames that draw the `WORLD_BASE` node's large slice.
- **Verdict**: adopted for implementation: `960 / 595 × 11.5% = 18.6%` of Span B's loop, and edges alone `480 / 595 × 11.5% = 9.3%`, both above the 5% gate.
  Both are upper bounds: the 11.5% came from skipping outline draws with their pixels and a `set_pipeline`, which merging keeps, and fills, which cover more pixels, likely spend a smaller share of their time on per-draw overhead than outlines do.
  The gain falls on Span B's second half (about 165 frames) and on similar overview frames; Span A gains 8 draws a frame.
- **Lives in**: not yet; `research/parity/lavapipe-render-time.md` takes the count and the timed result with the implementation.
