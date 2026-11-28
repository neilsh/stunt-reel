# The static world is streamed each frame, not uploaded

## Status

accepted 2026-11-26 for [#999](https://github.com/neilsh/stunt-reel/issues/999): the owner accepted the design note ([`design.md`](../../work/2026-11/999_frame-streamed-world/design.md)) and settled its open calls ([comment](https://github.com/neilsh/stunt-reel/issues/999#issuecomment-7184561095)), on the condition that the ADR enters `docs/adr/` only once stage C passes its gates; stage C ([#1093](https://github.com/neilsh/stunt-reel/issues/1093)) passed them and was implemented on 2026-11-28.
Stage D, un-baking the static props onto shared shapes ([#1094](https://github.com/neilsh/stunt-reel/issues/1094)), is not yet implemented.
It leaves ADRs [0035](0035-ground-lying-props-are-terrain-decals.md), [0045](0045-flat-ground-is-painted-in-walk-order.md) and [0046](0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) standing: the draw order, the passes and the pipelines are theirs.
The draft it was made from is [`adr-draft.md`](../../work/2026-11/999_frame-streamed-world/adr-draft.md).

## Context

`build_world_ir` copies every static prop placement's geometry into one world mesh, and every render worker uploaded all of it: on `LOCATION` `6,704,202` vertices and `333.75` MiB of buffers, of which one frame draws at most `60,838` vertices and on average about `7,000`, ground included ([journal](../../work/2026-11/999_frame-streamed-world/journal.md#2026-11-23-world-stream-sizes-a-frame-on-the-seven-reference-films)).
The walk already culls each placement on its own nodes, so un-baking buys no cull (#920).
On 2026-11-22 the owner ruled that architecture alone justifies changing this if it costs no performance and moves toward a more modern, maintainable design.
Instanced draws per shape cannot keep the stores byte-identical: the bake rounds twice (`fl(v + pos)`, plus `base_y` on y, then the shader adds the eye offset), and a per-instance matrix or eye-relative position rounds once.

## Decision

* **Stream the visible slices.**
  The world mesh is not uploaded.
  Each frame the renderer copies the slices the walk keeps (`collect_world_meshes`: ground, base and decal, ground included), with their vertices, apexes, rebased indices and rebased outline indices, into one buffer, in walk order, and draws them from it (`world_stream.rs`, `stream_buffers.rs`).
  The vertices, primitives and their order are the bake's, so only `vertex_index` changes.
* **One write a frame into one growable buffer.**
  The four sections share one buffer, written with one `write_buffer` a frame; it grows to the next power of two, at least double, from an 8 MiB floor, and never shrinks.
* **Pipelines untouched.**
  The apex stream stays: each streamed vertex carries its apex and its prop shape word in the second vertex stream, as the baked buffer held it.
* **No buffer splitting.**
  Only the world could outgrow a buffer, so every other model is uploaded as one buffer set.
* **Un-bake the CPU side (stage D).**
  A prop node references a shared shape mesh and a placement through a world-side table keyed by `NodeId`, not a new IR node kind, so seam 3 is unchanged; a function expands it back to baked geometry for the glTF export.
  The stream builder replays the bake's own additions (`Placed::position`), so the streamed vertices stay bit-identical; placements whose triangles depend on where they stand (ADR 0045's flat-ground split, ADR 0035's snap, per-placement `OP_TAP` decodes) stay baked and stream like any other node.
* **Byte-identical, or it does not land.**
  Each stage lands only if the stores of all seven reference films are byte-identical on lavapipe and the RTX 4070.

## Consequences

`[Bounded Observation]`, stage C against `main`, one run of each gate on one machine ([journal](../../work/2026-11/999_frame-streamed-world/journal.md#2026-11-28-stage-c-the-stream-as-the-only-world-path-loop-memory-and-stores)):

* The whole `LOCATION` loop on Windows lavapipe moved `-0.4%` (faster in 3 of 4 pairs), within the issue's `+2%` bar; on the RTX 4070 it was `+14.5%` slower (all 4 pairs), which the issue reports and does not gate on.
* Peak memory on `LOCATION` ticks 12-120 fell `285.6` to `287.4` MiB on lavapipe and `16.3` to `17.3` MiB on the RTX 4070; the stores were identical on all seven films on both.
* Removed: the world's device buffers and staging copies, the per-worker world upload, buffer splitting, and the `STUNT_WORLD_STREAM` switch.
  `marks`, `cut` and `cut_out` stay: a sprite's props are cut out of a shared slice at their placement's span ends, and the outline offset at each end is computed only by the plan.
* Until stage D the renderer keeps a CPU copy of the mesh for the stream after the scene frees its own, and on the RTX 4070 the resident set after the renderer opens rose about `277` MiB, which that copy is inferred, not measured, to account for.
* Each frame copies its visible world on the CPU and writes it to the device: on the seven films' captured ranges at `320 x 200`, up to about `4.61` MiB a frame at today's vertex and apex sizes (`stream_buffers.rs`); a frame that needs more grows the buffer.

## Considered Options

* **Keep the baked world** (the status quo before #999). It cost about `333.75` MiB of buffers and an upload a worker on `LOCATION`, for no rendering benefit once the walk has culled.
* **Instanced draws per shape** (#920's candidate). Rejected: a per-instance transform rounds once where the bake rounds twice, so the vertex positions, and the stores, would differ.
* **A per-placement frustum test on the baked mesh** (#920 step 2). Rejected: it removes `0%` of the drawn world vertices, since each placement already has nodes of its own.
* **Un-bake only (stage D) and keep the upload of what stays.** Leaves the upload and the splitting in place, so it removes less of what the owner's maintainability condition asks to simplify.
* **One buffer per stream, each with its own write** (design note open call 1 (a)). The owner chose one buffer and one write a frame instead, as #596 packs a frame's uniforms into one write.
