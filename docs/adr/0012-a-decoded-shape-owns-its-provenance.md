# A decoded shape owns its provenance

## Status

accepted; implemented by unit B of the architecture deepening programme.

## Context

The `.SOD` decoder decided where a walk stopped in four places: the strict
stop-to-error remap and three duplicated "lenient returns a stop, otherwise an
error" branches. Partiality then travelled as parallel side lists - `ArchiveShapes.partial`
and `SceneReport.partial` - keyed by shape id, so it was lost as soon as shapes
were merged or passed on. The shape IR itself was four public vectors with no
record of how it was produced, and every consumer re-validated node ranges and
re-measured bounds on its own: the world builder, the renderer and the glTF
exporter each defended against offsets the decoder had produced.

## Decision

[`crates/stunt-core/src/sod/tessellate.rs`](../../crates/stunt-core/src/sod/tessellate.rs)
has one decode entry, `decode_sod(data, name, anchors, DecodeMode)`, where
`DecodeMode` is strict, lenient or census. All three run one VM pass and differ
only in the policy applied at a blockage.

A decoded shape carries its own [`DecodeRecord`](../../crates/stunt-core/src/contracts/shape.rs):
the stream's 10-byte header, the first blocking opcode (`stop`), the opcodes a
census decode stepped over in stream order, and the byte offset of the first
`OP_RETURN`. `SodModelIr::decode()` returns it, and authored shapes - the world
IR and the synthetic aircraft - return `None`. A Partial SOD is a decoded shape
whose record carries a `stop`; partiality is no longer a parallel list.

The shape owns the discipline its consumers rely on. `meshes()` yields one
whole-triangle mesh slice per contained node with every index inside that node's
own vertex window, and `extent()` answers min/max/radius in one vertex pass.
`decode_sod` enforces the arena, handle, slice and ordering invariants before it
returns, so a violation is `SodError::InvariantViolation` and a decoded shape
cannot be corrupt. The world, renderer and glTF exporter read `meshes()` and
`extent()`; their range repairs, clamp clauses and slice checks were deleted.

## Considered Options

- **Keep the side lists and add only a single stop decision.** Rejected: the
  partiality a consumer sees would still be a second structure that can be lost,
  and the CLI printers would still read a different shape than the renderer.
- **Put a completion enum on every shape.** Rejected: authored shapes have no
  decode and would report a fabricated "complete".
- **Expose a public `check()` that consumers call.** Rejected: the decoder is the
  only producer of decoded shapes, so validation belongs where the shape is
  built; consumers should not have to remember to validate.
- **Give the IR and record serde derives for future wire use.** Rejected: neither
  is a wire type today; adding derives for a hypothetical consumer invites a
  format nobody reads. The additive-field rule in SOP 4 applies when such a
  wire form exists.

## Consequences

- Consumers read provenance and geometry through the shape; a corrupt
  hand-built IR is no longer silently repaired by the world, renderer or glTF,
  which is a deliberate failure-mode change for internal code only.
- Adding a non-geometry draw such as `OP_ANIMATE` is a sibling collection plus an
  accessor beside `meshes()`; it does not change `meshes()`, `extent()` or the
  stop policy.
- Census mode returns a root-only shape with empty geometry; its record carries
  the step-overs and return offset.
- The contract documentation lives in [`docs/SPEC.md`](../SPEC.md) section 4,
  [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) and [`GLOSSARY.md`](../../GLOSSARY.md)
  (Partial SOD, Decode record).
