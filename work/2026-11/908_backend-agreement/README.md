---
title: "Pin fidelity on lavapipe and measure lavapipe-GPU agreement separately"
started: 2026-11-21
issue: 908
outcome: "Fidelity is judged and pinned on the canonical lavapipe (Ubuntu mesa-vulkan-drivers 25.2.8-0ubuntu0.24.04.5) and no PR waits for the GPU (ADR 0055); class agreement is measured by `mise run agreement`, first pinned in #935 on crates 4d18e7a. The nightly scheduled task is documented but not registered, by the owner's choice."
---

# Pin fidelity on lavapipe and measure lavapipe-GPU agreement separately

Rendering PRs that touch depth, the transform, projection, clipping, draw order or `shade` interpolation wait unmerged for a GPU judge, so parity work queues behind the owner's GPU.
This item splits capture-against-lavapipe fidelity, judged and pinned on lavapipe, from lavapipe-against-GPU class agreement, measured in unattended batches with its own pinned figures and issues.

- Design: [`spec.md`](spec.md)
- Plan: [`plan.md`](plan.md)
