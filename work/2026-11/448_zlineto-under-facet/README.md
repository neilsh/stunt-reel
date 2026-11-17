---
title: "ZLINETO lines on a coplanar facet draw under it"
started: 2026-11-17
issue: 448
outcome: "Adopted on lavapipe (evidence track): a MOVETO/ZLINETO line lying on an earlier decal is a decal, so 0x037C's yard lines and TRAINTNL's rails draw (TRAINTNL +0.0030, BOMB -0.0003); a line on any facet was rejected for BOMB's near wall; INTRO 848 does not move. GPU judge pending."
---

# ZLINETO lines on a coplanar facet draw under it

Journal: [`journal.md`](journal.md).

**Handoff.** The rule is committed with lavapipe scores and repinned lavapipe tables. It moves lines from the base pass to the decal pass, a draw-order change, so `mise run judge` on the GPU (local-windows) must confirm it and repin the `gpu` tables before merge. Open: `BOMB` 2652 to 2740's near wall ([`world-scene-residuals.md`](../../../research/playone-exe/world-scene-residuals.md) open question 5).
