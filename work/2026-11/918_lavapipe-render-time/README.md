---
title: "Where does lavapipe render time go after #644 and #811, and do multiple VkDevices parallelize in-process?"
started: 2026-11-21
issue: 918
outcome: "Profiled post-#644/#811 lavapipe across LOCATION and INTRO: #914 view_facing culling go (-52.4% to -80.6% loop), #916 subprocess workers go (2.82x-3.21x loop at 4 workers; in-process pooling no-go), #919 and #915b no-go, #915a/c/d and #920 defer."
---

# Where does lavapipe render time go after #644 and #811, and do multiple VkDevices parallelize in-process?

After `#644` (world frustum culling) and `#811` (`ScaleReach` per-frame scenery distance culling), the lavapipe render-time profile and `LP_NUM_THREADS` entry in [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) still rest on `LOCATION` ticks 12-300 (plus a cloud `INTRO` relight check in `Ruled out`) and pre-`#644` stack samples, leaving `#914`, `#915`, `#916`, `#919` and `#920` waiting in `needs-triage`.
This investigation measures post-`#644`/`#811` per-category draw counts, per-phase wall-clock shares with isolation probes, `LP_NUM_THREADS` scaling, and in-process multi-`VkDevice` versus multi-process scaling on lavapipe, and updates [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) and [`evidence-limits.md`](../../../research/parity/evidence-limits.md) with go/no-go guidance.

- Design: [`spec.md`](spec.md)
- Plan: [`plan.md`](plan.md)
- Journal: [`journal.md`](journal.md)
- Probe patch: [`probe.patch`](probe.patch)
