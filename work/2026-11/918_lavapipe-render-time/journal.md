# Lavapipe render-time profile after `#644` and `#811`

Design: [`spec.md`](spec.md).
Implementation plan: [`plan.md`](plan.md).
Archived instrumentation diff (applied on `main` commit `6955e159d35cb8634a6ca5d66691a709901f8191`, `crates` tree `90057c0248be1cd2462459bed9e2d953477bdc68`, with `git apply --unidiff-zero`): [`probe.patch`](probe.patch) (`94,685` bytes across 16 tracked files under `crates/`, `+1916/-125` lines, SHA-256 `875776c9a7668b1cf7f0cf79d775fec9b9ee60dbcfa1379401a209d4734e38d7`).
Branch HEAD at handoff shares the identical `crates/` tree (`c50bd5f9d80fbffdda15f1d5404b1638645a73c2:crates` == `90057c0248be1cd2462459bed9e2d953477bdc68`), and `crates/` was reverted cleanly after measurements completed (`git diff -- crates/` empty).

## Environments and fixed geometry

- **Primary Windows (`local-windows`).**
  AMD Ryzen 7 7745HX (8 cores, 16 logical processors), `rustc 1.100.0 (0ef1bc386 2026-11-09)`, Windows `mesa-dist-win 25.2.8` (`llvmpipe (LLVM 21.1.7, 256 bits)`), selected with `VK_DRIVER_FILES=E:\git\stunt-reel.data\tools\mesa-25.2.8\x64\lvp_icd.x86_64.json` and `--software-only`.
- **Hardware GPU baseline.**
  Same Windows laptop (`NVIDIA GeForce RTX 4070 Laptop GPU`) with `VK_DRIVER_FILES` unset and `--software-only` omitted.
- **Secondary Linux (`WSL 2 Ubuntu-24.04`).**
  Canonical `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`) on the same Ryzen 7 7745HX host (`nproc=16`, `getconf CLK_TCK=100`, `rustc 1.100.0 (0ef1bc386 2026-11-09)`), built and run inside `/root/stunt-reel` against `/root/stunt-reel.data` with `--software-only`.
- **Fixed capture command shape.**
  Every timed render invoked `stuntreel --headless --width 320 --height 200 --viewport-rows 185 --sidata <data root>/corpus/siarchive/Developer/FreeFlight/SIDATA` with `builds/patch3/VAULT/LOCATION.FLM` + `captures/vault-location/archives/LOCATION.ALL` or `builds/patch3/VAULT/INTRO.FLM` + `captures/vault-intro/archives/INTRO.ALL` and `--out-dir`.

---

## 2026-11-21: Throwaway probe and zero-drift verification

- **Question**: Does the temporary `DBG_PROBE_*` instrumentation keep headless render stores byte-identical across reporting, `FRAMES_IN_FLIGHT=1`, `#919` plane-only, `#914` `view_facing` frustum culling, and `#915` relight switches?
- **Method**: Built the unpatched `6955e159` binary (`cargo build --release --locked -p stunt-cli`) and captured control stores for `LOCATION` `12..=120` (109 ticks) and `INTRO` `12..=300` (289 ticks) on Windows `mesa-dist-win 25.2.8`.
  Applied the 16-file env-gated probe (`probe.patch`, zero warnings in release build) and ran 11 combinations across `DBG_PROBE_REPORT=1`, `DBG_PROBE_FRAMES_IN_FLIGHT=1`, `DBG_PROBE_PLANE_ONLY=1`, `DBG_PROBE_CULL_VIEW_FACING=1`, `DBG_PROBE_SKIP_APEX_REWRITE=1`, and `DBG_PROBE_RING_LIT=1`.
- **Result**: Each of the 11 variants matched its unpatched control's four `.zst` SHA-256 digests (`frames.zst`, `layers.zst`, `shapes.zst`, `palettes.zst`) on Windows `llvmpipe (LLVM 21.1.7, 256 bits)`:
  - `LOCATION 12..=120` (109 ticks, 5 tested runs: unset, report, `fif=1`, `plane_only`, `cull_vf`):
    - `frames.zst`: `5fe9e30d0468d3c2867aed7a9340eaef3d63724af18fa4f2d2062b135f03ad47`
    - `layers.zst`: `1ee38e4f27fae30ce33a5717cd5f49e526ef1ab29f17c531f64b65b796414c7a`
    - `shapes.zst`: `656a3e89e065303f1c3afbb2543a3c9fb1bcde57c275b9bceaf35df4557b44ae`
    - `palettes.zst`: `42100b14084af937363162b132d73336562c883fc5891c13f556c6fe626fc40`
  - `INTRO 12..=300` (289 ticks, 6 tested runs: report, `plane_only`, `cull_vf`, `skip_apex`, `ring_lit`, `skip_apex+ring_lit`):
    - `frames.zst`: `dcdbce69241514010e5c67c8b803a88d7895974c80c32575c2ae7990331a7874`
    - `layers.zst`: `769320d7adbb1afc06932e863780afdc702df5d77d10ebf954e310594bf94912`
    - `shapes.zst`: `2d4745cc226babc60b4893b68226cf49882318d90c908e7e2c9876264085fe5f`
    - `palettes.zst`: `3da628247552727642ec97d93bbb559a6ea05c7ba8b7689867d3a436353f60a8`
- **Verdict**: Zero-drift probe established; valid for timing and draw-count attribution.
- **Lives in**: this journal and [`probe.patch`](probe.patch).

---

## 2026-11-21: Whole-film draw and relight scans and span selection

