---
summary: "Which renderer changes cut headless render time on lavapipe and the GPU, and where the time goes now. Landed: #596, #602, #644, #811, the view-facing cull #914 (52.4% to 80.6% of the Windows lavapipe loop in its probe), #933, #942, #943 and #944, and stuntreel --workers (#916): four child processes render LOCATION 1.85x faster on 4 vCPUs, while four in-process VkDevices sharing one instance regress on Ubuntu Mesa 25.2.8. On lavapipe the world's base and decal draws hold 49.0% of the whole LOCATION loop, on Span B mostly the decal fill-to-outline switch (by elimination). No-go: culling actors, #919, #915b, #926, #622 and #920; #1000 awaits the owner's ruling."
---
# Parity: Render Time on Lavapipe

* **Scope**: how long a headless render takes on lavapipe, Mesa's software Vulkan driver, and on the GPU, and which renderer changes cut it; split from [`lavapipe.md`](lavapipe.md), which holds how lavapipe's frames differ from the GPU's.
* **Sources**: `cdb` stack samples, timed renders and CPU counts from #596 to #1000, on mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and the RTX 4070 laptop, set up by [`render-on-lavapipe.md`](../../docs/howto/render-on-lavapipe.md), Ubuntu 24.04's `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`) under WSL 2, and a cloud Ubuntu session (4 vCPUs).
  * **Evidence tier**: `[Bounded Observation]` throughout unless a claim says otherwise; each figure holds for the tree, machine and span it names.
* **Spans**: Span A is `LOCATION 12..=300` (289 ticks, eye at `7.00 m`), Span B `LOCATION 3680..=3979` (300 ticks, an elevated overview, median eye `125.0 m`) and Span C `INTRO 2500..=2949` (450 ticks); the whole films are `LOCATION 12..=8262` (8,251 ticks) and `INTRO 12..=3818` (3,807 ticks).
  The loop is the per-tick render loop; whole-process wall adds the scene build and the renderer open.

## 1. Changes that cut render time

Each landed change but #811, whose effect on the stores this note does not record, left the render stores (`frames.zst`, `layers.zst`, `palettes.zst`, and `shapes.zst` once it existed) byte-identical on the ticks its journal entry names.
Each row's before is its own tree, so the rows do not chain (one machine took 88.7 s on lavapipe for `5844b4b8`, #602's before, against 81.8 s for `80a3ad5`, #596's after).

