---
title: "Seven stock shapes decode to fragments or no geometry"
started: 2026-11-11
issue: 273
outcome: "All seven SUPERSET items traced and recorded in sod-opcode-coverage.md section 2.1 (#391); two-vertex polygons and OP_PERFDISK followed in #393 and #392."
---

# Seven stock shapes decode to fragments or no geometry

## Handoff

Each shape's stop is named in [`sod-opcode-coverage.md` § 2.1](../../../research/formats/sod-opcode-coverage.md#21-the-side-view-census-shapes-that-do-not-decode-whole); the [journal](journal.md) has the method. Follow-ups to file: skip or draw a two-vertex `POLYZ`/`GVPOLY` instead of stopping the walk, and draw `OP_PERFDISK` (open from #272).