- **Question**: Across `LOCATION` (`12..=8262`, 8,251 ticks) and `INTRO` (`12..=3818`, 3,807 ticks), how do `draw_indexed` calls split across categories (`world`, `view_facing`, unlit/relit `actors`, `shadows`, `sprites`) and `#811` `WORLD_REACH` gates, which sustained spans represent wide-island `LOCATION` and relight-heavy `INTRO`, and do CPU-scan counts match live lavapipe?
- **Method**: Ran `DBG_PROBE_CPU_SCAN_FILE` across `LOCATION 12..=8262` and `INTRO 12..=3818` on `6955e159` + `probe.patch`.
  Locked three measurement spans:
  - **Span A (`LOCATION` close-up):** `12..=300` (289 ticks), matching `#644`'s runway close-up (`eye_y` `7.00..7.42` m, median `7.00` m, FOV `22.10` deg).
  - **Span B (`LOCATION` wide-island):** `3680..=3979` (300 ticks, 6 film seconds), chosen after comparing `#918`'s candidate spans `2500..=2900` (`world_total` median `437`, max `1,454`) and `6500..=6800` (`world_total` median `530`, max `830`) against a 50-tick rolling profile; at `3680..=3979` the camera sits at `eye_y` `39.70..125.00` m (median `125.00` m, FOV `42.67..56.97` deg) sweeping across the island so `world_total` reaches `1,803..1,962` draws/frame across `3812..=3970` (`159` of `300` frames).
  - **Span C (`INTRO` relight-heavy):** `2500..=2949` (450 ticks, 9 film seconds), capturing 144 of `INTRO`'s 190 `Refresh::Rewrite` events alongside 466 warm-scan (472 cold-start) `Refresh::Upload`s (`405` of `450` frames mutating relit shapes) plus dense forested `view_facing` draws (`2500..=2799`, up to `8,421` calls/frame; `eye_y` `0.30..500.53` m, median `16.04` m).
  Ran live Windows `mesa-dist-win 25.2.8` with `DBG_PROBE_REPORT=1` and `DBG_PROBE_DRAW_FILE` on Spans A, B, and C and checked frame-by-frame equality across the 14 draw/reach counters.
- **Result**:
  - **World totals (`#811`, from scene build `[stuntreel] world:` logs during the whole-film scans):** `LOCATION` built world holds `158` terrain patches, `56,395` static props (`6,702,570` vertices, `7,488,138` indices), and `31,314` `WORLD_REACH` gated nodes; `INTRO` built world holds `158` terrain patches, `26,386` static props (`819,169` vertices, `1,002,135` indices), and `8,336` `WORLD_REACH` gated nodes.
  - **Live cross-check:** Live lavapipe `DRAWFRAME` counts matched `DBG_PROBE_CPU_SCAN_FILE` on 100% of frames across Spans A (`289`), B (`300`), and C (`450`) and equalled `world_reach_total`.
    Because `SceneRenderer::relight` caches `self.lit` across frames, warm whole-film scan vs cold span start shifted tick 1 cache hits into uploads while preserving `rewrite` and `keep + rewrite + upload`: Span A `(399, 0, 179)` live = `(399, 0, 179)` scan; Span B `(466, 0, 134)` live vs `(467, 0, 133)` scan (`+1` cold upload at tick `3680`); Span C `(3,473, 144, 472)` live vs `(3,479, 144, 466)` scan (`+6` cold uploads at tick `2500`).

### Whole-film and candidate span draw counts (`draw_indexed` calls/frame)

| Span (ticks / frames) | `world_ground` med (max) | `world_base` med (max) | `world_decal` med (max) | `world_total` med / p95 / max | `view_facing` med / mean / max | `actor_unlit` med (max) | `actor_lit` med (max) | `shadow` med (max) | `sprite` med (max) | `total` med / mean / p95 / max | `reach_frustum` -> `reach_kept` med (max) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `LOCATION` whole (`12..=8262`, 8,251) | `23+13` (`287+197`) | `80+75` (`622+621`) | `12+12` (`333+333`) | `229` / `1,033` / `1,962` | `33` / `727.2` / `4,071` | `28` (`65`) | `80` (`93`) | `49` (`62`) | `0` (`0`) | `648` / `1,215.0` / `3,312` / `4,272` | `5` (`214`) -> `5` (`214`) |
| `INTRO` whole (`12..=3818`, 3,807) | `5+3` (`92+76`) | `2+0` (`75+70`) | `0+0` (`12+12`) | `36` / `208` / `259` | `1` / `1,587.8` / `8,627` | `0` (`15`) | `199` (`284`) | `137` (`221`) | `0` (`2`) | `435` / `2,001.3` / `8,823` / `9,124` | `0` (`8`) -> `0` (`8`) |
| `LOCATION 2500..=2900` (401) | `63+43` (`230+154`) | `125+114` (`456+452`) | `25+25` (`81+81`) | `437` / `1,254` / `1,454` | `2` / `11.0` / `99` | `28` (`28`) | `82` (`84`) | `51` (`53`) | `0` (`0`) | `601` / `603.0` / `1,500` / `1,710` | `17` (`176`) -> `17` (`176`) |
| `LOCATION 6500..=6800` (301) | `72+47` (`141+88`) | `146+143` (`289+270`) | `30+30` (`71+71`) | `530` / `748` / `830` | `2,390` / `1,602.8` / `2,441` | `28` (`28`) | `80` (`83`) | `49` (`52`) | `0` (`0`) | `3,075` / `2,257.2` / `3,333` / `3,414` | `15` (`50`) -> `15` (`36`) |
| **Span A** `LOCATION 12..=300` (289) | `5+3` (`5+3`) | `11+10` (`60+59`) | `0+0` (`3+3`) | `29` / `119` / `133` | `2,411` / `2,411.0` / `2,411` | `28` (`28`) | `82` (`86`) | `50` (`53`) | `0` (`0`) | `2,602` / `2,618.7` / `2,694` / `2,711` | `2` (`2`) -> `2` (`2`) |
| **Span B** `LOCATION 3680..=3979` (300) | `5+3` (`57+49`) | `596+595` (`622+621`) | `317+317` (`333+333`) | `1,828` / `1,941.1` / `1,962` | `627.5` / `1,120.7` / `3,138` | `28` (`44`) | `82` (`86`) | `51` (`53`) | `0` (`0`) | `2,555` / `2,465.8` / `2,922.1` / `3,490` | `15` (`32`) -> `15` (`26`) |
| **Span C** `INTRO 2500..=2949` (450) | `5+3` (`31+28`) | `9+1` (`42+41`) | `1+0` (`12+12`) | `52` / `109` / `115` | `4,712` / `4,108.8` / `8,421` | `0` (`0`) | `257` (`284`) | `126` (`221`) | `0` (`2`) | `5,219` / `4,565.6` / `8,881.1` / `8,919` | `0` (`0`) -> `0` (`0`) |

