# Render-time profile after `#914`

Probe: [`probe.patch`](probe.patch), `#918`'s [`probe.patch`](../918_lavapipe-render-time/probe.patch) carried onto `main` commit `7845a3c` (`crates` tree unchanged at `682f74c`), applied with `git apply`.
`DBG_PROBE_CULL_VIEW_FACING` no longer switches anything, since the landed cull always runs (`PROBE_SUMMARY` still prints `cull_vf=0`), and the CPU scan culls through `GpuModel::in_frustum` as `SceneRenderer::prepare` does.
The Windows runs used the patch as of `682f74c`; the current file adds only `DBG_PROBE_ROW_COPY`, off unless set.
Spans and command shape: as in [`#918`'s journal](../918_lavapipe-render-time/journal.md#environments-and-fixed-geometry): Span A `LOCATION 12..=300`, Span B `LOCATION 3680..=3979`, Span C `INTRO 2500..=2949`, headless `320x200`, `--viewport-rows 185`.

## Environments

- **Windows lavapipe and RTX 4070.**
  The laptop of `#918` (AMD Ryzen 7 7745HX, 16 logical processors, Windows 11 build 26300, on AC), `rustc 1.100.0`, mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`, `VK_DRIVER_FILES` set and `--software-only`) and `NVIDIA GeForce RTX 4070 Laptop GPU`, driver 610.88.
  Three binaries: `682f74c` unpatched (control), `682f74c` + this probe (post-`#914`), and `6955e159` + `#918`'s probe applied with `--unidiff-zero` (pre-`#914`).
  Runs went one at a time; raw stdout and stores are in the data root under `scratch/931/`.
- **Ubuntu lavapipe.**
  A cloud session (4 vCPUs, 15 GiB), Ubuntu 24.04 `mesa-vulkan-drivers` 25.2.8 (`llvmpipe (LLVM 20.1.2, 256 bits)`), `--software-only`.
  Raw `PROBE_*` lines: [`cloud-probe-lines.txt`](cloud-probe-lines.txt).

---

## 2026-11-22: Where loop time goes after `#914`

- **Question**: With `#914`'s view-facing cull landed, which phase of the headless loop now costs most on Spans A, B and C, on Windows lavapipe and the RTX 4070, and which of `#926` (view-facing instancing), caching `collect_world_meshes`, and reusing `readback_copy`'s CPU `Vec` would save most?
- **Method**: On Windows, one unpatched control run per span per adapter, then three `DBG_PROBE_REPORT=1` runs per span per adapter of the post-`#914` probe, and three per span of the pre-`#914` probe on lavapipe only.
  On Ubuntu, one control run and three probe runs per span.
  Each probe run's `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` were hashed against its span and adapter's control.
- **Result**: Every probe run on every adapter matched its control's four SHA-256 digests, and the pre-`#914` probe's lavapipe stores matched the post-`#914` controls (Windows lavapipe Span A: `frames.zst` `7c6aa0d1584be8c6…`, the Span A digests `#918` recorded on WSL 2).
  `#918`'s raw probe logs were not kept (no `PROBE_PHASES` line anywhere under the checkout's `build/scratch` or the data root), so the pre-`#914` cells below re-measure `#918`'s baseline.

### Loop and whole-process wall (ms, 3 runs each)

| Cell | Span | Loop runs | Loop median | End-to-end runs | End-to-end median |
|---|---|---|---|---|---|
| Windows lavapipe, pre-`#914` | A | `6178.2, 6335.0, 6157.4` | `6178.2` | `7579.5, 7727.9, 7547.0` | `7579.5` |
| Windows lavapipe, post-`#914` | A | `1240.3, 1343.9, 1292.8` | `1292.8` (`-79.1%`) | `2617.7, 2730.4, 2676.8` | `2676.8` |
| RTX 4070, post-`#914` | A | `846.8, 852.4, 909.3` | `852.4` | `2494.1, 2434.5, 2479.0` | `2479.0` |
| Ubuntu lavapipe, post-`#914` | A | `2107.9, 1924.5, 1971.9` | `1971.9` | `4574.0, 4781.5, 4422.6` | `4574.0` |
| Windows lavapipe, pre-`#914` | B | `5011.7, 4974.3, 4922.3` | `4974.3` | `6413.2, 6370.1, 6315.3` | `6370.1` |
| Windows lavapipe, post-`#914` | B | `2467.4, 2430.1, 2481.0` | `2467.4` (`-50.4%`) | `3876.1, 3847.0, 3872.2` | `3872.2` |
| RTX 4070, post-`#914` | B | `819.6, 866.7, 863.8` | `863.8` | `2382.5, 2438.7, 2467.6` | `2438.7` |
| Ubuntu lavapipe, post-`#914` | B | `3898.9, 3891.0, 3884.3` | `3891.0` | `6453.9, 6721.5, 6420.2` | `6453.9` |
| Windows lavapipe, pre-`#914` | C | `8634.2, 8717.9, 8731.2` | `8717.9` | `9046.5, 9129.3, 9141.9` | `9129.3` |
| Windows lavapipe, post-`#914` | C | `2079.0, 2089.6, 2115.6` | `2089.6` (`-76.0%`) | `2483.5, 2503.8, 2528.2` | `2503.8` |
| RTX 4070, post-`#914` | C | `1525.4, 1465.9, 1499.2` | `1499.2` | `2083.0, 2028.3, 2071.6` | `2071.6` |
| Ubuntu lavapipe, post-`#914` | C | `3311.0, 3074.4, 3225.7` | `3225.7` | `3923.1, 3723.7, 4023.2` | `3923.1` |

