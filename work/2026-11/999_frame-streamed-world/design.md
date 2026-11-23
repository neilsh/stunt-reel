# Design note: a frame-streamed world

Issue [#999](https://github.com/neilsh/stunt-reel/issues/999) asks for this note, with an ADR draft ([`adr-draft.md`](adr-draft.md)), before any code, and for the owner to accept both.
It sets out what the change removes and adds, a net count of each, and the open calls.
It changes no gate: the issue's gates (§ Gates below) are quoted as written.
Status: **proposed, awaiting the owner**; no renderer code is written.

## 1. What the inputs say

- **The probe** (this folder's [journal](journal.md#2026-11-23-world-stream-sizes-a-frame-on-the-seven-reference-films), `[Bounded Observation]`).
  Over all seven reference films' captured tick ranges, one frame's walk emits at most `75,576` vertices, `76,008` indices and `149,956` outline indices, all on `INTRO` tick 3635: `2.88` MiB at the upload's sizes (`3.74` MiB with a `12` B apex a vertex), against the `333.75` MiB of buffers `LOCATION`'s baked world uploads.
  `LOCATION`'s largest frame is `60,838` vertices, `62,712` indices and `116,832` outline indices (tick 5151), and its mean frame about `0.26` MB.
  A per-frame runs table would hold at most `987` run pieces (`399` merged), against `LOCATION`'s `31,441` runs.
- **`#920`** (closed not planned; [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3, § 6 and § 7).
  Each worker builds the world on the CPU in about `622 ms` and uploads it in about `471 ms` (lavapipe); removing the whole upload fell the post-upload resident set `413.4` MiB on lavapipe and `106.1` MiB on the RTX 4070 (Span A, one run each); the walk already culls each placement on its own nodes.
- **`#1000`** (closed by [PR #1010](https://github.com/neilsh/stunt-reel/pull/1010), § 6).
  Batching the world's decal slices by disjoint screen box is a no-go: its ceiling is `#920`'s `7.7%` grouping saving times the `45.8%` of the whole film's decal pipeline switches batching removes, about `3.5%` of the loop (`3.7%` span-weighted), inferences under its `5%` gate.
  The owner asked this note to cite that close.
  A stream keeps the decal slices in walk order, each outline after its fill ([ADR 0046](../../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)), so it removes none of those switches either.
- **`#1002`** ([PR #1011](https://github.com/neilsh/stunt-reel/pull/1011), § 3).
  Over the whole `LOCATION` film, the levers above 5% of lavapipe's queue thread, recomputed from [`profile-parts.json`](../1002_lavapipe-world-profile/profile-parts.json) as the mean of the two sampled base runs' shares: rasterizer threads `26.7%` (`26.92`, `26.41`), vertex processing `21.4%` (`21.46`, `21.38`), line setup `14.6%` (`14.55`, `14.65`), fragment-state copy `10.2%` (`9.86`, `10.49`), other state `8.5%` (`8.49`, `8.51`) and triangle setup `5.4%` (`5.41`, `5.41`); they agree with the note.
  The first, second, third and sixth follow the primitives drawn; a stream draws the same primitives in the same order (§ 2), so it is not expected to cut them, and the issue asks only that it cost nothing.
  Whether drawing a list's contiguous base slices as one range moves the state levers was not measured.
- **`#1001`**: not timed in this run.
  `#1004`'s A/A check ([PR #1016](https://github.com/neilsh/stunt-reel/pull/1016), § 3) missed the owner's `±1%` bar (one binary against itself on Span B, 4 pairs: median `-9.4%`), and the owner holds `#1001` until they have seen that.
  This note draws no conclusion from `#1001`.

## 2. The design (the issue's, restated)

1. **Stream the visible slices.**
   No world mesh is uploaded.
   Each frame the stream builder copies the slices `collect_world_meshes` emits, ground, then base, then decal, into one small dynamic buffer set: each emitted node's vertex window, its indices rebased to where the window landed, and its outline indices rebased the same way.
   Vertices, primitives and their order are the same f32 values in the same sequence, so only `vertex_index` changes, and `prop_shape` reads a per-frame runs table built in the same pass.
   The draws keep their order: ground slices one by one with their outlines (ADR 0045), the base slices then the base outlines, decal slices one by one with their outlines (ADR 0046).
   A list's slices lie back to back in the stream, so its base fills, and its base outlines, can each be one range.
   A `WalkStep`'s props become ranges of the stream instead of cuts of the baked mesh.
2. **Un-bake the CPU side.**
   A prop node references a shared shape mesh and a placement; the stream builder replays the bake's own additions (`Placed::position`: `fl(fl(v + pos) + base_y)` on y, `fl(v + pos)` on x and z, or the snapped vertex), so the streamed vertices stay bit-identical.

Pipelines, shaders other than `prop_shape`, and draw order are untouched, except as open call 5 says.

## 3. Removed

Step 1 (stream the visible slices):

1. **The world's device buffers and their staging copies**: the world `GpuChunk`'s vertex, index and outline buffers (`333.75` MiB on `LOCATION` with the apex and runs, `#920`), and the `write_buffer` copies of them that lavapipe fills at the first submit (§ 7).
2. **The per-worker world upload**: `GpuModel::from_ir_outlined` for the world in `SceneRenderer::new`, and `UploadTimes::world` (about `471 ms` a lavapipe worker).
3. **The world apex buffer** (`own_positions`, `76.72` MiB on `LOCATION`), if open call 5 is decided that way.
4. **World chunk splitting**: `plan_upload`'s split branch, `flush_run`, `ChunkPlan::indices`, `GpuChunk::vertex_ranges` and the split half of `plan_edges` (the cross-run boundary set); the world is the model they were written for, and even it plans one chunk under the 256 MiB limit on all seven films (probe; `#645` for `LOCATION`); whether any shape could need them was not checked.
5. **`marks`, `cut` and `cut_out`**: `GpuNode::marks`, `GpuModel::cut`, `WorldPlacements::marks`, `cut_out`, and the marks half of `plan_edges`; a `WalkStep` takes ranges of the stream.
6. **The whole-world runs table**: `GpuModel::attach_prop_runs` and `chunk_prop_runs` for the world's `31,441` runs, replaced by the per-frame table (Added 3).

Step 2 (un-bake the CPU side):

7. **The CPU world mesh** of the un-baked props: their vertices and indices in `World::ir` (`253` MiB of `LOCATION`'s built scene, § 7; `95.4%` of its vertices are in nodes un-baking would drop, `#920`).
8. **The per-placement outline list**: `plan_edges` over the whole world at start-up (`61` MiB at `LOCATION`'s peak, § 7), replaced by one outline per shared shape.
9. **`FilmScene::release_world_mesh`**, whose job (freeing the CPU mesh after the upload) goes with the upload; see open call 4 for what step 1 does in the meantime.

## 4. Added

1. **The stream builder** (step 1): a CPU pass over the walk's slices that appends vertices, rebased indices and rebased outline indices, and the runs table, in stream order.
   In step 2 it reads a prop node's vertices from its shared shape and replays `Placed::position` on each.
2. **The dynamic buffers** (step 1): one vertex, index and outline buffer (and an apex buffer if open call 5 keeps one), sized to a capacity that grows (open call 1), written once a frame.
3. **The per-frame runs table** (step 1): `prop_shape`'s table in stream vertex numbering, at most `987` entries on the seven films, bound as the world's runs are today.
4. **Placement references** (step 2): per prop node, a shared shape and a placement (`Placed`'s position, `base_y`, snapped vertices if any), and one store of shared shape meshes with their outlines (open call 2).
5. **The offline byte-identity test** (step 1, kept in step 2): streaming every node reproduces today's baked vertex, index and outline buffers byte for byte, as the issue's **Stores** gate asks.

## 5. Net count

| Step | Removed | Added | Net |
|---|---|---|---|
| 1 | 6 (5 if the apex buffer stays) | 4 (builder, buffers, runs table, test) | -2 (-1) |
| 2 | 3 | 1 (placement references and shared shapes) | -2 |
| Both | 9 (8) | 5 | -4 (-3) |

The count is of mechanisms as listed, not of lines; the issue's "Removed" acceptance item is checked against items 1 to 9.

## 6. Open calls for the owner

1. **Buffer growth and the per-frame write path** (#596).
   The probe's largest frame is `2.88` MiB; `LOCATION` moves about `2.0` GiB over the film at its mean frame.
   Options:
   (a) one buffer per stream, each written with its own `write_buffer` (three or four a frame);
   (b) one buffer holding every stream at aligned offsets (`VERTEX | INDEX` usage), written with one `write_buffer` a frame, as #596 packs the uniforms.
   Growth: start at a capacity above the seven films' maxima (for example `128k` vertices, `128k` indices and `256k` outline indices, about `4.5` MiB) and double on overflow, never shrinking; the probe's maxima are of these films' captured ranges at `320 x 200`, so another film, lens or viewport can need more.
   Two frames in flight need no second buffer set: `write_buffer` is ordered on the queue after the submission that read the previous contents.
   The copy's cost on lavapipe is not measured; it is what the **Lavapipe loop** gate decides.
2. **Where step 2's placement references live**, against `[I2]` (`docs/SPEC.md` § 2) and ADRs 0035, 0045 and 0046.
   `[I2]` asks for flat arenas and integer handles, which a `(shape, placement)` pair of indices meets.
   (a) In `SodModelIr` as a new node kind: changes seam 3, so it follows [`changing-seam-contracts`](../../../.agents/skills/changing-seam-contracts/SKILL.md), and every consumer of the world IR (`stunt-gltf` among them) must expand it;
   (b) in a world-side table keyed by `NodeId`, beside `MeshSpans`: no seam change, and the IR keeps its prop nodes with empty windows.
   Not every placement draws its shape's own triangles: ADR 0045 splits each placement's flat-ground triangles (by its placed height) into `WORLD_GROUND` nodes, ADR 0035 snaps a ground-lying prop's vertices onto the terrain, and `OP_TAP` shapes decode per placement; `#920` counted that class at `15.71` MiB of `LOCATION`'s buffers against `318.04` MiB dropped.
   The note's proposal is that those stay baked and stream like any other node, and that a reference covers only a placement whose nodes hold its shape's triangles unchanged in order; the stream order is the walk's either way, so ADR 0046's ordered decal pass is unchanged.
3. **Whether ground slices stream too.**
   The ground slices peak at `14,935` vertices a frame (`TRAINTNL` 101).
   Streaming them leaves no static world model, so items 1 to 6 go whole; keeping them baked keeps an uploaded ground model (the `WORLD_GROUND`, terrain and ocean nodes) and with it the upload path for that model.
   The note proposes streaming them, since the draw order and the pipelines are unchanged either way.
4. **Memory between step 1 and step 2.**
   Step 1 streams from the CPU mesh, so `release_world_mesh` cannot run after start-up and the CPU mesh (`253` MiB on `LOCATION`) and the outline list stay resident while rendering, where today they are freed.
   By `#920`'s one-run figures the world's device buffers (`333.75` MiB) go and the start-up peak no longer holds the mesh, its staging copies and the device buffers at once, so the **Peak memory** gate may still hold; that is arithmetic on other runs' figures, not a measurement, and the RTX 4070, whose resident set held only `106.1` MiB of the world, is the adapter where it is least sure.
   If step 1 fails that gate, steps 1 and 2 land together.
5. **The apex stream** against "pipelines untouched".
   The world's apex is each vertex's own position, so the stream can drop the apex buffer only if the world's pipelines read the apex from the vertex stream (a second vertex-buffer layout at the 28 B stride), which changes their layout; keeping "pipelines untouched" means streaming a `12` B apex a vertex (`3.74` MiB at the largest frame).
   The issue lists both; the owner picks one.
6. **Order against `#1001`.**
   `#1001`'s body asks whether it lands first and `#999` builds on it, or the other way round.
   A stream gives `prop_shape` a table of at most `987` entries a frame on these films; this note draws no conclusion on `#1001`'s cost or order, which waits on the owner's `#1004` decision.
7. **The view-facing path** (#926, closed not planned).
   The stream takes slices from any CPU-side source in walk order, so view-facing props could feed it later; their vertices are drawn today through per-draw matrices, so feeding them would bake their positions per frame and round differently, which the **Stores** gate would catch.
   Nothing in this design blocks that path or builds it.
8. **Cuts in the shared `WORLD_BASE` and `WORLD_DECAL` slices.**
   Today a sprite's props are cut out of those two slices at their placement's marks; `#920` found no placement with geometry there on `LOCATION` or `INTRO`, and the other five films were not checked.
   The stream builder would emit such a placement's span as its own range, with its share of the outline, so the marks' data moves into the builder rather than vanishing; whether any reference film exercises it should be checked before step 1 lands.

## 7. Gates (the issue's, as written)

Measure as in #920: one release binary per side, 4 interleaved pairs, Windows mesa-dist-win 25.2.8 and the RTX 4070.

- **Lavapipe loop:** the whole `LOCATION` film (`12..=8262`) median loop is no slower than base, within 2%.
- **RTX 4070 loop:** the same figure, reported but never gating.
- **Peak memory:** no higher on either adapter (`--report-memory`).
- **Stores:** byte-identical on all seven reference films, on both adapters.
  An offline test shows that streaming every node reproduces today's baked buffers byte for byte.

`#1004`'s A/A check on Span B differed `9.4%` between two identical binaries in a 4-pair median, against the `2%` the loop gate reads on the whole film; the gate is not changed here, but whether a 4-pair median resolves it is the owner's `#1004` question.

## 8. What remains after this note

- The owner accepts or amends this note and the ADR draft, and decides open calls 1 to 8.
- Step 1, then step 2, each meeting every gate, with step 1's figures in its journal and `lavapipe-render-time.md` § 6.
- The mechanisms § 3 lists are gone.
