---
title: "PlacementRecords::shadow_top walks every placement record per shadowed actor though few have a collision list"
started: 2026-11-22
issue: 944
outcome: "Walking only the 4,085 (LOCATION) or 2,979 (INTRO) collision-bearing records leaves shadow_top's result, the four stores on Spans A, B and C and the seven reference films' renders and scores unchanged (at 7488642e) and cuts its median 7.4-33.8% (3.0-20.3 ms) on Windows lavapipe and the RTX 4070; the loop is not shown faster, and the median fall puts the visits at roughly 7-34% of it, the rest not split."
---

# PlacementRecords::shadow_top walks every placement record per shadowed actor though few have a collision list

Issue `#944` (from `#934`): `PlacementRecords::shadow_top` skips every placement record without a collision list on each call.

- Journal: [`journal.md`](journal.md)
- Changed: `PlacementRecords::collision_bearing` in `crates/stunt-core/src/world/placed.rs`, read by `shadow_top` in `world/probe.rs`.
- Not done: Ubuntu lavapipe figures (no cloud session in this run); a bounding test per record, which would cut the walks that remain.
