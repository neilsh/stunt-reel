---
title: "research: what PLAYONE.EXE steps per drawn frame rather than per film tick"
started: 2026-11-18
issue: 723
outcome: ""
---

# research: what PLAYONE.EXE steps per drawn frame rather than per film tick

The static read is in the [journal](journal.md) and [`film-load.md`](../../../research/playone-exe/film-load.md) § 5.

## Handoff

The per-frame call steps no frame counter, `0x22DC` has no reader by address, `0x22BA` feeds input timing, and the `0xB58D` phase follows the timer.
Still to read: `0x14D5`, `0x240A` and `0x1588` in the slot update `0x1463` (state kept from the previous frame?), the callers of `0x3712` and `0xB58D`, and the film step's other calls (`film-load.md` open question 1).
