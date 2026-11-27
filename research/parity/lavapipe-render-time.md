---
summary: "Which renderer changes cut headless render time on lavapipe and the GPU, and where the loop's time goes now. Landed: #596, #602, #644, #811, the view-facing cull #914 (52.4% to 80.6% of the Windows lavapipe loop in its probe), #933, #942, #943, #944 and stuntreel --workers (#916, in lavapipe-render-workers.md with thread scaling and memory per worker). What the world's draws cost (49.0% of the whole LOCATION lavapipe loop) and where lavapipe spends that time are in lavapipe-world-draws.md. Other processes' CPU load slows the Span B lavapipe loop (16 spinners +75.2%), so mise run ab records and gates on it (#1018). No-go: culling actors, #919, #915b, #926 and caching collect_world_meshes."
---
# Parity: Render Time on Lavapipe

* **Scope**: how long a headless render takes on lavapipe, Mesa's software Vulkan driver, and on the GPU, which renderer changes cut it, and where the loop's time goes; split from [`lavapipe.md`](lavapipe.md), which holds how lavapipe's frames differ from the GPU's.
  What the world's base and decal draws cost, where lavapipe spends that time and how much of the world a frame emits are in [`lavapipe-world-draws.md`](lavapipe-world-draws.md); how a render uses cores and RAM (thread scaling, `--workers`, memory per worker) is in [`lavapipe-render-workers.md`](lavapipe-render-workers.md).