(Note: world sub-columns show `fill+edge`; `#811` distance culling dropped `1,198` frustum-surviving `WORLD_REACH` nodes across `LOCATION`'s 8,251 ticks, `169,636` -> `168,438`, and `0` of `437` across `INTRO`'s 3,807 ticks.)

- **Verdict**: Unculled `view_facing` draws are `92.7%` of Span A median draws (`2,411 / 2,602`), `90.3%` of Span C median draws (`4,712 / 5,219`), and `59.9%` of `LOCATION` whole-film mean draws (`727.2 / 1,215.0`); even at `LOCATION`'s peak wide-island stretch (`Span B`, `world_total` up to `1,962`), world draws sit at `1,828` median against `627.5` median / `1,120.7` mean `view_facing` draws.
  Notice also on `INTRO`, `LitLayout::refresh` produced `2,014` `Upload` events across `1,491` ticks vs `190` `Rewrite` events (`190` ticks, max `1`/tick), because current welding/outlines trigger index/node reallocation (`Refresh::Upload`) more often than in-place `Refresh::Rewrite`.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md#2-draws-by-category-after-644-and-811).

---

## 2026-11-21: Phase breakdown and isolation probes across three spans

- **Question**: Where does post-`#644`/`#811` render wall time go under `FRAMES_IN_FLIGHT = 2` and synchronous `= 1`, and how much does each candidate target (`#914`, `#919`, `#915` relight) save on Spans A, B, and C compared with RTX 4070 Laptop GPU?
- **Method**: Ran 3 sequential repetitions per cell (18 cells, 54 runs total) on Windows `mesa-dist-win 25.2.8` and RTX 4070 Laptop GPU, verifying 4-file `.zst` SHA-256 byte-identity against each span's baseline across the 15 lavapipe cells and self-determinism across the 3 RTX 4070 runs.
- **Result**: Every tested lavapipe cell (`lvp_baseline`, `lvp_fif1`, `lvp_plane_only`, `lvp_cull_vf`, and Span C `#915` variants) produced byte-identical `frames.zst`, `layers.zst`, `shapes.zst`, and `palettes.zst` against its span baseline (Span A/B/C hashes in Item 1 baseline cross-check).
  RTX 4070 produced distinct deterministic hashes per span (`palettes.zst` identical to lavapipe).
  Raw loop spreads stayed between `0.6%` and `4.9%` (`(max - min) / min`; end-to-end spreads stayed `0.3%..4.3%` on lavapipe and `2.2%..7.1%` on RTX 4070).

### Raw 3-run summary and deltas (Windows, `320x200`)

| Cell / Span | Adapter | Loop raw runs (ms) | Loop med [min..max] (ms/f) | vs `lvp_baseline` | E2E med [min..max] (ms) | CPU med (s) | Startup `build` / `open` (ms) | Peak RSS / Priv (MiB) |
|---|---|---|---|---|---|---|---|---|
| `lvp_baseline` / Span A | LLVM 21.1.7 | `6370.1, 6391.8, 6266.8` | `6370.1` `[6266.8..6391.8]` (`22.04`) | — | `7744.0` `[7612.2..7749.6]` | `11.062` | `747.4` / `547.0` | `903.9` / `1453.3` |
| `lvp_fif1` / Span A | LLVM 21.1.7 | `7965.1, 8354.5, 8012.2` | `8012.2` `[7965.1..8354.5]` (`27.72`) | `+25.8%` | `9359.2` `[9308.1..9708.8]` | `11.312` | `751.6` / `544.3` | `904.3` / `1453.5` |
| `lvp_plane_only` / Span A | LLVM 21.1.7 | `6314.3, 6227.3, 6289.5` | `6289.5` `[6227.3..6314.3]` (`21.76`) | `-1.3%` | `7624.6` `[7585.5..7661.5]` | `10.594` | `754.1` / `542.1` | `903.8` / `1452.9` |
| `lvp_cull_vf` / Span A | LLVM 21.1.7 | `1236.3, 1225.7, 1239.2` | `1236.3` `[1225.7..1239.2]` (`4.28`) | `-80.6%` | `2581.4` `[2566.2..2597.2]` | `5.219` | `752.8` / `543.6` | `904.7` / `1453.2` |
| `rtx4070_baseline` / Span A | RTX 4070 | `1299.8, 1289.1, 1326.0` | `1299.8` `[1289.1..1326.0]` (`4.50`) | `-79.6%` | `2805.2` `[2774.6..2971.8]` | `2.719` | `751.2` / `682.5` | `700.2` / `1413.5` |
| `lvp_baseline` / Span B | LLVM 21.1.7 | `5055.2, 5113.9, 5006.5` | `5055.2` `[5006.5..5113.9]` (`16.85`) | — | `6396.8` `[6370.7..6454.0]` | `11.375` | `746.5` / `540.3` | `903.4` / `1453.0` |
| `lvp_fif1` / Span B | LLVM 21.1.7 | `6536.9, 6591.2, 6688.4` | `6591.2` `[6536.9..6688.4]` (`21.97`) | `+30.4%` | `7962.0` `[7882.5..8046.7]` | `11.234` | `748.8` / `554.5` | `904.3` / `1453.5` |
| `lvp_plane_only` / Span B | LLVM 21.1.7 | `5311.7, 5285.4, 5337.2` | `5311.7` `[5285.4..5337.2]` (`17.71`) | `+5.1%` | `6657.5` `[6632.6..6694.2]` | `11.609` | `750.0` / `544.8` | `903.7` / `1452.9` |
| `lvp_cull_vf` / Span B | LLVM 21.1.7 | `2424.5, 2406.9, 2389.6` | `2406.9` `[2389.6..2424.5]` (`8.02`) | `-52.4%` | `3755.7` `[3751.6..3764.0]` | `7.422` | `746.3` / `543.2` | `904.1` / `1453.3` |
| `rtx4070_baseline` / Span B | RTX 4070 | `1078.8, 1038.3, 1047.1` | `1047.1` `[1038.3..1078.8]` (`3.49`) | `-79.3%` | `2530.4` `[2518.2..2596.8]` | `2.516` | `748.6` / `685.6` | `699.3` / `1412.4` |
| `lvp_baseline` / Span C | LLVM 21.1.7 | `8794.9, 8751.5, 8564.6` | `8751.5` `[8564.6..8794.9]` (`19.45`) | — | `9133.4` `[8949.3..9179.2]` | `15.703` | `185.2` / `166.5` | `309.6` / `413.1` |
| `lvp_fif1` / Span C | LLVM 21.1.7 | `12562.4, 12629.5, 12444.1` | `12562.4` `[12444.1..12629.5]` (`27.92`) | `+43.5%` | `12947.7` `[12824.6..13008.3]` | `14.750` | `185.7` / `165.4` | `294.8` / `409.5` |
| `lvp_plane_only` / Span C | LLVM 21.1.7 | `8783.1, 8770.8, 8435.6` | `8770.8` `[8435.6..8783.1]` (`19.49`) | `+0.2%` | `9154.8` `[8815.7..9162.4]` | `15.734` | `184.7` / `165.4` | `309.3` / `413.5` |
| `lvp_cull_vf` / Span C | LLVM 21.1.7 | `2023.0, 2068.8, 2046.3` | `2046.3` `[2023.0..2068.8]` (`4.55`) | `-76.6%` | `2430.6` `[2401.2..2453.1]` | `5.469` | `185.7` / `165.5` | `251.3` / `409.5` |
| `lvp_skip_apex` / Span C | LLVM 21.1.7 | `8731.9, 8713.3, 8766.3` | `8731.9` `[8713.3..8766.3]` (`19.40`) | `-0.2%` | `9118.3` `[9091.0..9148.5]` | `15.656` | `186.3` / `165.2` | `305.7` / `410.0` |
| `lvp_ring_lit` / Span C | LLVM 21.1.7 | `8638.9, 8695.2, 8746.0` | `8695.2` `[8638.9..8746.0]` (`19.32`) | `-0.6%` | `9078.2` `[9023.8..9138.1]` | `15.328` | `187.4` / `167.3` | `309.2` / `412.1` |
| `lvp_skip_apex_ring_lit` / Span C | LLVM 21.1.7 | `8702.4, 8710.0, 8655.4` | `8702.4` `[8655.4..8710.0]` (`19.34`) | `-0.6%` | `9088.4` `[9041.4..9091.4]` | `16.172` | `185.6` / `167.7` | `310.1` / `414.0` |
| `rtx4070_baseline` / Span C | RTX 4070 | `2569.5, 2627.5, 2588.7` | `2588.7` `[2569.5..2627.5]` (`5.75`) | `-70.4%` | `3080.0` `[3052.9..3120.2]` | `3.047` | `186.2` / `263.8` | `256.3` / `439.1` |

