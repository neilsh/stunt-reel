---
title: "research: what PLAYONE.EXE steps per drawn frame rather than per film tick"
started: 2026-11-18
issue: 723
outcome: "Read statically: each drawn frame copies every slot's position to slot +0x24 before moving it, and the ground and collision probe sweeps from there, so the shadow's plane and box top can depend on the previous frame; no frame counter or reader of the per-frame deltas was found. Whether this explains CTRY's padded-archive pages is #779."
---

# research: what PLAYONE.EXE steps per drawn frame rather than per film tick

The static read is in the [journal](journal.md) and [`film-load.md`](../../../research/playone-exe/film-load.md) § 5.

## Handoff

Done: [`film-load.md`](../../../research/playone-exe/film-load.md) § 5 records the per-frame state, slot `+0x24..+0x2F`, and the probe sweep that reads it, and rules out a frame counter, a reader of `0x22DC` or a caller of `0x3712` (the one user of `0x22BE`) by any direct reference, and the pair test `0x1588`.
Left: the live check that the sweep is what changes CTRY's pages ([#779](https://github.com/neilsh/stunt-reel/issues/779), `local-only`), and other per-frame state in the film step's other calls, read only for counters (`film-load.md` open question 1).
