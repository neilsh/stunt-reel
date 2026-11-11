---
title: "Props reached only through SP_POSXZ nodes get no ground height"
started: 2026-11-11
issue: 253
outcome: ""
---

# Props reached only through SP_POSXZ nodes get no ground height

## Handoff

`[BK-MAP-07]` is closed in [`scenery.md` § 3.3](../../../research/formats/auxiliary/scenery.md#33-prop-height). `PLAYONE` samples no terrain for an `SP_POSXZ` prop. The prop's height is its ancestors' `SP_POS` `y` plus the header lift, and `world.rs` already does the same. No render changed, so no parity score was taken. Follow-ups:

- Cite the actor path `0x1D5F`, which never reads `[es:6]`, in `research/parity/framing-and-actors.md` section 1 as the evidence for the actors-without-lift heuristic.
- State in `sod.md` section 2.1 that `PLAYONE` applies `ground_y_offset` as a translation of scene-tree shapes, not in the VM.