### Phase medians across loop stages (ms)

| Cell / Span | `scene_frame` | `prepare` (`vf` / `rdec` / `rupl`) | `scene_draw` | `queue_submit` | `poll_color` + `poll_plane` | `readback_copy` | `journal_write` (`check_der` / `u16` / `zstd`) | `finish` |
|---|---|---|---|---|---|---|---|---|
| `lvp_baseline` / Span A | `579.7` | `262.9` (`137.7` / `72.2` / `8.7`) | `83.5` | `4,981.6` | `20.3` + `0.5` | `337.6` | `93.6` (`21.4` / `33.2` / `20.2`) | `1.4` |
| `lvp_fif1` / Span A | `558.9` | `258.9` (`136.9` / `72.1` / `7.4`) | `82.3` | `400.6` | `6,282.2` + `0.8` | `332.7` | `87.2` (`20.5` / `29.0` / `19.8`) | `1.5` |
| `lvp_plane_only` / Span A | `550.1` | `260.3` (`140.4` / `71.5` / `8.6`) | `82.8` | `5,067.7` | `0.0` + `20.8` | `245.2` | `71.4` (`0.0` / `32.7` / `20.0`) | `1.4` |
| `lvp_cull_vf` / Span A | `330.0` | `94.9` (`20.2` / `59.2` / `5.1`) | `1.8` | `423.3` | `1.2` + `0.3` | `281.8` | `94.5` (`27.0` / `29.0` / `20.4`) | `1.5` |
| `rtx4070_baseline` / Span A | `359.2` | `239.7` (`129.9` / `61.6` / `9.0`) | `86.2` | `203.8` | `10.8` + `2.5` | `281.8` | `84.0` (`20.8` / `26.0` / `19.8`) | `1.2` |
| `lvp_baseline` / Span B | `531.5` | `177.7` (`69.3` / `49.6` / `6.5`) | `71.4` | `3,679.0` | `27.8` + `0.8` | `449.1` | `113.1` (`21.9` / `32.2` / `37.6`) | `4.6` |
| `lvp_fif1` / Span B | `508.2` | `175.6` (`68.9` / `51.3` / `5.5`) | `54.5` | `258.9` | `5,132.7` + `0.8` | `348.4` | `105.2` (`21.4` / `27.1` / `36.3`) | `4.6` |
| `lvp_plane_only` / Span B | `546.7` | `177.8` (`67.8` / `50.2` / `6.6`) | `67.9` | `4,023.5` | `0.0` + `23.8` | `371.9` | `92.5` (`0.0` / `33.4` / `37.7`) | `4.6` |
| `lvp_cull_vf` / Span B | `468.5` | `96.0` (`10.1` / `44.9` / `5.2`) | `26.4` | `1,268.2` | `9.0` + `0.8` | `425.9` | `115.7` (`22.7` / `32.5` / `38.7`) | `4.6` |
| `rtx4070_baseline` / Span B | `265.2` | `156.0` (`64.7` / `46.0` / `7.0`) | `53.1` | `167.5` | `10.3` + `2.6` | `274.0` | `100.0` (`21.4` / `23.4` / `35.9`) | `4.4` |
| `lvp_baseline` / Span C | `611.9` | `858.1` (`331.5` / `379.9` / `31.4`) | `289.2` | `6,355.5` | `2.7` + `0.7` | `472.4` | `149.8` (`36.9` / `47.2` / `35.2`) | `6.1` |
| `lvp_fif1` / Span C | `609.4` | `843.2` (`326.7` / `371.0` / `31.3`) | `267.7` | `1,080.2` | `9,146.9` + `1.5` | `450.6` | `132.3` (`31.9` / `38.8` / `33.9`) | `5.9` |
| `lvp_plane_only` / Span C | `615.6` | `847.7` (`326.2` / `378.0` / `31.2`) | `281.4` | `6,550.2` | `0.0` + `3.0` | `338.5` | `109.3` (`0.0` / `44.8` / `35.2`) | `5.8` |
| `lvp_cull_vf` / Span C | `490.9` | `439.5` (`42.8` / `344.5` / `23.5`) | `5.0` | `462.8` | `1.2` + `0.7` | `492.2` | `147.5` (`38.7` / `45.3` / `35.5`) | `5.9` |
| `lvp_skip_apex` / Span C | `609.8` | `870.0` (`346.4` / `382.0` / `30.6`) | `292.4` | `6,305.8` | `2.6` + `0.7` | `479.6` | `149.9` (`37.0` / `48.6` / `35.1`) | `6.1` |
| `lvp_ring_lit` / Span C | `616.3` | `868.9` (`333.3` / `380.8` / `31.8`) | `284.2` | `6,277.9` | `2.7` + `0.8` | `480.4` | `148.8` (`36.7` / `48.5` / `34.7`) | `5.8` |
| `lvp_skip_apex_ring_lit` / Span C | `604.7` | `854.8` (`326.8` / `380.4` / `31.1`) | `283.3` | `6,284.6` | `2.7` + `0.7` | `480.0` | `150.6` (`37.7` / `47.8` / `35.2`) | `5.8` |
| `rtx4070_baseline` / Span C | `441.4` | `787.6` (`297.1` / `343.8` / `36.6`) | `255.7` | `533.0` | `3.0` + `2.4` | `407.5` | `129.7` (`32.2` / `37.3` / `34.0`) | `5.6` |

