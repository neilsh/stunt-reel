---
summary: "Post-#644/#811 lavapipe profiling across LOCATION and INTRO shows culling view_facing draws (#914) cuts loop wall clock by 52.4% to 80.6% (go; landed, it cut whole-process wall by 38.7% to 72.0% on Windows lavapipe with the stores checked byte-identical); omitting color_texture (#919, -1.3% to +5.1%) and relight vertex-ring/apex-skip (#915b, -0.6%) save little (no-go). LP_NUM_THREADS=4 now cuts Span A loop by 10.8% on Windows (27.7% after #914) and 7.7% on Ubuntu 24.04; four child processes scale 2.82x-3.21x on LOCATION 50-649 while four in-process VkDevices sharing one instance regress on Ubuntu Mesa 25.2.8 (#916 child processes go, in-process pooling no-go)."
---
# Parity: Render Time on Lavapipe

* **Scope**: how long a headless render takes on lavapipe, Mesa's software Vulkan driver, and on the GPU, and which renderer changes cut it; split from [`lavapipe.md`](lavapipe.md), which holds how lavapipe's frames differ from the GPU's.
* **Sources**: `cdb` stack samples and timed renders from #596, #602, #603, #644, #629 and #918, on mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and the RTX 4070 laptop, set up by [`render-on-lavapipe.md`](../../docs/howto/render-on-lavapipe.md), Ubuntu 24.04's `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`) under WSL 2, and a cloud Ubuntu session.
* **Evidence tier**: stated at the start of each section.

## 1. Pre- and initial `#644` baseline

`[Bounded Observation]`, 2026-11-15 to 2026-11-16, mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and the RTX 4070 on the same laptop, LOCATION ticks 12-300, headless at 320×200.
Each change left the render stores (`frames.zst`, `layers.zst`, `palettes.zst`) byte-identical, on lavapipe over LOCATION ticks 12-300 and on the GPU over the seven reference films' captured ticks.
Each row's before is its own tree, so the rows do not chain (this machine took 88.7 s on lavapipe for `5844b4b8`, #602's before, against 81.8 s for `80a3ad5`, #596's after):