`#918`'s unculled RTX 4070 loop medians were `1299.8`, `1047.1` and `2588.7` ms, so the GPU's loop fell `34.4%`, `17.5%` and `42.1%`.

### Phase medians after `#914` (ms, share of the loop median)

| Phase | Win lvp A | Win lvp B | Win lvp C | RTX A | RTX B | RTX C | Ubuntu lvp A | Ubuntu lvp B | Ubuntu lvp C |
|---|---|---|---|---|---|---|---|---|---|
| `pass_encode_submit` | `423.1` (32.7%) | `1330.6` (53.9%) | `476.1` (22.8%) | `25.1` (2.9%) | `98.8` (11.4%) | `51.6` (3.4%) | `353.1` (17.9%) | `1658.7` (42.6%) | `308.2` (9.6%) |
| `scene_frame` | `392.4` (30.4%) | `486.5` (19.7%) | `534.3` (25.6%) | `333.4` (39.1%) | `269.0` (31.1%) | `418.1` (27.9%) | `741.9` (37.6%) | `1028.2` (26.4%) | `869.6` (27.0%) |
| `readback_copy` | `267.3` (20.7%) | `425.4` (17.2%) | `456.2` (21.8%) | `270.7` (31.8%) | `256.2` (29.7%) | `398.7` (26.6%) | `457.4` (23.2%) | `661.1` (17.0%) | `757.7` (23.5%) |
| `journal_write` | `102.7` | `119.0` | `161.3` | `88.6` | `105.8` | `143.1` | `210.2` | `307.2` | `292.6` |
| `prepare_total` | `100.7` | `98.0` | `452.3` | `99.3` | `85.0` | `449.3` | `195.0` | `223.1` | `936.5` |
| `prepare_relight_decode` | `62.3` | `45.4` | `350.9` (16.8%) | `60.0` | `43.3` | `343.6` (22.9%) | `114.2` | `100.8` | `713.4` (22.1%) |
| `prepare_world` | `4.3` (0.3%) | `26.7` (1.1%) | `6.3` (0.3%) | `3.3` (0.4%) | `18.4` (2.1%) | `5.0` (0.3%) | `8.4` (0.4%) | `61.4` (1.6%) | `13.6` (0.4%) |
| `prepare_view_facing` | `20.8` (1.6%) | `10.3` (0.4%) | `44.2` (2.1%) | `20.3` | `9.6` | `43.0` | `40.8` | `22.2` | `88.7` |
| `scene_draw` | `2.1` | `26.9` | `5.3` | `2.2` | `13.1` | `4.6` | `4.4` | `33.7` | `12.4` |

