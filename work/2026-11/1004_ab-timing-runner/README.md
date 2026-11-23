---
title: "Each render-time measurement writes its own interleaved A/B timing runner"
started: 2026-11-23
issue: 1004
outcome: ""
---

# Each render-time measurement writes its own interleaved A/B timing runner

Issue #1004: `mise run ab`, a shared interleaved A/B timing runner for headless renders ([`ab.py`](../../../python/scripts/ab.py), [`ab_timing.py`](../../../python/stunt_reel/ab_timing.py), [how to use it](../../../docs/howto/time-a-headless-render.md#3-time-variants-against-each-other)).

The owner's A/A check, one binary on both sides of Span B on lavapipe in 4 alternating pairs, missed its first condition: a median loop change of `-9.4%` against `±1%`; the second, neither side faster in all 4 pairs, held (`b` won 2 of 4).
Per the owner's ruling it was not re-run, the tool shipped as `Part of #1004`, and the issue goes to `status:ready-for-human`; `#1001` does not time with the tool until the owner has seen the figures ([`journal.md`](journal.md), raw rows [`aa-span-b.csv`](aa-span-b.csv)).
