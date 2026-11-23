---
title: "World decal slices switch pipelines twice each, a large share of lavapipe's Span B loop"
started: 2026-11-22
issue: 1000
outcome: ""
---

# World decal slices switch pipelines twice each, a large share of lavapipe's Span B loop

Issue #1000, probe only: a CPU count of the decal pipeline switches `SceneRenderer::encode` makes against those greedy batches of slices with disjoint conservative screen boxes would make.
Batching leaves `54.2%` of the whole `LOCATION` film's switches in place and `45.8%` of Span B's; the issue's rule names no scope, so whether #1000 closes is pending the owner's ruling ([`journal.md`](journal.md), [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6).
The probe is [`probe-decal-batch.patch`](probe-decal-batch.patch), against `7bfc6cca`.
