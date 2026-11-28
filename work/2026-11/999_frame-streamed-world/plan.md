# Draw the world from the per-frame stream (stage B, #1092) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or superpowers:subagent-driven-development) to implement this plan task by task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With `RenderOptions::world_stream` on (`STUNT_WORLD_STREAM=1` from the CLI), the scene renderer stages the frame's world slices on the CPU, writes them to one growable GPU buffer with one `write_buffer` a frame, and draws the world from it.
With it off, behaviour is today's, with one `match` per world draw added.
The goal is stores byte-identical either way; Tasks 6 and 7 check it.

**Architecture:** Stage A's [`WorldStream`](../../../crates/stunt-render/src/world_stream.rs) already stages slices and rebases indices; this plan
(1) makes the stream carry #1001's per-vertex shape word instead of a runs table,
(2) lets it restage the slice lists the renderer already holds, in place,
(3) adds `StreamBuffers`, one GPU buffer holding the vertex, apex, index and outline sections, and
(4) routes the world's draws through either the baked `GpuModel` or the stream.
Culling (`collect_world_meshes`) and sprite cuts (`GpuModel::cut`) are unchanged: they read only the CPU node arena, and the stream copies whatever slices they produce.
With the switch on, the world's device buffers are not created at all (Task 3), so stage B measures the stream's own memory and answers design.md open call 4; with it off, the baked upload is today's.

