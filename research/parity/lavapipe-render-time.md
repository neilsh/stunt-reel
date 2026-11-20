---
summary: "One matrix upload per frame nearly halved lavapipe's LOCATION render time, and keeping two frames in flight cut it further with the stores still identical over the seven films' captured ticks on the GPU and LOCATION ticks 12-300 on lavapipe. A LOCATION frame encodes 127,910 `draw_indexed` calls, nearly three quarters of them world base fills and outlines, none of which coalescing contiguous base slices in walk order removes on LOCATION; culling world nodes outside the view frustum cuts the median frame to 6,791 calls and LOCATION ticks 12-300's lavapipe render time by 83% (one run), with the stores byte-identical over every film's captured ticks."
---
# Parity: Render Time on Lavapipe

* **Scope**: how long a headless render takes on lavapipe, Mesa's software Vulkan driver, and on the GPU, and which renderer changes cut it; split from [`lavapipe.md`](lavapipe.md), which holds how lavapipe's frames differ from the GPU's.
* **Sources**: `cdb` stack samples and timed renders from #596, #602, #603, #644 and #629, on mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and the RTX 4070 laptop, set up by [`render-on-lavapipe.md`](../../docs/howto/render-on-lavapipe.md), and Ubuntu's `mesa-vulkan-drivers` 25.2.8 in a cloud session.
* **Evidence tier**: stated at the start of each section.

## 1. Render time

`[Bounded Observation]`, 2026-11-15 to 2026-11-16, mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and the RTX 4070 on the same laptop, LOCATION ticks 12-300, headless at 320×200.
Each change left the render stores (`frames.zst`, `layers.zst`, `palettes.zst`) byte-identical, on lavapipe over LOCATION ticks 12-300 and on the GPU over every reference film's captured ticks.
Each row's before is its own tree, so the rows do not chain (this machine took 88.7 s on lavapipe for `5844b4b8`, #602's before, against 81.8 s for `80a3ad5`, #596's after):

