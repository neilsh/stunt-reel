---
title: "SOD: type-8 vertical quads (trees) are drawn from one side only, PLAYONE draws both"
started: 2026-11-11
issue: 399
outcome: "Type-8 trees face the camera heading: header_flags bit 0 selects the yaw-less view matrix 0x809C; props and actors with it turn per frame."
---

# Type-8 trees turn with the camera's heading

## Handoff

Landed in one PR: the cause is in [`sod-vm.md` § 8.8](../../../research/playone-exe/sod-vm.md#88-model-frame-the-other-generators), the measurement in the [journal](journal.md). Not done: the clipping variant `0xC50E` of the edge builder was not read, and a view-facing shape seen with the camera pitched past vertical turns half a turn off `PLAYONE`'s yaw.
