---
title: "Recapture noise is heavy-tailed: how should the verdict tell noise from a change?"
started: 2026-11-09
issue: 305
outcome: ""
---

# Recapture noise is heavy-tailed: how should the verdict tell noise from a change?

On `BALLOON.FLM` and `CTRY.FLM` recapture noise comes from the archive's sound range (`0xC000`-`0xCFFF`): a capture pair with it stubbed agrees page for page, and `CTRY.FLM`'s demo archive, with shortened samples, replays identically too ([journal](journal.md)). This replaces consensus capture ([issue comment](https://github.com/neilsh/stunt-reel/issues/305#issuecomment-6732874951)) as the first candidate.

## Handoff

- Done: the cause recorded in [`method.md`](../../../research/parity/method.md) § 2.2.1 and [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4. The spike's captures are in `<data root>/spike/305/`.
- Done (PR 1): [spec](spec.md) and [plan](plan.md) Tasks 1 to 5: `stub_sound_samples`, `mise run stub-sound-samples`, `mise run capture-compare` (from #301), captures stub by default (`--sound-samples kept` otherwise), ADR 0043.
- Left (PR 2, plan Tasks 6 to 8): the drift check without a σ, then back up, recapture each reference film twice, compare, promote, repin, re-measure and retire `noise_sigma`.
