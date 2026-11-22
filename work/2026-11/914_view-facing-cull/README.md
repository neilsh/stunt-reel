---
title: "View-facing props, actors, shadows, and sprites skip frustum culling"
started: 2026-11-22
issue: 914
outcome: ""
---

# View-facing props, actors, shadows, and sprites skip frustum culling

Frustum-culling the non-world draws in `SceneRenderer::prepare`.
PR #930 lands the view-facing props' cull; actor bodies, shadows and sprites (the rest of the issue) are still to do, so `outcome` stays empty until the PR that finishes them.

- Journal: [`journal.md`](journal.md)
- Note: [`lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes)
