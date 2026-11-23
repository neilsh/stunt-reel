---
title: "Static 3D world prop placements bake into one 6.7M-vertex mesh instead of referencing shared shapes"
started: 2026-11-22
issue: 920
outcome: "rejected: skipping the world's base and decal draws cut the whole LOCATION film's lavapipe loop 49.0%, but every placement with geometry already has nodes of its own, so a per-placement frustum test removes 0% of the drawn world vertices; the probes are kept as a patch"
---

# Static 3D world prop placements bake into one 6.7M-vertex mesh instead of referencing shared shapes

Issue #920, measured against the bars the owner set before any run.
Step 1 passed: skipping the world's base and decal draws cut the whole `LOCATION` film's Windows lavapipe loop by 49.0%, faster in all four pairs.
Step 2 failed cleanly: no placement on `LOCATION` or `INTRO` has geometry in the shared `WORLD_BASE` or `WORLD_DECAL` run, so the walk already culls each placement on its own box and a per-placement frustum test removes 0% of the drawn vertices, against a 30% bar.
Step 3 (memory) gives no go and was not measured; #920 closes as not planned ([`journal.md`](journal.md), [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6).
What half of the lavapipe loop pays for in those draws, which carry about 4,400 vertices a frame on Span B, is that note's first open question.
The probes are [`world-skip-and-vertex-probe.patch`](world-skip-and-vertex-probe.patch), against `dc9622ea`.
