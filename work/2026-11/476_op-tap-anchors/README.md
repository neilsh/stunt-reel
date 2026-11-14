---
title: "OP_TAP sub-pixel culling uses pre-anchor shapes and OP_TAP anchors ignore prop rotation"
started: 2026-11-13
issue: 476
outcome: "build_world culls OP_TAP props by their own per-placement decode; PLAYONE does not rotate scenery props, so the translation-only anchor load stays; no reference film changes"
---

# OP_TAP sub-pixel culling uses pre-anchor shapes and OP_TAP anchors ignore prop rotation

Journal: [journal.md](journal.md). Handoff: done in the PR that fixes #476. Left open: a TAP shape drawn rotated (an actor, or a view-facing scenery shape) would need the inverse turn; none is known in `INTRO.ALL` or `CTRY.ALL` (`research/playone-exe/sod-vm.md`, open items after section 4).
