---
title: "World decal slices switch pipelines twice each, a large share of lavapipe's Span B loop"
started: 2026-11-22
issue: 1000
outcome: "Ruled out by the owner on 2026-11-23: batching the world's decal slices by screen box leaves 54.2% of the whole LOCATION film's decal pipeline switches in place, and its ceiling is about 3.5% to 3.7% of the loop (inferences), under the 5% gate; closed with no renderer change (lavapipe-render-time.md section 6)."
---

# World decal slices switch pipelines twice each, a large share of lavapipe's Span B loop

Issue #1000, probe only: a CPU count of the decal pipeline switches `SceneRenderer::encode` makes against those greedy batches of slices with disjoint conservative screen boxes would make.
Batching leaves `54.2%` of the whole `LOCATION` film's switches in place and `45.8%` of Span B's; the issue's rule names no scope, so the owner ruled it at the whole film's scope and #1000 closed with no renderer change ([`journal.md`](journal.md), [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6).
The probe is [`probe-decal-batch.patch`](probe-decal-batch.patch), against `7bfc6cca`.
