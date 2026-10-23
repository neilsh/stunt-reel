# SOD `OP_TAP` resolves an external anchor table

## Status

accepted

## Context

`OP_TAP` (`0x022E`) appears in 2,413 `.ALL`/`.RES` chunk stop sites. Disassembly of `PLAYONE.EXE` shows it copies `count` 28-byte records from a global terrain anchor table into the SOD vertex register bank; the operands are `reg_off`, `count`, then `count` byte offsets into that table. The records share their layout with `ANCHORPT.DAT`, which `MAP.BIN` terrain patches also index, and `CTRY.ALL` itself contains no anchor data.

## Decision

The SOD VM takes an optional `&[AnchorPoint]` anchor table (`SodAnchorPoint` when this was accepted; now `stunt_core::anchor`) at execution/transpile time and resolves `OP_TAP` from it. The CLI locates `ANCHORPT.DAT` beside the archive (with the existing scenery search path) and passes the parsed records. Without a table, strict decoding returns `SodError::MissingAnchors`; lenient decoding reports `SodStopReason::MissingAnchors` and retains geometry decoded so far.

## Considered Options

- **Pre-bake TAP vertices into `OP_VECTORS` during CLI ingestion.** Rejected: it creates a second bytecode dialect and hides the external-data dependency from the VM contract.
- **Carry anchor references in `SodModelIr` and resolve them at render time.** Rejected: anchors are static per scene, and render-time resolution would add a GPU-side data dependency for no benefit.
- **Treat TAP as a no-op or zero-fill anchors.** Rejected: both reproduce the degenerate polygons the ticket exists to fix.

## Consequences

`SodModelIr` is unchanged, but the VM/transpile entry points gain an anchor parameter. Partial SOD reporting now distinguishes missing anchors from unknown opcodes. The identity-transform path reconstructs model-space geometry, so the original engine's per-frame transform cache is not modelled.