(Remaining minor phases on baseline A/B/C: `palette_lut` `4.25`/`0.12`/`0.15` ms, `prepare_world` `6.33`/`28.94`/`8.07` ms, `prepare_actors_other` `7.67`/`6.72`/`29.77` ms, `prepare_sprites_place` `0.10`/`0.16`/`8.66` ms, `prepare_uniforms_upload` `8.03`/`4.27`/`12.67` ms, `credits_overlay` `0.42`/`0.00`/`0.00` ms, `preview_png` `5.69`/`7.88`/`10.35` ms; relight counts on Span C: `keep=3,473`, `rewrite=144`, `upload=472` on baseline and `skip_apex` with `apex_skipped=144`; under `ring_lit`, `keep=3,480`, `rewrite=141`, `upload=468`, with `apex_skipped=141` when combined.)

- **Key phase attributions**:
  1. Under `FRAMES_IN_FLIGHT = 2`, `queue.submit` waits inside `wgpu`/Mesa (`4,981.6`, `3,679.0`, and `6,355.5` ms across A, B, C) while `read_back` waits `<= 28.6` ms; switching to `FRAMES_IN_FLIGHT = 1` moves execution wait into `poll_color` (`6,282.2`, `5,132.7`, `9,146.9` ms) and slows the loop by `25.8%`, `30.4%`, and `43.5%` because main-thread CPU prep no longer overlaps lavapipe work.
  2. Frustum-culling `view_facing` props (`#914`) removes `92.7%` of Span A draws (`5,133.7 ms`, `-80.6%` loop), `24.6%` median / `45.4%` mean of Span B draws (`2,648.3 ms`, `-52.4%`), and `90.3%` of Span C draws (`6,705.2 ms`, `-76.6%`).
     With `view_facing` culled, lavapipe beats the unculled RTX 4070 loop on Spans A (`1,236.3` vs `1,299.8` ms) and C (`2,046.3` vs `2,588.7` ms).
  3. Dropping `color_texture`, fragment `palette_lut` reads, color readback, and `check_derivable` (`#919`) cuts loop time by `80.6 ms` (`-1.3%`) on Span A, adds `256.5 ms` (`+5.1%`) on Span B, and adds `19.3 ms` (`+0.2%`) on Span C; `check_derivable` itself takes `21.4..36.9 ms` on baseline (`0.3%..0.4%`).
  4. On Span C, skipping matching `apex_buffer` rewrites (`144` of `144` rewrites skipped) changes loop time by `-0.2%`, 2-slot relit buffering by `-0.6%`, and both combined by `-0.6%`.
     Even after `#914` culling (`2,046.3 ms` loop), GPU relight uploads/rewrites take `23.5 ms` (`1.1%`), whereas CPU decoding/outlining (`prepare_relight_decode`) takes `344.5 ms` (`16.8%`).
  5. Second-buffer polling (`poll_plane_ms`) takes `< 1.0 ms` in baseline (`0.52..0.78 ms`) because the first `poll_color` already drains the single render-pass submission.
- **Verdict**: Per-draw vertex/command work on unculled `view_facing` trees and props is the dominant post-`#644` lavapipe cost across desert, wide-island, and forested spans.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes).

---

## 2026-11-21: Thread scaling under LP_NUM_THREADS on Windows and Linux Mesa

- **Question**: After `#596` (single dynamic-offset uniform upload) and `#644` (world frustum cull), does `LP_NUM_THREADS` still leave lavapipe runtime flat, on Windows `mesa-dist-win 25.2.8` and Ubuntu 24.04 canonical `mesa-vulkan-drivers 25.2.8`, and does culling `view_facing` (`#914`) change scaling?
- **Method**: Ran `LOCATION` `12..=300` (289 frames), 3 runs each for `LP_NUM_THREADS` = `1`, `4`, and unset on Windows `mesa-dist-win 25.2.8` (both baseline and `DBG_PROBE_CULL_VIEW_FACING=1`) and WSL 2 `Ubuntu-24.04` (`mesa-vulkan-drivers 25.2.8-0ubuntu0.24.04.5`, baseline), checking 4-`.zst` SHA-256 byte-identity.
- **Result**: Every run in a given environment matched its 4-`.zst` SHA-256 digests (`WSL` hash: `frames.zst` `7c6aa0d1584be8c60ce12685f2ec92d4c570326491e086257f4b5ef0cdca1695`, `layers.zst` `8f89fdc5eef69d35283849dec8f03a3e6929846c95b30aed5b5b7d72c4598b5b`, `shapes.zst` `3b7330d8d3e862b038c45875993f8e0f018d0f733932122463993c70b183fe09`, `palettes.zst` `2537dc858937720397d4220fc3f8678c092f49ec0c81ff445fb5041d93ec2aab`, matching Windows Span A).

