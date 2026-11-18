---
title: "research: bisect how much .ALL padding changes PLAYONE's pages"
started: 2026-11-18
issue: 611
outcome: "On CTRY, unpatched, pages change from 368 one-byte chunks and from 137,500 bytes in 63 chunks; the drawn frames fall late by whole film ticks, not frames, and two archives drew alike exactly when every kept page fell on the same emulator frame."
---

# research: bisect how much .ALL padding changes PLAYONE's pages

Bisected the chunk-count and byte thresholds of #482 on `CTRY.FLM` with 34 captures in a cloud session; the log is [`journal.md`](journal.md), the finding is [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2.

## Handoff

Done: both thresholds, the delay of each arm in film ticks, and the answer to the step question (steps of whole film ticks; the last page's frame alone does not decide the pages).
The captures, archives and one-off scripts are in `<data root>/bench/vault-ctry/611/unpatched/` of the cloud session that ran them, as working output.
Left open in the notes: whether the film clock's start moves by whole timer ticks (the live log of [#722](https://github.com/neilsh/stunt-reel/issues/722)), and what drawing state carries from one drawn frame to the next, which the 27 pages that differ at the same tick on the same frame point to ([`film-load.md`](../../../research/playone-exe/film-load.md) open question 1, [#723](https://github.com/neilsh/stunt-reel/issues/723)).
