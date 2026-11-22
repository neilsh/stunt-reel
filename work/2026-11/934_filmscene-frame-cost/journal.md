# Where `FilmScene::frame` spends its time

Probe: [`probe.patch`](probe.patch), applied with `git apply` on `origin/main` `9ccfd39c`.
It times the headless loop and each `FilmScene::frame` call, splits `frame` into sub-timers with counters (`frame_probe` in `film.rs`), and prints them on a `PROBE934` line when `DBG_PROBE_REPORT` is set.
`DBG_PROBE_VF_SPLIT=1` collects the view-facing props in three timed passes and `DBG_PROBE_VF_FAST=1` through a prototype of a cheaper path; neither changes what a frame holds.
Spans and command shape: as in [`#918`'s journal](../918_lavapipe-render-time/journal.md#environments-and-fixed-geometry): Span A `LOCATION 12..=300`, Span B `LOCATION 3680..=3979`, Span C `INTRO 2500..=2949`, headless `320x200`, `--viewport-rows 185`.

## Environment

- **Windows lavapipe and RTX 4070.**
  The laptop of `#918` and `#931` (AMD Ryzen 7 7745HX, 16 logical processors, Windows 11 build 26300), `rustc 1.100.0`, mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`, `VK_DRIVER_FILES` set and `--software-only`) and `NVIDIA GeForce RTX 4070 Laptop GPU`, driver 610.88.
  Two binaries from `9ccfd39c` (`cargo build --release --locked -p stunt-cli`, no warnings): unpatched (control, `8f016e40…`) and patched; the patched binary of the first two entries (`bafbe4a5…`) lacked only `DBG_PROBE_VF_FAST`, which the third entry's (`36e54113…`) adds.
- **Load.**
  Other agents built and tested on the same machine throughout.
  Each run waited for the CPU load (`Win32_Processor.LoadPercentage`) to drop under 25% for up to 120 s; every run started at `6..24%` except `fast_B_lvp_r2`, which started at `67%` once the wait ran out.
  Loop medians are `21.5%..31.1%` above `#931`'s on the same spans and adapters, so the figures below are compared within this series, not with `#931`'s.
  Raw stdout, stores and `runs.log` (start load, wall time and the four store digests per run) are in the data root under `scratch/934/`.
- **Ubuntu lavapipe.**
  Not measured: this run had no cloud session.

---

## 2026-11-22: Where `FilmScene::frame` spends its time

- **Question**: Which part of `FilmScene::frame` (`scene_frame`, `19.7%..39.1%` of the loop in `#931`) costs most on Spans A, B and C: timeline sampling, the per-actor work (matrices, light, shadow, angle bank), the `view_facing` collection, or the rest?
- **Method**: One control run per span and adapter, then three `DBG_PROBE_REPORT=1` runs per span and adapter; each run's `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` were hashed against its span and adapter's control.
  Timers: `sampling` is the three `FilmTimeline::sample` calls (`tick`, and `tick - PREVIOUS_FRAME_TICKS` once in `previous_bank` and again for `previous_actors`); `actors` is the whole per-actor `map`, of which `shadow_top` is `FilmScene::shadow_top`; `view_facing` is the collection of world view-facing props; the rest (origin shape, `sprite_draws`, `credits_at`, `ViewCamera::from_authored`, timer overhead) is `scene_frame` less those three.
- **Result**: Every probe run matched its control's four digests (`18` of `18`); the controls match `#931`'s (Span A lavapipe `frames.zst` `7c6aa0d1584be8c6…`).

### Sub-timers (ms, median `[min..max]` of 3 runs; share of `scene_frame`, then of the loop)

| Cell | Loop | `scene_frame` | Sampling | Actors (all) | of which `shadow_top` | `view_facing` | Rest |
|---|---|---|---|---|---|---|---|
| Win lvp A | `1576.6` [`1464.1..1666.4`] | `535.1` [`474.0..587.5`] (`33.9%` of loop) | `1.4` [`1.4..1.6`] (`0.3%`) | `42.2` [`36.5..45.0`] (`7.9%`, `2.7%`) | `40.8` [`35.3..43.6`] (`7.6%`, `2.6%`) | `490.8` [`435.5..539.9`] (`91.7%`, `31.1%`) | `0.8` [`0.6..1.0`] (`0.1%`) |
| RTX A | `1035.6` [`1022.2..1124.1`] | `514.0` [`489.3..538.6`] (`49.6%`) | `1.2` [`1.2..1.3`] (`0.2%`) | `36.3` [`35.9..39.8`] (`7.1%`, `3.5%`) | `35.2` [`34.9..38.6`] (`6.8%`, `3.4%`) | `476.1` [`451.1..496.7`] (`92.6%`, `46.0%`) | `0.7` [`0.7..0.8`] (`0.1%`) |
| Win lvp B | `3082.3` [`2801.4..3117.5`] | `707.3` [`640.0..708.4`] (`22.9%`) | `2.0` [`1.8..2.1`] (`0.3%`) | `59.0` [`54.0..59.0`] (`8.3%`, `1.9%`) | `57.0` [`52.3..57.1`] (`8.1%`, `1.9%`) | `644.9` [`583.2..646.3`] (`91.2%`, `20.9%`) | `1.2` [`1.0..1.2`] (`0.2%`) |
| RTX B | `1108.6` [`1072.4..1312.5`] | `479.4` [`457.1..590.0`] (`43.2%`) | `1.3` [`1.2..1.7`] (`0.3%`) | `39.7` [`38.6..49.0`] (`8.3%`, `3.6%`) | `38.6` [`37.5..47.5`] (`8.1%`, `3.5%`) | `437.7` [`416.6..538.4`] (`91.3%`, `39.5%`) | `0.7` [`0.6..0.9`] (`0.1%`) |
| Win lvp C | `2691.7` [`2490.9..2872.8`] | `808.4` [`712.3..878.4`] (`30.0%`) | `3.2` [`2.7..3.5`] (`0.4%`) | `131.0` [`117.3..135.5`] (`16.2%`, `4.9%`) | `123.1` [`111.2..128.0`] (`15.2%`, `4.6%`) | `666.0` [`586.0..731.1`] (`82.4%`, `24.7%`) | `8.2` [`6.4..8.3`] (`1.0%`) |
| RTX C | `1965.4` [`1819.8..2180.6`] | `678.1` [`635.9..825.8`] (`34.5%`) | `2.5` [`2.4..3.0`] (`0.4%`) | `108.8` [`100.3..119.4`] (`16.1%`, `5.5%`) | `103.5` [`95.4..113.3`] (`15.3%`, `5.3%`) | `560.5` [`526.8..694.9`] (`82.7%`, `28.5%`) | `6.3` [`6.2..8.5`] (`0.9%`) |

Inside the per-actor `map`, the sub-timers other than `shadow_top` (world matrix, facing, light and distance; finding the previous position; `ground_shadow`'s matrix; `shape.decode()` and the angle bank) sum to at most `5.4 ms` per cell (`0.7%` of `scene_frame`), `ground_shadow` (`0.5..4.6 ms`) the largest, and `Actors (all)` less `shadow_top` is at most `7.9 ms` (`1.0%`, Win lvp C), the rest being the `map`'s own overhead; `sprite_draws` with its `drawn_after` scenery walks took at most `6.8 ms` (`0.8%`, Span C) and under `0.4 ms` on Spans A and B.

### Counts per tick (identical on both adapters)

| Span | Actors in the record / drawn | Shadowed | `shape.decode()` calls | `view_facing` props scanned / kept | Gates tested | `drawn_after` calls |
|---|---|---|---|---|---|---|
| A | `10` / `6` | `1` | `7` | `20,916` / `2,411` | `116,791` | `0` |
| B | `9` / `6` | `1` | `7` | `20,916` / `1,099.1` | `75,994.1` | `0` |
| C | `11.87` / `9.23` | `6.36` | `15.74` | `15,663` / `3,191.4` | `65,606.5` | `0.15` |

The worlds: `LOCATION` has `20,916` view-facing props holding `132,383` gate references (`42,652` distinct gates) over `51` shapes, `56,585` placement records (`4,085` non-stand-in with a collision list) and `238` terrain triangles; `INTRO` has `15,663` props, `98,732` references (`29,419` distinct) over `18` shapes, and `26,386` records (`2,979` with a collision list).
`shape.decode()` is a field read (`SodModelIr::decode` returns `Option<&DecodeRecord>`), not a decode.

- **Verdict**: The `view_facing` collection is `82.4%..92.6%` of `scene_frame` in every cell (`20.9%..46.0%` of the loop) and `shadow_top` `6.8%..15.3%`; timeline sampling (`0.2%..0.4%`), the rest of the per-actor work (at most `1.0%`) and everything else (at most `1.0%`) are not worth optimising.
  `frame` builds draws for `1,099..3,191` view-facing props per tick, nearly all of which `SceneRenderer::prepare`'s `#914` cull then drops (`#931` found none surviving on Spans A and C, at most `10` on Span B), but the cost is the scan of the whole world's props before that: `20,916` on `LOCATION` and `15,663` on `INTRO` per tick.
  `shadow_top` walks the placement records per shadowed actor, up to all of them unless a carry ends the probe, and skips all but the `7%..11%` with a collision list, which is why it scales with the shadowed-actor count (Span C).
- **Lives in**: [`lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes) and § 6.

---

## 2026-11-22: What the `view_facing` collection spends its time on

- **Question**: Within the `view_facing` collection, how much is the `self.shapes` lookup, the gate tests (`lod_gate_holds`) and building the `ActorDraw`s?
- **Method**: `DBG_PROBE_VF_SPLIT=1` runs the collection as three passes (shape lookup into a `Vec`, gate tests over it, then the draws), each timed, with the same output; three runs per span on Windows lavapipe only, since the work is on the CPU and the same on either adapter.
  Each run's stores were hashed against the lavapipe control.
- **Result**: Every run matched its control's digests (`9` of `9`).

| Span | `view_facing` | Shape lookup | Gate tests | Building draws | Loop |
|---|---|---|---|---|---|
| A | `434.7` [`405.5..462.3`] (`90.9%` of `scene_frame`) | `61.6` [`60.9..61.8`] (`12.9%`) | `366.8` [`338.3..394.0`] (`76.7%`, `24.4%` of the loop) | `6.2` [`6.2..6.5`] (`1.3%`) | `1504.5` [`1431.3..1541.2`] |
| B | `479.7` [`459.2..482.9`] (`89.5%`) | `73.1` [`70.6..73.7`] (`13.6%`) | `402.4` [`379.7..402.9`] (`75.1%`, `14.5%`) | `6.4` [`6.1..6.7`] (`1.2%`) | `2778.1` [`2733.5..2824.5`] |
| C | `477.1` [`465.7..559.8`] (`79.8%`) | `77.4` [`76.0..78.9`] (`12.9%`) | `369.6` [`359.1..449.3`] (`61.8%`, `15.9%`) | `31.5` [`28.9..31.5`] (`5.3%`) | `2319.7` [`2264.8..2482.4`] |

  The shape lookup rejects no prop on `stuntreel`'s render path: `FilmScene::drawn_only` keeps every view-facing prop's shape, and the CLI applies it before rendering (`crates/stunt-cli/src/scene/mod.rs`); a scene not passed through `drawn_only` can reject.
  A gate test costs about `10.9..17.7 ns` (Span A: `366.8 ms` over `116,791` tests a tick for `289` ticks; Span B: `402.4 ms` over `75,994` for `300`), and each one recomputes the camera's `lod_lens_words`, forward vector and its length.
- **Verdict**: The gate tests are most of `frame` (`61.8%..76.7%`); the shape lookup is a constant `~13%` that rejects no prop on the render path; building the draws is at most `5.3%`.
- **Lives in**: [`lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes) and § 6.

---

## 2026-11-22: Hoisting the shape lookup and the camera's gate words

- **Question**: How much of the `view_facing` collection goes if the shape lookup happens once per scene and the camera's gate words (`lod_lens_words`, forward vector, length) once per frame, with each gate's arithmetic otherwise unchanged?
- **Method**: `DBG_PROBE_VF_FAST=1` caches the per-prop shape test in a `OnceLock` on first use and inlines `lod_keeps_subtree` and `scale_reach_keeps` against per-frame camera words, keeping their floating-point operations in the same order.
  Three runs per span and adapter, each interleaved with a run of the same binary without the switch (`base`), all hashed against the controls.
- **Result**: Every run matched its control's digests (`36` of `36`).

| Cell | `view_facing` base / fast | Change | `scene_frame` base / fast | Change | Loop base / fast | Change |
|---|---|---|---|---|---|---|
| Win lvp A | `601.0` [`583.3..711.0`] / `386.2` [`377.2..446.6`] | `-35.7%` | `657.9` / `437.0` | `-33.6%` | `1765.2` [`1725.9..1968.7`] / `1497.9` [`1496.3..1724.8`] | `-15.1%` |
| RTX A | `531.0` [`455.2..713.3`] / `456.0` [`448.9..470.5`] | `-14.1%` | `574.2` / `511.2` | `-11.0%` | `1164.0` [`1068.1..1497.6`] / `1172.7` [`1154.0..1200.9`] | `+0.7%` |
| Win lvp B | `669.0` [`666.1..895.1`] / `473.7` [`404.6..550.0`] | `-29.2%` | `739.8` / `546.3` | `-26.2%` | `3188.6` [`3099.8..4458.1`] / `3106.5` [`2796.1..3582.6`] | `-2.6%` |
| RTX B | `414.8` [`396.9..522.8`] / `300.9` [`296.9..383.4`] | `-27.5%` | `459.2` / `347.6` | `-24.3%` | `1121.5` [`1103.9..1264.2`] / `1036.0` [`1005.4..1183.0`] | `-7.6%` |
| Win lvp C | `701.4` [`665.8..749.8`] / `548.6` [`485.3..583.1`] | `-21.8%` | `846.4` / `745.7` | `-11.9%` | `2713.9` [`2693.6..2877.8`] / `2733.0` [`2589.3..2768.6`] | `+0.7%` |
| RTX C | `692.3` [`561.1..715.9`] / `611.0` [`459.2..661.7`] | `-11.7%` | `819.3` / `764.6` | `-6.7%` | `2183.8` [`1957.5..2203.1`] / `2334.9` [`1884.5..2476.6`] | `+6.9%` |

  The `base` runs' `view_facing` medians sit `+3.7%..+22.5%` from the first entry's on lavapipe and `-5.2%..+23.5%` on the RTX 4070, and the run spreads reach `43%` of the median (Win lvp B, `base` loop), so the machine's other work moved these runs more than the first entry's.
- **Verdict**: Hoisting cuts the collection by `11.7%..35.7%` with byte-identical stores, a **go** filed as `#942`, but leaves the gate tests themselves as most of `frame`; the loop medians moved `-15.1%..+6.9%`, Span A's lavapipe loop (`-15.1%`) outside its runs' spread (fast `1,496.3..1,724.8 ms` against base `1,725.9..1,968.7 ms`) and the other five cells inside theirs.
  The larger saving is testing each shared gate once: `LOCATION`'s props hold `132,383` gate references but `42,652` distinct gates, because a prop's `LodBranch` gates are the `SP_1NODE` chain it stands behind and many props share a chain; filed as `#943` (`needs-triage`: where the chain structure lives is a design choice).
  `shadow_top`'s walk over every placement record, `6.8%..15.3%` of `frame`, is filed as `#944`.
- **Lives in**: [`lavapipe-render-time.md` § 6](../../../research/parity/lavapipe-render-time.md#6-optimization-verdicts).
