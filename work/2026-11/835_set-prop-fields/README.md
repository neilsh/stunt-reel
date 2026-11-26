---
title: "Name the unknown .SET prop bytes by flipping them under TYPESET ([BK-SET-02])"
started: 2026-11-24
issue: 835
outcome: "TYPESET flips on four BOMBING.SET props named the printed anims, Acceleration or Distance Anim, the method high byte and Locked, and Placed on one (set.md § 3.1-3.4); the rest stay [BK-SET-02]."
---

# Name the unknown .SET prop bytes by flipping them under TYPESET ([BK-SET-02])

## Question

Which printed `TYPESET` field reads each prop-record byte and bit [`set.md`](../../../research/formats/auxiliary/set.md) § 3.1 calls unknown?

## Handoff

- **Done (local-windows, one set, one TYPESET build):** `mise run typeset-flip` flips each listed byte and bit of chosen prop records, prints every variant with `TYPESET` in one `dosbox-x -silent` session, and diffs the dumps; two rounds (915 variants on four `BOMBING.SET` props) are in [`journal.md`](journal.md), with the per-variant results in the two CSVs beside it.
- **Left:** `+0x18`–`+0x19`, `+0x35`–`+0x3D`, bit 0 of `+0x02` and bits 1, 3 and 4 of `+0x03` print nothing under `TYPESET`; naming them needs the game's own reads of the prop record (`STUNT.EXE` or `PLAYONE.EXE`), which `[BK-SET-02]` now says.