(Ubuntu figures are from [`cloud-probe-lines.txt`](cloud-probe-lines.txt); its runs vary more, `9.5%` loop spread on Span A against `#918`'s `0.6%..4.9%` on Windows.)

### The four `#918` figures its note quoted but its journal did not hold

| Figure | `#918`'s note | Re-measured here (Windows lavapipe, pre-`#914` probe, per-run values) |
|---|---|---|
| Baseline `pass_encode_submit`, share of loop | `74.2%..79.5%`, `3,752.2..6,647.5 ms` | A `4888.8, 5028.2, 4876.2` (median `4888.8`, `79.1%`); B `3727.2, 3667.8, 3629.3` (median `3667.8`, `73.7%`); C `6488.5, 6571.2, 6606.6` (median `6571.2`, `75.4%`) |
| Post-`#914` `pass_encode_submit` share | `34.5%` A, `53.8%` B, `22.9%` C | `32.7%` A, `53.9%` B, `22.8%` C (table above) |
| `LOCATION` world and shape upload in `open` | `451..460 ms` | `scene_upload_ms` A `455.98, 465.62, 463.28`; B `470.61, 466.62, 459.51` (all six `455.98..470.61`); post-`#914` A `454.20..463.43`, B `456.75..466.74` |
| p95 `view_facing` (`LOCATION` `2,782.5`, `INTRO` `8,320`) and `WORLD_REACH` frustum p95 (`122.5`) | as quoted | reproduced exactly by the next entry's scan |

- **Verdict**: After `#914`, the world block of `prepare` (`prepare_world`, whose main call is `collect_world_meshes`; the timer also covers its matrices, uniform and draw push) costs at most `0.3%..2.1%` of the loop on every adapter and span, and view-facing preparation `0.4%..2.9%`, while `readback_copy` costs `17.2%..21.8%` on Windows lavapipe and `26.6%..31.8%` on the RTX 4070.
  Of the three candidates, `readback_copy` is the only one worth taking (the next two entries say why `#926` saves nothing and what the copy costs).
  `scene_frame` (`FilmScene::frame`, `19.7%..39.1%`) is now comparable to the GPU submit on lavapipe's Spans A and C and the largest phase on the RTX 4070, though none of the three candidates touches it.
- **Lives in**: [`lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes).

---

## 2026-11-22: View-facing draws left after `#914`

- **Question**: How many view-facing draws survive `#914`'s cull, across both whole films and on `#926`'s forested `INTRO 2500..=2799`, and do `#918`'s whole-film p95 figures reproduce?
- **Method**: Ran `DBG_PROBE_CPU_SCAN_FILE` over `LOCATION 12..=8262` and `INTRO 12..=3818` on the Ubuntu cloud session, once with `6955e159` + `#918`'s probe (pre-`#914`) and once with this probe (post-`#914`); p95 is linear interpolation between the closest ranks.
- **Result**:

| Film / span | Pre-`#914` `view_facing` med / mean / p95 / max | Post-`#914` `view_facing` med / mean / p95 / max | Pre / post `total` med / max |
|---|---|---|---|
| `LOCATION` whole (8,251) | `33 / 727.2 / 2,782.5 / 4,071` | `0 / 9.2 / 42 / 245` | `648 / 4,272` -> `394 / 2,123` |
| `INTRO` whole (3,807) | `1 / 1,587.8 / 8,320 / 8,627` | `0 / 23.7 / 188 / 237` | `435 / 9,124` -> `418 / 726` |
| Span A | `2,411` every frame | `0` every frame | `2,602 / 2,711` -> `191 / 300` |
| Span B | `627.5 / 1,120.7 / — / 3,138` | `0 / 0.3 / — / 10` | `2,555 / 3,490` -> `1,989 / 2,123` |
| Span C | `4,712 / 4,108.8 / — / 8,421` | `0` every frame | `5,219 / 8,919` -> `480 / 514` |
| `INTRO 2500..=2799` | `8,000 / 6,163.2 / — / 8,421` | `0` every frame | `8,324.5 / 8,919` -> `505 / 514` |

  `WORLD_REACH` frustum survivors on `LOCATION` are unchanged by `#914` (median `5`, mean `20.6`, p95 `122.5`, max `214`), as are the world draws (`229 / 1,033 / 1,962` med / p95 / max).
- **Verdict**: The forested `INTRO` shot `#926` names keeps no view-facing draw after `#914`, and no frame of either film keeps more than `245`, so instancing has nothing to batch there (no survivor on the forested span, at most `10` on Span B); view-facing preparation now costs `0.4%..2.9%` of the loop.
- **Lives in**: [`lavapipe-render-time.md` § 2](../../../research/parity/lavapipe-render-time.md#2-draws-by-category-after-644-and-811) and § 3.

---

## 2026-11-22: What `readback_copy` spends its time on

- **Question**: Is `readback_copy`'s cost the CPU `Vec` it allocates each frame, or the copy itself?
- **Method**: `read_back` builds each plane's bytes with `chunks_exact(padded_row_bytes).flat_map(|row| row.iter().take(row_bytes)).copied().collect()`, a byte-at-a-time iterator.
  `DBG_PROBE_ROW_COPY=1` (in [`probe.patch`](probe.patch)) instead reserves the `Vec` once per call and appends each row with `extend_from_slice`, still allocating per frame.
  Ran it three times on Spans A and C on the Ubuntu cloud session.
- **Result**: Stores stayed byte-identical to the control.
  `readback_copy` fell from a median `457.4` to `68.9` ms on Span A (`-84.9%`; runs `68.9, 60.9, 72.2`) and from `757.7` to `113.2` ms on Span C (`-85.1%`; runs `113.4, 104.9, 113.2`).
  The loop median fell from `1971.9` to `1908.7` ms on Span A (`-3.2%`; runs `1908.7, 1902.8, 2113.9`) and from `3225.7` to `2864.1` ms on Span C (`-11.2%`; runs `3134.6, 2864.1, 2851.9`).
- **Verdict**: On Ubuntu lavapipe the copy, not the allocation, is most of `readback_copy` (whose timer also covers `get_mapped_range` and the unmap): a row-wise copy that keeps the per-frame `Vec` removes about 85% of it, so the change to make is the copy (with `Vec` reuse optional on top), not `Vec` reuse alone.
  The loop medians moved `-3.2%` (Span A, inside its `9.5%` run-to-run spread, one row-copy run slower than every probe run) and `-11.2%` (Span C), so the phase saving did not all reach the loop: on Span A `scene_frame` (`714..803` to `953..1152 ms`) and `journal_write` (`204..216` to `252..259 ms`) rose while `queue_submit` held, and on Span C `queue_submit` (`281..351` to `415..477 ms`) and `scene_frame` rose; neither is explained, and none of it was measured on Windows or the RTX 4070.
- **Lives in**: [`lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes) and § 6.
