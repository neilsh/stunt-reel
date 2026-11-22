# Lavapipe Render-Time Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure post-`#644`/`#811` lavapipe draw counts, phase timings with A/B isolation probes, `LP_NUM_THREADS` scaling, and multi-`VkDevice` vs multi-process scaling, then record the findings and go/no-go guidance in `research/parity/lavapipe-render-time.md` and `research/parity/evidence-limits.md` with zero permanent changes in `crates/`.

**Architecture:** All instrumentation and isolation switches live behind `DBG_PROBE_*` environment variables in a single temporary patch so one release binary runs every measurement on Windows (`mesa-dist-win 25.2.8` and RTX 4070) and WSL 2 (`Ubuntu-24.04` canonical lavapipe).
Before running timed spans, a CPU-only whole-film scan selects the wide-island `LOCATION` span and relight-heavy `INTRO` span and confirms identical per-frame draw counts against rendered runs.
After all measurements and byte-identity checks complete, `crates/` is reverted cleanly, the diff is saved as `probe.patch`, and findings are distilled into the evergreen research notes.

**Tech Stack:** Rust (`stunt-core`, `stunt-render`, `stunt-score`, `stunt-cli`), Mesa `llvmpipe` (`mesa-dist-win 25.2.8` and Ubuntu 24.04 `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` under WSL 2), PowerShell 5.1, `mise run`.

**Spec:** [`spec.md`](spec.md) in this folder; read it before Task 1.

## Global Constraints

- Zero permanent edits to `crates/` or `python/`: revert `crates/` completely after archiving `probe.patch`.
- Always select Windows `mesa-dist-win 25.2.8` using an exported backslash path `$env:VK_DRIVER_FILES = "E:\git\stunt-reel.data\tools\mesa-25.2.8\x64\lvp_icd.x86_64.json"` plus `--software-only`, and confirm `"llvmpipe (LLVM 21.1.7, 256 bits)"` in each store's `render.json`.
- Always run WSL 2 measurements inside `/root/stunt-reel` against `/root/stunt-reel.data` (never `/mnt/e`), confirming `"llvmpipe (LLVM 20.1.2, 256 bits)"` in `render.json`.
- Every quoted timing needs at least 3 runs, reporting median and min-max spread; keep CPU and lavapipe runs single-active on the machine while timing.
- Verify byte-identical `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` across every A/B probe, `FRAMES_IN_FLIGHT = 1`, and `LP_NUM_THREADS` setting (and per-tick decoded planes and palettes across sharded multi-worker stores) before accepting any timing.
- Markdown starts every sentence on its own line; do not break links or code spans across lines.
- Before pushing or concluding changes to `research/` or `work/`, run a fresh reviewer pass per `AGENTS.md` § Committing 5 and verify `mise run check` passes.

## Review Focus

1. **`FRAMES_IN_FLIGHT = 2` vs `1`:** Under `FRAMES_IN_FLIGHT = 2`, `read_back_oldest` waits on frame N-1 while frame N executes on lavapipe, so wall-clock attribution needs both `FRAMES_IN_FLIGHT = 2` (production overlap) and `FRAMES_IN_FLIGHT = 1` (true unhidden lavapipe execution time).
2. **`WalkStep` (`self.steps`) and draw-category tagging:** `SceneRenderer::draw` issues draws from both `self.prepared` and `self.steps` (`WalkStep::sprites`, `WalkStep::props`, `WalkStep::actors`), so counting `self.prepared` alone would miss placed sprites, actors moved into steps, and post-sprite world prop slices.
   Both `view_facing` props and unlit actors currently share `Target::Shape`, so `PreparedDraw` must carry a temporary category tag so `draw` distinguishes `view_facing` fills from unlit actor fills.
3. **In-process multi-`VkDevice` ownership (`!Send` `Renderer`):** `Overlay` (`Box<dyn FnOnce(&mut RenderedPage)>`) and `sink: Box<dyn PageSink>` (`PageSlot` holds `Rc<RefCell<...>>`) make `Renderer` `!Send`.
   Therefore, each worker thread in the in-process multi-device harness must construct its own `Renderer::offscreen` inside `std::thread::scope`, synchronize at a `std::sync::Barrier` after all N uploads finish, release `world.ir`/`prop_runs` once via `Arc<RwLock<FilmScene>>` before starting the timed render loops, hit a second barrier, and then run `scene.frame()` + `renderer.submit()` + `RenderJournal::write()`.
