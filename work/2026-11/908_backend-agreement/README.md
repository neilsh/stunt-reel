---
title: "Pin fidelity on lavapipe and measure lavapipe-GPU agreement separately"
started: 2026-11-21
issue: 908
outcome: ""
---

# Pin fidelity on lavapipe and measure lavapipe-GPU agreement separately

Rendering PRs that touch depth, the transform, projection, clipping, draw order or `shade` interpolation wait unmerged for a GPU judge, so parity work queues behind the owner's GPU.
This item splits capture-against-lavapipe fidelity, judged and pinned on lavapipe, from lavapipe-against-GPU class agreement, measured in unattended batches with its own pinned figures and issues.

- Design: [`spec.md`](spec.md)
- Plan: [`plan.md`](plan.md)