| Platform & Mode | `LP_NUM_THREADS` | Loop raw runs (ms) | Loop med [min..max] | vs `LP=1` | E2E med [min..max] (ms) | CPU med [min..max] (s) | Cores busy med |
|---|---|---|---|---|---|---|---|
| Win baseline | `1` | `7031.8, 7102.3, 6995.0` | `7031.8` `[6995.0..7102.3]` | — | `8381.8` `[8346.7..8443.6]` | `10.484` `[10.344..10.562]` | `1.25` |
| Win baseline | `4` | `6214.3, 6353.7, 6275.0` | `6275.0` `[6214.3..6353.7]` | `-10.8%` | `7606.0` `[7549.3..7693.3]` | `10.438` `[10.312..10.469]` | `1.38` |
| Win baseline | `unset` | `6295.3, 6238.0, 6267.3` | `6267.3` `[6238.0..6295.3]` | `-10.9%` | `7621.3` `[7580.4..7635.9]` | `11.125` `[10.781..11.328]` | `1.46` |
| Win `#914` cull | `1` | `1633.3, 1625.6, 1601.5` | `1625.6` `[1601.5..1633.3]` | — | `2978.7` `[2945.8..2980.8]` | `3.844` `[3.797..3.906]` | `1.29` |
| Win `#914` cull | `4` | `1176.1, 1174.1, 1198.4` | `1176.1` `[1174.1..1198.4]` | `-27.7%` | `2518.2` `[2518.1..2549.3]` | `4.203` `[3.344..4.406]` | `1.65` |
| Win `#914` cull | `unset` | `1237.2, 1224.6, 1280.4` | `1237.2` `[1224.6..1280.4]` | `-23.9%` | `2580.7` `[2565.6..2626.2]` | `4.234` `[4.125..5.031]` | `1.61` |
| WSL 2 baseline | `1` | `10813.6, 10715.9, 10590.7` | `10715.9` `[10590.7..10813.6]` | — | `12574.4` `[12433.8..12962.1]` | `15.190` `[14.890..15.530]` | `1.20` |
| WSL 2 baseline | `4` | `9893.8, 9899.7, 9875.9` | `9893.8` `[9875.9..9899.7]` | `-7.7%` | `11522.2` `[11481.6..11624.1]` | `15.010` `[14.900..15.180]` | `1.31` |
| WSL 2 baseline | `unset` | `9755.0, 9787.2, 9802.4` | `9787.2` `[9755.0..9802.4]` | `-8.7%` | `11422.0` `[11388.1..11576.6]` | `15.700` `[15.530..15.730]` | `1.36` |

(`Cores busy med` is `median(cpu_s / (end_to_end_ms / 1000))` across the 3 runs, which can differ by `0.01..0.04` from `CPU med / (E2E med / 1000)`.)

- **Verdict**: Qualifies `#596`'s pre-`#644` flat observation: once staging-buffer churn and `121,148` culled world draws are gone, raising `LP_NUM_THREADS` from `1` to `4`/default speeds the loop by `7.7%..10.9%` on baseline and by `27.7%` (`LP_NUM_THREADS=4`) on `#914`-culled Windows `LOCATION` `12..=300` while maintaining byte-identical outputs.
  Setting `LP_NUM_THREADS=1` per process remains useful primarily to cap oversubscription when running multi-worker subprocess pools (`Item 4`).
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md#4-thread-scaling-under-lp_num_threads-after-596-and-644).

---

## 2026-11-21: Multi-VkDevice in-process versus child processes on Windows and Linux Mesa

- **Question**: Do N OS threads owning separate `wgpu::Device`s in one process scale cleanly on lavapipe after sharing one `FilmScene::build` and calling `release_world_mesh()`, or do multiple processes (`--tick-range` shards) scale better across both Windows MSVC Mesa and Ubuntu Linux Mesa?
- **Method**: Measured `LOCATION` `50..=649` (600 ticks, 12 aligned 50-tick `RENDER_CHUNK_TICKS` chunks) across 1, 2, and 4 workers (`LP_NUM_THREADS=1` and `unset`), comparing `DBG_PROBE_WORKERS=N` (in-process `std::thread::scope` sharing `offscreen_adapter`) against N concurrent child processes, plus `DBG_PROBE_SEPARATE_INSTANCES=1` (`N=4`, `LP_NUM_THREADS=1`) where 4-way in-process lagged 4-way child processes by `> 20%`.
  Verified exact per-tick decoded SHA-256 identity of `indices` (`frames.zst`), `layers.zst`, `shapes.zst`, and resolved 768-byte `palettes.zst` across `50..=649` for every multi-worker run against the 1-worker store.
  Recorded both summed child peak RSS / `VmHWM` (`PeakWorkingSet64`, `PeakPagedMemorySize64`) and 25 ms polled concurrent aggregate RSS / private commit across active child PIDs.
- **Result**: Every multi-worker run on Windows and WSL 2 matched the 1-worker store across 600 ticks x 4 planes with zero missing or duplicate ticks.

