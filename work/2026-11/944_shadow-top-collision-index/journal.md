# Walking only the collision-bearing records in `shadow_top`

Issue: `#944`, filed from [`#934`](../934_filmscene-frame-cost/journal.md).
Probe: [`#934`'s `probe.patch`](../934_filmscene-frame-cost/probe.patch), applied with `git apply` to each probe binary below and never committed under `crates/`.

## Environment

- **Windows lavapipe and RTX 4070.**
  The laptop of `#934` (AMD Ryzen 7 7745HX, 16 logical processors, Windows 11 build 26300), `rustc 1.100.0`, mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`, `VK_DRIVER_FILES` set and `--software-only`) and `NVIDIA GeForce RTX 4070 Laptop GPU`.
  Spans A (`LOCATION 12..=300`), B (`LOCATION 3680..=3979`) and C (`INTRO 2500..=2949`) and the command shape are those of [`#934`'s journal](../934_filmscene-frame-cost/journal.md).
- **Binaries.**
  Four `cargo build --release --locked -p stunt-cli` builds: `base` (`origin/main` `7488642e`, SHA-256 `8a8d1ee2…`), `head` (`7488642e` plus the change, `b93d3bef…`), and `basep` and `headp` (each of those plus `probe.patch`, `8edff649…` and `11691d77…`).
  Two commits have landed on `origin/main` since: `a00d17a0` (`#819`, the order of actors against a placed sprite, which repins the GPU expected scores) and `b87b3625` (`#942`, the view-facing collection in `FilmScene::frame`).
  The stores, the parity run and the timing below were measured on `7488642e`, not re-run on the head `#944` now sits on; neither commit changes `placed.rs` or `probe.rs`, and neither changes `FilmScene::shadow_top`, but both change `film.rs`, so the `scene_frame` and loop figures do not include them.
- **Load.**
  Other agents built, rendered and tested on the same machine throughout.
  Each run waited for `Win32_Processor.LoadPercentage` to fall under 25% for up to 120 s, and every run started at `2..22%`.
  Raw stdout, stores and `runs.log` (start load, wall time, adapter and the four store digests per run) are in the data root under `scratch/944/`.

---

## 2026-11-22: Index the placement records that carry a collision list

- **Question**: Does building, once with `PlacementRecords`, the indices of the non-stand-in records that have a collision list (`PlacementRecords::collision_bearing`, built on first use) and walking only those in `shadow_top` return the same box top and cut the time in `shadow_top`?
- **Method**: `12` control runs (`base` then `head`, once per span and adapter) and `108` probe runs: `9` rounds, each running `basep` and `headp` back to back on every span and adapter, in alternating order by round, so each pair shares its load.
  `shadow_top` is the probe's `shadow_top_ns` timer around `FilmScene::shadow_top`, which includes building the index on its first call.
  Each run's `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` were hashed.
  `mise run parity` then ran over the seven reference films on `head` and on `base` (`--no-build`, with `base`'s binary copied over `target/release/stuntreel.exe`) on each adapter, and the `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` of each render were hashed together.
- **Result**:
  - Stores: the `20` runs of each of the six span-and-adapter cells (`base`, `head`, nine `basep` and nine `headp`) share one set of four digests, `120` of `120` runs with `rc=0`.
  - Scores: `mise run parity` prints the same summary line for `head` and for `base` on all seven films on both adapters, and each of the `14` renders has the same store digest on both.
    `mise run parity`'s lines, the same for `head` and `base` (GPU, then lavapipe; the intro, land and location lines differ in the last digit between adapters):

    ctry  ssim 0.9376  iou 0.9955  idx 0.961  scored 114/121
    intro ssim 0.8824  iou 0.9879  idx 0.917  scored 209/347
    land  ssim 0.9237  iou 0.9869  idx 0.946  scored 97/103
    balloon ssim 0.9059  iou 0.9504  idx 0.911  scored 107/108
    traintnl ssim 0.9103  iou 0.9716  idx 0.948  scored 112/112
    bomb  ssim 0.8945  iou 0.9660  idx 0.929  scored 316/339
    location ssim 0.8721  iou 0.9820  idx 0.906  scored 732/745

    ctry  ssim 0.9376  iou 0.9955  idx 0.961  scored 114/121
    intro ssim 0.8823  iou 0.9879  idx 0.917  scored 209/347
    land  ssim 0.9236  iou 0.9869  idx 0.946  scored 97/103
    balloon ssim 0.9059  iou 0.9504  idx 0.911  scored 107/108
    traintnl ssim 0.9103  iou 0.9716  idx 0.948  scored 112/112
    bomb  ssim 0.8945  iou 0.9660  idx 0.929  scored 316/339
    location ssim 0.8722  iou 0.9820  idx 0.906  scored 732/745

  On the RTX 4070 `head`'s deltas to the pinned expected lines are `0.0000000` on all seven (the pins are marked not comparable: they were measured on another `crates/` tree).
  - Timing, median `[min..max]` of `9` runs in ms; "rounds head < base" counts the back-to-back pairs in which `headp`'s `shadow_top` was lower:

| Cell | `shadow_top` base | `shadow_top` head | change of medians | rounds head < base | `scene_frame` base | `scene_frame` head | loop base | loop head |
|---|---|---|---|---|---|---|---|---|
| A lavapipe | 28.9 [25.5..39.5] | 19.7 [17.3..67.5] | -9.2 ms (-31.8%) | 7 of 9 | 419.9 [392.2..584.3] | 396.2 [366.1..915.1] | 1095.6 [1048.1..1346.1] | 1071.6 [1021.7..2083.1] |
| A RTX 4070 | 24.5 [21.6..33.6] | 16.2 [14.8..26.5] | -8.3 ms (-33.8%) | 9 of 9 | 337.5 [309.4..482.8] | 316.9 [297.3..413.7] | 601.2 [560.4..789.8] | 579.2 [548.1..707.9] |
| B lavapipe | 40.8 [39.9..56.0] | 37.8 [33.9..84.6] | -3.0 ms (-7.4%) | 8 of 9 | 496.1 [467.9..693.8] | 476.4 [442.5..991.3] | 2471.6 [2368.3..2933.5] | 2446.2 [2327.5..4549.9] |
| B RTX 4070 | 26.2 [22.9..42.1] | 17.3 [15.5..29.7] | -8.9 ms (-33.8%) | 9 of 9 | 269.6 [254.0..514.8] | 248.5 [234.3..368.9] | 600.7 [572.1..943.5] | 579.5 [552.2..748.2] |
| C lavapipe | 91.5 [89.2..99.8] | 74.1 [71.1..97.4] | -17.5 ms (-19.1%) | 9 of 9 | 550.5 [531.1..770.1] | 493.6 [470.3..745.6] | 1763.3 [1739.0..2124.0] | 1712.2 [1687.3..2141.1] |
| C RTX 4070 | 87.2 [83.6..97.5] | 67.0 [65.2..88.2] | -20.3 ms (-23.2%) | 9 of 9 | 412.6 [401.5..489.2] | 389.4 [384.4..610.8] | 1121.5 [1093.6..1265.2] | 1105.2 [1087.4..1445.1] |

  `shadow_top` fell by `3.0..20.3 ms` at the median (`7.4%..33.8%`), and `headp` was lower in `7` to `9` of the `9` pairs of each cell, but the base and head ranges overlap in every cell (`headp` has runs at `67.5` and `84.6 ms` on lavapipe Spans A and B, under other agents' load), so the pairs, not the ranges, carry the result; Span B on lavapipe (`-3.0 ms`, `8` of `9`) is the smallest and the least certain.
  The `scene_frame` and loop medians are also lower in every cell, but by more than the `shadow_top` saving in most (for example Span C on lavapipe: loop `-51.1 ms`, `shadow_top` `-17.5 ms`) and inside `basep`'s run range in `8` of the `12` cell-and-metric pairs (six cells, `scene_frame` and loop), so the change is not claimed to speed up the loop; the rest is unexplained.
- **Verdict**: `shadow_top`'s result is unchanged (stores and scores identical in `14` of `14` renders), and its median time falls by `19.1%..33.8%` on Spans A and C and on the RTX 4070's Span B, `7.4%` on lavapipe's Span B.
  It still takes `16.2..74.1 ms` a span at the median; the median fall puts the visits to the other `52,500` (`LOCATION`) or `23,407` (`INTRO`) records at roughly `7%..34%` of it, and the remaining time was not split between the walks of the `4,085` or `2,979` records that carry a list and anything else the timer covers (building the index on the first call, `Probe::new`, the timer).
  A further cut has to skip walks (for example a bounding test per record before `Probe::new`), which this change does not do.
- **Lives in**: [`lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes) and § 6.
