# The static world is streamed each frame, not uploaded

## Status

proposed 2026-11-23 for [#999](https://github.com/neilsh/stunt-reel/issues/999), a draft for the owner to accept, amend or reject.
On acceptance it moves to `docs/adr/` under the next free number (`0056` today), with the owner's choices on the open calls of [`design.md`](design.md) § 6 written into the Decision.
It would leave ADRs [0035](../../../docs/adr/0035-ground-lying-props-are-terrain-decals.md), [0045](../../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md) and [0046](../../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) standing: the draw order, the passes and the pipelines are theirs.

## Context

`build_world_ir` copies every static prop placement's geometry into one world mesh, and every render worker uploads all of it: on `LOCATION` `6,704,202` vertices and `333.75` MiB of buffers, of which one frame draws at most `60,838` vertices and on average about `7,000`, ground included ([journal](journal.md#2026-11-23-world-stream-sizes-a-frame-on-the-seven-reference-films)).
The walk already culls each placement on its own nodes, so un-baking buys no cull (`#920`), and `#920` closed as a no-go on performance and memory ([`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6).
On 2026-11-22 the owner ruled that architecture alone justifies changing this if it costs no performance and moves toward a more modern, maintainable design.
Instanced draws per shape, `#920`'s candidate, cannot keep the stores byte-identical: the bake rounds twice (`fl(v + pos)`, plus `base_y` on y, then the shader adds the eye offset), and a per-instance matrix or eye-relative position rounds once.

## Decision

- **Stream the visible slices.**
  The world mesh is not uploaded.
  Each frame the renderer copies the slices the walk emits (`collect_world_meshes`: ground, base, decal), with their vertices, rebased indices and rebased outline indices, into one small dynamic buffer set, in walk order, and draws contiguous ranges of it.
  The vertices, primitives and their order are the bake's, so only `vertex_index` changes; `prop_shape` reads a per-frame runs table built in the same pass.
- **Size it to the frame.**
  On the seven reference films the largest frame is `75,576` vertices, `76,008` indices and `149,956` outline indices, `2.88` MiB; the buffers start above that and grow on overflow (`design.md` open call 1).
- **Un-bake the CPU side.**
  A prop node references a shared shape mesh and a placement, and the stream builder replays the bake's own additions (`Placed::position`), so the streamed vertices stay bit-identical; placements whose triangles depend on where they stand (ADR 0045's flat-ground split, ADR 0035's snap, per-placement `OP_TAP` decodes) stay baked and stream like any other node (`design.md` open call 2).
- **Byte-identical, or it does not land.**
  Each step lands only if the stores of all seven reference films are byte-identical on lavapipe and the RTX 4070, and an offline test shows streaming every node reproduces the baked buffers byte for byte.

## Consequences

- Removed: the world's device buffers and staging copies, the per-worker world upload, the world apex buffer (if `design.md` open call 5 drops it), world chunk splitting, `marks`/`cut`/`cut_out`, the whole-world runs table, and after step 2 the CPU world mesh, the per-placement outline list and `release_world_mesh` (`design.md` § 3).
- Added: the stream builder, the dynamic buffers, the per-frame runs table, the placement references with their shared shapes, and the byte-identity test (`design.md` § 4).
- Each frame copies its visible world on the CPU and writes it to the device: about `0.26` MB a frame on `LOCATION`'s mean, up to `2.88` MiB; whether that costs lavapipe loop time is what the issue's loop gate measures.
- Between steps 1 and 2 the CPU mesh stays resident while rendering (`release_world_mesh` cannot run), so the peak-memory gate is checked at step 1, not assumed.
- A frame emitting more than the buffers hold grows them; the maxima above are of these films' captured ranges at `320 x 200`.

## Considered Options

- **Keep the baked world** (status quo). Costs about `333.75` MiB of buffers and an upload a worker on `LOCATION`, for no rendering benefit once the walk has culled.
- **Instanced draws per shape** (`#920`'s candidate). Rejected: a per-instance transform rounds once where the bake rounds twice, so the vertex positions, and the stores, would differ.
- **A per-placement frustum test on the baked mesh** (`#920` step 2). Rejected: it removes `0%` of the drawn world vertices, since each placement already has nodes of its own.
- **Un-bake only (step 2) and keep the upload of what stays.** Leaves the upload, the chunking and the cut machinery in place, so it removes less of what the owner's maintainability condition asks to simplify.