| Config (`LOCATION 50..=649`) | Mode / Workers / `LP` | Loop med [min..max] (ms) | Loop speedup | E2E med [min..max] (ms) | E2E speedup | CPU med (s) | Cores busy med | Peak RSS (`VmHWM`/sum) / Polled agg RSS (MiB) | Peak Priv / Polled agg Priv (MiB) |
|---|---|---|---|---|---|---|---|---|---|
| `win_1w_lp1` | 1 proc, `LP=1` | `13953.9` `[13871.4..14020.3]` | `1.00x` | `15304.3` `[15219.6..15398.8]` | `1.00x` | `19.73` | `1.29` | `900.9` / `889.2` | `1449.8` / `1447.9` |
| `win_1w_unset` | 1 proc, `unset` | `12581.6` `[12563.0..12731.1]` | `1.11x` | `13922.8` `[13913.6..14083.5]` | `1.10x` | `20.64` | `1.48` | `904.3` / `878.7` | `1453.3` / `1449.5` |
| `win_2w_inproc_lp1` | 2 thread, shared, `LP=1` | `8993.9` `[8960.6..9297.7]` | `1.55x` | `10401.4` `[10382.5..10716.5]` | `1.47x` | `23.42` | `2.21` | `1652.2` / `1651.5` | `2538.1` / `2472.8` |
| `win_2w_inproc_unset` | 2 thread, shared, `unset` | `7669.7` `[7492.2..7678.9]` | `1.82x` | `9079.2` `[8907.1..9107.0]` | `1.69x` | `23.89` | `2.62` | `1656.8` / `1655.8` | `2543.0` / `2532.9` |
| `win_2w_proc_lp1` | 2 child, `LP=1` | `7698.4` `[7685.5..7721.7]` | `1.81x` | `9399.7` `[9377.5..9448.3]` | `1.63x` | `22.72` | `2.42` | `1801.9` / `1727.3` | `2899.3` / `2888.2` |
| `win_2w_proc_unset` | 2 child, `unset` | `6932.8` `[6907.6..6984.9]` | `2.01x` | `8619.5` `[8615.6..8696.3]` | `1.78x` | `23.55` | `2.73` | `1808.8` / `1765.2` | `2906.6` / `2897.0` |
| `win_4w_inproc_lp1` | 4 thread, shared, `LP=1` | `6727.8` `[6724.8..6795.5]` | `2.07x` | `8267.2` `[8250.1..8333.0]` | `1.85x` | `30.00` | `3.64` | `3244.6` / `3243.6` | `4561.3` / `4535.3` |
| `win_4w_inproc_sep_lp1` | 4 thread, sep inst, `LP=1` | `5451.2` `[5387.2..6281.8]` | `2.56x` | `7030.7` `[7010.0..7836.5]` | `2.18x` | `29.44` | `4.15` | `3246.1` / `3241.9` | `4543.7` / `4530.4` |
| `win_4w_proc_lp1` | 4 child, `LP=1` | `4344.1` `[4339.9..4350.5]` | `3.21x` | `6162.1` `[6139.9..6171.6]` | `2.48x` | `28.28` | `4.59` | `3602.7` / `3501.1` | `5798.5` / `5783.1` |
| `wsl_1w_lp1` | 1 proc, `LP=1` | `21579.7` `[21512.1..21743.0]` | `1.00x` | `23399.0` `[23099.1..23797.4]` | `1.00x` | `28.51` | `1.22` | `952.6` / `943.3` | — |
| `wsl_1w_unset` | 1 proc, `unset` | `20536.8` `[20431.8..20548.4]` | `1.05x` | `22367.7` `[22273.4..22373.4]` | `1.05x` | `30.66` | `1.37` | `953.1` / `937.2` | — |
| `wsl_2w_inproc_lp1` | 2 thread, shared, `LP=1` | `15121.2` `[14958.2..15344.9]` | `1.43x` | `17067.8` `[16717.5..17244.2]` | `1.37x` | `35.40` | `2.07` | `1717.6` / `1711.5` | — |
| `wsl_2w_inproc_unset` | 2 thread, shared, `unset` | `14113.9` `[13954.4..14162.9]` | `1.53x` | `15986.9` `[15628.5..16015.8]` | `1.46x` | `36.59` | `2.30` | `1719.6` / `1718.9` | — |
| `wsl_2w_proc_lp1` | 2 child, `LP=1` | `12913.2` `[12759.4..12970.0]` | `1.67x` | `14874.1` `[14871.0..14978.5]` | `1.57x` | `35.53` | `2.38` | `1905.2` / `1854.9` | — |
| `wsl_2w_proc_unset` | 2 child, `unset` | `12274.9` `[12251.9..12316.5]` | `1.76x` | `14203.9` `[14180.1..14358.9]` | `1.65x` | `36.96` | `2.60` | `1905.9` / `1868.3` | — |
| `wsl_4w_inproc_lp1` | 4 thread, shared, `LP=1` | `15890.6` `[15290.6..15955.1]` | `1.36x` | `18080.2` `[17488.2..18172.4]` | `1.29x` | `58.22` | `3.22` | `3287.1` / `3287.1` | — |
| `wsl_4w_inproc_sep_lp1` | 4 thread, sep inst, `LP=1` | `13128.4` `[13003.2..13590.4]` | `1.64x` | `15532.8` `[15384.1..15783.3]` | `1.51x` | `52.71` | `3.38` | `3277.0` / `3276.1` | — |
| `wsl_4w_proc_lp1` | 4 child, `LP=1` | `7650.1` `[7599.3..8132.9]` | `2.82x` | `9889.7` `[9661.5..10150.2]` | `2.37x` | `45.70` | `4.62` | `3810.7` / `3586.7` | — |

