---
title: "Count draws per frame and merge adjacent world base mesh slices"
started: 2026-11-16
issue: 603
outcome: "Closed no-go: a LOCATION frame's median 127,910 draw_indexed calls were counted, 94,817 of them the world base pass's fills and outlines, and coalescing contiguous base slices removes none of them; research/parity/lavapipe.md section 6 holds the counts."
---

# Count draws per frame and merge adjacent world base mesh slices
