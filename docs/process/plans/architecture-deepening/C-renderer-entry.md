# Unit C: the renderer entry point

Status: design agreed 2026-10-24; all stages merged. Source: architecture review card 5 (one renderer entry point for headless and window).

## 1. Problem

Opening a renderer exists twice: the headless one is a struct of public GPU fields built with a high-performance-then-software adapter fallback, the window one hand-builds instance, surface, adapter, device, pipelines, LUT, camera resources and scene renderer with a high-performance-only policy. The CLI holds `device`, `queue` and `pipelines` to draw, the crate re-exports about 40 items including GPU internals, and a pipeline change touches GUI code.

## 2. Constraints

- Two real destinations: offscreen readback (PNG, planes, video) and a surface (present, resize, free-cam, pause).
- Invariants I3, I5, I6 and I7 survive; 320x240 offscreen, 320x200 / 185-row parity configuration, 4:3 letterbox on surfaces.
- No behaviour change: window pixels and keys, headless output bytes, plane packing and the parity baseline stay identical.
- The CLI stops naming GPU types.
- ADR-0006: under `STUNT_REQUIRE_GPU` a missing adapter must fail rather than skip; the software adapter is first-class CI; the window path cannot run in CI and must be isolated.
- wgpu 24, winit 0.30, pollster 0.4; no new dependency.
- Unit A is settled: the CLI journal is the first artifact sink; `stunt-render` must not depend on the parity port crate.

## 3. Decisions settled in the design round

- **Base:** the two-constructor design with a page sink, unified acquisition policy and explicit resize, with the minimal-interface design's grafts.
- **Options:** a boolean `software_only` instead of a GPU policy enum; the acquisition policy itself is fixed.
- **Window handle:** raw-window-handle trait bounds on the surface constructor, recorded as windowing traits rather than GPU types.
- **Resize:** explicit `resize`; offscreen is a documented no-op.
- **Output:** the sink seam stays inside `stunt-render`; unit A's journal is the first adapter.

## 4. Chosen design

### Seam placement

`crates/stunt-render/src/renderer.rs` is the module. The crate root keeps only `Renderer`, `Offscreen`, `PageSize`, `PageSink`, `SinkError`, `RenderedPage`, `RenderOptions`, `RenderError` and the `LAYER_*` constants. `SceneRenderer` and the GPU plumbing become crate-private; the plane is the test seam.

### Interface

    impl Renderer {
        pub fn offscreen(scene: &FilmScene, target: Offscreen,
                         sink: Box<dyn PageSink>, options: RenderOptions) -> Result<Self, RenderError>;
        pub fn surface<W>(scene: &FilmScene, window: Arc<W>, options: RenderOptions)
            -> Result<Self, RenderError>
            where W: wgpu::rwh::HasWindowHandle + wgpu::rwh::HasDisplayHandle + Send + Sync + 'static;
        pub fn draw(&mut self, frame: &SceneFrame, camera: Option<&CameraController>)
            -> Result<(), RenderError>;
        pub fn resize(&mut self, width: u32, height: u32);
    }
    pub trait PageSink { fn accept(&mut self, page: RenderedPage) -> Result<(), SinkError>; }
    pub struct RenderOptions { pub clear_palette_index: u8, pub software_only: bool }
    pub enum RenderError { NoGpuAdapter, DeviceRequest, SurfaceCreate, SurfaceConfig, Readback, Sink, SurfaceOutOfMemory }

### Invariants

- Destination is fixed at open; offscreen requires a sink, surface presents. The caller never branches on destination and never receives readback.
- `draw` is synchronous, never advances time, uploads `frame.palette` into the 256x32 LUT first (I3), applies a camera override without changing the scene frame's LOD distances, and skips actors whose shape was not uploaded.
- Ordering: instance, then surface if any, then adapter, then device; within a frame palette, prepare, base meshes, decal meshes (I5).
- Offscreen `draw` calls `accept` exactly once after readback mapping; surface `draw` reconfigures and drops the frame on a lost surface and returns `SurfaceOutOfMemory` on exhaustion.
- `resize` clamps to the adapter's `max_texture_dimension_2d`, reconfigures and recreates the depth view; offscreen page size is fixed at open.
- One acquisition policy for both destinations: instance with all backends, then surface when needed, then a high-performance adapter with `compatible_surface`, then a low-power `force_fallback_adapter`, then a device with `downlevel_defaults().using_resolution(limits)`. A software adapter is an outcome, not an offscreen privilege.
- No public signature names a GPU type; raw-window-handle windowing traits are the recorded exception.
- The sink owns every file, so the interface never learns a path; a sink failure is terminal.
- Guarantees: I3, I5, I6, I7 untouched.

### What the interface hides

Readback pitch and stripping, texture/buffer/target creation, the `R32Uint` plane target and packing, palette-derived clear colour, the viewport-rows squeeze, surface format choice (non-sRGB so the LUT is not encoded twice), letterbox viewport/scissor/bars, depth-view lifetime, adapter negotiation and both attempts, pollster blocking, mesh upload, and the prepare/draw split.

