## 2026-11-23: where Windows lavapipe spends the loop on the whole LOCATION film

`[Bounded Observation]`

- **Question**: Where inside lavapipe does the whole `LOCATION` film's loop go, and Span B's: line rasterization, triangle setup and binning, fragment shading, state changes and pipeline binds, or the queue submit's own overhead?
  Which of these is above 5% of the whole film's loop?
- **Method**:
  - **Tool.**
    Kernel ETW sampling (`wpr -start CPU`) needs an elevated shell, and this unattended session's is not ("Failed to enable the policy to profile system performance"), so [`stack_sampler.py`](stack_sampler.py) samples from user mode.
    `record` starts `stuntreel`, waits for the probe's `[probe] loop_start` line, then on every sweep suspends each of the child's threads in turn, reads its `Rip` and `Rsp` (`GetThreadContext`), copies up to 32 KiB of its stack, keeps the first 96 qwords that point into a loaded module, and resumes it, until `[probe] loop_ms`.
    `report` resolves the addresses with the Windows Kits `dbghelp.dll`, keeps a stack qword as a frame only when the bytes before it are a call instruction, and sorts each sample by the first owning frame from the leaf up (the tables in `classify_setup` and `classify_raster`).
    This is stack scanning, not unwinding: a stale return address left on the stack can appear as a frame, so a part is the first matching frame's, and the shares below are sample counts, not exact times.
    The sweep rate was 250 Hz requested and about 190 Hz reached (37 threads a sweep: the main thread, lavapipe's queue thread `vk_queue_submit_thread_func`, 16 rasterizer threads, 16 idle compute-pool threads `lp_cs_tpool_worker`, and 3 others).
    A thread's samples are uniform in wall time over the loop, so a part's share of a thread's samples is its share of that thread's loop wall time, waits included.
  - **Symbols.**
    mesa-dist-win publishes `mesa3d-25.2.8-debug-info-msvc.7z` (81,639,192 bytes, SHA-256 `9dbdce32c79d7d8104a8c2e56490293b929170172bbfa812f8e9e2b322cf102e`, GitHub's digest, measured the same here); its `x64\vulkan_lvp.pdb` (57,061,376 bytes), unpacked into the data root's `tools\mesa-25.2.8-debug-info`, resolves the release `vulkan_lvp.dll` to function names, Mesa's and its static LLVM's.
    llvmpipe's JIT code (the fragment shaders, the vertex shaders and the triangle setup functions it compiles) lies in no module, so a JIT sample is named by its nearest module caller only: no JIT sample can be split between `fs_main_plane`, `prop_shape` and the rest of the shader.
    `stuntreel.exe` was built with line tables (`CARGO_PROFILE_RELEASE_DEBUG=line-tables-only`) for its PDB; system DLLs resolve to their nearest export.
  - **Builds.**
    `main` at `f6976e67` plus [`profile-probe.patch`](profile-probe.patch): the loop timer of `#920`'s probe, printing `[probe] loop_start` before the first frame and `[probe] loop_ms` after the last page, and `#920`'s skip-all switch (`STUNT_PROBE_SKIP_WORLD` returns from `SceneRenderer::encode` for every `Target::World` draw, read once).
    One release binary (`mise exec -- cargo build --release -p stunt-cli`, with the line tables), copied to the scratchpad and run for every variant; with the switch unset it draws as `main` does.
  - **Inputs.**
    `stuntreel --headless <data>/builds/patch3/VAULT/LOCATION.FLM --all <data>/captures/vault-location/archives/LOCATION.ALL --tick-range <span> --sidata <data>/corpus/siarchive/Developer/FreeFlight/SIDATA --out-dir <dir> --width 320 --height 200 --viewport-rows 185 --software-only`, `VK_DRIVER_FILES` naming mesa-dist-win 25.2.8's `lvp_icd.x86_64.json`, `LP_NUM_THREADS` unset; the whole film is `12..=8262`, Span B `3680..=3979`.
    Every run's `render.json` names `llvmpipe (LLVM 21.1.7, 256 bits)`.
    The owner's laptop (Ryzen 7 7745HX, 16 logical CPUs).
  - **Runs.**
    Before each run `tasklist` showed no `stuntreel`, `cargo` or `rustc` process; the check is logged with each run.
    Order: whole film skip-all sampled, base unsampled, skip-all unsampled, base sampled, base unsampled; then Span B base sampled, skip-all sampled, base unsampled, skip-all unsampled, base sampled, base unsampled.
    Base sampled and skip-all sampled once each on the whole film just before them, quiet as well.
    A first batch is discarded: its unsampled mode divided by a zero rate, and the renders it started kept running beside the next runs.
  - Each run's four stores were hashed.
- **Result**:
  - **Loop ms.**

    | Cell | Unsampled | Sampled | Sampler's cost |
    |---|---|---|---|
    | Whole film, base | 28,451, 28,311 (mean 28,381) | 28,802, 29,039 (mean 28,920.5) | +1.9% |
    | Whole film, skip-all | 14,422 | 15,385, 15,216 (mean 15,300.5) | +6.1% |
    | Span B, base | 2,449, 2,474 (mean 2,461.5) | 2,623, 2,642 (mean 2,632.5) | +6.9% |
    | Span B, skip-all | 669 | 684 | +2.2% |

    Unsampled, skip-all cuts the whole film's loop `49.2%` and Span B's `72.8%`, as `#920` found (`49.0%` and `70.7%`).
    Each variant's four stores hash the same in every one of its runs, sampled or not, on each span.
  - **The threads.**
    Over the whole film the main thread waits on lavapipe's queue fence (`lvp_pipe_sync_wait_locked`) for `59.6%` and `59.0%` of its samples, and runs `stuntreel`'s own code (`31.6%`, `31.5%`) and `wgpu` (`5.6%`, `5.9%`, mostly render-pass encoding and buffer frees, not the submit).
    lavapipe's queue thread executes every command buffer: in the sampled runs it is busy or waiting on the rasterizers for `96.5%` and `96.8%` of the loop and idle, awaiting a submit, for `3.5%` and `3.2%`, so it is the loop's critical path, and a part's share of its samples is that part's share of the loop wall while the main thread waits on it.
    It waits on the rasterizer threads' fence (`lp_fence_wait` under `llvmpipe_flush`) for `26.9%` and `26.4%`, while the rasterizers are idle in `93%` of their samples, so that wait is the rasterizers' work left after binning, on the critical path.
    The 16 rasterizer threads are busy in `6.8%` and `7.1%` of their samples, `1.08` and `1.14` threads a sweep on average.
  - **The queue thread's parts, whole film** (share of its samples, mean of two runs with each run; ms is the share times that run's loop, averaged; skip-all the same over its two runs):

    | Part | Base % | Base ms | Skip-all % | Skip-all ms | Base minus skip-all, ms |
    |---|---|---|---|---|---|
    | Wait: rasterizer threads (fence) | 26.7 (26.9, 26.4) | 7,712 | 36.2 (35.4, 37.0) | 5,540 | 2,172 |
    | Vertex: draw module (fetch, shade, clip) | 21.4 (21.5, 21.4) | 6,194 | 19.7 (20.1, 19.4) | 3,021 | 3,173 |
    | Setup: lines (setup and binning) | 14.6 (14.6, 14.7) | 4,223 | 3.0 (3.1, 3.0) | 466 | 3,757 |
    | State: storing the fragment state (`try_update_scene_state`) | 10.2 (9.9, 10.5) | 2,944 | 10.8 (11.8, 9.8) | 1,651 | 1,293 |
    | State: other changes and pipeline binds | 8.5 (8.5, 8.5) | 2,459 | 8.2 (8.0, 8.4) | 1,250 | 1,209 |
    | Setup: triangles (setup and binning) | 5.4 (5.4, 5.4) | 1,564 | 5.9 (5.3, 6.4) | 899 | 665 |
    | Idle: awaiting a submit | 3.3 (3.5, 3.2) | 962 | 4.2 (4.2, 4.2) | 646 | 317 |
    | Scene flush and reset | 2.4 (2.4, 2.4) | 706 | 2.4 (2.5, 2.2) | 361 | 344 |
    | Dispatch: command execution and queue submit | 2.1 (1.9, 2.2) | 594 | 1.8 (1.5, 2.1) | 277 | 317 |
    | Clears | 1.7 (1.6, 1.7) | 477 | 2.9 (3.0, 2.8) | 446 | 31 |
    | JIT compile (LLVM) | 1.4 (1.4, 1.4) | 410 | 2.0 (2.0, 2.1) | 310 | 100 |
    | Setup: primitive dispatch (`lp_setup_draw_elements`) | 1.2 (1.1, 1.3) | 350 | 0.9 (1.2, 0.7) | 144 | 207 |
    | Copies (readback, uploads) | 0.8 (1.0, 0.7) | 241 | 1.6 (1.6, 1.6) | 243 | -2 |
    | Wait: other | 0.3 (0.3, 0.3) | 83 | 0.3 (0.3, 0.3) | 46 | 37 |

  - **Inside the parts, whole film** (`w_base_s1`, share of the queue thread's samples):
    - Storing the fragment state: `memcpy` `6.51%`, `memcmp` `2.70%` (`9.2%` together), the function itself `0.56%`.
      `[Supported Inference]` for the rest of this bullet, read from the source and the PDB, not measured: in Mesa 25.2.8's `lp_setup.c`, `try_update_scene_state` compares the current fragment state with the one last stored in the scene and, when they differ, allocates a new `lp_rast_state` in the scene and copies it in; the PDB gives `sizeof(lp_rast_state)` as `32,440` bytes, of which `lp_jit_resources` (the texture, sampler, image, constant and storage-buffer arrays) is `32,384`.
      lavapipe binds a descriptor set as a constant buffer of each stage its layout names, so a fragment-visible bind or a pipeline switch that changes the fragment shader variant makes a new store; the vertex-only model uniform at group 2 does not, by the same source.
      How many stores a frame makes was not counted.
    - Lines: `try_setup_line` `5.64%`, `setup_line_coefficients` `2.70%`, the rest in binning, `lrintf`, `setup_fragcoord_coef` and the scene's command blocks.
    - Vertex: JIT samples under the draw module (the vertex shader and fetch) `6.8%`, `vsplit_segment_cache_uint32_t` `2.13%`, `llvmpipe_cleanup_stage_images` `1.68%`, `llvm_middle_end_bind_parameters` `0.96%`, and a long tail.
    - Other state: `prepare_shader_images` `1.48%`, `lp_make_setup_variant_key` with its allocations about `1.4%`, and a long tail of `handle_graphics_pipeline`, `compute_vertex_info`, `emit_state` and the setup variant lookup.
    - Triangles: `do_triangle_ccw` and its JIT setup function `2.31%`, binning `1.61%`, `triangle_cw` `0.87%`.
    - Queue submit: `2.1%` on the queue thread and `1.5%` (`1.4%`, `1.6%`) of the main thread's samples in lavapipe's submit path; `wgpu`'s `5.7%` on the main thread is encoding, off the critical path while the main thread waits.
  - **The rasterizer threads, whole film** (share of their busy samples, base runs then skip-all runs):
    fragment shading in JIT code `77.9%`, `78.4%` (`83.8%`, `83.5%`), coverage `13.5%`, `13.2%` (`6.0%`, `5.6%`), the rest dispatch, bookkeeping and `3.5%..3.7%` unattributed in `ntdll` (lock wakes).
    Primitives with 4 edge planes, the count llvmpipe gives a line (and a triangle cut by one scissor edge), take `7.6%` and `8.2%` of the busy samples (`1.1%`, `1.2%` with the world skipped): rasterizing lines is small; setting them up is not.
    All of the JIT fragment-shading samples are unattributed between `fs_main_plane`, `prop_shape` and the rest.
  - **Span B** (queue thread, base mean of two runs, skip-all one run):
    storing the fragment state `28.3%` (`27.9`, `28.7`; `745 ms`; skip-all `5 ms`), JIT compile `17.2%` (`454 ms`; every such sample falls in the loop's first `87` and `91` of `513` and `508` sweeps, about `0.45 s` and `0.47 s`, with LLVM's own functions at the leaf, as llvmpipe compiles a shader variant at its first use; over the whole film the `79` such samples of the first run fall in its first `146` of `5,546` sweeps, about `0.76 s`), vertex `16.4%` (`433 ms`), other state `11.3%` (`297 ms`), the rasterizer wait `8.1%` (`214 ms`), lines `6.9%` (`183 ms`), dispatch `3.9%`, triangles `3.6%`; the main thread waits on the queue for `71.6%`.
  - **Unattributed share.**
    No queue-thread sample is left unattributed; its "wait: other" is `0.3%`, the main thread's `1.8%`; `3.5%..3.7%` of the rasterizers' busy samples are in `ntdll` with no Mesa owner, and every JIT fragment-shading sample is unattributed within the shader.
- **Verdict**: control.
  - Each part above 5% of the whole film's loop, the share of the queue thread's samples (two runs), is a lever:
    - the rasterizer threads' work, the queue thread's fence wait: `26.7%`, of which fragment shading is about four fifths of the rasterizers' busy samples (the world's part, base minus skip-all: `2,172 ms`, `7.5%`);
    - the draw module's vertex work: `21.4%` (world `3,173 ms`, `11.0%`);
    - line setup and binning: `14.6%` (world `3,757 ms`, `13.0%`);
    - storing the fragment state (`try_update_scene_state`): `10.2%` (world `1,293 ms`, `4.5%`, so most of it is not the world's on the whole film, while on Span B nearly all of it is: `745 ms`, and `5 ms` with skip-all);
    - other state changes and pipeline binds: `8.5%` (world `1,209 ms`, `4.2%`);
    - triangle setup and binning: `5.4%` (world `665 ms`, `2.3%`), `0.4` points above the bar, less than the sampler's cost to the loop (`1.9%..6.9%`), so it may not clear the bar unsampled.
  - The world's part is the base and skip-all difference in sampled loops, and the percentages are of the base's sampled mean loop (`28,920.5 ms`); the queue thread's busy and waiting share only becomes loop time while the main thread waits on it (`59.3%` of the main thread's samples), and the main thread's own work (`37.3%` with `wgpu`) would cap what any of these saves, if that work does not change.
  - The world's parts are differences of sampled loops whose sampler cost differs (`+1.9%` base, `+6.1%` skip-all): the sampled loops cut `47.1%` (`13,620` of `28,920.5 ms`) where the unsampled ones cut `49.2%`, so each world's part leans low, by about 2 points of the base loop in total (`604 ms`: the skip-all sampled mean is `15,300.5 ms`, and `14,696 ms` were its sampler cost base's `+1.9%`).
  - The queue submit's own overhead is under 5% (`2.1%` on the queue thread, `1.5%` on the main thread).
  - This is consistent with `#920`'s finding that the whole film leans toward outlines and pixels, though no grouping, scissor or outline probe was run here: the whole film's world cost is mostly line setup, vertex work and rasterization (`9,102` of `13,620 ms`), while on Span B the state store is the largest single part of the loop (`28.3%`; `740` of the world's `1,948.5 ms`, about `38%`, from `745 - 5` and `2,632.5 - 684`).
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3 and its Open questions; figures per run in [`profile-parts.json`](profile-parts.json).
