---
title: "How do film variables 10 and 12 change per tick in PLAYONE?"
started: 2026-11-13
issue: 456
outcome: "[Established] Vars 10 and 12 are ordinary film variables (var_set keys, interpolated per frame); once per frame, for the whole film, 0x1D96 writes bank 0x12 = var 10 change saturated at 255 << 8, 0x14 = previous frame var 10 low byte << 8, 0x18/0x1A = +/-var 12. Static, and 94 DOSBox-X stops on INTRO.FLM."
---

# How do film variables 10 and 12 change per tick in PLAYONE?

The rule and its evidence are in [`angle-bank.md`](../../../research/playone-exe/angle-bank.md); the experiment is the [journal](journal.md).

For [#271](https://github.com/neilsh/stunt-reel/issues/271): `bank_word` can take `0x10`, `0x18` and `0x1A` from the film timeline at the tick. `0x14` is var 10 one `PLAYONE` frame earlier and `0x12` its change over that frame, so both need a frame spacing; DOSBox-X showed 2 to 5 ticks.