## 5. Dependency strategy and adapters

- In-process: wgpu, pollster, glam, bytemuck, the scene renderer.
- Local-substitutable: the GPU with lavapipe as the CI stand-in (ADR-0006), and temporary directories for sinks in tests.
- Ports and adapters: the destination seam (offscreen readback, window surface) and the sink seam (unit A journal, single PNG, ffmpeg, test ledger).
- True external: ffmpeg and the window system; the window adapter is thin and untested in CI.

## 6. Migration

1. Add the offscreen constructor, moving today's headless machinery behind it; `run_headless` builds a sink around the existing PNG/plane/sidecar writers. Bar: identical PNG bytes and byte-identical `.idx`/`.layer`.
2. Add the surface constructor, moving `pick_surface_format`, depth-view creation, configuration, letterbox and bars out of `window.rs`; `resize` replaces the resize body.
3. Re-point unit A's journal at `RenderedPage` for geometry, palette and planes; the port crate stays unaware.
4. Delete `HeadlessRenderer`, `HeadlessError`, the GPU-shaped root re-exports and the CLI's `wgpu`/`pollster` dependencies; require `rg wgpu crates/stunt-cli/src` empty while the window still builds. Bar: window title, 960x720 logical, AutoVsync, latency 2, 4:3 bars, clear index, keys, free-cam and pause unchanged.

## 7. Tests

- Survive without a GPU: palette LUT integrity, camera/aspect ratio, SSIM evaluator, SSIM cross-check.
- Move under lavapipe to `renderer_test.rs` through `draw` and `RenderedPage`: headless execution (page lengths, alpha, plane words), unaligned-width pitch, the four scene-renderer tests, and the interval export with a counting sink.
- Move without a GPU: surface format preference into the surface module; the 28-byte vertex stride into a pure pipelines unit test.
- Die: shader-compilation and dual-pipeline depth-bias tests, replaced by a plane test that a coplanar decal wins the depth tie.
- New: one `accept` per draw; sink error surfaces; `viewport_rows(185)` leaves lower rows at the clear index; resize no-op offscreen; `software_only` renders on lavapipe; `RenderedPage` invariants.
- Untested and recorded as such: window present and resize, free-cam input, surface acquisition, and every adapter that is not lavapipe.

## 8. Deletions

`HeadlessRenderer`'s sixteen public fields, `HeadlessError`, `render_scene`/`render_scene_with_plane`, the window bootstrap and depth helper, the root re-exports of GPU model/mesh types, `RenderPipelines`, `PaletteLut`, `CameraGpuResources` and `SceneRenderer`, and the CLI's `wgpu` and `pollster` dependencies.

## 9. Kill criteria

Abandon or re-shape if: a public signature names a GPU type (raw-window-handle windowing traits excepted); the CLI still imports wgpu after phase 4; window pixels or keys, PNG bytes, plane bytes or report fields change; `open` needs another lifecycle call before it can render; offscreen fails on lavapipe under `STUNT_REQUIRE_GPU`; a destination needs its own draw; `RenderedPage` forces a copy beyond readback; or `software_only` spreads past one caller.

## 10. Open items

Names (`Renderer`, `Offscreen`, `PageSink`, `RenderedPage`) are proposals. The single-PNG and ffmpeg sinks land in migration phase 1; unit A's journal sink in phase 3. The window path stays untested in CI and is recorded as such.

## 11. Landing log

Merged as 58745f8 together with unit B; full `mise run check` green.

1. **Stage 1, offscreen.** `Renderer::offscreen`, `PageSink`, `RenderedPage`, one acquisition policy including the software fallback, one accept per draw; `run_headless` migrated. 3-tick byte compare against the baseline: PNG, `.idx` and `.layer` identical 9/9.
2. **Stage 2, surface.** `Renderer::surface` owns the window bootstrap, format choice, resize and letterbox; `window.rs` dropped from 533 to 245 lines and keeps title, size, timing, keys, free-cam, pause and clear colour by inspection. Byte compare 9/9 identical. Release build and a short window smoke were run locally.
3. **Deletion stage merged (95d8d4f).** `HeadlessRenderer` and `HeadlessError` deleted; `mesh`, `palette`, `pipeline` and `scene_renderer` made crate-private; the GPU re-exports removed; `CameraGpuResources` moved to `pub(crate)`; `wgpu` and `pollster` dropped from `stunt-cli`, with one authorised doc-link fix in `main.rs`. Verification: `cargo doc` with `-D warnings` clean, `rg wgpu|pollster crates/stunt-cli/src` empty, clippy clean, three-tick render 9/9 byte-identical, parity reports unchanged. `mesh.rs` keeps a module-level allow until its items become `pub(crate)`, tracked as a follow-up.
