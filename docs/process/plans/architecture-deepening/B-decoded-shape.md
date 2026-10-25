# Unit B: the decoded shape seam

Status: design agreed 2026-10-24; implemented, merged 58745f8. Source: architecture review cards 2 (one stop decision), 3 (shape IR owning interface) and 4 (partial SOD carries its stop), designed as one seam and shipped as up to three PRs.

## 1. Problem

Four copies of the stop policy: the strict wrapper's stop-to-error remap and three "lenient returns Ok(stop), otherwise Err" branches. A second opcode-width table consulted only by the census step-over. Partiality as parallel side lists that never reach the shape. A shape IR that is four public vectors: the SOD header is discarded, and the world, the renderer and the glTF exporter each re-validate node ranges and recompute bounds on their own.

## 2. Constraints

- Invariant I2: flat `Vec<SodNode>` arena indexed by `NodeId(u32)`; no recursive pointers.
- Invariant I7: no I/O and no new dependency in `stunt-core`.
- `contracts/shape.rs` is the only definition of Seam 3 fields; G03 gates the 28-byte vertex, the arena and sharp facet normals.
- No decoded geometry or render output change; the local parity baseline stays identical.
- Offline synthetic fixtures only.
- Strict, lenient and census keep their public behaviour until PR3 replaces them with one entry point.
- T10 facts: `OP_ANIMATE` is a clipped screen-space image draw, not geometry; completeness must not be defined as "geometry emitted"; the `.FLM` animate-to-selector mapping is still Unknown.
- The IR types have no serde derives, so the additive-field serde(default) rule is inapplicable; record the exception instead of adding derives.
- GLOSSARY gains **Decode record**; **Partial SOD** is sharpened to "a decoded shape whose decode record carries a stop".

## 3. Decisions settled in the design round

- **Base:** the provenance-record design with the validated-invariant design's checks enforced internally; no public `check()` or `ShapeIndex` surface.
- **Partiality and header:** a `DecodeRecord` on decoded shapes, returning `None` for authored shapes.
- **Census:** delete `SodWalk`, `SodWalkEnd` and `SodSkip`; migrate the census CLI onto the decode record.
- **`OP_ANIMATE` channel:** deferred; the extension point is recorded, no `draws` field yet.

## 4. Chosen design

### Interface

    pub enum DecodeMode { Strict, Lenient, Census }
    pub fn decode_sod(data: &[u8], name: &str, anchors: Option<&[AnchorPoint]>,
                      mode: DecodeMode) -> Result<SodModelIr, SodError>;

    pub struct DecodeRecord {
        pub header: SodHeader,            // was parsed and discarded
        pub stop: Option<SodStop>,        // first blocking opcode
        pub stepped_over: Vec<SodStop>,   // census order: first blocking, rest masked
        pub returned_at: Option<usize>,   // first OP_RETURN; (None, None) = end of data
    }
    impl SodModelIr {
        pub fn decode(&self) -> Option<&DecodeRecord>;   // None for authored shapes
        pub fn meshes(&self) -> impl Iterator<Item = ShapeMesh<'_>>;
        pub fn extent(&self) -> Option<ShapeExtent>;     // min, max, radius
    }

`ShapeMesh` carries node, vertices, indices, vertex offset and index offset. `SodStop`, `SodStopReason` and `SodHeader` move into `contracts/shape.rs`.

### Semantics

- `decode()` is `Some` only for shapes a decode produced; authored shapes (the world IR, the demo aircraft) are `None` and never claim a fabricated completeness.
- `stop` is the first blocking opcode; `stepped_over` is census-only stream order; `returned_at` is the first `OP_RETURN`; `(None, None)` means end of data. Census ignores anchors and steps each `OP_TAP` by its count.
- `meshes()` yields one `ShapeMesh` per valid mesh node in arena order, empty slices included; index count is a multiple of three; every index lies inside its node's own vertex window and below `vertices.len()`.
- `extent()` is one pass over vertices; `None` iff there are no vertices; radius is the maximum |position| (an AABB-corner distance would cull props differently).
- Errors: malformed header, operands and truncation are errors in every mode; a blocked stream is an error only in Strict; an unskippable census opcode is recorded in `stop`.
- Performance: Strict and Lenient are one VM pass plus tessellation, O(V + I); Census walks operands only and returns empty geometry; `meshes()` is allocation-free; `extent()` is O(vertices).

### Internally enforced invariants (a defect is a decoder bug, surfaced as SodError)

