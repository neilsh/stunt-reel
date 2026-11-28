---
title: "Class agreement at 57fa24d: GPU and lavapipe disagree on 2-13x more pixels per tick than at the 3bb9878 pin"
started: 2026-11-28
issue: 1125
outcome: ""
---

# Class agreement at 57fa24d: GPU and lavapipe disagree on 2-13x more pixels per tick than at the 3bb9878 pin

## Handoff

The 2026-11-26 batch's rise is #1099's vertex placement on pixel centres: with it off (`switches/DBG_SNAP.diff`, `DBG_SNAP=off`), no film keeps any of its rise over the pin ([journal](journal.md#2026-11-28-the-rise-is-the-pixel-centre-vertex-placement); finding in [`lavapipe-pixel-centres.md`](../../../research/parity/lavapipe-pixel-centres.md)).
A (5, 3)/256-pixel offset from the centre removes only part of it, and capping grazing slides removes none; three hypothesis rounds are spent.

Left for the owner (ADR 0055): pin the higher disagreement with `mise run agreement -- pin --accept "<reason>"` after a fresh batch on current `main`, or change the placement.
The renders here were not scored: the data root's LAND and BALLOON captures were replaced on 2026-11-28 and no longer match `references.toml`.
