---
title: "Coplanar decals on CW ground faces are displaced downward"
started: 2026-11-13
issue: 449
outcome: ""
---

# Coplanar decals on CW ground faces are displaced downward

`[I5]` decals moved along the stored shading normal, which for a `POLYZ` or `GVPOLY` face clockwise from above points down. The [journal](journal.md) finds why the first attempt (front-normal displacement alone) flipped `BOMB`'s truck, and adopts front-normal matching and displacement with decals stacked one 1 mm level above the polygons they cover.

## Handoff

Committed on `fix/449-cw-decal-displacement` (PR pending). Open: decal levels do not separate far from the eye, and an actor's shadow (lifted 1 mm) lies under ground decals of level 2 and above off the terrain; [`render-model.md`](../../../research/parity/render-model.md) open question 6. `0x037C`'s ground slices are also what [#446](https://github.com/neilsh/stunt-reel/issues/446) moves into a `WORLD_GROUND` pass.