* **Sources**: `cdb` stack samples, timed renders and CPU counts from #596 to #1018, on mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and the RTX 4070 laptop, set up by [`render-on-lavapipe.md`](../../docs/howto/render-on-lavapipe.md), Ubuntu 24.04's `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`) under WSL 2, and a cloud Ubuntu session (4 vCPUs).
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
| Workers (#916) | `stuntreel --workers N` renders in N child processes | [`lavapipe-render-workers.md` § 2](lavapipe-render-workers.md#2-multi-vkdevice-in-process-versus-child-processes) |

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

What the world's base and decal draws cost the loop, and where lavapipe spends it, are in [`lavapipe-world-draws.md`](lavapipe-world-draws.md).

**Startup (#920, the `a0fcd348` binary).**
On the whole `LOCATION` film the scene build took 894 ms on lavapipe and 888 ms on the RTX 4070, and the renderer open 650 and 796 ms: 5.3% and 15.1% of a single process's wall.
The world's CPU build is 622 ms of the scene build (382 ms of it `TerrainSurface::new` and `build_world_ir`, under one timer) and its device upload 471 and 520 ms of the open; the shape uploads take 1.2 ms.
Against a 4-worker chunk estimated as a quarter of the loop plus startup (not measured; no multi-worker RTX 4070 run exists), startup is 18.5% and 43.9% on `LOCATION` and 58.1% and 72.3% on Span C, and a cached world build would save at most 7.5% and 16.2% of a chunk; the upload is per device.
_Source: [per-worker startup](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-per-worker-startup-goes-920), [the #919 and #915 probes and startup](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-the-919-and-915-probes-and-one-time-startup)._

**Timing noise: one binary against itself on Span B (`#1004`, `#1018`).**
`[Bounded Observation]`, Windows `mesa-dist-win 25.2.8`, one release binary as both variants of `mise run ab` ([`time-a-headless-render.md`](../../docs/howto/time-a-headless-render.md) § 3) or run back to back, each figure from one run on one machine; it says nothing about other days or cells.
On `71b6e10d` (`#1004`, 2026-11-23, 4 pairs, the order alternated, load not recorded) the loop medians were `4319.0` and `3914.5 ms` (`-9.4%`), `b` faster in 2 of 4 pairs, the eight runs spread `32.2%` (`3680.8..4867.3 ms`) and the stores hashed alike in every run: the owner's A/A bar (a median within `±1%`) was missed.
On `d4f00c76` (`#1018`, 2026-11-24, the owner's 16-thread Ryzen 7 7745HX laptop, other processes' share of all logical CPUs recorded per run), other load slows the loop: 8 spinning processes (about `55%` of the CPUs) raised the median `19.3%` over a quiet probe's (`2885.5` against `2418.05 ms`) and 16 (about `92%`) `75.2%` (`4237.3 ms`, its runs `4103.2..4318.1 ms`, inside `#1004`'s range); a steady load moved every run alike (spreads `3.7%` and `5.2%` under 8 and 16 spinners).
In `#1018`'s A/A the one run at `10.3%` other load was `16.3%` slower than the slowest of the four runs before it (`2815.1 ms`, at `3.1%..4.5%`); no probe tested whether that load caused it, and in a quiet probe a run at `12.7%` was faster than one at `5.3%` (`2482.7` against `2563.4 ms`).
On a quiet machine (`4.5%..12.7%` other load) seven runs still spread `9.6%` (`2338.1..2563.4 ms`), unexplained by load or by the effective clock (`119.2%..128.5%` of base, which did not order the runs); run order was already ruled out by `#1004`'s A/A, and a slow first run (`11.0%` over the median of the next seven in one quiet probe, the fastest after 120 s idle in another) is not separated from the load of starting the runner.
So `mise run ab` now records other processes' load per run, waits before each timed run for the machine to be at most `10%` busy, stops after a timed run over it, and runs one untimed, ungated warm-up round.
Its A/A with those checks stopped on the load check twice (after 5 and 2 of 8 runs, at `10.3%` and `10.2%` other load); a third, at a `15%` load bar, completed at `8.9%..11.2%` other load with a median change of `-1.07%` against `±1%`, each side faster in 2 of 4 pairs and the eight loops spread `6.2%` (`2302.9..2445.3 ms`): the bar was missed, and the owner accepted that one result as an exception, not a pass.
A Valgrind instruction count of a 30-tick render counted inside its unloaded range in one loaded cloud run, and outside glibc's allocator put #951's `0.13%` cut at 10 times its three-repeat range, at 29 to 49 times the render's wall time ([`lavapipe-instruction-counts.md`](lavapipe-instruction-counts.md), `#1122`).
_Source: [the same binary on both sides of `mise run ab`](../../work/2026-11/1004_ab-timing-runner/journal.md#2026-11-23-the-same-binary-on-both-sides-of-mise-run-ab-span-b-on-lavapipe), [what spreads one binary's Span B lavapipe runs](../../work/2026-11/1018_lavapipe-ab-variance/journal.md#2026-11-24-what-spreads-one-binarys-span-b-lavapipe-runs), [the A/A check after the fix](../../work/2026-11/1018_lavapipe-ab-variance/journal.md#2026-11-24-the-aa-check-after-the-fix-stopped-by-the-load-check), [the second re-run, completed](../../work/2026-11/1018_lavapipe-ab-variance/journal.md#2026-11-25-the-second-owner-approved-aa-re-run-at-a-15-load-bar-completed-missed-the-median-bar); as this note stated [`#1004`](../../work/2026-11/distill-lavapipe-render-time-3/journal.md#2026-11-23-one-binary-against-itself-through-the-interleaved-runner-as--3-stated-it-1004) and [`#1018`](../../work/2026-11/distill-lavapipe-render-time-3/journal.md#2026-11-24-what-spreads-one-binarys-span-b-lavapipe-runs-as--3-stated-it-1018)._

## 4. Deferred and pending

- **#915 (a) bind-state dedup, defer:** `scene_draw` is at most 1.1% of the loop after #914.
- **#915 (c) apex-free world layout, defer:** revisit for about 76.7 MiB a worker of RAM headroom under #916.
- **#915 (d) pass discard, single poll and CPU readback reuse, defer:** `poll_plane` is under 0.8 ms, `OffscreenTarget` already reuses its `[Readback; 2]` staging buffers, and after #933 the copy needs no `Vec` reuse.
- **#920's memory case:** what un-baking the world could save, and when memory would justify it, is in [`lavapipe-render-workers.md` § 3](lavapipe-render-workers.md#3-memory-per-worker); [`#999`](https://github.com/neilsh/stunt-reel/issues/999) carries un-baking on architecture alone, with its gates.

_Source: [verdicts](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-optimization-verdicts-as-of-f6976e67)._

## Ruled out

* **`LP_NUM_THREADS` or `GALLIVM_PERF=nopt` before #596 and #644** (`52d84e6`): `LP_NUM_THREADS` 1, 4 or unset left Span A flat at about 151 s and 1.00 core, and `nopt` took 47.5 s against 48.4 s on `LOCATION 12-100`, while staging allocation held half the main-thread samples; [`lavapipe-render-workers.md` § 1](lavapipe-render-workers.md#1-thread-scaling-under-lp_num_threads-after-596-and-644) supersedes it; [journal](../../work/2026-11/596_lavapipe-staging-buffers/journal.md#2026-11-15-one-model-matrix-upload-per-frame).
* **One `plane_texture` target without `color_texture` (#919):** `-1.3%`, `+5.1%` and `+0.2%` of the loop on Spans A to C, while dropping `check_derivable`'s validation of the LUT output; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-the-919-and-915-probes-and-one-time-startup).
* **Skipping matching `apex_buffer` rewrites or a 2-slot relit ring (#915 b):** `-0.2%`, `-0.6%` and `-0.6%` combined on pre-#914 Span C, where the relight upload took 31.4 ms against 379.9 ms of CPU decode; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-21-the-919-and-915-probes-and-one-time-startup).
* **View-facing instancing (#926) after #914:** the forested `INTRO 2500..=2799` keeps no view-facing draw, Span B at most 10, no frame of either film more than 245; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-view-facing-draws-after-914).
* **Frustum-culling actor bodies, shadows and sprites after #914:** the actor-body slices fell (110 to 0 a frame on Span B) but no loop change resolved from the noise on either adapter (GPU Span B, with nearly every actor draw gone, ran 3% to 7% slower), and their CPU preparation is 0.25% to 1.19% of the loop, so the code and its pose handling buy nothing measured (skipping every actor and its relight cut the lavapipe loop 20% on A and 22.5% on C, B unchanged: what actors cost, not their off-screen draws); [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-culling-actor-bodies-shadows-and-sprites-and-the-world-disc-guard-914), which keeps the patch.
* **Caching `collect_world_meshes` after #914:** `prepare_world` is at most 0.3% to 2.1% of the loop on Windows and Ubuntu lavapipe and the RTX 4070; [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-loop-time-went-after-914-931).
* **A cloud session as the place to measure #629's relit-vertex rewrite cost:** whole `INTRO` took 147.4 s and 129.5 s with the rewrite against 133.7 s without; [journal](../../work/2026-11/629_relight-cost/journal.md#2026-11-18-the-rewrites-cost-on-the-clouds-lavapipe).
* **Speeding up timeline sampling, per-actor matrices, light, angle bank or `sprite_draws` (#934):** each is at most 1.0% of `scene_frame` (merging the previous tick's two samples would save under 0.1%); [journal](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-where-filmsceneframe-spent-its-time-942-and-944).
* **A high priority as a fix for, and the CPU clock as the cause of, `mise run ab`'s spread (`#1018`):** under 16 spinning processes a high-priority render ran `3440.6` and `3478.9 ms`, then `27598.8 ms`, so priority is no stable fix; and the effective clock, `119.2%..128.5%` of base in every run, did not order the loop times; [journal](../../work/2026-11/1018_lavapipe-ab-variance/journal.md#2026-11-24-what-spreads-one-binarys-span-b-lavapipe-runs).

## Open questions

1. What the loop gains from `#942`'s hoist and `#943`'s gate tree on Ubuntu lavapipe, where neither measured, and whether the Windows loop drop survives a run under controlled load: `#943`'s loop medians fell `0.7%..23.0%` across nine cells with ranges separated in six, under other agents' load, so no saving is claimed, and `#942`'s moved `-20.9%..+2.3%` on Windows lavapipe without a stable sign (on Span B `scene_frame` fell `31.1%` and `40.2%` while the loop moved `+2.3%` and `-3.6%`).
2. How the 272 ms of `LOCATION`'s scene build outside `build_world` and the 177 to 274 ms of the renderer open outside its two uploads divide, whether four real `--workers` each pay the full startup, and what reading a cached world build would cost.
3. What spreads one binary's Span B lavapipe loop by `9.6%` on a quiet machine, and `6.2%` across the completed A/A's eight runs at `0.089..0.112` other load (section 3, `#1018`): load and clock did not explain the quiet-run `9.6%`, the `6.2%` was not traced, and the pairs `mise run ab` needs at that spread are in [`lavapipe-ab-pair-count.md`](lavapipe-ab-pair-count.md) (on Span B: about 20 for ±2%, no recommendation for ±1%). A change that cuts instructions can be gated on a count instead, which this spread does not reach ([`lavapipe-instruction-counts.md`](lavapipe-instruction-counts.md)).
