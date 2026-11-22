---
title: "Find which change cut LOCATION's non-world draws after #644"
started: 2026-11-22
outcome: "f95ec4a0 (#811, PR #902) cut the median non-world fills on LOCATION 12..=300 from 6,764 to 2,571: its ScaleReach gate drops far view-facing props per frame; research/parity/lavapipe-render-time.md section 1 holds it"
---
# Find which change cut LOCATION's non-world draws after `#644`

[`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) section 1 counted 6,762 median non-world fills on LOCATION ticks 12..=300 at `b0f6c120`, and section 2 about 2,573 at `6955e159`, without saying which change between the trees made the difference.
[`journal.md`](journal.md) bisects the `crates/` history between them with a temporary counter, [`draw-counter.patch`](draw-counter.patch).
