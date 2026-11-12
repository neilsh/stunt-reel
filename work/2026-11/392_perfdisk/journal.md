# Journal: OP_PERFDISK

## 2026-11-12: the handler read to its end and drawn

- **Question**: What does `PLAYONE`'s `OP_PERFDISK` handler draw, and does drawing it in `vm.rs` move the reference films ([#392](https://github.com/neilsh/stunt-reel/issues/392))?
- **Method**: The unpacked image (`mise run unlzexe`) read with `mise run disasm` over `0xA040..0xA2BC`, the span builder `0xD11D` and the normaliser `0x9FD9`. `vm.rs` then draws a 16-gon in the plane perpendicular to `regs[centre] - regs[axis]`, one face for each side, radius in register units. `mise run sod-census` before and after, `mise run parity` on commit `a8df7ce3` (`crates/` tree `17472a6`, RTX 4070). The before scores are the pinned expected tables, which a `bomb` render of `origin/main` reproduced (0.8100869, delta -0.0000001).
- **Result**: The handler builds one quadratic form and hands an ellipse to `0xD11D`, which writes row spans; no vertex count and no facing test; the entry `0xA040` has no hole, though a sibling entry `0xA05C` saves the spans instead of filling them (unread). CTRY also falls by 0.00002, and INTRO's IoU moves 0.9856691 to 0.9856574. Census: unchanged, 0 unimplemented opcodes other than the 14 `TAP`-only models (the census counts stops, and `PERFDISK` never stopped the walk). SSIM before to after: CTRY 0.89960 to 0.89958, INTRO 0.84177 to 0.84233, LAND 0.86539 to 0.86499, BALLOON 0.80298 to 0.80298, TRAINTNL 0.85181 to 0.85207, BOMB 0.81009 to 0.81146, LOCATION 0.80682 to 0.80726. The worst fall is LAND at -0.0004, and BOMB rises by 0.0014. Picture: `bomb` tick 2014, where a flat grey rectangle becomes a disc; the capture's frame at that tick shows a different scene, so the picture shows the shape, not the size.
- **Verdict**: adopted on the evidence-backed track (rule read at image offset `0xA040`; no film falls by more than 0.002, and INTRO, TRAINTNL, BOMB and LOCATION rise). Every delta is under 0.002, so the score does not itself attribute the gain.
- **Lives in**: [`sod-vm.md` § 8.8](../../../research/playone-exe/sod-vm.md#88-model-frame-the-other-generators); `references.toml` expected tables.

## 2026-11-12: merged with main, re-scored

- **Method**: `main` (view-facing trees #419, the census #421 and #422) merged in; `mise run parity` on commit `ea113a02` (`crates/` tree `aa69c72`, RTX 4070), against the merged pins.
- **Result**: SSIM main to merged: CTRY 0.89962 to 0.89960, INTRO 0.84172 to 0.84228, LAND 0.86539 to 0.86499, BALLOON 0.80299 to 0.80299, TRAINTNL 0.85181 to 0.85207, BOMB 0.81014 to 0.81151, LOCATION 0.80800 to 0.80845. Worst fall LAND -0.0004. `sod-census` is unchanged by this PR.
- **Size check**: `BOMB` ticks 2014 to 2058 show a dark disc in the capture; our render at those ticks draws a different camera, so no same-camera pair exists. Sizes agree only in order of magnitude; the radius stays unverified.