Dense arena (`nodes[i].id == NodeId(i)`), symmetric parent/child handles and one root, slice containment (offsets and counts inside the buffers, `index_count % 3 == 0`, every index inside its node's window), non-decal slices before decal slices in ascending index offset, and extent derived from vertices only. Enforced inside `decode_sod`; there is no public check type. Hand-built authored IRs are trusted internal constructions.

### What the interface hides

The stop-site identity and the single stop-or-step-over decision; the opcode-width source; register arithmetic; TAP operand validation; raw polygons; decal identification; welding; node ranges; header parsing and scale; the stop-to-error mapping.

### T10 extension point

When `OP_ANIMATE` lands: delete its census entry (fixed words 4, count word 3), add a sibling image-draw collection and one accessor; `meshes()` stays geometry-only, `extent()` stays metric, and the stop policy does not change.

## 5. Dependency strategy and adapters

- In-process: decode, tessellation, `meshes()`, `extent()`.
- Local-substitutable: the archive bytes behind `decode_archive_shapes` and the anchor table.
- Ports and adapters: three policy adapters (Strict, Lenient, Census) over one VM; `decode_archive_shapes` is the archive-driving adapter; the CLI is the I/O adapter.
- The census width table stays a const (one adapter) guarded by the modulo-9 and no-shadow tests.

## 6. Migration (each landing green, baseline identical)

1. **One stop decision:** private VM run and blocked/step-over classification; `run_vm` returns the verdict; public functions become translations; VM unit tests move onto public calls.
2. **Partial SOD carries its stop:** move header/stop/reason into `contracts/shape.rs`; add `DecodeRecord`, the private field and `decode()`; set it in both transpiles; delete `ArchiveShapes.partial` and `SceneReport.partial`; printers read decoded shapes sorted by shape id; update SPEC section 4, ARCHITECTURE and GLOSSARY.
3. **One entry point and shape-owned ranges:** add `meshes()` and `extent()`; switch world (delete the radius fold, the AABB loop, the unguarded prop slice and the index re-filter), render (sources from `meshes()`, delete clamps) and glTF (POSITION bounds from `extent()`, delete index and slice checks); collapse the three public functions into `decode_sod`; delete `SodWalk`, `SodWalkEnd` and `SodSkip`; migrate `sod_census.rs`. Verify report fields identical and sampled `.idx`/`.layer` byte-identical.

## 7. Tests

- Survive: `sod_spec.rs:673-763` strict variants; `sod_tap_test.rs:57-111` through `decode_sod`; `sod_fuzz.rs`; the render and scene-renderer tests; glTF structural tests; tessellate welding tests.
- Move: `vm_tests.rs:341-417` onto `decode_sod` plus `decode()`; `vm_tests.rs:463-488` keeps the table guard and calls Strict; `sod_census_test.rs:52-128` onto `stepped_over` and `returned_at`, one case pinning first-blocking/rest-masked; `scene_test.rs:164-188` onto `shape.decode().stop`.
- Die: the world corrupt-prop filter; the render drops-out-of-range half; the glTF IndexOutOfRange and MeshSliceOutOfRange halves; assertions written through `execute_sod_vm*` and `transpile_sod_lenient`.
- New: `meshes_never_yields_an_unsafe_slice`, `extent_of_empty_shape`, `authored_shape_has_no_decode_record`, `census_records_masked_opcodes`, a synthetic masked fixture, and an internal-defect refusal.

## 8. Deletions

`execute_sod_vm`, `execute_sod_vm_impl` and the strict remap; `SodSkip`, `SodWalk`, `SodWalkEnd`; `ArchiveShapes.partial` and `SceneReport.partial`; `transpile_sod`, `transpile_sod_lenient` and `walk_sod`; range and bounds re-validation in world, render and glTF.

## 9. Kill criteria

Abandon if: the baseline needs consumer clamping; `OP_ANIMATE` forces `meshes()` to branch on draw type instead of adding a sibling collection; census needs a mode flag in every handler or a second width table; the decode record breaks a committed fixture; or a landing cannot stay green alone.

## 10. Open items

Names (`DecodeRecord`, `ShapeMesh`, `ShapeExtent`, `DecodeMode`) are proposals, confirmed in PR1. The serde exception is recorded in PR2. GLOSSARY terms land with PR2. Census geometry is empty and documented.

## 11. Landing log

Merged as 58745f8 together with unit C stages 1-2; the full `mise run check` passed on the integrated tree (Rust workspace and doc tests, 262 Python tests).

1. **One stop decision.** The VM returns one `VmRun` and asks one policy at every blockage; strict, lenient and census are translations. Existing VM and census assertions were rewritten onto the public entry point.
2. **Partial SOD as a value.** `SodHeader`, `SodStop` and `SodStopReason` moved into the seam; `DecodeRecord` and `SodModelIr::decode()` added; `ArchiveShapes.partial` and `SceneReport.partial` deleted; the CLI reads records sorted by shape id.
3. **Shape-owned discipline.** `decode_sod` is the only decode entry and enforces the arena, handle, slice and ordering invariants (`SodError::InvariantViolation`); `meshes()` and `extent()` landed; world, renderer and glTF consume them and their re-validation was deleted; `SodWalk`/`SodSkip`/`walk_sod`/`transpile_sod*` and the glTF range error variants were deleted; census migrated onto the record. `OP_ANIMATE` stays deferred with its extension point recorded.

Docs: SPEC section 4, GLOSSARY (Partial SOD and Decode record), ARCHITECTURE decoding paragraph, ADR 0012.
