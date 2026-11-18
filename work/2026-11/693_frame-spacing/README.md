---
title: "Frame spacing under the capture harness is unmeasured, so var 10's previous value is a guess"
started: 2026-11-18
issue: 693
outcome: "Measured: under the capture profile drawn frames are mostly 0 or 1 tick apart, not 2 to 5; PREVIOUS_FRAME_TICKS set to 0 by an evidence-backed sweep (location 0.8320 to 0.8383 on lavapipe)."
---

# Frame spacing under the capture harness is unmeasured, so var 10's previous value is a guess

Under dosbox-automation's `capture` profile, the settings the reference captures use, `PLAYONE` draws several frames per film tick, so consecutive drawn frames are mostly 0 or 1 tick apart (2 in up to 19% of counted frames; unmapped changes of var 10 are not counted), not the 2 to 5 DOSBox-X showed at its default cycles.
The share at 0 varies by film and scene, so no constant fits every frame; of 0, 1 and 3, a sweep adopted 0.

- Journal: [`journal.md`](journal.md).
- The fact: [`angle-bank.md`](../../../research/playone-exe/angle-bank.md) § 2.
- The constant: [`bank.rs`](../../../crates/stunt-core/src/scene/bank.rs).
