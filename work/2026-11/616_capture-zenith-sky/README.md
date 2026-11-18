---
title: "parity: capture sky mask omits PLAYONE's zenith indices 224-226"
started: 2026-11-18
issue: 616
outcome: "Attributed: the traintnl and bomb pixels at 224 to 226 on our geometry are shape paint (a wall rectangle, an emblem), so the scorer keeps the 227..=238 sky band; a positional sky rule is a follow-up."
---

# parity: capture sky mask omits PLAYONE's zenith indices 224-226

Attributed the capture pixels at palette indices 224 to 226 on the seven `VAULT` references from the capture planes alone.
The figures are in [`journal.md`](journal.md); the decision is in `research/parity/method.md` section 2.0 and the attribution in `research/parity/attribution.md` section 7.

## Handoff

- The scorer's `CAPTURE_SKY_INDICES` stays 227..=238, so no expected `iou` in `research/parity/references.toml` changes.
- The `background` band re-check moved to [#614](https://github.com/neilsh/stunt-reel/issues/614) (local-windows).
- Follow-up: a positional capture-sky rule that counts the zenith sky at 224 to 226 without counting shape paint ([#718](https://github.com/neilsh/stunt-reel/issues/718)).
