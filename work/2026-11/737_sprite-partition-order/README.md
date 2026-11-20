---
title: "Explosion sprites cannot take their place in the scenery partition order: the world walk drops the planes"
started: 2026-11-20
issue: 737
outcome: "Adopted on lavapipe and on the GPU (evidence track; gpu tables repinned, the lavapipe repin left for a cloud run): each OP_ANIMATE sprite is drawn at its slot's place in the scenery walk, over the depth-tested world and under the props the walk draws after it, so the CTRY tick 871 explosion covers the tower and stays under the hill; actors nearer than its slot are drawn after it; ordering 3D actors by their own walk is #819."
---

# Explosion sprites cannot take their place in the scenery partition order: the world walk drops the planes

## Handoff

- The Rust walk (`PlacementRecords::slot_order`) and the per-placement mesh runs (`MeshSpans`) landed with the renderer change; the [journal](journal.md) holds the three sweeps and the tick 871 check, recorded in [`sod-animate.md` § 4](../../../research/playone-exe/sod-animate.md#4-rust-mapping) and [`scene-walk-actors.md` § 4](../../../research/playone-exe/scene-walk-actors.md#4-ctry-tick-871).
- The change alters draw order, so its PR is `local-only`: `mise run judge` on the GPU is still to run (`cloud.md` § Rendering).
- 3D actors against a placed sprite by their own walk: [#819](https://github.com/neilsh/stunt-reel/issues/819).
