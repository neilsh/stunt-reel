# The reference sky range is separate from the renderer's sky shader

## Status

accepted; implemented

## Context

`PLAYONE.EXE` paints the sky as elevation bands of palette indices. The captured reference frames of `CTRY.FLM` show those bands at `227..=238` ([`palette-and-shading.md`](../../research/formats/concepts/palette-and-shading.md#sky-bands)). The native renderer draws its own sky with a band table in [`mode13h.wgsl`](../../crates/stunt-render/src/shaders/mode13h.wgsl), a model of the original that is still being fitted. The two ranges overlap but are not the same thing: the shader's table is a hypothesis about geometry, while the capture range is what the original actually scanned out.

Parity scoring masks the sky out of both frames, so the range it uses decides which pixels count as sky.

## Decision

The parity scorer uses a parity-local constant, `CAPTURE_SKY_INDICES: RangeInclusive<u8> = 227..=238`, in [`parity/mask.rs`](../../crates/stunt-score/src/parity/mask.rs). It describes the capture and is deliberately not shared with `mode13h.wgsl`. Its doc comment points at the research note. The report records the range as `sky_indices` in `report.json` ([`parity/mod.rs`](../../crates/stunt-score/src/parity/mod.rs)).

## Considered Options

- **Share one constant between the scorer and the shader.** Rejected. A change to the renderer's sky would then move the scoring mask, so the baseline would shift without any change to what PLAYONE draws. The scorer must describe the reference, not the renderer under test.
- **Derive the scorer's range from the renderer at run time.** Rejected for the same reason, and it would also tie a scoring result to a build of the renderer.

## Consequences

There are two sources of truth for sky indices: the capture constant and the shader's band table. Changing either one is a deliberate act that should be re-scored, and the `report.json` field lets a reader see which range a score used. The shader and the capture may still disagree; that disagreement is what parity measures.

## Amendment 2026-11-20: the renderer's sky follows the sky drawer

The shader's band table is gone: `crates/stunt-render/src/sky.rs` now lays out the bands, their colours 224 to 238 and `0xD0`, and the sun disc each frame from `PLAYONE`'s sky drawer `0x8C45` ([`palette-and-shading.md`](../../research/formats/concepts/palette-and-shading.md#sky-bands), [#617](https://github.com/neilsh/stunt-reel/issues/617)), and `mode13h.wgsl` draws that layout.
Read "the shader's band table" above as that layout; the decision stands, and the scorer's ranges still describe the capture alone.
