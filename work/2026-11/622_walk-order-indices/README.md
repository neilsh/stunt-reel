---
title: "Lay out world base indices in walk order so visible base slices coalesce"
started: 2026-11-22
issue: 622
outcome: "rejected: the walk-order layout merged the predicted draws byte-identically but cut Span B's lavapipe loop only 4.4-4.8%, did not resolve on the whole film, and raised peak memory 11-76 MiB; kept as a patch"
---

# Lay out world base indices in walk order so visible base slices coalesce

Issue #622.
The issue's first gate, 25% of a median LOCATION frame's `draw_indexed` calls, cannot be met once #644 and #914 have landed, but skipping Span B's base outlines cut its lavapipe loop by 11-12%, so the work goes on, gated on loop time: [`journal.md`](journal.md).

A CPU count then found the walk's order fixed and that a walk-order layout would cut Span B's base draws from 1,170 to 197 a frame by median, an estimated 9.3% to 18.6% of its loop at most, so the layout goes ahead.

The owner chose the static layout over a per-frame compacted index buffer, which would copy about 10,000 indices a frame on Span B.
Built as [`walk-order-layout.patch`](walk-order-layout.patch), it merges the predicted draws and leaves all 28 stores of the seven reference films byte-identical on the RTX 4070 and on lavapipe.
It cut Span B's lavapipe loop only 4.4% to 4.8%, under the 5% gate; the whole film was faster in 3 of 4 pairs, and peak memory rose 11 MiB on lavapipe and 69 to 76 MiB on the RTX 4070, a transient rise during the upload attributed to its second copy of the indices and outlines.
The owner ruled it out against bars set before those last measurements, and #622 closes as not planned ([`journal.md`](journal.md), [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6).