| Change | Lavapipe before, after | GPU before, after |
|---|---|---|
| One matrix upload per frame (#596, after on `80a3ad5`, one run each) | 150.5 s, 81.8 s | 20.9 s, 16.0 s |
| Two frames in flight (#602, `5844b4b8` before, two runs each) | 88.7 s and 89.9 s, 76.3 s and 78.2 s | 16.7 s and 16.6 s, 12.4 s and 12.6 s |
| Frustum cull (#644, `857f80a8` before, PR #652 at `3e956d1a` after, one run each) | 81.7 s, 13.7 s | 14.6 s, 4.7 s |

#596 also cut the GPU's full captures, LOCATION's (ticks 12-8262) from 301.2 s to 229.6 s and INTRO's (12-3818) from 96.8 s to 67.8 s.
_Source: [One model-matrix upload per frame](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-one-model-matrix-upload-per-frame), [Two frames in flight](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-two-frames-in-flight), [culling world nodes outside the view frustum](../../work/2026-11/644_frustum-cull/journal.md#2026-11-16-culling-world-nodes-outside-the-view-frustum)._

**One matrix upload per frame (#596).**
`SceneRenderer::prepare` wrote each draw's model matrix with its own `write_buffer`, and wgpu allocates a staging buffer per call; on lavapipe that allocation held about half of the main-thread samples, with the process at 1.00 core whatever `LP_NUM_THREADS` was (before `#596` and `#644`; see section 4 for post-`#644` scaling).
#596 packs a frame's matrices into one uniform buffer at dynamic offsets, uploaded with one `write_buffer`.
Afterwards 16 of 20 main-thread samples sat in `wait_for_fence`, inside `vulkan_lvp`, and the staging samples vanished; thread samples placed lavapipe's work on the command-buffer thread (busy in 52 of 65 samples) ([#600](https://github.com/neilsh/stunt-reel/issues/600)); on the GPU 8 of 42 main-thread samples sat in `GpuModel::collect_world_meshes`.
_Source: [2026-11-15: where a frame's time goes after the change](../../work/2026-11/596_lavapipe-staging-buffers/journal.md#2026-11-15-where-a-frames-time-goes-after-the-change), [One model-matrix upload per frame](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-one-model-matrix-upload-per-frame)._

**Two frames in flight (#602).**
The offscreen target waited for each frame's readback, so the main thread and lavapipe's command-buffer thread did not overlap.
The headless loop submits tick N+1 before mapping tick N's readback buffers, and waits for tick N's own submission while delivering pages in tick order without changing scores.
_Source: [Two frames in flight in headless capture](../../work/2026-11/602_headless-capture-two-frames/journal.md#2026-11-15-two-frames-in-flight-in-headless-capture)._

**Draws per frame (#603, #644).**
Before the cull, the median LOCATION frame (ticks 12-300, `b0f6c120`) encoded 127,910 `draw_indexed` calls: 8,963 ground fills and 6,269 ground outlines, 49,257 base fills and 45,560 base outlines (94,817, 74.1%), 5,550 decal fills and 5,549 decal outlines, and 6,762 non-world fills.
Because the world uploads as one chunk of 6,702,496 vertices (now `6,702,570` vertices / `7,488,138` indices) and walk order visits child slices in reverse index order, contiguous-slice coalescing removed zero calls (`#603` no-go).
`#644` frustum-culls world nodes (`PR #652`), cutting the median frame of those 289 from `127,910` to `6,791` calls (`29` median world draws).
On `6955e159` the same span's median frame makes `2,602` calls, `29` of them world draws (section 2).
The non-world fills fell from `6,764` to `2,571` at `f95ec4a0` (`#811`, PR `#902`), counted over the prepared lists on a cloud session's Ubuntu lavapipe; every earlier tree tested kept `6,762..6,764`.
`#811` gives each view-facing prop that some camera eye puts past `PLAYONE`'s `scale_index` distance cut a `ScaleReach` gate, and `FilmScene::frame` drops the prop on a frame once its largest eye-relative coordinate reaches the cut ([`world-scene-residuals.md` § 6.4](../playone-exe/world-scene-residuals.md#64-the-ground-decal-pass)).
On this span the median frame's shape base slices (view-facing props and unlit actors) fell from `5,317` to `2,435` and its shape decal slices from `1,315` to `4`, and `f95ec4a0` with only that gate left off view-facing props drew a median `6,764` again.
View-facing draws are not frustum-culled before `#914`, so a prop the gate drops need not have been in the frame: over the seven reference films' scored ticks, `#811` counted 14 placements of any kind past the cut, in front of the eye and inside the frame's half-diagonal widened by their radius, all on `LOCATION`.
_Source: [bisecting the non-world draw count](../../work/2026-11/nonworld-draws-bisect/journal.md#2026-11-22-bisecting-the-non-world-draw-count)._
Ubuntu's Mesa 25.2.8 rendered the seven reference films byte-identical with and without the cull (`734d3a8`, 2026-11-17).
_Source: [Draws per frame](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-draws-per-frame), [culling world nodes outside the view frustum](../../work/2026-11/644_frustum-cull/journal.md#2026-11-16-culling-world-nodes-outside-the-view-frustum), [the cull on top of eye-relative transforms](../../work/2026-11/644_frustum-cull/journal.md#2026-11-17-the-cull-on-top-of-eye-relative-transforms)._

## 2. Draws by category after `#644` and `#811`

`[Bounded Observation]`, 2026-11-21, `main` commit `6955e159` (`crates` tree `90057c02`), headless `320x200` (`--viewport-rows 185`).
CPU scan counts across `LOCATION` (`12..=8262`, `8,251` ticks) and `INTRO` (`12..=3818`, `3,807` ticks) matched live Windows `mesa-dist-win 25.2.8` `SceneRenderer::draw` counts across 100% of frames on Spans A (`12..=300`), B (`3680..=3979`), and C (`2500..=2949`).

- **World totals (`#811`).**
  `LOCATION`'s built world has `158` terrain patches, `56,395` static props (`6,702,570` vertices, `7,488,138` indices), and `31,314` `WORLD_REACH` nodes; `INTRO`'s built world has `158` terrain patches, `26,386` static props (`819,169` vertices, `1,002,135` indices), and `8,336` `WORLD_REACH` nodes.
  On `LOCATION` (`8,251` ticks), frustum-surviving `WORLD_REACH` nodes have median `5`, p95 `122.5`, max `214`, and `#811` distance culling drops `1,198` of `169,636` frustum node-frame visits (`mean 20.6 -> 20.4`); on `INTRO`, `437` node-frame visits survive frustum (`0` dropped by distance cull).
- **Draw distribution (`med / p95 / max`):**
  - `LOCATION` whole (`8,251` ticks): `world_total` `229 / 1,033 / 1,962` (`ground` `23+13`, `base` `80+75`, `decal` `12+12` med fill+edge); `view_facing` `33` med (`727.2` mean, `2,782.5` p95, `4,071` max); `actor_unlit` `28` (`65` max); `actor_lit` `80` (`93` max); `shadow` `49` (`62` max); `sprite` `0`; `total` `648 / 3,312 / 4,272` (`1,215.0` mean).
  - `INTRO` whole (`3,807` ticks): `world_total` `36 / 208 / 259`; `view_facing` `1` med (`1,587.8` mean, `8,320` p95, `8,627` max); `actor_unlit` `0` (`15` max); `actor_lit` `199` (`284` max); `shadow` `137` (`221` max); `sprite` `0` (`2` max); `total` `435 / 8,823 / 9,124` (`2,001.3` mean).
  - Span A (`LOCATION 12..=300`, `289` ticks, `eye_y` `7.00 m`): `world_total` `29` (`133` max), `view_facing` `2,411` (`92.7%` of `2,602` med total).
  - Span B (`LOCATION 3680..=3979`, `300` ticks, elevated overview `eye_y` med `125.0 m`): `world_total` `1,828` med (`1,962` max; `base` `596+595`, `decal` `317+317`), `view_facing` `627.5` med (`1,120.7` mean, `3,138` max), `total` `2,555` med (`3,490` max).
  - Span C (`INTRO 2500..=2949`, `450` ticks): `world_total` `52` (`115` max), `view_facing` `4,712` med (`8,421` max), `actor_lit` `257` (`284` max), `shadow` `126` (`221` max), `total` `5,219` med (`8,919` max).
- **Relighting profile.**
  Over `INTRO` (`3,807` ticks), `LitLayout::refresh` produced `26,394` `Keep`, `190` `Rewrite` (`190` ticks, max `1`/tick), and `2,014` `Upload` events (`1,491` ticks, max `11`/tick); vertex welding and outlines can move indices/nodes (even at equal counts) or change vertex/shape counts on pose/light transitions so uploads outnumber in-place rewrites (`144` `Rewrite` vs `466` warm-scan / `472` cold-start `Upload` on Span C).
_Source: [Whole-film draw and relight scans and span selection](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-whole-film-draw-and-relight-scans-and-span-selection)._

## 3. Post-`#644` phase breakdown and A/B probes

`[Bounded Observation]`, 2026-11-21, `6955e159` + `probe.patch`, Windows `mesa-dist-win 25.2.8` (`llvmpipe (LLVM 21.1.7, 256 bits)`) and `RTX 4070 Laptop GPU`, 3 sequential runs per cell (median `[min..max]`; loop spread `0.6%..4.9%`).
Each tested lavapipe A/B probe kept `frames.zst`, `layers.zst`, `shapes.zst`, and `palettes.zst` byte-identical to its span baseline.

| Cell | Span A `LOCATION 12..=300` (289f) | Span B `LOCATION 3680..=3979` (300f) | Span C `INTRO 2500..=2949` (450f) |
|---|---|---|---|
| `lvp_baseline` (`FIF=2`) | `6,370.1 ms` (`22.04 ms/f`) | `5,055.2 ms` (`16.85 ms/f`) | `8,751.5 ms` (`19.45 ms/f`) |
| `lvp_fif1` (`FIF=1`) | `8,012.2 ms` (`+25.8%`) | `6,591.2 ms` (`+30.4%`) | `12,562.4 ms` (`+43.5%`) |
| `lvp_plane_only` (`#919`) | `6,289.5 ms` (`-1.3%`) | `5,311.7 ms` (`+5.1%`) | `8,770.8 ms` (`+0.2%`) |
| `lvp_cull_vf` (`#914`) | `1,236.3 ms` (`4.28 ms/f`, `-80.6%`) | `2,406.9 ms` (`8.02 ms/f`, `-52.4%`) | `2,046.3 ms` (`4.55 ms/f`, `-76.6%`) |
| `rtx4070_baseline` | `1,299.8 ms` (`4.50 ms/f`) | `1,047.1 ms` (`3.49 ms/f`) | `2,588.7 ms` (`5.75 ms/f`) |

- **Submission vs readback wait.**
  Under `FRAMES_IN_FLIGHT=2`, `pass_encode_submit` takes `74.2%..79.5%` of baseline loop wall (`3,752.2..6,647.5 ms`), almost entirely inside `queue.submit`, while `poll_color + poll_plane` sits under `29 ms`.
  Under synchronous `FRAMES_IN_FLIGHT=1`, `queue.submit` drops (`258.9..1,080.2 ms`) and `poll_color` absorbs the unhidden execution wait (`6,282.2 ms`, `5,132.7 ms`, `9,146.9 ms`) while `poll_plane` stays `<= 1.5 ms`.
- **`#914` (`view_facing` frustum cull).**
  Frustum-culling `view_facing` root boxes cuts loop time by `80.6%` (`Span A`), `52.4%` (`Span B`), and `76.6%` (`Span C`), bringing lavapipe below the unculled RTX 4070 loop on Spans A and C.
  Post-cull remaining loop shares: `pass_encode_submit` (`34.5%` Span A, `53.8%` Span B, `22.9%` Span C), `scene_frame` (`19.5%..26.7%`), `readback_copy` (`17.7%..24.1%`), `journal_write` (`4.8%..7.6%`), and on Span C `prepare_relight_decode` (`344.5 ms`, `16.8%`) vs `prepare_relight_upload` (`23.5 ms`, `1.1%`).
- **`#914` as landed.**
  `[Bounded Observation]`, 2026-11-22, `dab2184` against the branch, whole-process wall clock (scene build and renderer open included), 3 interleaved runs per cell.
  `SceneRenderer::prepare` skips a `view_facing` draw whose model box (the union of its roots' subtree boxes) `frustum_keeps` rejects, before its walk; a model with disc rim vertices is kept whenever the lens is not the default, since `squeeze_disc` can then move a rim vertex into the view.
  On a cloud session's Ubuntu 24.04 Mesa 25.2.8 (`llvmpipe (LLVM 20.1.2, 256 bits)`, 4 vCPUs) median wall fell from `15.95 s` to `5.10 s` on Span A (`-68.1%`), `11.93 s` to `6.33 s` on Span B (`-47.0%`) and `21.68 s` to `3.81 s` on Span C (`-82.4%`).
  Before the disc guard, the laptop's mesa-dist-win 25.2.8 fell from `8.11 s` to `2.82 s` (Span A, `-65.2%`), `6.56 s` to `4.02 s` (Span B, `-38.7%`) and `9.44 s` to `2.64 s` (Span C, `-72.0%`), and the RTX 4070 from `3.01 s` to `2.57 s` (Span A, `-14.6%`); the guard cost Ubuntu's Span A, whose lens is 22.1 degrees, `0.55 s`, and not Spans B or C.
  The four stores stayed byte-identical in every cell checked: Spans A, B and C on both lavapipes, Span A on the RTX 4070, and the seven reference films (`28` of `28` files) on Ubuntu lavapipe with and without the guard and on the RTX 4070 without it.
  _Source: [culling view-facing props on the cloud's lavapipe](../../work/2026-11/914_view-facing-cull/journal.md#2026-11-22-culling-view-facing-props-on-the-clouds-lavapipe), [the cull on the RTX 4070 and on Windows lavapipe](../../work/2026-11/914_view-facing-cull/journal.md#2026-11-22-the-cull-on-the-rtx-4070-and-on-windows-lavapipe), [keeping disc props under a zoomed lens](../../work/2026-11/914_view-facing-cull/journal.md#2026-11-22-keeping-disc-props-under-a-zoomed-lens)._
- **`#919` (`plane_texture` without `color_texture`) and `#915` (Span C relight probes).**
  Omitting `color_texture`, `palette_lut`, color readback, and `check_derivable` (`21.4..36.9 ms` baseline) yielded `-1.3%` (`A`), `+5.1%` (`B`), and `+0.2%` (`C`).
  On Span C (`8,751.5 ms`), skipping matching `apex_buffer` rewrites (`144` skipped) ran `8,731.9 ms` (`-0.2%`), a 2-slot relit ring ran `8,695.2 ms` (`-0.6%`), and both combined ran `8,702.4 ms` (`-0.6%`).
- **One-time startup (`build` + `open`).**
  `LOCATION` took ~`750 ms` scene build + `540..555 ms` lavapipe `open` (`451..460 ms` world/shape upload); `INTRO` took ~`185 ms` + `166 ms`.
_Source: [Phase breakdown and isolation probes across three spans](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-phase-breakdown-and-isolation-probes-across-three-spans)._

## 4. Thread scaling under `LP_NUM_THREADS` after `#596` and `#644`

`[Bounded Observation]`, 2026-11-21, `6955e159` + `probe.patch`, `LOCATION` `12..=300` (289 ticks), 3 runs each, stores byte-identical across thread counts.
With staging churn and `121,148` culled world draws removed, `LP_NUM_THREADS` no longer stays flat (`CPU / wall` cores busy in parentheses):
- **Windows `mesa-dist-win 25.2.8` baseline:** `LP=1` `7,031.8 ms` (`1.25`) -> `LP=4` `6,275.0 ms` (`-10.8%`, `1.38`) -> `unset` `6,267.3 ms` (`-10.9%`, `1.46`).
- **Windows `#914` `view_facing`-culled:** `LP=1` `1,625.6 ms` (`1.29`) -> `LP=4` `1,176.1 ms` (`-27.7%`, `1.65`) -> `unset` `1,237.2 ms` (`-23.9%`, `1.61`).
- **WSL 2 Ubuntu 24.04 `mesa-vulkan-drivers 25.2.8` baseline:** `LP=1` `10,715.9 ms` (`1.20`) -> `LP=4` `9,893.8 ms` (`-7.7%`, `1.31`) -> `unset` `9,787.2 ms` (`-8.7%`, `1.36`).
_Source: [Thread scaling under `LP_NUM_THREADS` on Windows and Linux Mesa](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-thread-scaling-under-lp_num_threads-on-windows-and-linux-mesa)._

## 5. Multi-`VkDevice` in-process versus child processes

`[Bounded Observation]`, 2026-11-21, `LOCATION 50..=649` (600 ticks, 12 aligned seconds), 3 runs each across Windows `mesa-dist-win 25.2.8` and WSL 2 Ubuntu 24.04 `mesa-vulkan-drivers 25.2.8`.
Decoded per-tick `indices`, `layers`, `shapes`, and 768-byte palettes across `50..=649` matched the 1-worker store for every multi-worker mode (`LP=1` baseline loop `13,953.9 ms` Win / `21,579.7 ms` WSL; E2E `15,304.3 ms` Win / `23,399.0 ms` WSL).

- **In-process partial scaling vs 4-worker regression.**
  Two threads sharing `offscreen_adapter` (`LP=1`) scaled to `2.21` cores (`8,993.9 ms` loop, `1.55x`) on Windows and `2.07` cores (`15,121.2 ms` loop, `1.43x`) on Ubuntu 24.04, showing Mesa lavapipe does not force strict single-thread serialization across two in-process `VkDevice`s.
  At four workers (`LP=1`), however, shared-instance in-process slowed to `6,727.8 ms` (`2.07x`) on Windows and **regressed** below 2-way on Ubuntu (`15,890.6 ms` loop, `1.36x`, burning `58.22 s` CPU vs `28.51 s` for 1 worker).
  Giving each thread its own `wgpu::Instance`/`Adapter` recovered `1,276.6 ms` on Windows (`5,451.2 ms` loop, `4.15` cores) and `2,762.2 ms` on Ubuntu (`13,128.4 ms` loop, `3.38` cores), so part of the shared-instance loss comes from state shared through one instance (whether `wgpu`'s or Mesa's is not separated), while still trailing child processes.
- **Child processes win on speed and CPU efficiency for modest RSS.**
  Four child processes (`LP=1`) reached `4,344.1 ms` max loop (`3.21x`) / `6,162.1 ms` E2E (`2.48x`, `4.59` cores, `28.28 s` CPU) on Windows and `7,650.1 ms` max loop (`2.82x`) / `9,889.7 ms` E2E (`2.37x`, `4.62` cores, `45.70 s` CPU) on Ubuntu.
  Each extra lavapipe `VkDevice` still adds `751..796 MiB` RSS of device buffers and driver state, close to one process's `889..953 MiB`, so sharing one `FilmScene` and one instance in-process saved `257.5..299.6 MiB` polled RSS at 4 workers (`3,243.6` vs `3,501.1 MiB` Win; `3,287.1` vs `3,586.7 MiB` WSL; Windows private commit `4,535.3` vs `5,783.1 MiB`).
_Source: [Multi-`VkDevice` in-process versus child processes on Windows and Linux Mesa](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-multi-vkdevice-in-process-versus-child-processes-on-windows-and-linux-mesa)._

## 6. Optimization verdicts

- **`#914`: Go, landed** (`view_facing` frustum culling cuts `52.4%..80.6%` of loop wall across the three spans, and `38.7%..72.0%` of whole-process wall on Windows lavapipe as landed before its disc guard, section 3; actor/shadow/sprite culling and instancing defer/follow-up).
- **`#916`: Go via chunked child processes** (`2.82x..3.21x` loop / `2.37x..2.48x` E2E at 4 workers with `~953 MiB` / `0.93 GiB` Linux RSS budget/worker); **no-go** on in-process multi-`VkDevice` pooling.
- **`#919`: No-go** (`-1.3%` to `+5.1%` loop impact while dropping `check_derivable` validation of LUT output).
- **`#915` sub-items:** (a) bind-state dedup **defer** (`scene_draw <= 1.1%` post-`#914`); (b) relit vertex ring + apex-skip **no-go** (`-0.6%` combined; `Refresh::Upload` dominates under welding, and CPU decode exceeds GPU upload by `> 12x`); (c) apex-free world layout **defer** (revisit for `~76.7 MiB`/worker RAM headroom under `#916`); (d) pass discard / single poll / CPU readback reuse **defer** (`poll_plane < 0.8 ms`; `OffscreenTarget` already reuses GPU `[Readback; 2]` staging buffers).
- **`#920`: Defer** (`LOCATION` `world_total` median `229`, p95 `1,033`, max `1,962`; Span B post-`#914` runs `8.02 ms/f` without un-baking `56,395` static props).
_Source: [Qualitative go, defer, and no-go verdicts](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-qualitative-go-defer-and-no-go-verdicts)._

## Ruled out

* **Pre-`#644`/`#596` `LP_NUM_THREADS` invariance on `52d84e6`** (mesa-dist-win 25.2.8): `GALLIVM_PERF=nopt` (`47.5 s` against `48.4 s` over `LOCATION 12-100`) and `LP_NUM_THREADS` = `1`, `4`, or unset left runtime flat (`~151 s`, `1.00` core) while per-draw staging allocation held ~half of main-thread samples (`#596`).
  Section 4 supersedes this for post-`#644` trees, where `LP_NUM_THREADS=4` cuts Span A by `10.8%` (`27.7%` after `#914`).
  _Source: [2026-11-15](../../work/2026-11/596_lavapipe-staging-buffers/journal.md#2026-11-15-one-model-matrix-upload-per-frame) and [2026-11-21](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-thread-scaling-under-lp_num_threads-on-windows-and-linux-mesa)._
* **Coalescing contiguous world base slices as a speed-up** (`LOCATION` `12..=300`): zero adjacent pairs continue the previous slice's index range (`#603` no-go); [journal](../../work/2026-11/603_draw-counts-per-frame/journal.md#2026-11-16-draws-per-frame-and-coalescing-adjacent-base-slices).
* **Single `plane_texture` offscreen target (`#919`) as a speed-up** (`LOCATION` Spans A/B and `INTRO` Span C, mesa-dist-win 25.2.8): `-1.3%`, `+5.1%`, and `+0.2%` loop change; [journal](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-phase-breakdown-and-isolation-probes-across-three-spans).
* **Skipping matching `apex_buffer` rewrites or double-buffering `LitShape` (`#915`b) on `INTRO`:** `-0.2%`, `-0.6%`, and `-0.6%` combined on Span C (`31.4 ms` baseline / `23.5 ms` post-`#914` total relight upload time vs `379.9 ms` / `344.5 ms` CPU decode); [journal](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-phase-breakdown-and-isolation-probes-across-three-spans).
* **In-process multi-`VkDevice` pooling for 4 chunk workers (`#916`):** regresses on Ubuntu 24.04 Mesa 25.2.8 (`15.89 s` loop / `58.22 s` CPU vs `7.65 s` / `45.70 s` across 4 child processes) and trails child processes on Windows (`6.73 s` shared / `5.45 s` separate instances vs `4.34 s`); [journal](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-multi-vkdevice-in-process-versus-child-processes-on-windows-and-linux-mesa).
* **A cloud session as the place to measure `#629`'s relit-vertex rewrite cost** (Ubuntu Mesa 25.2.8, 4 vCPUs): whole `INTRO` took `147.4 s` and `129.5 s` with rewrite against `133.7 s` without it (`[Bounded Observation]`); [journal](../../work/2026-11/629_relight-cost/journal.md#2026-11-18-the-rewrites-cost-on-the-clouds-lavapipe).

## Open questions

1. After `#914` lands `view_facing` frustum culling, how much further `view_facing` instancing saves on surviving forested views (`INTRO` `2500..=2799`), and whether CPU-side `collect_world_meshes` caching (`~3.6..6.3 ms` on `LOCATION` close-ups, `~17.2..28.9 ms` on wide views) or CPU readback `Vec` reuse inside `readback_copy` (`OffscreenTarget` already reuses its `[Readback; 2]` GPU staging buffers; `readback_copy` takes `~274..492 ms` across `289..450` frames) shifts the bottleneck on hardware GPU and post-`#914` lavapipe.
2. What Linux/Mesa lock causes 4-way in-process separate `wgpu::Instance` devices (`13.13 s` / `52.71 s` CPU) to trail 4 child processes (`7.65 s` / `45.70 s` CPU) on Ubuntu Mesa 25.2.8.
