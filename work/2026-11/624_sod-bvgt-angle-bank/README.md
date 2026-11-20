---
title: "sod: BVGT reads the angle bank, so rotors draw line blades when spinning"
started: 2026-11-19
issue: 624
outcome: "OP_BVGT now reads the angle bank at draw time and records its operand in DecodeRecord::bank_operands; location rescored unchanged (0.8383 SSIM, 0.9796 IoU) because PREVIOUS_FRAME_TICKS = 0 keeps bank word 0x12 at 0."
---

# sod: BVGT reads the angle bank, so rotors draw line blades when spinning

- Journal: [`journal.md`](journal.md).
- Research note: [`framing-and-actors.md`](../../../research/parity/framing-and-actors.md#3-location-the-rotors-solid-blades-on-every-tick).
- Implementation: [`vm.rs`](../../../crates/stunt-core/src/sod/vm.rs), [`vm_tests.rs`](../../../crates/stunt-core/src/sod/vm_tests.rs).
