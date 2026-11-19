---
title: "Keep far props the inclusive span filler still paints instead of culling them under half a pixel"
started: 2026-11-18
issue: 777
outcome: ""
---

# Keep far props the inclusive span filler still paints instead of culling them under half a pixel

## Handoff

The issue's first step bounded the gain at zero: the half-pixel cull drops no placement on six reference films, and on `location` only 190 placements of shapes with no vertices ([journal](journal.md#2026-11-18-how-many-placements-the-sub-pixel-cull-drops)).
`PLAYONE`'s scenery cull `0x1B0C` has no size test ([journal](journal.md#2026-11-18-whether-playone-culls-a-whole-scenery-object-by-screen-size)), but removing ours moves no reference film, so the evidence track rejects it ([journal](journal.md#2026-11-18-removing-the-size-test-from-the-cull)) and the null result is in `attribution.md` § Ruled out.
Done-when item 2 (a unit test that a sub-half-pixel on-screen prop survives `build_world`) is not met, because the change it tests was not adopted; a person decides whether to close #777 on the null result.
