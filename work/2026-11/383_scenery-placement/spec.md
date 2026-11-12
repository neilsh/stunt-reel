# Scenery placement module

Status: agreed in conversation 2026-11-10, from an architecture review (candidate 3 of six); not
started. Implementation starts in a fresh session from this file.

## Intent

[`world.rs`](../../../crates/stunt-core/src/world/mod.rs) (now `world/mod.rs`; this spec describes it before the split) was 2,080 lines, about 1,230 of them outside
tests (which start at l.1227). It mixes two jobs:

- Building the `World`: the ground, the terrain and the `build_world_ir` meshes.
- Working out where the props stand: the SCENERY.scn walk with its LOD gate, then dedup, then the
  sub-pixel cull.

The second job has no interface of its own. `traverse_scn` is `pub(crate)` and takes nine
parameters:

- Four carry recursion state: `ni`, `cx`, `cy`, `cz`.
- `depth`.
- The output `Vec`.
- Three lookup arguments: `words`, `available_models` and `near`.

About 17 in-file tests reach the walk through those internals. Some also reach `walk_scn` and
`ScnWalk` directly. Changing any of those signatures breaks the tests, even when the placements are
the same.

The goal is one deep module that answers a single question: given the inputs, which props stand
where, and did the walk stop early? Its tests go through that question only.

## Current shape (2026-11-10)

- **Entry point.** `build_world(inputs: &WorldInputs, shapes: &HashMap<u16, SodModelIr>) ->
  Option<World>` (l.305) is the only public entry. Its only non-test caller is
  [`scene.rs:393`](../../../crates/stunt-core/src/scene.rs).
- **Order inside `build_world`:**
  1. `available_models` is built from `shapes.keys()` (l.321).
  2. `near` is built from `inputs.view_eyes` with `path_distance`, `lod_threshold` and `LOD_SCALE`
     (l.325–328).
  3. `traverse_scn` runs from `1, 0, 0, 0` at depth 0. It calls `near` at each `SP_1NODE` to choose
     the subtree or the stand-in, so LOD is applied during the walk, not afterwards.
  4. `dedup_instances` runs (l.341).
  5. `cull_subpixel_instances` runs with `view_eyes`, `inputs.max_zoom.max(1.0)` and `shapes` for each
     shape's radius (l.345, l.454–459).
- **Walk.** `traverse_scn` (l.529, pub(crate)) wraps the private `walk_scn` (l.561) and `walk_chain`
  (l.606). The state is held in:
  - `ScnWalk`: `on_path`, `visits`, `budget`, `stop`, `halted`.
  - Two private constants: `SCN_VISITS_PER_WORD` (l.222) and `SCN_MAX_DEPTH` = 128 (l.225).
- **Placement-only items.** These are `pub(crate)` or private, and nothing outside `world.rs` uses
  them. Greps of `crates/`, `stunt-cli` included, found no other user.
  - Steps: `dedup_instances` (l.366), `lod_threshold` (l.426), `cull_subpixel_instances` (l.441).
  - Helpers and constants: `path_distance`, `point_segment_distance`, `LOD_SCALE`, `FOCAL_PIXELS`,
    `CORNER_DEPTH_FLOOR`, `MIN_PROP_PIXELS`. `FOCAL_PIXELS` is also cited in the doc of `WorldInputs`
    (l.47).
- **Stop types.** `ScnStop` (l.174) and `ScnStopReason` (l.205) are public and defined in
  `world.rs`. They are imported by `scene.rs:29`, `scene_test.rs:24` and `world_test.rs:13`.
- **Tests.**
  - [`world_test.rs`](../../../crates/stunt-core/tests/it/world_test.rs) imports exactly
    `ScnStopReason`, `WorldInputs` and `build_world`, and calls `build_world` 13 times.
  - Cycle stops are asserted at `world_test.rs:414` and `scene_test.rs:529`.
  - The sub-pixel cull is tested only through `build_world` (`world_test.rs:209`), as is a dedup case
    (`world_test.rs:238`).
  - In-file tests in `world.rs`:
    - The walk tests: l.1324–1721. Some use `walk_scn`, `ScnWalk`, `walk.halted` and `SCN_MAX_DEPTH`
      directly (l.1466–1510).
    - `test_lod_threshold_matches_playone_branches`: l.1723.
    - `test_prop_deduplication_signed_zero`: l.1880.
  - Corpus counts are recorded only as prose. CTRY keeps 286 of the 6,345 instances it places after
    dedup and the cull ([`attribution.md:86`](../../../research/parity/attribution.md)).
- **Governing notes:**
  - [`scenery.md`](../../../research/formats/auxiliary/scenery.md)
  - [`map.md`](../../../research/formats/auxiliary/map.md)
  - [`anchorpt.md`](../../../research/formats/auxiliary/anchorpt.md)
  - [`world-scene.md`](../../../research/playone-exe/world-scene.md)
  - [`render-model.md`](../../../research/parity/render-model.md)

