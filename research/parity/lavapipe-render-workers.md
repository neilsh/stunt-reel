---
summary: "How a headless render uses cores and RAM: LP_NUM_THREADS scaling after #596 and #644 (4 threads cut Span A's Windows loop at most 27.7%), in-process VkDevices against child processes (four child processes win; four in-process devices sharing one instance regress on Ubuntu Mesa 25.2.8), stuntreel --workers (#916: four workers render LOCATION 1.85x faster on 4 vCPUs) and what a render's memory goes to per worker: mostly its world mesh (1,004 MiB Linux lavapipe peak, 749 MiB once release_world_mesh frees it; each extra lavapipe device adds 751..796 MiB RSS; un-baking could save at most 413.4 MiB of the post-upload lavapipe resident set and 555.7 MiB of its peak, on Span A)."
---
# Parity: Render Workers and Memory on Lavapipe

* **Scope**: how a headless render on lavapipe, Mesa's software Vulkan driver, and on the GPU uses cores and RAM: thread scaling, in-process devices against child processes, `stuntreel --workers`, and what a render's memory goes to per worker; split from [`lavapipe-render-time.md`](lavapipe-render-time.md), which holds which renderer changes cut render time and where loop time goes.
* **Sources**: timed renders, memory probes and CPU counts from #645 to #920, on mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and the RTX 4070 laptop, Ubuntu 24.04's `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`) under WSL 2, and a cloud Ubuntu session (4 vCPUs).
  * **Evidence tier**: `[Bounded Observation]` throughout unless a claim says otherwise; each figure holds for the tree, machine and span it names.
* **Spans**: as in [`lavapipe-render-time.md`](lavapipe-render-time.md); Span A is `LOCATION 12..=300` (289 ticks) and the whole films are `LOCATION 12..=8262` (8,251 ticks) and `INTRO 12..=3818` (3,807 ticks).
  The loop is the per-tick render loop; whole-process wall adds the scene build and the renderer open.

## 1. Thread scaling under `LP_NUM_THREADS` after `#596` and `#644`

`[Bounded Observation]`, 2026-11-21, `6955e159` + `probe.patch`, `LOCATION` `12..=300` (289 ticks), 3 runs each, stores byte-identical across thread counts.
With staging churn and `121,148` culled world draws removed, `LP_NUM_THREADS` no longer stays flat (`CPU / wall` cores busy in parentheses):
- **Windows `mesa-dist-win 25.2.8` baseline:** `LP=1` `7,031.8 ms` (`1.25`) -> `LP=4` `6,275.0 ms` (`-10.8%`, `1.38`) -> `unset` `6,267.3 ms` (`-10.9%`, `1.46`).
- **Windows `#914` `view_facing`-culled:** `LP=1` `1,625.6 ms` (`1.29`) -> `LP=4` `1,176.1 ms` (`-27.7%`, `1.65`) -> `unset` `1,237.2 ms` (`-23.9%`, `1.61`).
- **WSL 2 Ubuntu 24.04 `mesa-vulkan-drivers 25.2.8` baseline:** `LP=1` `10,715.9 ms` (`1.20`) -> `LP=4` `9,893.8 ms` (`-7.7%`, `1.31`) -> `unset` `9,787.2 ms` (`-8.7%`, `1.36`).
_Source: [Thread scaling under `LP_NUM_THREADS` on Windows and Linux Mesa](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-thread-scaling-under-lp_num_threads-on-windows-and-linux-mesa)._

## 2. Multi-`VkDevice` in-process versus child processes

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

## 3. Memory per worker

