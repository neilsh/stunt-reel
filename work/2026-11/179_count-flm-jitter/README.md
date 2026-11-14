---
title: "Find what moves the 50 Hz tick between boots (COUNT.FLM experiment)"
started: 2026-11-13
issue: 179
outcome: "[Bounded Observation] COUNT.FLM's 10-window capture varies with the 12-byte sound sample 0xC31E in its archive: ten stubbed traces were identical, ten with it kept gave five variants; the fallback setups were not needed."
---

# Find what moves the 50 Hz tick between boots (COUNT.FLM experiment)

**Question.** What moves the 50 Hz tick by one emulated frame between boots of `COUNT.FLM`: the archive's sound sample, or a setup such as `sbtype`, `core` or a host-driven key?

**Outcome.** The sound sample, as a `[Bounded Observation]` on the 10-window capture; that it also caused the 157-frame clock jitter is a `[Supported Inference]`. See [the journal entry](journal.md#2026-11-13-countflm-with-its-sound-sample-stubbed); the fact lives in [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4 and its open question 5.