## Decisions

1. **Scope.** This topic is candidate 3 only. Candidate 1, one module for an archive's shapes in
   `stunt-cli`, is a separate PR after this one. The review's other candidates are out of scope.
2. **One module.** A new `crates/stunt-core/src/world/scenery.rs` owns these:
   - The walk, with its LOD gate.
   - Dedup.
   - The sub-pixel cull.
   - Every helper and constant listed under "Placement-only items" above.

   `world.rs` keeps the `World` build and calls the module once. It stays where it is, and Rust's
   `world/` directory beside it holds the new file. If `FOCAL_PIXELS` moves, update the doc reference
   on `WorldInputs`.
3. **What leaves the interface.** These become private to the module:
   - The walk's internal inputs: the start node, the origin offset, `depth`, `ScnWalk`, `walk_scn`
     and `walk_chain`.
   - The steps `traverse_scn`, `dedup_instances`, `cull_subpixel_instances` and `lod_threshold`.

   The walk always starts at the root.
4. **What the module returns.** The final placements (the walk with LOD applied, then dedup, then the
   cull) and the reason the walk stopped early, if it did. `ScnStop` and `ScnStopReason` stay public.
   If they move into `scenery.rs`, `world.rs` re-exports them, so the paths `crate::world::ScnStop`
   and `world::ScnStopReason` keep working.
5. **Tests replace, not layer.** Rewrite the in-file walk, LOD and dedup tests as tests of the
   module's interface, built from synthetic SCENERY words. These cases stay covered:
   - Cycles, and halt outranking an earlier stop.
   - The depth cap and the visit budget.
   - Chains.
   - Missing models and unknown opcodes.
   - The `Malformed` stop variants, and a null pointer not counting as a stop.
   - The `near` (LOD) gate and the `lod_threshold` branches.
   - Duplicates, including signed zero.
   - Sub-pixel props. This is a new module-level test. The `world_test.rs` version stays.

   Three cases currently enter the walk below the root, or inspect the gate's arguments. Each gets
   new synthetic words or a new observable that reaches it from the root:
   - `walk_from`, which uses a nonzero `cx` for position overflow (l.1537).
   - The null-pointer test, which starts at node 0 and node 99 (l.1493–1508).
   - The `near` test, which records `(pos, ext, splitdist)` (l.1695–1706).

   A case that cannot be reached from the root does not justify widening the interface. Drop it
   only if the walk cannot produce it from the root, and say so in the PR body. `world_test.rs` stays
   as it is. The `parse_map_bin`, `push_terrain` and `build_world_ir` tests stay in `world.rs`.
6. **Output unchanged, checked on the corpus.** The refactor must not change output.
   - Before the first code change, a local-only run over every film in the corpus records the
     instance count and a hash of the placements for each film.
   - After the change, the same run must match exactly.
   - The script and its output stay uncommitted (directive 1).
   - The PR body states the film count and that everything matched.
   - The PR changes no rendered output, so it needs no before/after picture.
7. **Glossary.** Add two terms to [`GLOSSARY.md`](../../../GLOSSARY.md) and use them in the module's
   doc comments:
   - **Placement**: a prop's model id and position, after the walk, dedup and the cull.
   - **Scenery walk**: the SCENERY.scn traversal, including its LOD gate, that produces placements.
8. **Routing.** [`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md) gets a row for the new file
   that names its invariants and research notes.
   - Confirm while implementing which of `[I1]`, `[I2]` and `[I3]` the file carries.
   - The existing `world.rs` row (l.35) lists `[I1]` and `[I5]`. Re-check it once the split is done.

## Left open for implementation

The exact interface is not settled. Before writing code, sketch two shapes and pick one (design it
twice).

The module needs four inputs: `scenery`, the shapes (for the model set and each shape's radius),
`view_eyes` and `max_zoom`. The open points are:

- **How the view inputs arrive.** The module could take `&WorldInputs` whole, or only the two view
  fields.
- **How `near` is built.** It could be built inside the module from `view_eyes`, or injected as a
  closure. Injection is only worth it if a test needs it to reach a gate case.
- **The result shape.** Either a struct holding the placements and an `Option<ScnStop>`, or a tuple.
- **The placement type.** Either a named struct, or the existing `(u16, [f32; 3])`.

Whichever shapes are chosen, a test must need nothing beyond synthetic SCENERY words, a small shape
map and the view inputs.

## Done when

- `world.rs` holds no walk, LOD gate, dedup or cull code.
- None of the items in decision 3 are visible outside `world/scenery.rs`.
- The module's own tests cover every case in decision 5 through its interface only, apart from any
  case named in the PR body as unreachable.
- The corpus before/after run matches for every film.
- The glossary and `ARCHITECTURE.md` changes from decisions 7 and 8 are in.
- `mise run check` passes.
- This folder's README `outcome` is written.
