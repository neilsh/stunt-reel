---
title: "Order 3D actors against a placed OP_ANIMATE sprite by their scenery walk, not by view depth"
started: 2026-11-22
issue: 819
outcome: "Adopted on the GPU (evidence track; gpu tables repinned, lavapipe left for a cloud run): at intro:1398 the explosion and the vehicle reach one SP_LEAF, so no plane decides and the depth sort does, by the slots' own positions; the renderer now takes actor and sprite depths at ActorDraw::position instead of the ground-offset model origin, putting the explosion back over the vehicle."
---

# Order 3D actors against a placed OP_ANIMATE sprite by their scenery walk, not by view depth

## Handoff

- The [journal](journal.md) holds the tick 1398 replay and the sweep; the findings are in [`scene-walk-actors.md` § 6](../../../research/playone-exe/scene-walk-actors.md#6-intro-tick-1398).
- No plane decides at `intro:1398`, so ordering an actor against a sprite by a plane where their entries part was not built; no frame has been searched for one.
- The `lavapipe` expected tables keep `main`'s figures until a cloud catch-up repin ([#830](https://github.com/neilsh/stunt-reel/issues/830)).
