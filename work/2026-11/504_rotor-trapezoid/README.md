---
title: "location: render draws a black trapezoid over the foreground at ticks 717-903 that the capture mostly lacks"
started: 2026-11-16
issue: 504
outcome: "Attributed: the trapezoid is shape 0x3E57's rotor drawn with its solid blades at rest, because our VM reads the angle bank as 0 for ROTY and BVGT; fix filed as #624 beside #271."
---

# location: render draws a black trapezoid over the foreground at ticks 717-903 that the capture mostly lacks

## Handoff

No renderer change. The finding is in [`angle-bank.md`](../../../research/playone-exe/angle-bank.md) § 4 and [`framing-and-actors.md`](../../../research/parity/framing-and-actors.md) § 3; the experiment is in [`journal.md`](journal.md). The fix is [#624](https://github.com/neilsh/stunt-reel/issues/624) (BVGT on the bank, both arms chosen per frame), which needs #271's draw-time bank values and a measured frame spacing under dosbox-automation.