4. **`#919` plane-only probe pitfalls (`credits.rs`, `RenderedPage::new`, `bars.wgsl`):** `RenderedPage::new` rejects empty `rgba`, `paint_credits` writes `indices` and `layers` inside an `if let` that also borrows `page.rgba.get_mut`, and dropping `color_texture` moves `plane_texture` from `@location(1)` to `@location(0)`.
   The plane-only probe must bypass `RenderedPage::new`'s `rgba` length check, decouple `indices`/`layers` writes in `credits.rs` from `page.rgba` (so `INTRO` credits stay byte-identical), keep group-1 `palette_lut` layout/bind intact or adjust pipeline layout, and supply `@location(0) vec2<u32>` plane-only fragment entries in both `mode13h.wgsl` and `bars.wgsl`.
5. **`#915` relight probe pitfalls (`SceneRenderer::relight` vs `GpuChunk::rewrite_vertices`):** `Refresh::Rewrite` can fire on `AngleBank` changes where vertex positions differ, and `GpuChunk::rewrite_vertices` does not see the previous vertex slice, so `DBG_PROBE_SKIP_APEX_REWRITE=1` must compare `lit.layout.vertices` vs `shape.ir.vertices` positions inside `SceneRenderer::relight`.
   For `DBG_PROBE_RING_LIT=1`, each ring slot must track its own `(GpuModel, LitLayout)` (or invalidate the alternate slot on `Refresh::Upload`) so an index/node change never leaves the other slot stale on the next rewrite.
6. **`read_back_oldest` dual polls and Windows stats:** `OffscreenTarget::read_back_oldest` runs two sequential `read_back` calls (`&readback.color`, then `&readback.plane`), each polling `device.poll(Wait)`; time both polls separately.
   Use Windows backslash paths in `VK_DRIVER_FILES` (forward slashes silently fell back to WARP in `#596`) and inspect `render.json`'s `adapter`.
   Read Windows CPU time, peak working set (`PeakWorkingSet64`), and peak private bytes (`PeakPagedMemorySize64`) via one PowerShell call at process end outside timed sections.

---

### Task 1: Build env-gated throwaway probe (`probe.patch`) and verify zero-drift control

**Files (temporary, reverted in Task 6):**
- Modify: `crates/stunt-render/src/scene_renderer.rs` (`SceneRenderer::prepare`, `SceneRenderer::draw`, `SceneRenderer::relight`, `LitShape`, `DrawUniforms`, `PreparedDraw`, `WalkStep`)
- Modify: `crates/stunt-render/src/mesh.rs` (`GpuModel::collect_world_meshes`, `GpuModel::collect_visible_meshes`, `VisibleWalk::walk`, `frustum_keeps`, `GpuChunk::rewrite_vertices`, CPU metadata helpers)
- Modify: `crates/stunt-render/src/renderer/offscreen.rs` (`OffscreenTarget::new`, `OffscreenTarget::submit`, `OffscreenTarget::read_back_oldest`, `FRAMES_IN_FLIGHT`)
- Modify: `crates/stunt-render/src/renderer/readback.rs` (`read_back`)
- Modify: `crates/stunt-render/src/renderer/credits.rs` (`paint_credits` decoupling `indices`/`layers` from optional `rgba`)
- Modify: `crates/stunt-render/src/renderer/mod.rs` (`Renderer::offscreen`, `Renderer::submit_offscreen`, `RenderedPage::new`)
- Modify: `crates/stunt-render/src/renderer/adapter.rs` (`offscreen_adapter`, separate-instance support)
- Modify: `crates/stunt-render/src/pipeline.rs` (`RenderPipelines::build` plane-only target config)
- Modify: `crates/stunt-render/src/shaders/mode13h.wgsl` (plane-only `@location(0)` fragment entries omitting `color` output & `palette_lut` load)
- Modify: `crates/stunt-render/src/shaders/bars.wgsl` (matching `@location(0)` plane-only fragment entry)
- Modify: `crates/stunt-score/src/parity_artifacts/mod.rs` (`RenderJournal::write`, `RenderJournal::finish`)
- Modify: `crates/stunt-score/src/render_store/mod.rs` (`StoreWriter::push`, `StoreWriter::close_chunk`, `StoreWriter::write_preview`, `StoreWriter::finish`, `check_derivable`)
- Modify: `crates/stunt-cli/src/main.rs` (`build_identified_scene` startup timing)
- Modify: `crates/stunt-cli/src/headless.rs` (`run_headless`, CPU-only scan mode, multi-worker in-process harness, process CPU/wall/RSS reporting)

