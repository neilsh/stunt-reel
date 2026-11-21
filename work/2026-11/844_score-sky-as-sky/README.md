---
title: "Score the sun disc (239) and the sky drawer's 0xD0 fill as the capture's sky, not geometry"
started: 2026-11-20
issue: 844
outcome: "Adopted: the captured sun disc (239) and the sky drawer's 0xD0 fill (208) count as sky by position, which raises every film's mask IoU; the fill rule's reach is one row under a level horizon and a wedge under a banked one, and the roll-independent rule is left to #893."
---

# Score the sun disc (239) and the sky drawer's 0xD0 fill as the capture's sky, not geometry

**Question**: Does counting the capture's sun disc (239) and the sky drawer's `0xD0` fill (208) as sky by position raise each reference film's mask IoU, and how far does the fill rule reach?

Scored both rules on one RTX 4070 render of the seven `VAULT` references; the figures are in [`journal.md`](journal.md) and the rule in [`method.md`](../../../research/parity/method.md#20-sky-mask-and-iou-scale) section 2.0.
