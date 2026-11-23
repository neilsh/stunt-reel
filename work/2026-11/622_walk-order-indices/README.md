---
title: "Lay out world base indices in walk order so visible base slices coalesce"
started: 2026-11-22
issue: 622
outcome: ""
---

# Lay out world base indices in walk order so visible base slices coalesce

Issue #622.
The issue's first gate, 25% of a median LOCATION frame's `draw_indexed` calls, cannot be met once #644 and #914 have landed, but skipping Span B's base outlines cut its lavapipe loop by 11-12%, so the work goes on, gated on loop time: [`journal.md`](journal.md).

A CPU count then found the walk's order fixed and that a walk-order layout would cut Span B's base draws from 1,170 to 197 a frame by median, an estimated 9.3% to 18.6% of its loop at most, so the layout goes ahead.

Next: choose between the static walk-order layout and a per-frame compacted index buffer (Span B copies about 10,000 indices a frame by median), implement it, and time Spans A and B before and after on lavapipe and the GPU with byte-identical stores over every reference film.
