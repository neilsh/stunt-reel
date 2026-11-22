# Where does lavapipe render time go after #644 and #811, and do multiple VkDevices parallelize in-process?

Design agreed with the owner on 2026-11-21; the plan is [`plan.md`](plan.md).
Base tree at agreement: `main` commit `6955e159`.

## Problem

[`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) section 1 records `#644`'s world frustum cull on `LOCATION` ticks 12-300 (`mesa-dist-win 25.2.8`, one run each: median `draw_indexed` calls per frame fell from 127,910 to 6,791 and wall clock from 81.7 s to 13.7 s; [`644_frustum-cull/journal.md`](../644_frustum-cull/journal.md#2026-11-16-culling-world-nodes-outside-the-view-frustum)).
That baseline leaves four gaps before `#914`, `#915`, `#916`, `#919` and `#920` can be judged go, defer or no-go:

1. **Unculled buckets and wide shots.**
   `#644` grouped `view_facing` props, actors, actor shadows and sprites into a single 6,762-draw bucket, measured only the `LOCATION` 12-300 aircraft close-up, omitted wide shots across the island and `INTRO`, and predates `#811` (`VisibilityCondition::ScaleReach` / `WORLD_REACH` / `WORLD_GATED` nodes in `crates/stunt-core/src/world/mesh.rs`) and `WalkStep` sprite-partitioning (`self.steps` in `crates/stunt-render/src/scene_renderer.rs`).
2. **Post-`#644` phase breakdown.**
   The phase evidence in [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) is `#596`/`#600`'s pre-`#644` `cdb` stack sampling ([`596_lavapipe-staging-buffers/journal.md`](../596_lavapipe-staging-buffers/journal.md#2026-11-15-where-a-frames-time-goes-after-the-change)), which predates `#602` (`FRAMES_IN_FLIGHT = 2` overlapping frame N+1's CPU work with frame N's lavapipe wait), `#474` (`SceneRenderer::relight`), and `#644`'s 95% cut in total draws (99.98% cut in world draws, from 121,148 to 29).
   Under `FRAMES_IN_FLIGHT = 2`, main-thread waiting inside `read_back` (`device.poll(Wait)`) also hides overlapped lavapipe execution and conflates vertex/draw work (`#914`/`#920`), dual-target fragment/LUT/color-copy work (`#919`), and relit-actor writes (`#915`).
3. **Post-`#644` `LP_NUM_THREADS`.**
   The `Ruled out` entry showing `LP_NUM_THREADS` = 1, 4 and unset unchanged (`~151 s`, ~1.00 core) was measured pre-`#644` and pre-`#596` on `crates` `52d84e6` ([`596_lavapipe-staging-buffers/journal.md`](../596_lavapipe-staging-buffers/journal.md#2026-11-15-one-model-matrix-upload-per-frame)), where per-draw staging-buffer allocation held about half of main-thread samples.
4. **In-process multi-`VkDevice` scaling.**
   [`evidence-limits.md`](../../../research/parity/evidence-limits.md) section 3 records `#645`'s decision to set aside splitting one film across processes or across `wgpu::Device`s in one process (each process repeats the scene build and world memory, `--jobs` already runs films in parallel, and one device's queue runs on one lavapipe thread).
   `offscreen_adapter` in `crates/stunt-render/src/renderer/adapter.rs` caches one `wgpu::Adapter` per process while each `Renderer::offscreen` opens its own `wgpu::Device`.
   Whether two threads with separate lavapipe `VkDevice`s in one process scale across cores or serialize on an internal Mesa/LLVM lock decides `#916`'s architecture and confirms or revises `#645`'s note.

## Environments

- **Primary (`local-windows`).**
  AMD Ryzen 7 7745HX (8 physical cores, 16 logical processors), Windows `mesa-dist-win 25.2.8` MSVC (`llvmpipe (LLVM 21.1.7, 256 bits)`), selected via `VK_DRIVER_FILES=<data root>\tools\mesa-25.2.8\x64\lvp_icd.x86_64.json` and `--software-only` per [`render-on-lavapipe.md`](../../../docs/howto/render-on-lavapipe.md).
  All four measurement items and all A/B probes run here.
  One 3-run RTX 4070 Laptop GPU observational baseline per span (with `VK_DRIVER_FILES` unset and without `--software-only`) is also recorded for reference.
- **Secondary cross-check (WSL 2 `Ubuntu-24.04`).**
  Canonical Linux `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`) on the same Ryzen 7 7745HX machine, in `/root/stunt-reel` against `/root/stunt-reel.data` on the Linux filesystem (set up per [`render-on-lavapipe.md`](../../../docs/howto/render-on-lavapipe.md) section 5 and [`908_backend-agreement/journal.md`](../908_backend-agreement/journal.md#2026-11-21-four-renderer-builds-on-one-crates-tree-two-machines)).
  Items 3 (`LP_NUM_THREADS`) and 4 (multi-`VkDevice` vs child processes) run here in addition to Windows, because Windows MSVC Mesa and Linux Mesa can differ in thread pooling and global locking, and CI/cloud parity runs use Linux Mesa.

## Spans and geometry

Every timed render uses parity geometry (`--width 320 --height 200 --viewport-rows 185`, `--sidata <data root>/corpus/siarchive/Developer/FreeFlight/SIDATA`) and the film's pinned `.ALL` archive from [`references.toml`](../../../research/parity/references.toml), writing real render stores via `--out-dir`:

- **Span A (`LOCATION` close-up):** ticks `12..=300` (289 frames), matching `#644`'s baseline (`LOCATION.FLM` + `captures/vault-location/archives/LOCATION.ALL`).
- **Span B (`LOCATION` wide-island):** a ~300-400 tick span chosen empirically from a single CPU-only draw-count scan across all 8,251 captured `LOCATION` ticks (`12..=8262`).
  The scan compares the issue's suggested spans (`2500..=2900` and `6500..=6800`) against the widest sustained stretch across the island and records why the chosen span is wide.
  Whole-film median, p95 and max per-category draw counts from the full scan are also recorded to size `#920`.
- **Span C (`INTRO` relight-heavy):** a ~300-500 tick span chosen empirically from a single CPU-only draw-and-relight scan across all 3,807 captured `INTRO` ticks (`12..=3818`) to include sustained `SceneRenderer::relight` vertex rewrites (`Target::Lit`) and forested `view_facing` draws.
  Whole-film draw and relight counts are recorded alongside the timed span.

## Measurements

### Item 1: Draws by category (deterministic)

Count exact `draw_indexed` calls emitted inside `SceneRenderer::draw` (both `self.prepared` and `self.steps` (`WalkStep`)) per frame across Spans A, B and C, plus whole-film median, p95 and max on `LOCATION` (`12..=8262`) and `INTRO` (`12..=3818`).
Verify that the real lavapipe render emits identical per-frame counts to the CPU scan on all three spans.
Report median and max calls per frame for:

1. `world ground` (fill and outline)
2. `world base` (fill and outline, including `WalkStep::props` base slices drawn after placed sprites)
3. `world decal` (fill and outline, including `WalkStep::props` decal slices)
4. `view_facing` props (`frame.view_facing`)
5. `actors` (split into unlit `Target::Shape` and relit `Target::Lit`, including `WalkStep::actors`, excluding shadows)
6. `actor shadows` (`PreparedDraw::shadow`)
7. `sprites` (`Target::Image`, unplaced and `WalkStep::sprites`)

Also record `#811` `ScaleReach` accounting on `LOCATION` and `INTRO`: total `WORLD_REACH` nodes in the built world, and median and max surviving frustum + `ScaleReach` per frame on each span.

### Item 2: Phase timings and isolation probes

Every quoted timing uses at least 3 runs, reporting median and min-max spread, and separates one-time startup (`build_identified_scene` + `Renderer::offscreen` upload) from the per-frame render loop and `RenderJournal::finish`.

1. **Observational phase breakdown (`FRAMES_IN_FLIGHT = 2` baseline) and synchronous control (`FRAMES_IN_FLIGHT = 1`):**
   Measured on Spans A, B and C on Windows `mesa-dist-win 25.2.8` (3 runs each for `FRAMES_IN_FLIGHT = 2` and `FRAMES_IN_FLIGHT = 1`, where `FRAMES_IN_FLIGHT = 1` exposes full unhidden lavapipe execution time per frame):
   - `FilmScene::frame`
   - `SceneRenderer::prepare`, broken out into `collect_world_meshes`, `view_facing` loop, `relight` (`.SOD` decode + `outlined()` vs `rewrite_vertices` / `LitShape::upload`), actor/sprite prep + `place_sprites`, and `uniforms.upload`
   - `palette_lut.set_controls`
   - pass encoding (`SceneRenderer::draw` + `copy_texture_to_buffer` + `encoder.finish` + `queue.submit`)
   - waiting on lavapipe (`device.poll(Wait)` in `read_back`, split into the first poll on `readback.color` vs the second poll on `readback.plane`)
   - readback copy (`get_mapped_range` + row unpadding + `RenderedPage::new` word split + `paint_credits` overlay)
   - `RenderJournal::write`, broken out into `check_derivable`, `u16_bytes`, `write_preview` PNG, and `zstd::bulk::compress` in `StoreWriter::close_chunk`
   - `RenderJournal::finish` (final chunk + `palettes.zst` + `shapes.zst` SHA-256 + `render.json`)
2. **Throwaway A/B probes (Windows `mesa-dist-win 25.2.8`, 3 runs each on `FRAMES_IN_FLIGHT = 2`):**
   All probes are gated behind `DBG_PROBE_*` environment variables in one release binary:
   - **`#919` plane-only probe** on Spans A, B and C: drop `color_texture` attachment, `palette_lut` fragment lookup, `color_texture` copy/readback, and `check_derivable`, rendering only `plane_texture` + depth while keeping `paint_credits` updating `indices` and `layers`; verify `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` stay byte-identical.
   - **`#914` `view_facing`-culled probe** on Spans A, B and C: frustum-cull each `view_facing` prop's root `NodeBounds` against its model-to-clip matrix before `collect_visible_meshes` (mirroring world node culling); verify `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` stay byte-identical.
   - **`#915` `INTRO` relight probes** on Span C: (a) skip rewriting `apex_buffer` in `GpuChunk::rewrite_vertices` when decoded vertex positions match the uploaded layout, (b) double-buffer `LitShape` (`GpuModel` + `LitLayout` per slot) across 2 slots (alternating per rewrite to avoid stalling on an in-flight buffer), and (c) both combined; verify `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` stay byte-identical.
     This tests `#915`'s stall hypothesis against [`474_actor-light/journal.md`](../474_actor-light/journal.md#2026-11-16-what-relighting-actors-costs-a-render), where variant (e) (mapped-at-creation buffer per rewrite) still took 26.0 s vs 23.9 s on full `INTRO`.
3. **RTX 4070 Laptop GPU observational baseline:**
   3 runs per span (`FRAMES_IN_FLIGHT = 2`, observational phases) on local Windows.

### Item 3: `LP_NUM_THREADS` scaling

Measure `LP_NUM_THREADS` = `1`, `4` and unset on `LOCATION` ticks `12..=300`, 3 runs each, reporting wall clock (render loop and end-to-end), total process CPU time, average cores busy (`CPU / wall`), and store byte-identity across settings:

- On Windows `mesa-dist-win 25.2.8`, both on baseline and with the `#914` `view_facing`-culled probe (to check whether thread scaling changes once unculled per-draw overhead is removed).
- On WSL 2 `Ubuntu-24.04` canonical lavapipe on baseline.

### Item 4: Multi-`VkDevice` in-process vs child processes

Measure parallel scaling on `LOCATION` ticks `50..=649` (600 ticks, 12 aligned 50-tick `RENDER_CHUNK_TICKS` seconds, evenly divisible across 1, 2 and 4 workers), 3 runs per configuration on both Windows `mesa-dist-win 25.2.8` and WSL 2 `Ubuntu-24.04`:

- **Worker counts:** 1, 2 and 4 disjoint tick ranges (`50..=649`; `50..=349` + `350..=649`; `50..=199` + `200..=349` + `350..=499` + `500..=649`).
- **In-process mode:** build `FilmScene` once, open N `Renderer::offscreen` devices (sharing `offscreen_adapter` and calling `release_world_mesh()` after all N uploads finish before starting the timed worker render loops), render the N disjoint ranges on N OS threads into separate render stores.
- **Child-process mode:** spawn N concurrent `stuntreel --headless` processes over the same N tick ranges and wait for all to finish.
- **Thread settings:** `LP_NUM_THREADS=1` for 1, 2 and 4 workers in both modes, plus `LP_NUM_THREADS` unset for 2-way in-process and 2-way child processes.
- **Serialization fallback:** if 2 in-process devices sharing `offscreen_adapter` serialize (`cores busy` near 1.0), run an additional 2-way in-process check where each worker thread creates its own `wgpu::Instance` and `wgpu::Adapter` (`DBG_PROBE_SEPARATE_INSTANCES=1`) to distinguish `wgpu`/adapter locking from DLL-global Mesa/LLVM locking.
- **Metrics:** end-to-end wall clock, render-loop wall clock (excluding one-time scene build + upload), total CPU time across all threads/processes, average cores busy, peak memory (Windows working set and peak private bytes; Linux `VmHWM`), and per-tick `frames.zst`/`layers.zst`/`shapes.zst` byte-identity (plus decoded `palettes.zst` per-tick palette equality) against the 1-worker baseline.

## Throwaway instrumentation and reproducibility

- Zero permanent code changes land in `crates/`.
- All counters, timers, CPU scan mode, multi-worker harness and `DBG_PROBE_*` switches are kept as a single throwaway patch archived as `probe.patch` (`git diff --unified=0`, matching [`603_draw-counts-per-frame/draw-counter.patch`](../603_draw-counts-per-frame/draw-counter.patch)).
- `journal.md` records the base commit, exact commands, Mesa/LLVM versions, CPU model, raw per-run figures and byte-identity checks.

## Go/no-go guidance criteria

No hard percentage threshold is applied.
Each follow-up ticket is assigned a qualitative recommendation (`go`, `defer`, or `no-go`) backed by the exact targetable frame share (ms/frame and % of wall clock across Spans A, B and C), plus memory and contract/ADR tradeoffs:

- **`#914`** (`view_facing`, actor, shadow, sprite frustum culling + `view_facing` instancing)
- **`#915`** split across its four triage sub-items: (a) bind-state deduplication, (b) per-frame resource ring + vertex-position-matched `rewrite_vertices` skipping `apex_buffer`, (c) apex-free world vertex layout + constant `light_level` removal (including the ~77 MiB world apex buffer RAM impact), and (d) offscreen pass hygiene (`StoreOp::Discard`, single `read_back_oldest` poll, reused readback buffers)
- **`#916`** (chunk-parallel headless `--workers N`: in-process vs subprocess architecture, RAM budget, and confirmation or revision of `#645` in [`evidence-limits.md`](../../../research/parity/evidence-limits.md))
- **`#919`** (plane-only offscreen target, weighed against replacing runtime `check_derivable` validation of GPU LUT output)
- **`#920`** (wide-view draw counts across all 8,251 `LOCATION` ticks, steady/peak world RAM, and static-prop un-baking tradeoffs)

## Acceptance and deliverables

- `journal.md` and `probe.patch` in `work/2026-11/918_lavapipe-render-time/`.
- [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) updated per the [`recording-findings`](../../../.agents/skills/recording-findings/SKILL.md) skill with items 1-4 (`[Bounded Observation]`), `#811` coverage, updated `LP_NUM_THREADS` status, `## Ruled out`, `## Open questions`, and `_Source:` links to `journal.md`.
- [`evidence-limits.md`](../../../research/parity/evidence-limits.md) `#645` sentence confirmed or revised in place, citing item 4 in `journal.md`.
- [`reconstruction.md`](../../../site/guides/reconstruction.md) (the site guide linking `evidence-limits.md`) checked for accuracy per `AGENTS.md` § Committing 5.
- Fresh reviewer pass per `AGENTS.md` § Committing 5, passing `mise run check`, and a closing comment on `#918` summarizing the go/no-go verdicts and linking [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md).

## Out of scope

- Any permanent change to `crates/`, `python/` or `parity_run.py --jobs` scheduling.
- `mesa-26.2.6` timing sweeps.
