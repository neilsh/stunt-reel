---
title: "Where does render time go after #914's view-facing cull?"
started: 2026-11-22
issue: 931
outcome: "After #914, readback_copy costs 17-22% of the loop on Windows lavapipe and 27-32% on the RTX 4070, and a row-wise copy cut it 85% on Ubuntu lavapipe; collect_world_meshes costs at most 2.1% and #926 has no view-facing draw left to instance on its forested span."
---

# Where does render time go after #914's view-facing cull?

`#918`'s throwaway timing probe, carried onto `main` after `#914` (PR `#930`) and `#916` (PR `#929`), re-run on its Spans A, B and C to decide what to speed up next: view-facing instancing (`#926`), caching `collect_world_meshes`, or reusing the CPU `Vec` in `readback_copy`.

- Probe patch: [`probe.patch`](probe.patch), applied on `7845a3c` with `git apply`; `DBG_PROBE_CULL_VIEW_FACING` is gone, since the landed cull always runs, and the CPU scan uses `GpuModel::in_frustum`.
- Journal: [`journal.md`](journal.md)
- Next: replace `read_back`'s byte iterator with a row-wise copy; leave `#926` and caching `collect_world_meshes` unstarted.