| Change | What it does | Measured cut |
|---|---|---|
| One matrix upload per frame (#596) | Packs a frame's model matrices into one uniform buffer at dynamic offsets, uploaded with one `write_buffer`, where each draw had its own and wgpu allocated a staging buffer per call | Span A 150.5 s to 81.8 s on lavapipe, 20.9 s to 16.0 s on the GPU (one run each); the GPU's whole LOCATION 301.2 s to 229.6 s and INTRO 96.8 s to 67.8 s |
| Two frames in flight (#602) | The headless loop submits tick N+1 before mapping tick N's readback, and delivers pages in tick order (`FRAMES_IN_FLIGHT = 2`) | Span A 88.7 s and 89.9 s to 76.3 s and 78.2 s on lavapipe, 16.7 s and 16.6 s to 12.4 s and 12.6 s on the GPU; back at one frame in flight the Windows lavapipe loop of `6955e159` ran 25.8% to 43.5% longer on Spans A to C |
| World frustum cull (#644) | Culls world nodes whose box lies outside the view | Span A 81.7 s to 13.7 s on lavapipe, 14.6 s to 4.7 s on the GPU (one run each); the median frame's `draw_indexed` calls 127,910 to 6,791 |
| `ScaleReach` gate (#811) | Drops a view-facing prop on a frame once its largest eye-relative coordinate reaches `PLAYONE`'s `scale_index` distance cut ([`world-scene-residuals.md` § 6.4](../playone-exe/world-scene-residuals.md#64-the-ground-decal-pass)) | Span A's median non-world fills 6,764 to 2,571; a dropped prop need not have been in frame (14 in-frame placements past the cut, all on `LOCATION`) |
| View-facing frustum cull (#914) | `SceneRenderer::prepare` skips a view-facing draw whose model box `frustum_keeps` rejects; a model with disc rim vertices is kept under any lens but the default, since `squeeze_disc` can move a rim into view | Windows lavapipe probe on `6955e159`: loop 80.6%, 52.4% and 76.6% shorter on Spans A, B and C, putting lavapipe below the unculled RTX 4070 on A and C. As landed, whole-process wall: Ubuntu lavapipe 68.1%, 47.0% and 82.4% shorter; Windows lavapipe (before the disc guard) 65.2%, 38.7% and 72.0%; RTX 4070 Span A 14.6% |
| World disc guard (#914, PR #947) | The world walk keeps a node whose subtree holds a disc rim vertex ([`GpuNode::discs`](../../crates/stunt-render/src/mesh.rs)) under any lens but the default | A correctness fix: no cost resolved from the noise in eight Windows runs a cell, though it cost Ubuntu lavapipe's Span A (lens 22.1 degrees) 0.55 s of whole-process wall; world slices per frame 16 to 23 (A), 915.5 to 915.5 (B), 34 to 36 (C) |
| Row-wise `read_back` copy (#933) | Reserves each plane's `Vec` once and appends each row with `extend_from_slice`, where a byte-at-a-time iterator built it | `readback_copy` 66.9% to 92.0% shorter on Windows lavapipe and 81.0% to 86.7% on the RTX 4070 (333.7 to 696.9 ms a span); it is now 2.4% to 6.3% of the loop |
| Hoisted shape lookup and gate words (#942) | Looks each view-facing prop's shape up once a scene and computes the camera's gate words once a frame | `scene_frame` medians 20.2% to 51.2% shorter on both adapters and all three spans |
| Shared LOD gate tree (#943) | Tests each shared `SP_1NODE` gate once a frame, not once a prop | `scene_frame` medians a further 39.2% to 73.6% shorter, every cell's ranges disjoint |
| Collision-bearing `shadow_top` walk (#944) | Walks only the placement records with a collision list (`PlacementRecords::collision_bearing`) | `shadow_top` medians 3.0 to 20.3 ms (7.4% to 33.8%) shorter in nine back-to-back pairs a cell, head lower in 7 to 9 of 9 but the ranges overlapping in every cell |
| Workers (#916) | `stuntreel --workers N` renders in N child processes | Section 5 |

#942, #943, #944 and #933 were timed on one machine with other agents rendering: their phase cuts resolve, but their loop medians scattered (#942 `-20.9%..+2.3%` on Windows lavapipe and `-18.6%..-11.6%` on the RTX 4070; #943 down `0.7%..23.0%`, ranges separated in six of nine cells; #933 down `4.0%..28.4%` with Spans A and B's lavapipe ranges overlapping), so no loop saving is claimed for #942, #943 or #944, and #933's is its copy cut.
_Source: [Render time of #596, #602 and #644](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-16-render-time-of-596-602-and-644-on-location-12-300), [draws before and after #644 and #811](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-draws-per-frame-before-and-after-644-and-811), [phase breakdown before #914](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-phase-breakdown-and-ab-probes-before-914), [the view-facing cull as landed](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-the-view-facing-cull-as-landed-914), [the world disc guard](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-culling-actor-bodies-shadows-and-sprites-and-the-world-disc-guard-914), [`read_back`](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-row-wise-read_back-copy-933), [`FilmScene::frame`, #942 and #944](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-filmsceneframe-spent-its-time-942-and-944), [verdicts](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-optimization-verdicts-as-of-f6976e67)._

**Why the staging buffers cost lavapipe.**
Before #596, per-draw staging allocation (`gpu_allocator::FreeListAllocator::allocate`) held about half of lavapipe's main-thread samples, with the process at 1.00 core whatever `LP_NUM_THREADS` was; after it, 16 of 20 main-thread samples waited in `wait_for_fence` and lavapipe's work sat on its command-buffer thread (busy in 52 of 65 samples, [#600](https://github.com/neilsh/stunt-reel/issues/600)).
Why the allocation costs more on lavapipe than on the NVIDIA driver is not measured.
Before #602 the offscreen target waited for each frame's readback, so the main thread and that command-buffer thread did not overlap.
_Source: [Render time of #596, #602 and #644](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-16-render-time-of-596-602-and-644-on-location-12-300), [`lavapipe.md` distillation](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-one-model-matrix-upload-per-frame)._

## 2. Draws per frame

**The world.**
`LOCATION`'s built world has 158 terrain patches, 56,395 static props (6,702,570 vertices, 7,488,138 indices, uploaded as one chunk) and 31,314 `WORLD_REACH` nodes; `INTRO`'s has 158 patches, 26,386 props (819,169 vertices, 1,002,135 indices) and 8,336 nodes.
On `LOCATION` the frustum-surviving `WORLD_REACH` nodes number a median 5, p95 122.5 and max 214 a frame, and #811's distance cut drops 1,198 of 169,636 node-frame visits; on `INTRO` 437 node-frame visits survive the frustum and none is dropped.
_Source: [draws by category after #644 and #811](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-draws-by-category-after-644-and-811)._

**By category.**
CPU scans on `6955e159` matched live Windows lavapipe `SceneRenderer::draw` counts on every frame of Spans A, B and C; #914 left the world draws and `WORLD_REACH` survivors unchanged (CPU scan on `682f74c`).
Medians (p95, max) per frame:

| Draws | `LOCATION` whole | `INTRO` whole | Span A | Span B | Span C |
|---|---|---|---|---|---|
| World (fill + outline) | 229 (1,033, 1,962) | 36 (208, 259) | 29 (max 133) | 1,828 (max 1,962): base 596 + 595, decal 317 + 317 | 52 (max 115) |
| View-facing before #914 | 33 (2,782.5, 4,071) | 1 (8,320, 8,627) | 2,411 | 627.5 (max 3,138) | 4,712 (max 8,421) |
| View-facing after #914 | 0 (42, 245) | 0 (188, 237) | 0 on every frame | at most 10 | 0 on every frame |
| Actors, lit / unlit | 80 / 28 | 199 / 0 | | | 257 lit (max 284) |
| Shadows | 49 (max 62) | 137 (max 221) | | | 126 (max 221) |
| Total after #914 | | | 191 | 1,989 | 480 |

Before #644 the median Span A frame encoded 127,910 calls, 74.1% of them world base fills and outlines; because the world is one chunk and the walk visits child slices in reverse index order, coalescing contiguous slices removed no call (#603).
_Source: [draws by category after #644 and #811](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-draws-by-category-after-644-and-811), [view-facing draws after #914](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-view-facing-draws-after-914), [draws before and after #644 and #811](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-draws-per-frame-before-and-after-644-and-811)._

**Relighting.**
Over `INTRO`, `LitLayout::refresh` produced 26,394 `Keep`, 190 `Rewrite` (at most 1 a tick) and 2,014 `Upload` events (at most 11 a tick): vertex welding and outlines can move indices or nodes, or change vertex or shape counts, on a pose or light change, so uploads outnumber in-place rewrites (144 `Rewrite` against 466 to 472 `Upload` on Span C).
_Source: [draws by category after #644 and #811](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-draws-by-category-after-644-and-811)._

## 3. Where loop time goes

**After #914 (`682f74c`, #931's probe, before #933 and #942 to #944).**
Loop medians on Windows lavapipe were 1,292.8, 2,467.4 and 2,089.6 ms on Spans A, B and C, and on the RTX 4070 852.4, 863.8 and 1,499.2 ms.
`pass_encode_submit` took 22.8% to 53.9% of the lavapipe loop (largest on Span B) and 2.9% to 11.4% of the GPU's; `scene_frame` 19.7% to 30.4% and 27.9% to 39.1%; `readback_copy` 17.2% to 21.8% and 26.6% to 31.8%; and on Span C `prepare_relight_decode` 16.8% and 22.9%.
`prepare_world` (whose main call is `collect_world_meshes`) took at most 0.3% to 2.1% and `prepare_view_facing` 0.4% to 2.9% on either adapter.
In the pre-#914 probe `pass_encode_submit` was almost all `queue.submit` and the readback polls took under 29 ms a span; at one frame in flight `poll_color` absorbed the execution wait.
#933 has since cut `readback_copy`, and #942 to #944 `scene_frame` (section 1).
_Source: [where loop time went after #914](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-loop-time-went-after-914-931), [phase breakdown before #914](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-phase-breakdown-and-ab-probes-before-914), [the #919 and #915 probes](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-the-919-and-915-probes-and-one-time-startup)._

**Inside `FilmScene::frame` (`9ccfd39c`, before #942).**
Collecting the view-facing props took 82.4% to 92.6% of `scene_frame` on every span and adapter: each frame scanned all of them (20,916 on `LOCATION`, 15,663 on `INTRO`), looked each shape up and tested each prop's `SP_1NODE` and distance gates (65,606 to 116,791 tests a tick), to keep 1,099 to 3,191 props that `SceneRenderer::prepare`'s cull then nearly all dropped.
On Windows lavapipe the gate tests took 61.8% to 76.7% of `scene_frame` and the shape lookup 12.9% to 13.6%, though on `stuntreel`'s path it rejects no prop (`FilmScene::drawn_only` keeps every view-facing prop's shape).
`LOCATION`'s props hold 132,383 gate references but 42,652 distinct gates; since #943 a frame tests at most 48,604 on `LOCATION` (27,719 `SP_1NODE` branches and 20,885 per-prop distance gates) and 36,584 on `INTRO` (20,985 and 15,599), a bound counted from the world's nodes and props, not from tests made.
`shadow_top` took 6.8% to 15.3% of `scene_frame`, largest on Span C (6.36 shadowed actors a tick against 1 on `LOCATION`), walking up to every placement record (56,585 or 26,386) per shadowed actor, stopping only at a carry, though only 4,085 or 2,979 carry a collision list; after #944 it still takes 16.2 to 74.1 ms a span at the median, and the visits #944 removed were roughly 7% to 34% of it.
Timeline sampling (0.2% to 0.4%), the other per-actor work and `sprite_draws` (each at most 1.0%) are small.
_Source: [`FilmScene::frame`, #942 and #944](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-filmsceneframe-spent-its-time-942-and-944), [verdicts](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-optimization-verdicts-as-of-f6976e67)._

**The world's base and decal draws on lavapipe (#920, `67f409b7`).**
Skipping all four kinds (base and decal, fill and outline) cut the whole `LOCATION` film's lavapipe loop 49.0% (27,986 to 14,272.5 ms, on `dc9622ea`) and Span B's 70.7% to 72.9%; on the RTX 4070 the whole film's fell 5.8% and Span B's 20.6% to 26.8%.
On Span B the decal fills alone cut 42.9% and the decal outlines alone 47.4%, not additive: encoding each world draw's decal fills together and then its outlines, every draw and pixel kept, cut 40.2%, which puts the fill-to-outline pipeline switch at about 55% of what the four skips save there (attributed by elimination).
A 1-pixel scissor on every world base and decal draw cut Span B only 11.8%, the base outlines alone 11.1%, the base fills alone 5.3% (unresolved).
Over the whole film (2 rounds) outlines and pixels weigh more: base outlines `-23.1%`, the scissor `-26.1%`, the decal grouping `-7.7%`, all four `-48.0%`.
The draws skipped carry a median 4,423 vertices a frame on Span B (1,000 over the whole film), so their cost is not fill-vertex work (their outlines were not counted).
On Span A the resident set's 172.6 MiB rise during rendering does not move with these draws.
_Source: [the world base and decal draws](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-the-world-base-and-decal-draws-cost-sits-920), [verdicts](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-optimization-verdicts-as-of-f6976e67)._

**The plane shader's `prop_shape` lookup (#920, `a0fcd348`).**
Replacing its binary search of the world's prop runs (31,441 on `LOCATION`) with a constant shape word cut the lavapipe loop 5.9% on Span B and 10.8% over the whole film (about 0.35 ms a frame), faster in 4 of 4 pairs, and moved nothing resolved on RTX 4070 Span B; the shapes store differed, so it is a probe, and 10.8% bounds what a per-vertex `shape_id` could save, from above.
_Source: [the per-fragment `prop_shape` lookup](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-what-the-per-fragment-prop_shape-lookup-costs-920)._

**Decal pipeline switches batching would leave (#1000, `7bfc6cca`, CPU count).**
Each world decal slice switches pipelines twice a frame (fill, then outline), or once with no outline.
Greedy batches of consecutive slices whose node boxes, projected to 320×200 and grown 1 pixel, are pairwise disjoint would leave 228,160 of the whole `LOCATION` film's 421,326 switches (54.2%, 1.85 slices a batch) and 53,728 of Span B's 117,228 (45.8%, 2.18 a batch); with the boxes not grown, 43.6% and 29.4%, a sensitivity run.
_Source: [decal pipeline switches](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-decal-pipeline-switches-batching-would-leave-1000)._

**Startup (#920, the `a0fcd348` binary).**
On the whole `LOCATION` film the scene build took 894 ms on lavapipe and 888 ms on the RTX 4070, and the renderer open 650 and 796 ms: 5.3% and 15.1% of a single process's wall.
The world's CPU build is 622 ms of the scene build (382 ms of it `TerrainSurface::new` and `build_world_ir`, under one timer) and its device upload 471 and 520 ms of the open; the shape uploads take 1.2 ms.
Against a 4-worker chunk estimated as a quarter of the loop plus startup (not measured; no multi-worker RTX 4070 run exists), startup is 18.5% and 43.9% on `LOCATION` and 58.1% and 72.3% on Span C, and a cached world build would save at most 7.5% and 16.2% of a chunk; the upload is per device.
_Source: [per-worker startup](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-per-worker-startup-goes-920), [the #919 and #915 probes and startup](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-the-919-and-915-probes-and-one-time-startup)._

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

**Shipped as `stuntreel --workers N` (#916).**
`[Bounded Observation]`, 2026-11-22, one run per cell on a cloud Ubuntu session (4 vCPUs, 15 GiB, `llvmpipe (LLVM 20.1.2, 256 bits)`).
At 2 and 4 workers, in one run each, every file of the render directory matched the 1-worker render on all seven reference films' captured tick ranges.
Against one process at lavapipe's default `LP_NUM_THREADS`, 4 workers cut the whole `LOCATION` render (8,251 ticks) from `140.5 s` to `76.1 s` (`1.85x`) and `INTRO` (3,807 ticks) from `84.7 s` to `42.2 s` (`2.01x`), at about the same total CPU (`253.7 s` against `260.7 s` for `LOCATION`, `139.4 s` against `135.1 s` for `INTRO`), with no child above `949 MiB` peak RSS.
Two workers were slower than one on `BOMB` (`31.5 s` against `30.3 s`) and `CTRY` (`6.8 s` against `6.2 s`), so the gain is not monotonic in workers for short films.
A seven-film `mise run parity -- --software-only` took `201.3 s` at `--workers 1` (4 jobs), `185.1 s` at 2 (2 jobs) and `192.7 s` at 4 (1 job): on 4 vCPUs four film jobs already fill the cores, so the workers pay off for one film rendered alone or when cores outnumber the films.
_Source: [Worker processes on the cloud's lavapipe over the seven reference films](../../work/2026-11/916_chunked-render-workers/journal.md#2026-11-22-worker-processes-on-the-clouds-lavapipe-over-the-seven-reference-films)._

## 6. Deferred and pending

- **#915 (a) bind-state dedup, defer:** `scene_draw` is at most 1.1% of the loop after #914.
- **#915 (c) apex-free world layout, defer:** revisit for about 76.7 MiB a worker of RAM headroom under #916.
- **#915 (d) pass discard, single poll and CPU readback reuse, defer:** `poll_plane` is under 0.8 ms, `OffscreenTarget` already reuses its `[Readback; 2]` staging buffers, and after #933 the copy needs no `Vec` reuse.
- **#920's memory case:** with the world not uploaded at all (Span A, one run each) the post-upload resident set fell 413.4 MiB on lavapipe (499.4 to 86.0) and 106.1 MiB on the RTX 4070 (267.8 to 161.7), and the peak 555.7 and 301.0 MiB, upper bounds on what un-baking could save.
  A CPU count puts 333.75 MiB in `LOCATION`'s world buffers, 318.04 MiB (95.4% of the vertices) in nodes un-baking would drop; un-baking would drop 281.5 MiB of buffers net with `outlined()` quads or 308.1 MiB with line-list outlines, once its 823 shapes and 28,434 per-placement entries are added (buffer bytes, not a measured fall; the world's `GpuNode` arena is 56.5 MiB of the 79.7 MiB between 333.75 and 413.4 MiB).
  Memory gives no go while no parity machine is short of it: the trigger to revisit is one whose cores, times about 0.93 GiB a worker (section 5), exceed its RAM.
  The owner has since ruled that architecture alone can justify un-baking if it costs no performance: [`#999`](https://github.com/neilsh/stunt-reel/issues/999) carries that, with its gates.
- **#1000, decal batching by screen box, awaits the owner's ruling on scope:** the issue's rule, "if batching leaves most switches in place, close this issue", names no scope, and the conservative count leaves most of the whole film's switches (54.2%) but not most of Span B's (45.8%); the ceiling is #920's grouping probe, `-7.7%` of the whole film's loop with about every switch gone, which gives about 3.5% (proportional to switches removed) to 3.7% (weighted by each span's own saving), both inferences, not measured, under the issue's 5% gate; with the boxes not grown, 4.3% to 4.6%, still under it.

_Source: [verdicts](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-optimization-verdicts-as-of-f6976e67), [decal pipeline switches](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-decal-pipeline-switches-batching-would-leave-1000)._

## Ruled out

* **`LP_NUM_THREADS` or `GALLIVM_PERF=nopt` before #596 and #644** (`52d84e6`): `LP_NUM_THREADS` 1, 4 or unset left Span A flat at about 151 s and 1.00 core, and `nopt` took 47.5 s against 48.4 s on `LOCATION 12-100`, while staging allocation held half the main-thread samples; section 4 supersedes it; [journal](../../work/2026-11/596_lavapipe-staging-buffers/journal.md#2026-11-15-one-model-matrix-upload-per-frame).
* **Coalescing world base slices (#603, #622):** in node creation order no slice continues the previous one's index range (#603); laid out in walk order they merge (Span B 1,170 to 197 base draws a frame, the 28 stores byte-identical), but Span B's lavapipe loop fell only 4.4% to 4.8% over 16 pairs, under the 5% gate, the whole film's did not resolve, and peak memory rose transiently during the upload (a second copy), 11.4 MiB on lavapipe and 68.6 to 76.0 MiB on the RTX 4070; a revival needs an upload that reorders without a second copy; [#622 journal](../../work/2026-11/622_walk-order-indices/journal.md#2026-11-22-the-whole-film-span-a-on-the-rtx-4070-peak-memory-and-the-decision), [patch](../../work/2026-11/622_walk-order-indices/walk-order-layout.patch).
* **One `plane_texture` target without `color_texture` (#919):** `-1.3%`, `+5.1%` and `+0.2%` of the loop on Spans A to C, while dropping `check_derivable`'s validation of the LUT output; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-the-919-and-915-probes-and-one-time-startup).
* **Skipping matching `apex_buffer` rewrites or a 2-slot relit ring (#915 b):** `-0.2%`, `-0.6%` and `-0.6%` combined on pre-#914 Span C, where the relight upload took 31.4 ms against 379.9 ms of CPU decode; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-the-919-and-915-probes-and-one-time-startup).
* **In-process multi-`VkDevice` pooling for 4 workers (#916):** regresses on Ubuntu (15.89 s loop, 58.22 s CPU, against 7.65 s and 45.70 s in 4 child processes) and trails child processes on Windows (6.73 s shared, 5.45 s separate instances, against 4.34 s); section 5.
* **View-facing instancing (#926) after #914:** the forested `INTRO 2500..=2799` keeps no view-facing draw, Span B at most 10, no frame of either film more than 245; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-view-facing-draws-after-914).
* **Frustum-culling actor bodies, shadows and sprites after #914:** the actor-body slices fell (110 to 0 a frame on Span B) but no loop change resolved from the noise on either adapter (GPU Span B, with nearly every actor draw gone, ran 3% to 7% slower), and their CPU preparation is 0.25% to 1.19% of the loop, so the code and its pose handling buy nothing measured (skipping every actor and its relight cut the lavapipe loop 20% on A and 22.5% on C, B unchanged: what actors cost, not their off-screen draws); [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-culling-actor-bodies-shadows-and-sprites-and-the-world-disc-guard-914), which keeps the patch.
* **Caching `collect_world_meshes` after #914:** `prepare_world` is at most 0.3% to 2.1% of the loop on Windows and Ubuntu lavapipe and the RTX 4070; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-loop-time-went-after-914-931).
* **A cloud session as the place to measure #629's relit-vertex rewrite cost:** whole `INTRO` took 147.4 s and 129.5 s with the rewrite against 133.7 s without; [journal](../../work/2026-11/629_relight-cost/journal.md#2026-11-18-the-rewrites-cost-on-the-clouds-lavapipe).
* **Speeding up timeline sampling, per-actor matrices, light, angle bank or `sprite_draws` (#934):** each is at most 1.0% of `scene_frame` (merging the previous tick's two samples would save under 0.1%); [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-filmsceneframe-spent-its-time-942-and-944).
* **Un-baking the world's static props for a per-placement cull (#920):** skipping the world's base and decal draws, the saving's upper bound, cuts the whole `LOCATION` loop 49.0%, but no placement on `LOCATION` or `INTRO` has geometry in the shared `WORLD_BASE` or `WORLD_DECAL` run (342 and 18 terrain indices): each lies in nodes made for it alone, already culled on their own boxes, so a per-placement frustum test removes 0% of the 35,456,495 base and decal vertices drawn over the film, against a 30% bar; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-optimization-verdicts-as-of-f6976e67).
* **The world draws' Span B lavapipe cost as pixel work or as the base outlines (#920):** a 1-pixel scissor left 88.2% of Span B's loop and the base outlines alone saved 11.1%, though over the whole film the scissor recovers 26.1% and the base outlines 23.1%; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-the-world-base-and-decal-draws-cost-sits-920).
* **The per-fragment `prop_shape` lookup as the world draws' lavapipe cost (#920):** a constant saves 10.8% of the whole film's loop against the 49.0% the base and decal draws take; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-what-the-per-fragment-prop_shape-lookup-costs-920).

## Open questions

1. What inside lavapipe makes the world decal slices' fill-to-outline alternation cost Span B's loop: grouping saves 955 ms of 2,377 ms, attributed to the switches by elimination, and the rest of the world's draws cost 779 ms more; whether a state or binning flush at the switch is the cost, what the 779 ms is, and why the whole film leans toward outlines and pixels (2 rounds) are open.
   The memory rise during rendering is not these draws either: its timing is consistent with lavapipe filling the world's device buffers at the first submit ([`evidence-limits.md`](evidence-limits.md), `[Supported Inference]`), though it is about half of the world's 333.75 MiB of buffers; untested.
2. What the loop gains from #942's hoist and #943's gate tree on Ubuntu lavapipe, where neither was measured, and whether the Windows loop drop survives a run under controlled load (on Span B `scene_frame` fell 31.1% and 40.2% while the loop moved `+2.3%` and `-3.6%`).
3. What Linux/Mesa lock makes 4 in-process devices with separate `wgpu::Instance`s (13.13 s, 52.71 s CPU) trail 4 child processes (7.65 s, 45.70 s CPU) on Ubuntu Mesa 25.2.8.
4. How much `mise run parity -- --software-only --workers N` saves on a machine with more cores than films, such as an 8-core laptop, and whether `LOCATION` should take more workers than the shorter films, since on 4 vCPUs the run gained about 8% at best (section 5).
5. Whether a per-vertex (or per-instance) `shape_id` costs less than the 10.8% of the whole `LOCATION` lavapipe loop the constant saved: what a carried id adds to the vertex fetch and the upload, and how much of the saving is the shapes plane compressing differently, are not measured.
6. How the 272 ms of `LOCATION`'s scene build outside `build_world` and the 177 to 274 ms of the renderer open outside its two uploads divide, whether four real `--workers` each pay the full startup, and what reading a cached world build would cost.
