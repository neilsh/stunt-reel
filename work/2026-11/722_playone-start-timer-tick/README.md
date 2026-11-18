---
title: "research: log PLAYONE's film-clock start against the emulator frame for padded archives"
started: 2026-11-18
issue: 722
outcome: "Archives that draw alike start the film clock on the same timer interrupt; the others start 3 to 24 ticks later, which accounts for their late last page. Recorded in film-load.md § 6."
---

# research: log PLAYONE's film-clock start against the emulator frame for padded archives

Ten per-frame memory logs of `CTRY.FLM` on dosbox-automation in a cloud session, the own `CTRY.ALL` and nine padded arms; the log is [`journal.md`](journal.md), the finding is [`film-load.md`](../../../research/playone-exe/film-load.md) § 6.
The logs, arms and one-off scripts are in `<data root>/bench/vault-ctry/722/unpatched/`.

## Handoff

The timer tick is the quantum of the start: the film clock's tick 1 falls on interrupt 904 for every arm that draws the own archive's pages, and 3 to 24 interrupts later for the others.
Why a start whole ticks later changes what is drawn at a film tick is `film-load.md` open question 1 ([#779](https://github.com/neilsh/stunt-reel/issues/779)).
The per-frame Lua reads worked in the cloud on the unpatched build, which also boots there.