| Change | Lavapipe before, after | GPU before, after |
|---|---|---|
| One matrix upload per frame (#596, after on `80a3ad5`, one run each) | 150.5 s, 81.8 s | 20.9 s, 16.0 s |
| Two frames in flight (#602, `5844b4b8` before, two runs each) | 88.7 s and 89.9 s, 76.3 s and 78.2 s | 16.7 s and 16.6 s, 12.4 s and 12.6 s |
| Frustum cull (#644, `857f80a8` before, PR #652 at `3e956d1a` after, one run each) | 81.7 s, 13.7 s | 14.6 s, 4.7 s |

#596 also cut the GPU's full captures, LOCATION's (ticks 12-8262) from 301.2 s to 229.6 s and INTRO's (12-3818) from 96.8 s to 67.8 s.
_Source: [One model-matrix upload per frame](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-one-model-matrix-upload-per-frame), [Two frames in flight](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-two-frames-in-flight), [culling world nodes outside the view frustum](../../work/2026-11/644_frustum-cull/journal.md#2026-11-16-culling-world-nodes-outside-the-view-frustum)._

**One matrix upload per frame (#596).**
`SceneRenderer::prepare` wrote each draw's model matrix with its own `write_buffer`, and wgpu allocates a staging buffer per call; on lavapipe that allocation held about half of the main-thread samples, with the process at 1.00 core whatever `LP_NUM_THREADS` was (why it costs more there than on the NVIDIA driver is not measured). #596 packs a frame's matrices into one uniform buffer at dynamic offsets, uploaded with one `write_buffer`.
Afterwards 16 of 20 main-thread samples sit in `wait_for_fence`, inside `vulkan_lvp`, and none in staging allocation, and all-thread samples put lavapipe's work on the one `vulkan_lvp` thread that executes command buffers (busy in 52 of 65 all-thread samples), known by offset only since mesa-dist-win ships no PDBs ([#600](https://github.com/neilsh/stunt-reel/issues/600)); on the GPU only the main thread is busy, 8 of its 42 samples in `GpuModel::collect_world_meshes`.
_Source: [2026-11-15: where a frame's time goes after the change](../../work/2026-11/596_lavapipe-staging-buffers/journal.md#2026-11-15-where-a-frames-time-goes-after-the-change), [One model-matrix upload per frame](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-one-model-matrix-upload-per-frame)._

**Two frames in flight (#602).**
The offscreen target waited for each frame's readback, so the main thread and lavapipe's command-buffer thread did not overlap.
The headless loop now submits tick N+1 before it maps tick N's readback buffers, and waits only for tick N's own submission; pages still reach the sink in tick order.
The seven `mise run parity` score lines do not move.
_Source: [Two frames in flight in headless capture](../../work/2026-11/602_headless-capture-two-frames/journal.md#2026-11-15-two-frames-in-flight-in-headless-capture)._

**Draws per frame (#603, #644).**
Before the cull, the median LOCATION frame (ticks 12-300, `b0f6c120`, the same 289 per-frame counts on both backends) encoded 127,910 `draw_indexed` calls: 8,963 world ground fills and 6,269 ground outlines, 49,257 world base fills and 45,560 base outlines (94,817, 74.1%), 5,550 world decal fills and 5,549 decal outlines, and 6,762 prop, actor and sprite fills.
The world uploads as one chunk of 6,702,496 vertices and 7,488,138 indices, so every base slice draws with base vertex 0 from its own index range, and the base walk emits a parent's child slices in the reverse of their index order; in none of the 289 frames did an adjacent pair of base slices continue the previous one's index range, so coalescing them removes no call (#603's decision: no-go against its 25% bar).
_Source: [Draws per frame](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-draws-per-frame)._

**Frustum cull (#644).**
`[Bounded Observation]`, 2026-11-16, PR #652 at `3e956d1a` against `857f80a8`, mesa-dist-win 25.2.8 and the RTX 4070 laptop, LOCATION ticks 12-300, one run each.
The world walk skips a node whose box around its own and its descendants' vertices lies wholly outside one plane of the view frustum.
Over #603's 289 frames the median frame's `draw_indexed` calls fall from 127,910 to 6,791: the six world categories' medians from 121,148 in sum to 29 (the world's per-frame total at most 133), as these frames look at an aircraft against sea and sky; the 6,762 prop, actor and sprite fills are not culled.

Render times are in the table above.
On top of #636's eye-relative transforms (`e6fb29c`), on `origin/main` `734d3a8`, Ubuntu's Mesa 25.2.8 rendered all seven films' captured ticks byte-identical with and without the cull, 2026-11-17; the GPU was not re-checked there.
`852db54`, which stops moving each box by the node's `local_matrix`, was not re-run; every world node's `local_matrix` is the identity (`stunt_core::world::mesh`), so no box changes.
_Source: [culling world nodes outside the view frustum](../../work/2026-11/644_frustum-cull/journal.md#2026-11-16-culling-world-nodes-outside-the-view-frustum), [the cull on top of eye-relative transforms](../../work/2026-11/644_frustum-cull/journal.md#2026-11-17-the-cull-on-top-of-eye-relative-transforms)._

## Ruled out

* **LLVM shader compilation, or `LP_NUM_THREADS`, as the cost of a lavapipe render** (mesa-dist-win 25.2.8): `GALLIVM_PERF=nopt` (47.5 s against 48.4 s over LOCATION ticks 12-100) and 1, 4 or unset threads left the time and the frames unchanged; [journal](../../work/2026-11/596_lavapipe-staging-buffers/journal.md#2026-11-15-one-model-matrix-upload-per-frame).
* **Coalescing contiguous world base slices as a speed-up** (LOCATION): no adjacent pair of the base list in walk order continues the previous one's index range, so it removes 0 of a frame's 127,910 `draw_indexed` calls on the 289 frames measured (section 1); [journal](../../work/2026-11/603_draw-counts-per-frame/journal.md#2026-11-16-draws-per-frame-and-coalescing-adjacent-base-slices).
* **A cloud session as the place to measure #629's relit-vertex rewrite cost** (Ubuntu's Mesa 25.2.8, 4 vCPUs): a whole INTRO render took 147.4 s and 129.5 s with the rewrite and 133.7 s without it, so mesa-dist-win's 11.4 s cost (one run each way, #474) is smaller than the spread between identical runs there, `[Bounded Observation]`; [journal](../../work/2026-11/629_relight-cost/journal.md#2026-11-18-the-rewrites-cost-on-the-clouds-lavapipe).

## Open questions

1. Which lavapipe functions hold its command-buffer thread, busy in 52 of 65 samples of a 0.28 s LOCATION tick after #596, and whether fewer draws ([#603](https://github.com/neilsh/stunt-reel/issues/603)) shorten it (section 1, [#600](https://github.com/neilsh/stunt-reel/issues/600)); #602 overlapped the readback with the next tick's work, which section 1 measures.
2. Whether caching the world's visible mesh slices while the camera holds still is worth it now that readback overlaps the next tick (#602, section 1): `GpuModel::collect_world_meshes` depends only on the world, the eye, and the authored view's eye, target and lens, and took 8 of 42 GPU main-thread samples in #596's profile.
   The overlap took the GPU run from 16.7 s to 12.4 s, so what remains is the main-thread work plus the part of the wait the pipeline cannot hide; whether a cache shortens that enough to pay is unmeasured.
