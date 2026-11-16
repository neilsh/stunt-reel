# Journal

## 2026-11-15: one model-matrix upload per frame

- **Question**: Does uploading a frame's model matrices with one `write_buffer`, instead of one per draw, take the staging-buffer allocation out of lavapipe renders, and does it keep the output byte-identical?
- **Method**:
  - Profiled first, on a guarded build of `crates` `52d84e6` (#596's spike, mesa-dist-win 25.2.8):
    - LOCATION ticks 12-300 timed on lavapipe with `LP_NUM_THREADS` set to 1, 4 and unset, and on the GPU.
    - Ticks 12-100 timed with `GALLIVM_PERF=nopt` and with `DRAW_USE_LLVM=0`.
    - 30 non-invasive `cdb` samples of the main thread.
  - Then built `c72727b` without (`mise run build-at`) and with the change (`80a3ad5`, `cargo build --release -p stunt-cli`).
  - Rendered each headless with the parity pipeline's arguments (`--tick-range A..=B --width 320 --height 200 --viewport-rows 185`), on lavapipe (`VK_DRIVER_FILES` naming the 25.2.8 `lvp_icd.x86_64.json`, `--software-only`) and on the RTX 4070. One run each.
  - Compared `frames.zst`, `layers.zst` and `palettes.zst` with `cmp`.
  - Took 20 `cdb` main-thread samples of the lavapipe render after the change, with the matching PDB.
- **Result**:
  - **Spike:**
    - Lavapipe took 151 s against 21 s on the GPU, at 1.00 core whatever `LP_NUM_THREADS` was. `frames.zst` was identical across the three thread settings.
    - Over ticks 12-100, the baseline took 48.4 s. `GALLIVM_PERF=nopt` took 47.5 s with the same frames; `DRAW_USE_LLVM=0` took 76.1 s with different frames.
    - About half of the 30 samples were in `gpu_allocator::FreeListAllocator::allocate`, under `wgpu_core::resource::StagingBuffer::new`, `Queue::write_buffer` and `SceneRenderer::prepare`. The rest were in `wait_for_fence`, with lavapipe's rasterizer threads idle in nearly every sample.
  - **With the change:**

    | Run | Before | After |
    |---|---|---|
    | lavapipe, LOCATION ticks 12-300 | 150.5 s | 81.8 s |
    | GPU, LOCATION ticks 12-300 | 20.9 s | 16.0 s |
    | GPU, LOCATION's captured ticks (12-8262) | 301.2 s | 229.6 s |
    | GPU, INTRO's captured ticks (12-3818) | 96.8 s | 67.8 s |

  - **Byte identity:** all three store files are byte-identical before and after:
    - on lavapipe, over LOCATION ticks 12-300;
    - on the GPU, over every reference film's captured ticks (CTRY, INTRO, LAND, BALLOON, TRAINTNL, BOMB, LOCATION).
  - **Samples after the change:** 16 of 20 were in `wgpu_hal::vulkan::DeviceShared::wait_for_fence`, sleeping on a condition variable inside `vulkan_lvp`, and none were in staging allocation. Of the other 4, one was command encoding (`CommandEncoder::finish`, `draw_indexed`), two `Device::poll`, and one `GpuModel::collect_world_meshes` under `prepare`.
  - **WARP fallback:** a first lavapipe pair run from Git Bash with a forward-slash `VK_DRIVER_FILES` landed on WARP (Microsoft Basic Render Driver) and was discarded. An exported backslash path reached llvmpipe.
- **Verdict**: adopted (#601). The output is byte-identical and the lavapipe time falls by 46%. The remaining wait in lavapipe is #600.
- **Lives in**: [`research/parity/lavapipe.md`](../../../research/parity/lavapipe.md) section 6.

## 2026-11-15: where a frame's time goes after the change

- **Question**: With staging allocation gone, which thread and which code hold a frame's time, on lavapipe and on the GPU?
- **Method**:
  - `80a3ad5`'s release build, rendering LOCATION ticks 12-300 headless, the same as the first entry.
  - Non-invasive `cdb` all-thread samples (`~*kc`) with the build's PDB:
    - 25 + 40 on lavapipe;
    - 42 over three GPU runs.
  - Process CPU time read over the sampled stretch.
  - Searched the mesa-dist-win 25.2.8 tree for debug symbols.
- **Result**:
  - **Lavapipe:** only two threads were ever busy, the main thread and one `vulkan_lvp` thread that executes command buffers.
    - The `vulkan_lvp` thread was busy in 52 of 65 samples. Every other `vulkan_lvp` thread was parked on a condition variable in every sample, and exactly one thread was busy in each.
    - The main thread was in `wait_for_fence` in 20 of 25, under `OffscreenTarget::capture`'s synchronous readback, so main-thread work and the lavapipe thread's work do not overlap.
    - Process CPU was 0.92 core, `cdb` included.
    - The tree has no PDBs and `vulkan_lvp.dll` exports only `vk_icd*`, so the busy thread's frames are known by module and offset only.
  - **GPU:** only the main thread was busy (42 of 42), at about 0.6 core.

    | Main-thread samples | Count |
    |---|---|
    | wgpu render-pass encoding (`encode_render_pass`) | 14 |
    | Waiting on the GPU | 11 |
    | `GpuModel::collect_world_meshes` under `SceneRenderer::prepare` | 8 |
    | `draw_slices` and `draw_edges` | 4 |
    | Other renderer frames | 5 |

    No SOD VM or store-write frame appeared.
- **Verdict**: control. It measured where the time goes and changed nothing. Most of a lavapipe frame sits on one Mesa thread that we cannot name without symbols, in series with the main thread's share, and the GPU cost is our draw encoding and world walk.
  - That the lavapipe thread's work is per-draw vertex, clip and setup work is inferred from the parked threads and the 320×200 target, not from named functions.
  - That the GPU's encode time scales with draw count is inferred from the per-slice `draw_indexed` loops; draws per frame were not counted.
- **Lives in**: [`research/parity/lavapipe.md`](../../../research/parity/lavapipe.md) section 6; open work in #600.
