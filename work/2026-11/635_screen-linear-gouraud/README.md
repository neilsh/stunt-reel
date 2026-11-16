---
title: "Gouraud polygons that lavapipe's clipper breaks draw perspective-correct, not screen-linear"
started: 2026-11-16
issue: 635
outcome: "Rebuilding a clipper-broken Gouraud polygon's shade as shade*w / w makes lavapipe draw the GPU's gradient at BALLOON 145 (4,044 of 4,044 pixels match), with the GPU stores byte-identical and no scored frame moved."
---

# Gouraud polygons that lavapipe's clipper breaks draw perspective-correct, not screen-linear

The shader change and its measurements are on PR #648; the figures and verdict are in [`journal.md`](journal.md) and `research/parity/lavapipe.md` sections 3 (e), 4 and 5.

## Handoff

Done. Left open: the ratio-everywhere experiment on the GPU (`lavapipe.md` Open question 6) and a lavapipe re-measurement on `857f80a8`.