What a render's memory goes to, per worker process, which sets the RAM each `--workers` child costs (section 2).
`#622`'s peak memory for the walk-order layout is in [`lavapipe-world-draws.md`'s Ruled out](lavapipe-world-draws.md#ruled-out).

* **A LOCATION render's memory is mostly its world mesh (`[Bounded Observation]`, 2026-11-18 and 2026-11-20: Linux figures on `56a530d`, a cloud session's lavapipe, Ubuntu's Mesa 25.2.8 with LLVM 20.1.2; GPU figures on `4c43baa` and `2ecbad1`, an RTX 4070 Laptop).**
  CTRY's world is 20,044 vertices and its render peaks at 139 MiB; LOCATION's is 6,702,496 vertices, 7,488,138 indices and 12,861,990 outline indices in one chunk, and its render of ticks 12-120 peaked at 1,004 MiB.
  At `48f5d49` LOCATION's world was 795,172 vertices and 6,463 static props against 56,395 now, and the same render on the same lavapipe peaks at 258 MiB.
  Of LOCATION's peak, the built scene held 301 MiB, 253 MiB of it the world mesh's CPU copy; opening the device and uploading the shapes and sprites added 82 MiB, the outline list `plan_edges` builds 61 MiB, and the staging copies `write_buffer` makes of the world's vertex, index and outline buffers 257 MiB.
  Lavapipe fills the device buffers' pages when those copies run, at the first submit, so the first frames held the CPU mesh, the staging copies and the device buffers at once (`[Supported Inference]`: a submit and wait forced straight after the upload raised the high-water mark from 749 to 944 MiB, the upload's 687 MiB plus the buffers' 257).
  `run_headless` frees the CPU mesh after upload, before the first submit (`FilmScene::release_world_mesh`): LOCATION's peak falls to 749 MiB and its steady RSS from about 823 to 563 MiB, with the render stores byte-identical over LOCATION ticks 12-300 and CTRY's captured ticks.
  The world's three device buffers, 257 MiB, are then about half of LOCATION's steady RSS.
  With the mesh freed (`[Bounded Observation]`, `77a9a49`, 2026-11-19, `--report-memory` on Windows), the same render peaked at a 715 MiB working set on mesa-dist-win 25.2.8 and 603 MiB on the RTX 4070; the built scene held 289 MiB on both, and the working set after the last frame was 513 MiB on lavapipe and 233 MiB on the GPU ([`measure-a-renders-memory.md`](../../docs/howto/measure-a-renders-memory.md) § 3).
  At #706's pair on the RTX 4070 (`4c43baa`, its parent, against `2ecbad1`, its merge, `crates` `71486d7` and `a00c4e7`; three runs each), LOCATION ticks 12-120 peaked at about 598 MiB working set at both commits, which puts the peak before `release_world_mesh` runs, while peak private fell about 10 MiB (1,297-1,303 to 1,289-1,291 MiB, about 0.7 GiB above the working set) and the working set after the upload about 256 MiB (483 to 227 MiB, about the CPU mesh's 253 MiB).
  CTRY's captured ticks 14-1333 peaked at 161 MiB working set and 343 MiB private before the change and 160 and 341 MiB after; `nvidia-smi`'s whole-GPU used memory rose from idle to 520 MiB during LOCATION's render and 200 MiB during CTRY's at both commits (200 ms sampling); all seven films' `frames.zst`, `layers.zst` and `palettes.zst` and their scores matched, and every report named the RTX 4070 Laptop GPU.
  A 2026-11-16 reading on that GPU before the mesh was freed (942 MB working set, 1,443 MB private, [#645](https://github.com/neilsh/stunt-reel/issues/645)) is not reproduced at `4c43baa`; the 603 MiB peak `--report-memory` read at `77a9a49` agrees with the pair's, and the gap to 942 MB is not attributed.
  Linux lavapipe's 749 and 556 MiB are `VmHWM` and `VmRSS` on another Mesa build (LLVM 20.1.2 against 21.1.7), so the gaps to them are not attributed.
  For CTRY, one run of a build with `VmRSS` and `VmHWM` probes at `9c9c6a5` (its captured ticks 14-1333) peaked at 144 MiB, against the 139-140 MiB of the unprobed runs at `342cc7a` (`56a530d` plus the freeing change), a gap not explained: RSS is 9 MiB once the scene is built, opening the device and uploading the shapes, sprites and world adds 97 MiB, and the frames that follow 38 MiB more.
  Splitting one film's ticks across processes or devices, set aside in [#645](https://github.com/neilsh/stunt-reel/issues/645) on the assumptions that one queue per device serializes in-process work and that each process repeats the whole memory cost while parity already runs films in parallel (`--jobs`), was measured on both by `#918`: two in-process devices use more than two cores, but four child processes beat four in-process devices, so `--workers` shards a film across child processes ([section 2](#2-multi-vkdevice-in-process-versus-child-processes)).
  _Source: [LOCATION's world at `48f5d49`](../../work/2026-11/645_world-mesh-memory/journal.md#2026-11-18-locations-world-at-48f5d49), [where a LOCATION render's memory goes on lavapipe](../../work/2026-11/645_world-mesh-memory/journal.md#2026-11-18-where-a-location-renders-memory-goes-on-lavapipe), [freeing the world mesh after upload](../../work/2026-11/645_world-mesh-memory/journal.md#2026-11-18-freeing-the-world-mesh-after-upload), [where a CTRY render's memory goes](../../work/2026-11/645_world-mesh-memory/journal.md#2026-11-18-where-a-ctry-renders-memory-goes-on-lavapipe), [`--report-memory` on Windows](../../work/2026-11/769_windows-render-memory/journal.md#2026-11-19---report-memory-on-windows-gpu-and-lavapipe), [the GPU's memory and byte-identity after freeing the world mesh](../../work/2026-11/707_gpu-free-world-mesh/journal.md#2026-11-20-the-gpus-memory-and-byte-identity-after-freeing-the-world-mesh), [multi-VkDevice in-process versus child processes](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-multi-vkdevice-in-process-versus-child-processes-on-windows-and-linux-mesa), [the 2026-11-16 Windows peak](../../work/2026-11/distill-lavapipe-render-time-2/journal.md#2026-11-16-locations-peak-memory-on-windows-before-the-world-mesh-was-freed), [#706's pair as first stated](../../work/2026-11/distill-lavapipe-render-time-2/journal.md#2026-11-20-memory-at-706s-pair-on-the-rtx-4070)._

* **The world has no device buffers since #1093 (`[Bounded Observation]`, 2026-11-28, `181fabc9` against `459f46d2`, `--report-memory` on Windows, 3 runs each).**
  Each frame copies its visible slices into one small buffer, so neither the world's device buffers nor their staging copies exist, while the renderer keeps its own copy of the CPU mesh for the stream after the scene's is freed.
  `LOCATION` ticks 12-120 peaked `285.6` to `287.4` MiB lower on mesa-dist-win 25.2.8 (`1025.3..1026.2` to `738.5..739.7` MiB) and `16.3` to `17.3` MiB lower on the RTX 4070 (`827.9..828.7` to `811.4..811.7` MiB), where the resident set after the renderer opens rose about `277` MiB (`533.9..534.7` to `811.3..811.6` MiB); that the copy is what raised it is `[Supported Inference]`, from its size, not measured.
  _Source: [#1093's gates](../../work/2026-11/999_frame-streamed-world/journal.md#2026-11-28-stage-c-the-stream-as-the-only-world-path-loop-memory-and-stores)._

* **What un-baking the world could save (#920's memory case):** with the world not uploaded at all (Span A, one run each) the post-upload resident set fell 413.4 MiB on lavapipe (499.4 to 86.0) and 106.1 MiB on the RTX 4070 (267.8 to 161.7), and the peak 555.7 and 301.0 MiB, upper bounds on what un-baking could save.
  A CPU count puts 333.75 MiB in `LOCATION`'s world buffers, 318.04 MiB (95.4% of the vertices) in nodes un-baking would drop; un-baking would drop 281.5 MiB of buffers net with `outlined()` quads or 308.1 MiB with line-list outlines, once its 823 shapes and 28,434 per-placement entries are added (buffer bytes, not a measured fall; the world's `GpuNode` arena is 56.5 MiB of the 79.7 MiB between 333.75 and 413.4 MiB).
  Memory gives no go while no parity machine is short of it: the trigger to revisit is one whose cores, times about 0.93 GiB a worker (section 2), exceed its RAM.
  The owner has since ruled that architecture alone can justify un-baking if it costs no performance and moves the renderer toward a more maintainable design: [`#999`](https://github.com/neilsh/stunt-reel/issues/999) carries that, with its gates.

  _Source: [verdicts](../../work/2026-11/distill-lavapipe-render-time/journal.md#2026-11-22-optimization-verdicts-as-of-f6976e67)._

## Ruled out

* **In-process multi-`VkDevice` pooling for 4 workers (#916):** sharing one instance regresses on Ubuntu, and with one instance a device it still trails 4 child processes on both systems; section 2.

## Open questions

1. What Linux/Mesa lock causes 4-way in-process separate `wgpu::Instance` devices (`13.13 s` / `52.71 s` CPU) to trail 4 child processes (`7.65 s` / `45.70 s` CPU) on Ubuntu Mesa 25.2.8.
2. How much `mise run parity -- --software-only --workers N` saves on a machine with more cores than films, such as an 8-core laptop, and whether `LOCATION` should take more workers than the shorter films, since on 4 vCPUs (section 2) the run gained about 8% at best.
