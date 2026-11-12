---
title: "OP_ANIMATE is unimplemented: 28 models in 191 films draw no image"
started: 2026-11-11
issue: 222
outcome: "OP_ANIMATE decodes into screen-facing sprites drawn from RES image chunks; census 3654 -> 3682 clean of 3703; CTRY 0.8973 -> 0.8974, INTRO 0.8344 -> 0.8357, no film falls. Draw order against neighbours stays open."
---

# OP_ANIMATE is unimplemented: 28 models in 191 films draw no image

## Handoff

- The handler and its frame pick are in [`sod-animate.md`](../../../research/playone-exe/sod-animate.md); the scores are in [`journal.md`](journal.md).
- `sod-census` before: 3654 of 3703 clean, 35 stepping over an opcode; after this change alone: 3682 clean, 7 stepping over; merged with #393: 3689 clean, only `TESTTEXT.BIN` left.
- Open: PLAYONE paints the explosion over neighbouring objects (CTRY tick 871 tower, INTRO tick 1398 truck); our depth test cuts it. The bank words other than selectors 0x10 and 0x16 read as zero.
