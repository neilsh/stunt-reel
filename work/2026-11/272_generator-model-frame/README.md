---
title: "OP_IPG quads, OP_SPHERE, OP_PERFDISK and OP_VEC write coordinates in an unchecked model frame"
started: 2026-11-11
issue: 272
outcome: "Generator handlers read in sod-vm.md section 8.8; type-8 IPG winding, type-6 operand count and reversed sphere faces fixed in vm.rs (#388)."
---

# OP_IPG quads, OP_SPHERE, OP_PERFDISK and OP_VEC write coordinates in an unchecked model frame

## Handoff

The handlers are read and `vm.rs` matches them except where [`sod-vm.md` § 8.8](../../../research/playone-exe/sod-vm.md#88-model-frame-the-other-generators) says otherwise; the [journal](journal.md) has the method. Before the PR: capture-beside-render pictures of a type-8 user and of tree crowns, for the type-8 winding fix and the reversed sphere faces. Left open: drawing `OP_PERFDISK`, and the type-6 streamer's registers.
