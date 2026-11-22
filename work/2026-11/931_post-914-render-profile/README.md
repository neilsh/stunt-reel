---
title: "Where does render time go after #914's view-facing cull?"
started: 2026-11-22
issue: 931
outcome: ""
---

# Where does render time go after #914's view-facing cull?

`#918`'s throwaway timing probe, carried onto `main` after `#914` (PR `#930`) and `#916` (PR `#929`), re-run on its Spans A, B and C to decide what to speed up next: view-facing instancing (`#926`), caching `collect_world_meshes`, or reusing the CPU `Vec` in `readback_copy`.

- Probe patch: [`probe.patch`](probe.patch), applied on `7845a3c` with `git apply`; `DBG_PROBE_CULL_VIEW_FACING` is gone, since the landed cull always runs, and the CPU scan uses `GpuModel::in_frustum`.
- Journal: [`journal.md`](journal.md)
