---
title: "OP_ANIMATE reads every bank word but 0x10 and 0x16 as 0, and skips its register-flag and SIF_ANIMATES tests"
started: 2026-11-11
issue: 408
outcome: "The corpus uses only OP_ANIMATE selectors 0, 0x10 and 0x16, all modelled; the SIF_ANIMATES test is already held by the slot player; the register-flag test (a clip outcode) moves no reference film, so it stays unimplemented."
---

# OP_ANIMATE reads every bank word but 0x10 and 0x16 as 0, and skips its register-flag and SIF_ANIMATES tests

## Handoff

- Findings and the census are in [`journal.md`](journal.md); the evergreen statement is in [`sod-animate.md`](../../../research/playone-exe/sod-animate.md).
- No code changed. Open: the register-flag test would matter only for a sprite whose centre is outside the frustum, which changes no scored frame of the seven reference films.