**Probe controls (all off by default when unset):**
- `DBG_PROBE_REPORT=1`: prints startup build/upload times, per-frame `DRAWFRAME` counts (ground/base/decal fill & edge, `view_facing`, unlit/relit actors, shadows, sprites, `WORLD_REACH` nodes total & surviving), per-phase cumulative nanoseconds, and process wall/CPU/peak memory summary.
- `DBG_PROBE_FRAMES_IN_FLIGHT=1|2`: overrides `FRAMES_IN_FLIGHT` in `OffscreenTarget` (`VecDeque` drain threshold).
- `DBG_PROBE_PLANE_ONLY=1`: `#919` probe; configures `OffscreenTarget`, `RenderPipelines`, `mode13h.wgsl`, and `bars.wgsl` with only `plane_texture` at `@location(0)` + depth, skips `palette_lut.set_controls` and `check_derivable`, keeps `paint_credits` updating `indices`/`layers`, and passes empty `rgba` to `RenderedPage::new`.
- `DBG_PROBE_CULL_VIEW_FACING=1`: `#914` probe; frustum-culls each `view_facing` prop's root `NodeBounds` against its model-to-clip matrix (`rotation_proj * eye_relative_matrix`) before `collect_visible_meshes`.
- `DBG_PROBE_SKIP_APEX_REWRITE=1`: `#915` sub-probe; checks vertex position equality inside `SceneRenderer::relight` and skips the `apex_buffer` write in `GpuChunk::rewrite_vertices` when all decoded vertex positions match the uploaded layout.
- `DBG_PROBE_RING_LIT=1`: `#915` sub-probe; alternates `LitShape` writes across 2 `(GpuModel, LitLayout)` slots per actor instead of rewriting one in-flight buffer.
- `DBG_PROBE_CPU_SCAN_FILE=<path>`: CPU-only draw/relight scan mode; builds `FilmScene`, constructs `GpuModel`-equivalent node bounds, `plan_upload` (`usize::MAX` single-chunk limit matching lavapipe), `plan_edges`, and `WorldPlacements::new` without opening a GPU device, applies `projection_y_scale` for `--viewport-rows` and `capture_tick(tick)` sampling, walks every tick in `--tick-range`, and writes per-frame category `draw_indexed` counts and `SceneRenderer::relight` action counts (`keep` / `rewrite` / `upload`) to `<path>`.
- `DBG_PROBE_WORKERS=<N>`: multi-device in-process mode; wraps `FilmScene` in `Arc<RwLock<FilmScene>>`, spawns `N` worker threads inside `std::thread::scope` dividing `--tick-range` into disjoint 50-tick-aligned shards, opens `Renderer::offscreen` per thread, synchronizes with a `Barrier` to call `release_world_mesh()` once before starting timed worker loops, hits a second barrier, writes shard stores under `--out-dir/worker_<k>`, and reports startup wall, loop wall, end-to-end wall, process CPU time, and peak RSS/working-set/private bytes.
- `DBG_PROBE_SEPARATE_INSTANCES=1`: makes `offscreen_adapter` bypass the `OnceLock` cache so each thread creates its own `wgpu::Instance` and `wgpu::Adapter`.

- [ ] **Step 1: Implement the env-gated probe across the files above**
  Respect workspace lints (`unsafe_code = "deny"` in `Cargo.toml`): on Windows, collect `TotalProcessorTime`, `WorkingSet64`, `PeakWorkingSet64`, and `PeakPagedMemorySize64` via one PowerShell `Get-Process` invocation at process exit outside timed loops; on Linux, read `/proc/self/stat` and `/proc/self/status` (`VmHWM`).

- [ ] **Step 2: Build release binary and run zero-drift control check**
  - Build: `cargo build --release --locked -p stunt-cli`
  - Run `LOCATION` `12..=120` on Windows `mesa-dist-win 25.2.8` with all `DBG_PROBE_*` unset vs `DBG_PROBE_REPORT=1` vs `DBG_PROBE_FRAMES_IN_FLIGHT=1` vs `DBG_PROBE_PLANE_ONLY=1` vs `DBG_PROBE_CULL_VIEW_FACING=1`.
  - Verify `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` SHA-256 match unpatched `main` across every variant.
  - Also run the `INTRO` relight probes (`DBG_PROBE_SKIP_APEX_REWRITE=1`, `DBG_PROBE_RING_LIT=1`, and both) on ticks `12..=300` and verify store SHA-256 identity.

- [ ] **Step 3: Export `probe.patch`**
  - Run: `git diff --unified=0 crates/ > work/2026-11/918_lavapipe-render-time/probe.patch`
  - Check `git diff --check` passes cleanly on the patch and working tree.

---

### Task 2: Whole-film CPU draw/relight scans and span selection (Item 1)

