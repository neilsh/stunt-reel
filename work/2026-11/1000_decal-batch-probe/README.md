---
title: "World decal slices switch pipelines twice each, a large share of lavapipe's Span B loop"
started: 2026-11-22
issue: 1000
outcome: "rejected: greedy batching of disjoint-box decal slices leaves 54.2% of the whole LOCATION film's decal pipeline switches in place (45.8% on Span B), and its ceiling, 7.7% times the 45.8% removed, is under the 5% gate; the probe is kept as a patch"
---

# World decal slices switch pipelines twice each, a large share of lavapipe's Span B loop

Issue #1000, probe only: a CPU count of the decal pipeline switches `SceneRenderer::encode` makes against those greedy batches of slices with disjoint conservative screen boxes would make.
Batching leaves `54.2%` of the whole `LOCATION` film's switches in place and `45.8%` of Span B's, so #1000 closes by its own rule ([`journal.md`](journal.md), [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6).
The probe is [`probe-decal-batch.patch`](probe-decal-batch.patch), against `7bfc6cca`.
