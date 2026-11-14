---
title: "Does PLAYONE draw one TRAINTNL rail or two at tick 12?"
started: 2026-11-13
issue: 452
outcome: "Recorded, no rendering change: at TRAINTNL tick 12 PLAYONE's SP_1NODE gate draws the two-rail stand-in 0x06CE in rows 155 to 184 (pieces 121 to 153 m deep, CX 15 to 19 against 9), not 0x06CF, whose bed colour 12 the capture shows only in rows 73 to 78; our render picks the same stand-in but shows no rail there, consistent with #448's tie-over-rail grouping."
---

# Does PLAYONE draw one TRAINTNL rail or two at tick 12?

## Handoff

Done, in the [journal](journal.md) and [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 6.7. `PLAYONE` draws `0x06CE`, the stand-in with two rails, where the capture shows them, and our gate already does the same. The missing rails in ours fit [#448](https://github.com/neilsh/stunt-reel/issues/448)'s tie-over-rail grouping (not tested here), and no level-of-detail change follows. Left open: a DOSBox-X break on the gate (`0x2133`) would read `CX` live and promote the depths from our camera to an observation.
