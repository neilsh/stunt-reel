---
title: "View-facing props, actors, shadows, and sprites skip frustum culling"
started: 2026-11-22
issue: 914
outcome: "Culling actor bodies, shadows and sprites removes 25-100% of the actor-body draw slices on three spans and moves no loop time out of the run-to-run spread on lavapipe or the RTX 4070 (no-go, patch kept); the world cull did drop a disc rim that a zoomed lens squeezes into view, fixed with a per-node disc flag, 28 of 28 stores unchanged on both adapters."
---

# View-facing props, actors, shadows, and sprites skip frustum culling

Frustum-culling the non-world draws in `SceneRenderer::prepare`.
PR #930 landed the view-facing props' cull; the second PR measured the other three loops (no-go) and closed the world cull's disc gap.

- Journal: [`journal.md`](journal.md)
- Actor, shadow and sprite culls as built, not landed: [`actor-sprite-cull.patch`](actor-sprite-cull.patch), on `9ccfd39c`
- Note: [`lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes)