**Spec:** [`design.md`](design.md) § 2 to § 6 and the owner's settled open calls on [#999](https://github.com/neilsh/stunt-reel/issues/999#issuecomment-7184561095) (2026-11-26 triage comment): one `write_buffer` a frame, one buffer for all the streams, grow to the next power of two and at least double, never shrink; ground streams too; pipelines untouched.
Issue: [#1092](https://github.com/neilsh/stunt-reel/issues/1092).
Read `design.md` first; this plan argues from it.

**Base branch:** this plan's branch is stacked on PR #1101 (`neilsh/1001-prop-shape-shader-search`, #1001), which carries each world prop vertex's shape word in the 16 B second vertex stream (`mesh::ApexVertex`).
Open call 6 says whichever of #999 and #1001 lands second adapts; this stack adapts #999 to #1001.
If #1101 is closed instead of merged, rebase onto `main` and restore stage A's per-frame runs table (`WorldStream::runs`, `chunk_prop_runs`) and bind it at `PROP_RUNS_GROUP`; Tasks 1 and 4 say what changes.

## Global constraints

- `mise run check` passes at the end of every task (AGENTS.md Directive 2); iterate with `mise run check-rust` and `STUNT_REQUIRE_GPU=1 mise run test-gpu` (lavapipe runs it in a cloud session).
- No pipeline, vertex layout, bind group layout or shader changes: the stream's vertex section is `SodVertex` at its 28 B stride and its apex section is `ApexVertex` at 16 B, exactly what `RenderPipelines::vertex_buffer_layout` already reads.
- No seam contract change (`crates/stunt-core/src/contracts/`), no `stunt-core` change at all in this stage.
- `[I2]` flat arenas and integer handles; `[I5]` the decal pass is unchanged (each decal slice's outline right after its fill); ADR 0045's ground order is unchanged.
- With the option off, no new allocation, buffer or branch cost beyond one `match` per world draw.
- Corpus-free tests only (Directive 1): GPU tests build synthetic worlds.
- Commits: paths staged by name, Conventional Commit subjects (`feat(render): ...`, `test(render): ...`, `docs(parity): ...`), a body that says why.

## File map

| File | Change |
|---|---|
| `crates/stunt-render/src/world_stream.rs` | Task 1 (shape word per vertex), Task 2 (restage in place) |
| `crates/stunt-render/src/mesh.rs` | Task 1 (drop `chunk_prop_runs` if unused), Task 3 (plan the world without device buffers) |
| `crates/stunt-render/src/stream_buffers.rs` (new) | Task 4 |
| `crates/stunt-render/src/lib.rs` | Task 4 (`mod stream_buffers;`) |
| `crates/stunt-render/src/renderer/mod.rs` | Task 5 (`RenderOptions::world_stream`, passed to `SceneRenderer::new`) |
| `crates/stunt-render/src/scene_renderer.rs` | Task 5 |
| `crates/stunt-cli/src/config/mod.rs`, `crates/stunt-cli/src/headless.rs` | Task 5 (`STUNT_WORLD_STREAM`, the start-up line) |
| `crates/stunt-render/tests/gpu/scene_renderer.rs` | Task 6 |
| `work/2026-11/999_frame-streamed-world/` | Task 7 (store script, journal, README) |

## Task 1: the stream carries the shape word

Stage A stages each streamed vertex's apex as `[f32; 3]` and builds a per-frame runs table (`WorldStream::runs`, from `mesh::chunk_prop_runs`) for the `prop_shape` search that #1101 removed.
On top of #1101 the stream's apex section must be `ApexVertex` (position and shape word), so no table is needed.

- [ ] Change `WorldStream::apex` to `Vec<ApexVertex>`.
  In `append`, after taking the window `range`, extend it with `mesh::apex_vertices(source.apex, std::slice::from_ref(&range), source.prop_runs)` (make `apex_vertices` `pub(crate)`).
  That is the same function the baked upload fills its apex buffer with, so a streamed vertex's 16 B equal the baked buffer's for the same source vertex.
- [ ] Delete `WorldStream::runs` and its `chunk_prop_runs` call; delete `mesh::chunk_prop_runs` and its test if nothing else uses it (`rg chunk_prop_runs crates/`).
- [ ] Update the tests: `the_runs_table_follows_the_streamed_windows` becomes a test that each streamed vertex's `prop_shape` equals the run's `shape + 1` for its source vertex, with windows streamed out of source order (reuse that test's runs and expected words).
  The byte-identity test compares `bytes(&stream.apex)` with `bytes(&apex_vertices(&apex, &[0..n], &[]))`.
- [ ] Fix the module doc and `WorldSource` docs (no runs table; the shape word rides in the apex section).
- [ ] `mise run check-rust`; commit `refactor(render): carry the shape word in the world stream's apex section (#1092)`.

*Without #1101:* skip this task.

## Task 2: restage the renderer's slice lists in place

`prepare` ends with the world's slices in several lists: the world draw's `ground`, `base` and `decals` (`PreparedDraw` with `Target::World`), and each `WalkStep::props`' `base` and `decals` after `place_sprites` cut the sprites' props out (`WorldPlacements::split`, `GpuModel::cut`).
The stream must hold every one of them, and each list must then address the stream.

- [ ] Add `WorldStream::restage(&mut self, source: &WorldSource<'_>, lists: &mut [&mut Vec<GpuMeshSlice>]) -> Result<(), SliceOutsideSource>`: clear, then append every slice of every list in the order given, replacing each slice with the streamed one.
  On an error, clear the stream and leave the lists as they were (stage into a scratch `Vec<GpuMeshSlice>` and write back only on success).
- [ ] Replace `rebuild` and the stream's own `ground`, `base` and `decals` lists with `restage`: `rebuild` has no caller outside `world_stream.rs`'s tests, which call it at about seven sites; port each to `restage` over local lists.
  The design's offline byte-identity test (stream every node, compare with the baked buffers) must stay.
- [ ] Test: restaging lists `[ground, base, decals, step0.base, step0.decals]` gives the same `vertices`, `apex`, `indices` and `edges` as one `rebuild` of the concatenation, and the lists' slices draw the same index ranges as the stream's own lists did.
- [ ] Test: a slice of chunk 1 in the last list leaves the stream empty and every list unchanged.
- [ ] Commit `feat(render): restage the world stream from the renderer's slice lists (#1092)`.

Note on cuts: [#1090](https://github.com/neilsh/stunt-reel/issues/1090) found no placement cut out of the shared `WORLD_BASE` and `WORLD_DECAL` slices on the seven reference films ([`lavapipe-world-draws.md`](../../../research/parity/lavapipe-world-draws.md)); a cut slice still streams like any other (its own index and edge range), so the stream does not depend on that finding, but the seven-film store check (Task 7) exercises cuts only where a film has them.
Cite that in the PR as #1092 asks.

## Task 3: plan the world without device buffers

The stream copies outline indices from the same list the baked chunk's edge buffer holds (`plan_edges` output), so a streamed slice's `edge_offset` means the same thing.
Today that list goes to the GPU and is dropped, and the world's device buffers (about `334` MiB on `LOCATION`, design.md § 1) are created whether or not anything draws from them.

- [ ] Split `GpuModel::upload` into a CPU-only planning step (nodes, roots, bounds, marks, the slice plan and the outline list from `plan_edges`) and the step that creates each chunk's device buffers (`GpuChunk::upload`).
- [ ] Add a constructor for the streamed world, for example `GpuModel::plan_outlined(ir, outlined, marks) -> Option<(GpuModel, Vec<u32>)>`, that runs only the planning step: the model has no chunks (`chunks` empty), and the `Vec<u32>` is the one chunk's outline list.
  It returns `None` when the plan splits the model into more than one chunk: stage A's stream refuses a split world, and the design note's probe found one chunk on each of the seven films; the caller then uses the baked upload.
  `from_ir_outlined` keeps its signature and behaviour, built from the two steps.
- [ ] Unit test (no GPU): `plan_outlined` on a fixture world gives the same nodes, marks and outline list as `plan_edges` on the same plan (the stage A tests' `baked` helper computes it), and `None` for a fixture forced to split (a small `max_buffer_size`, if the planning step takes the limit as an argument).
- [ ] Commit `refactor(render): plan the world's slices and outline without device buffers (#1092)`.

## Task 4: `StreamBuffers`, one buffer written once a frame

New module `crates/stunt-render/src/stream_buffers.rs`.

- [ ] `pub(crate) struct StreamLayout { vertices: Range<u64>, apex: Range<u64>, indices: Range<u64>, edges: Range<u64>, len: u64 }` and a pure `fn layout(stream: &WorldStream) -> StreamLayout`: sections back to back in that order, each starting on a multiple of `wgpu::COPY_BUFFER_ALIGNMENT` (4 B; every section's size already is one, since `SodVertex` is 28 B, `ApexVertex` 16 B and indices 4 B, but assert it).
  Index sections hold `u32`, so their offsets must be multiples of 4 for `set_index_buffer` (they are).
- [ ] `pub(crate) fn grown_capacity(current: u64, needed: u64) -> u64`: `current` when it fits; otherwise the next power of two at or above `max(needed, 2 * current)`, with a floor above the probe's maxima: its largest frame is `3.74` MiB with a 12 B apex, and with the 16 B `ApexVertex` `75,576 * 4` B more, about `4.03` MiB, so 8 MiB, said in a comment citing the journal; another film, lens or viewport can need more, which growth handles.
  Never shrinks.
- [ ] `pub(crate) struct StreamBuffers { buffer: Option<wgpu::Buffer>, capacity: u64, layout: StreamLayout, staging: Vec<u8> }` with:
  - `fn write(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, stream: &WorldStream)`: compute the layout (each section's length exactly `count * stride`: 28 B a vertex, 16 B an apex, 4 B an index, since wgpu checks draws against the bound slice's size); if it outgrows `capacity`, create a new buffer (`VERTEX | INDEX | COPY_DST`, label `stunt_world_stream`) at `grown_capacity`; pack the four sections into `staging` (cleared, not reallocated, each frame) at the layout's offsets with `bytemuck::cast_slice`; one `queue.write_buffer(buffer, 0, &staging)`; skip the write when the stream is empty.
  - `fn draw_slices(&self, rpass, meshes: &[GpuMeshSlice])`: binds vertex buffer 0 to the vertex section, 1 to the apex section, the index buffer to the index section, then `draw_indexed(index_offset..index_offset + index_count, 0, 0..1)` per slice (the stream's slices all have `chunk == 0` and `vertex_offset == 0`).
  - `fn draw_edges(&self, rpass, meshes)`: the same with the edge section as the index buffer, skipping slices with `edge_count == 0`, as `GpuModel::draw_edges` does.
  Bind once per call, not per slice.
  Both draw functions do nothing while `buffer` is `None` (an empty stream skips the write).
  Two frames in flight need no second buffer: `write_buffer` is ordered on the queue after the submission that read the previous contents (design.md open call 1), and `prepare` runs once per submit on both the offscreen and the surface paths (`renderer/mod.rs`).
- [ ] Unit tests (no GPU): `layout` of a stream with known counts gives contiguous, aligned sections; `grown_capacity` keeps, doubles, jumps to the next power of two, applies the floor, and never shrinks.
- [ ] Commit `feat(render): add the world stream's GPU buffer, written once a frame (#1092)`.

*Without #1101:* the apex section is `[f32; 3]` at 12 B, and the stream's runs table needs a storage buffer for `PROP_RUNS_GROUP`; give it its own small buffer (it is `STORAGE`, which `VERTEX | INDEX` cannot share without a usage change the owner did not settle) and say so in the PR.

## Task 5: the scene renderer draws the world from the stream when asked

- [ ] `RenderOptions::world_stream: bool` (default `false`), documented as the stage B debug switch of #999; pass `options.world_stream` to `SceneRenderer::new` at both its callers in `renderer/mod.rs` (offscreen and surface).
  Test sites build `RenderOptions` with `..Default::default()`; `crates/stunt-cli/src/config/mod.rs` `render_options` is a full struct literal and must name the field.
- [ ] The CLI reads `STUNT_WORLD_STREAM=1` once where it builds its config from the options (not inside `render_options`, which stays pure), stores it, and `render_options` copies it, so `mise run ab -- --variant 'stream STUNT_WORLD_STREAM=1'` can time one binary under both settings later; `config/tests.rs` stays unaffected.
  Print one `[stuntreel] world stream: on` line when it is on, beside `headless.rs`' other start-up lines.
- [ ] `SceneRenderer` gains, only when the option is on and the scene has a world:
  - the world model from `GpuModel::plan_outlined` (Task 3) in place of `from_ir_outlined`, so no world device buffer exists; when it returns `None`, the baked upload and today's draws, with the stream off for the run and one start-up line saying why.
  - `stream_source: Option<StreamSource>`, an owned copy of what `WorldSource` borrows: the world's `ir.vertices`, `ir.indices`, `prop_runs`, and the outline list from Task 3.
    No apex copy: the world's apex is each vertex's own position, so make `WorldSource::apex` an `Option<&[[f32; 3]]>` where `None` reads `vertices[i].position` (saves about `77` MiB on `LOCATION`, design.md § 3 item 3), and keep `Some` for the stage A tests that pass one.
    Task 1's `apex_vertices` call then takes the window's own positions when `apex` is `None`; give `apex_vertices` positions as an iterator if that is simpler than a slice.
    It must be copied in `SceneRenderer::new`, because the CLI calls `FilmScene::release_world_mesh` after the renderer opens (`crates/stunt-cli/src/headless.rs`); that holds the mesh twice until the release, and then keeps about 253 MiB of CPU mesh resident on `LOCATION` (design.md open call 4), both of which Task 7's memory check measures.
  - `stream: WorldStream` and `stream_buffers: StreamBuffers`.
  With the option off these are `None` / empty and never touched.
- [ ] At the end of `prepare` (after `place_sprites`, before returning), when `stream_source` is set: collect `&mut` to every world slice list in draw order (the `Target::World` draw's `ground`, `base`, `decals` in `self.prepared`, then each `self.steps[i].props`' `base` and `decals`), `restage` them, then `stream_buffers.write(device, queue, &stream)`; `prepare` already takes the device and queue.
  `place_sprites` returns early when no sprite is placed, so `self.steps` may be empty; borrow the lists with `iter_mut` over `self.prepared` (filtered to `Target::World`) chained with `self.steps`, since `restage` takes disjoint `&mut Vec`s.
  A split world never reaches here (Task 3), so `SliceOutsideSource` is a bug: there are no baked buffers to fall back to, so draw no world that frame, leave the lists untouched, and log it (`eprintln!`, once) so the store check catches it.
- [ ] Route the world's draws: replace `resolve`'s `&GpuModel` with a small `enum Drawable<'a> { Model(&'a GpuModel), Stream(&'a StreamBuffers) }` with `draw_slices` and `draw_edges` that forward; `Target::World` resolves to `Stream` when the world is streamed, else `Model`.
  The ground loop in `draw` (which calls `world.draw_slices` / `draw_edges` directly) goes through the same enum.
  Draw order, pipelines, bind groups 0 to 2 and the uniform are unchanged.
- [ ] `UploadTimes::world` keeps measuring the world's construction, which with the switch on is the plan and the source copy, not an upload; say so in its doc comment.
  The baked path stays for the switch off (stage C deletes it).
- [ ] Commit `feat(render): draw the world from the per-frame stream behind STUNT_WORLD_STREAM (#1092)`.

## Task 6: GPU tests, stream on against stream off

- [ ] In `crates/stunt-render/tests/gpu/scene_renderer.rs`, add tests that render the same synthetic world scene with `world_stream` off and on and assert identical colour, layer and shape planes (`RenderedPage` frames, layers, shapes):
  - a world with ground, base and decal nodes and outlines (reuse an existing fixture such as the one behind `a_world_props_run_reaches_the_shape_plane`, which also checks the shape word);
  - a frame with a placed sprite whose props are cut into a `WalkStep`, if an existing test builds one (`rg place_sprites crates/stunt-render/tests`); if none does, cover it with the unit test of Task 2 and say so;
  - two frames rendered in a row with different cameras, so the second frame's restage and write replace the first's (catches a stale buffer or a growth bug);
  - a frame large enough to force a buffer growth past the floor (or a test-only floor), then a smaller frame.
- [ ] `STUNT_REQUIRE_GPU=1 mise run test-gpu` passes on lavapipe in the cloud.
- [ ] Commit `test(render): the streamed world draws what the baked one does (#1092)`.

## Task 7: seven-film stores and peak memory, and the record

Stores (#1092's first acceptance item).

- [ ] Cloud lavapipe (canonical Ubuntu `mesa-vulkan-drivers 25.2.8`): fetch the data (`mise run cloud-assets -- fetch --replace-unmarked && mise run game-builds && mise run superset-all`), build one release binary, and render all seven reference films twice, with `STUNT_WORLD_STREAM` unset and `=1`.
  Adapt `work/2026-11/1001_prop-shape-shader-search/store_check.py` into this folder as `stream_store_check.py` (variants are an environment setting on one binary, not two binaries; it must write a fresh CSV, not append, and take the binary path as an argument), and commit its `stream-stores.csv`.
  Every film's frames, layers, palettes and shapes hashes must match.
- [ ] Windows lavapipe (mesa-dist-win 25.2.8) and the RTX 4070: the same script on the owner's machine, run through the thread that owns this work (Remote Control on Legion, folder `E:\git\stunt-reel`); report back to the PR rather than block on it.
  If `mise run ab` cannot render films other than `LOCATION`, the script's renders stand, as #1092 allows; say so in the PR.
  The renders relink each film's `.ALL` with `target/release/stuntreel.exe` (`render_film`), so build or copy one there first in a fresh worktree.
  On the owner's RTX 4070, `modern::the_vignette_leaves_the_centre_and_darkens_the_corners_by_its_formula` fails on `main` too while CI passes; a local `mise run check` failure on that test alone is not this stack's.
- [ ] Check every render with the switch on printed `[stuntreel] world stream: on`, workers included, so a store match is known to come from the stream.
- [ ] Peak memory (#1092's second item): `--report-memory` on `LOCATION` ticks `12..120`, three runs each with the switch off and on, on cloud lavapipe here and on both Windows adapters on Legion.
  With the switch on there are no world device buffers but a CPU copy of the mesh stays resident (design.md open call 4), and the mesh is held twice until `release_world_mesh`; the figure says whether the stream alone passes the memory gate.
  If it does not, the PR says so and why, as #1092 allows, and per the owner's call 4 steps 1 and 2 (stages C and D) land together.
- [ ] Journal entry in [`journal.md`](journal.md) dated the day of the runs: what was built, the store table, the memory table, how each was run.
  README `State` gains a stage B line; `outcome` stays empty (stage C and D follow).
- [ ] Before pushing changes to `work/` docs that cite research notes, follow AGENTS.md § 3 rule 5 for any `research/` or `docs/` change; this stage should need none (stage C writes `lavapipe-render-time.md` § 6).

## Delivery: a stack of PRs

Each layer is its own PR, based on the layer below, retargeted down the stack as each merges ([stacked PRs](../../../docs/agents/issue-tracker.md#conventions)).

| Layer | Base | Tasks | Title | Merges when |
|---|---|---|---|---|
| 0 | `main` | PR #1101 (#1001) | `perf(render): carry a world prop vertex's shape word in the apex stream (#1001)` | the owner's call on its mixed loop gate |
| 1 | layer 0 | Tasks 1 to 4 | `refactor(render): stream world slices with their shape words into one GPU buffer (#1092)` | `mise run check` and GPU tests pass; nothing draws from it yet, so no store or timing run |
| 2 | layer 1 | Tasks 5 to 7 | `feat(render): draw the world from a per-frame stream behind STUNT_WORLD_STREAM (#1092)` | cloud and Windows store checks match; memory reported |
| 3 | layer 2 | stage C, [#1093](https://github.com/neilsh/stunt-reel/issues/1093) | make the stream the default, delete the baked upload, move the ADR | the lavapipe loop gate (`mise run ab`, with `mise run icount` beside it) and peak memory pass |
| 4 | layer 3 | stage D, [#1094](https://github.com/neilsh/stunt-reel/issues/1094) | un-bake the static props onto shared shapes | stores, the glTF export, loop within 2% of layer 3, memory |

This plan details layers 1 and 2.
Layers 3 and 4 each get their own plan, written from the layer 2 figures, before code: layer 3's deletions are design.md § 3 items 1 to 6, and its timing needs a quiet Legion and one task at a time.
Layer 1 and 2 bodies say `Part of #999` and `Part of #1092`; layer 2 says `Closes #1092` once the Windows store check is in.
If layer 0 is closed rather than merged, rebase layer 1 onto `main` and apply the *Without #1101* notes above.
Neither layer 1 nor 2 times the loop.

## Review focus

1. A world decal slice's outline must still follow its own fill in the decal pass (`[I5]`, ADR 0046): `encode`'s per-slice loop must call the stream's `draw_slices` then `draw_edges` for one slice at a time, exactly as with the baked model.
2. A sprite's props cut into `WalkStep`s must be restaged too; a list missed by `restage` would still address the baked buffers' numbering and draw garbage from the stream (Task 6's sprite case or Task 2's test).
3. A streamed vertex's apex section must hold the same 16 B as the baked apex buffer (shape word included), or the shapes store changes (Task 1 test, Task 7 shapes hashes).
4. With the switch off, `prepare` and `draw` must not allocate or copy anything new (no `stream_source`, no `restage`, no `write`).
6. With the switch on, no world device buffer may be created (`plan_outlined`, Task 3); a stray `from_ir_outlined` for the world would hide the memory figure Task 7 reports.
5. Growth must replace the buffer before the write and never write past `capacity` (`write_buffer` past the end is a wgpu validation error).