(Across the 3 repetitions on Windows `win_4w_proc_lp1`, per-child startup `build_ms` ranged `811.3..831.3` ms and `open_ms` `635.6..656.3` ms vs `win_4w_inproc_lp1`'s single shared `build_ms` `750.7..762.8` ms [med `761.2` ms] and parallel `upload_ms` `665.7..670.0` ms [med `666.3` ms]; `Cores busy med` is `median(cpu_s / (end_to_end_ms / 1000))` across the 3 runs.)

- **Verdict**: Multiple `VkDevice`s in one process do not strictly serialize on one thread (`2.21` cores on Windows and `2.07` cores on Linux at `N=2`, `LP_NUM_THREADS=1`), revising `#645`'s single-thread statement in [`evidence-limits.md`](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).
  However, in-process pooling underperforms child processes on both speed and efficiency (`4` workers on Linux regressed to `15,890.6` ms loop / `58.22` s CPU vs `7,650.1` ms loop / `45.70` s CPU for `4` child processes, even with `1` shared scene build), and even separating `wgpu::Instance`/`Adapter` per thread (`13,128.4` ms Linux, `5,451.2` ms Windows) left in-process workers slower than child processes while saving `257.5..299.6 MiB` polled aggregate RSS at `4` workers (`3,243.6` vs `3,501.1 MiB` Win; `3,287.1` vs `3,586.7 MiB` WSL) because each extra lavapipe device adds `751..796 MiB` of RSS (`751.3..765.0 MiB` at `2w`, `784.7..796.2 MiB` marginal at `2w -> 4w`) for device buffers and driver state.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md#5-multi-vkdevice-in-process-versus-child-processes) and [`evidence-limits.md`](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).

---

## 2026-11-21: Qualitative go, defer, and no-go verdicts

- **Question**: What should `#914`, `#915` (a)-(d), `#916`, `#919`, and `#920` do on the evidence collected here?
- **Result**:

| Issue / Sub-item | Recommendation | Observed impact & scope | Rationale & contract/memory notes |
|---|---|---|---|
| `#914` (`view_facing` cull; actors/shadows/sprites & instancing) | **Go** (on `view_facing` frustum cull; instancing follow-up **defer**) | `-80.6%` (`-5,133.7 ms`, `22.04 -> 4.28 ms/f`) Span A; `-52.4%` (`-2,648.3 ms`, `16.85 -> 8.02 ms/f`) Span B; `-76.6%` (`-6,705.2 ms`, `19.45 -> 4.55 ms/f`) Span C; `0` store drift | Largest measured lever across desert, wide-island, and forested scenes; actor/shadow/sprite culling addresses `<=183` (`LOCATION`, med `157`) / `<=505` (`INTRO`) remaining non-world draws; `view_facing` instancing matters mainly where surviving visible trees remain high on forested shots. |
| `#915` (a) Bind-state deduplication | **Defer** | Baseline `scene_draw` is `83.5 / 71.4 / 289.2 ms`; post-`#914` `1.8 / 26.4 / 5.0 ms` (`0.1%..1.1%` of post-`#914` loop) | Per-draw encode CPU cost becomes `< 1.1%` once `#914` lands (`<= 26.4 ms` over 300 frames on Span B). |
| `#915` (b) 2-slot relit ring & skip matching `apex_buffer` rewrite | **No-go** | `-0.2%` (`skip_apex`), `-0.6%` (`ring_lit`), `-0.6%` combined on Span C; `prepare_relight_upload` is `31.4 ms` baseline / `23.5 ms` post-`#914` (`1.1%`) | Under current welding/outlines (`6955e159`), `Refresh::Upload` occurs `472` times vs `144` `Refresh::Rewrite` on Span C (`2,014` vs `190` across full `INTRO`); CPU decode (`379.9 ms` / `344.5 ms`) exceeds GPU upload (`31.4 ms` / `23.5 ms`) by `> 12x`, while adding slot memory and invalidation complexity. |
| `#915` (c) Apex-free world vertex layout & drop `light_level` | **Defer** | World `apex_buffer` holds `6,702,570 x 12 B = 76.7 MiB` per device (`LOCATION` RSS `901..953 MiB`); post-`#914` Span B GPU submit is `1,268.2 ms` (`4.23 ms/f`) | Fragment shading saving on lavapipe was `< 1.3%` in `#919`; reconsider primarily if shrinking per-worker world RAM (~`76.7 MiB`) is needed for higher subprocess concurrency under `#916`. |
| `#915` (d) `StoreOp::Discard`, single poll, reused readback buffers | **Defer** | Second poll (`poll_plane`) is `< 0.8 ms` per 300-450 frames; `readback_copy` is `281.8..492.2 ms` post-`#914` (`17.7%..24.1%` post-`#914` loop) | Single-poll gain is negligible (`< 0.8 ms`); `OffscreenTarget` already reuses its `[Readback; 2]` GPU staging buffers, so remaining targets are CPU `Vec` reuse (`readback_copy`) and `StoreOp::Discard` once `#914` lands. |
| `#916` Chunk-parallel `--workers N` | **Go** (child processes) / **No-go** (in-process multi-`VkDevice`) | Child processes reach `3.21x` loop / `2.48x` E2E (Win) and `2.82x` loop / `2.37x` E2E (Linux) at 4 workers (`LP=1`); in-process regresses at `N=4` on Linux (`15.89 s`, `58.2 s` CPU vs `7.65 s`, `45.7 s` CPU child processes) | Budget `~953 MiB` (`0.93 GiB`) RSS/worker on Linux (`~901 MiB` / `0.88 GiB` RSS and `~1,450 MiB` / `1.42 GiB` commit on Win); in-process saves `257.5..299.6 MiB` polled aggregate RSS at `N=4` (`358.1..523.6 MiB` summed peak RSS; `1,247.8 MiB` Windows polled private commit) while losing speed to state shared through one instance (whether `wgpu`'s or Mesa's is not separated) and to contention that separate instances do not remove; combine child processes with `--jobs` budget rather than adding in-process multi-device threads. |
| `#919` Plane-only offscreen target | **No-go** | `-1.3%` (`-80.6 ms`) Span A, `+5.1%` (`+256.5 ms`) Span B, `+0.2%` (`+19.3 ms`) Span C; `check_derivable` is `21.4..36.9 ms` baseline (`0.3%..0.4%`) and `22.7..38.7 ms` post-`#914` (`0.9%..2.2%`) | Yields `-80.6 ms` to `+256.5 ms` loop change while discarding per-pixel `check_derivable` validation of GPU `palette_lut` output. |
| `#920` Un-baking 56,395 static props | **Defer** | Whole-film `LOCATION` `world_total` med `229` / p95 `1,033` / max `1,962`; Span B post-`#914` is `8.02 ms/f` (vs `4.28 ms/f` Span A) | `#914` already brings worst-case wide-island `LOCATION` frames to `8.02 ms/f` with steady world RSS at ~`513..563 MiB` (`evidence-limits.md`); un-baking `56,395` static props adds draw/transform complexity for minor worst-window headroom. |

- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md#6-optimization-verdicts).
