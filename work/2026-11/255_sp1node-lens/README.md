---
title: "The per-frame SP_1NODE gate was never scored with the lens exponent 0x229E"
started: 2026-11-11
issue: 255
outcome: "Adopted: PLAYONE's SP_1NODE gate compares half the view-space depth shifted by 0x229E (0x211E takes the depth row's high word); tested per frame it raises CTRY 0.8973 to 0.8995, INTRO 0.8344 to 0.8404 and five films in all, and with a TAP anchor fix it draws CTRY's hill fins (#394)."
---

# The per-frame SP_1NODE gate was never scored with the lens exponent 0x229E

Also covers [#394](https://github.com/neilsh/stunt-reel/issues/394), `CTRY`'s missing hill fins, which had the same cause.

## Handoff

Done, in [`lod.md`](../../../research/playone-exe/lod.md) sections 2.2, 4.1 and 4.2 and the [journal](journal.md). The gate's `CX` is the high word of the depth row, half the depth over `2^0x229E`; neither the issue's exponent-only reading nor the true depth wins, and both are recorded under Ruled out. The renderer now tests every `SP_1NODE` per frame (`VisibilityCondition::LodBranch`), and a TAP placement is dropped only when an anchor it taps overflows. Expected tables in `research/parity/references.toml` are updated for all seven films. Left open:

- `INTRO` camera 1 (lens 44236) loses 0.0012 to 0.0023 on each of its 17 scored ticks; the frames were not inspected ([`lod.md`](../../../research/playone-exe/lod.md) section 6).
- Whether a fin shows through the hill patches in front of it was not checked against the capture ([`world-scene.md`](../../../research/playone-exe/world-scene.md) open question 3).
