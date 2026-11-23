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

The owner chose the static layout over a per-frame compacted index buffer, which would copy about 10,000 indices a frame on Span B.
Branch `claude/622-walk-order-indices` builds it (`f77fd073`): it merges the predicted draws and leaves all 28 stores of the seven reference films byte-identical on the RTX 4070 and on lavapipe.
Span B's lavapipe loop fell only 4.4% to 4.8% over 16 interleaved pairs, under the 5% gate, and the RTX 4070's Span A reads 2.4% to 5.0% slower, inside its noise ([`journal.md`](journal.md)).

Next: the owner decides whether to land the branch anyway (a lavapipe speed-up just under the gate, no pixel changed) or to record the layout under the note's Ruled out and close #622.
Either way `research/parity/lavapipe-render-time.md` takes the count and the timed result (§ 6's verdict and the Ruled-out `#603` coalescing bullet), with a fresh-reviewer pass.