- [ ] **Step 1: Run CPU-only scan on `LOCATION` (`12..=8262`) and `INTRO` (`12..=3818`)**
  - Invoke `target/release/stuntreel.exe --headless` with `DBG_PROBE_CPU_SCAN_FILE` on:
    - `E:\git\stunt-reel.data\builds\patch3\VAULT\LOCATION.FLM` + `E:\git\stunt-reel.data\captures\vault-location\archives\LOCATION.ALL` (`--tick-range 12..=8262`)
    - `E:\git\stunt-reel.data\builds\patch3\VAULT\INTRO.FLM` + `E:\git\stunt-reel.data\captures\vault-intro\archives\INTRO.ALL` (`--tick-range 12..=3818`)
    - Both with `--sidata E:\git\stunt-reel.data\corpus\siarchive\Developer\FreeFlight\SIDATA --width 320 --height 200 --viewport-rows 185 --software-only`.

- [ ] **Step 2: Analyze scan output and select Span B and Span C**
  - Compute whole-film median, p95 and max per category on `LOCATION` and `INTRO`, plus `#811` `WORLD_REACH` node counts (total and per-frame surviving).
  - Compare `LOCATION` `2500..=2900`, `6500..=6800`, and the peak sustained 300-400 tick wide-island window; pick Span B (~300-400 ticks) and document why it is wide.
  - Pick Span C on `INTRO` (~300-500 ticks) containing sustained `Target::Lit` relighting rewrites (`rewrite_vertices` / `LitShape::upload`) and forested `view_facing` draws.

- [ ] **Step 3: Cross-check deterministic draw counts on live lavapipe**
  - Run `DBG_PROBE_REPORT=1` on Spans A (`12..=300`), B and C on `mesa-dist-win 25.2.8` and confirm every frame's `DRAWFRAME` category counts match the CPU scan counts identically.

---

### Task 3: Windows `mesa-dist-win 25.2.8` phase timings, A/B probes, and RTX 4070 baseline (Item 2)

- [ ] **Step 1: Run Windows lavapipe observational + synchronous control matrix**
  - With `$env:VK_DRIVER_FILES = "E:\git\stunt-reel.data\tools\mesa-25.2.8\x64\lvp_icd.x86_64.json"` and `--software-only`, run 3 timed repetitions per cell on Spans A, B and C:
    - Baseline (`FRAMES_IN_FLIGHT = 2`, `DBG_PROBE_REPORT=1`)
    - Synchronous control (`FRAMES_IN_FLIGHT = 1`, `DBG_PROBE_REPORT=1`)

- [ ] **Step 2: Run throwaway A/B probes on Windows lavapipe (`FRAMES_IN_FLIGHT = 2`)**
  - Run 3 timed repetitions per cell:
    - `#919` plane-only (`DBG_PROBE_PLANE_ONLY=1`) on Spans A, B and C
    - `#914` `view_facing`-culled (`DBG_PROBE_CULL_VIEW_FACING=1`) on Spans A, B and C
    - `#915` `INTRO` relight probes on Span C: `DBG_PROBE_SKIP_APEX_REWRITE=1`, `DBG_PROBE_RING_LIT=1`, and both combined
  - Confirm SHA-256 byte-identity of `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` against each span's baseline store.

- [ ] **Step 3: Run RTX 4070 Laptop GPU observational baseline**
  - Unset `VK_DRIVER_FILES` and omit `--software-only`; confirm `NVIDIA GeForce RTX 4070 Laptop GPU` in `render.json`.
  - Run 3 timed repetitions per span on Spans A, B and C (`FRAMES_IN_FLIGHT = 2`, `DBG_PROBE_REPORT=1`).

---

### Task 4: `LP_NUM_THREADS` sweep on Windows and WSL 2 (Item 3)

- [ ] **Step 1: Run `LP_NUM_THREADS` = `1`, `4` and unset on Windows `mesa-dist-win 25.2.8`**
  - Render `LOCATION` ticks `12..=300` (3 runs per thread setting) on baseline, then repeat with `DBG_PROBE_CULL_VIEW_FACING=1`.
  - Record wall clock (end-to-end and render loop), CPU time, average cores busy, and verify byte-identical stores across `1`, `4` and unset.

- [ ] **Step 2: Sync WSL 2 `/root/stunt-reel` and run `LP_NUM_THREADS` sweep on canonical Linux lavapipe**
  - Copy `probe.patch` into `/root/stunt-reel`, ensure `HEAD` matches Windows `6955e159`, apply the patch, and build release `stuntreel` in WSL 2 `Ubuntu-24.04`.
  - Render `LOCATION` ticks `12..=300` reading `/root/stunt-reel.data` with `LP_NUM_THREADS` = `1`, `4` and unset (3 runs each).
  - Verify `"llvmpipe (LLVM 20.1.2, 256 bits)"` in `render.json` and store byte-identity across thread settings.

---

### Task 5: Multi-`VkDevice` in-process vs child processes on Windows and WSL 2 (Item 4)

- [ ] **Step 1: Run multi-worker scaling matrix on Windows `mesa-dist-win 25.2.8`**
  - Target span: `LOCATION` ticks `50..=649` (600 ticks, 12 film seconds of 50 ticks each).
  - Run 3 repetitions per configuration:
    - 1 worker (`LP_NUM_THREADS=1`, and `unset` baseline reference)
    - 2 workers in-process (`DBG_PROBE_WORKERS=2`, `LP_NUM_THREADS=1` and `unset`)
    - 2 child processes (`LP_NUM_THREADS=1` and `unset`)
    - 4 workers in-process (`DBG_PROBE_WORKERS=4`, `LP_NUM_THREADS=1`)
    - 4 child processes (`LP_NUM_THREADS=1`)
  - If 2-way in-process serializes (`cores busy` near 1.0), run 2-way in-process with `DBG_PROBE_SEPARATE_INSTANCES=1` (`LP_NUM_THREADS=1`, 3 runs).
  - Record end-to-end wall, render-loop wall, total CPU time, average cores busy, peak working set + peak private bytes (`PeakPagedMemorySize64`) on Windows, and decode each sharded store per tick (matching `indices`, `layers`, `shapes` and resolved palettes per tick) against the 1-worker store.

- [ ] **Step 2: Run the same multi-worker scaling matrix on WSL 2 `Ubuntu-24.04` canonical lavapipe**
  - Run the same 1/2/4 in-process vs child-process matrix on `/root/stunt-reel` + `/root/stunt-reel.data` (including the `DBG_PROBE_SEPARATE_INSTANCES=1` check if 2-way in-process serializes), 3 runs each, recording `VmHWM` alongside wall clock, CPU time and cores busy, and checking per-tick byte-identity.

---

### Task 6: Revert `crates/`, record findings, fresh review, and quality gate

- [ ] **Step 1: Revert all temporary instrumentation**
  - Run `git checkout -- crates/` in Windows checkout and in WSL 2 `/root/stunt-reel`, and verify `git status` shows zero modified tracked source files in `crates/` (and remove scratch renders under `build/scratch/`).

- [ ] **Step 2: Write `work/2026-11/918_lavapipe-render-time/journal.md`**
  - Record the base commit (`6955e159`), probe patch (`probe.patch`), exact Mesa/LLVM builds and Ryzen 7 7745HX hardware details, and all raw run data, medians, spreads, byte-identity digests, and go/no-go tables under dated `## 2026-11-21: ...` entries per `work/README.md` § Journal entries.

- [ ] **Step 3: Update [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) and [`evidence-limits.md`](../../../research/parity/evidence-limits.md)**
  - Update [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) per [`recording-findings`](../../../.agents/skills/recording-findings/SKILL.md): current `summary:`, Items 1-4 (`[Bounded Observation]`), `#811` `ScaleReach` coverage, updated/qualified `LP_NUM_THREADS` status, updated `## Ruled out` and `## Open questions`, go/no-go lines for `#914`, `#915`, `#916`, `#919` and `#920`, and `_Source:` links to `journal.md`.
  - Confirm or revise [`evidence-limits.md`](../../../research/parity/evidence-limits.md) `#645` sentence in place, citing `journal.md`.
  - Re-read [`reconstruction.md`](../../../site/guides/reconstruction.md) (the site guide linking `evidence-limits.md`) per `AGENTS.md` § Committing 5.
  - Link `journal.md` and `probe.patch` in `spec.md` and `plan.md` once both files exist, and keep [`README.md`](README.md) `outcome: ""` empty until the finishing PR closes `#918`.

- [ ] **Step 4: Fresh reviewer pass and quality gate**
  - Run `mise run fix` and `mise run claim-words`.
  - Invoke a fresh reviewer subagent over the diff, `journal.md`, [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), [`evidence-limits.md`](../../../research/parity/evidence-limits.md), and [`reconstruction.md`](../../../site/guides/reconstruction.md).
  - Fix every valid reviewer finding and run `mise run check` until it passes with zero warnings.
  - Prepare the `#918` closing comment summarizing the go/no-go verdicts and linking [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md).
