---
title: "Does a superset with the SPRITES palette items play like a film's own archive in PLAYONE?"
started: 2026-11-08
issue: 301
outcome: "With the SPRITES palette items, PLAYONE plays a superset with the film's palettes but some pages differ: 72/112, 48/101 and 108/115 identical against a zero noise band (CTRY both builds, TOD unpatched); the cause is open."
---

# Does a superset with the SPRITES palette items play like a film's own archive in PLAYONE?

Settled in a grilling session on 2026-11-08; the plan is in [`spec.md`](spec.md) and the run in [`journal.md`](journal.md). The finding lives in [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2.

## The question

With `SPRITES.RES` items `0x801E` and `0x8042` added, does `PLAYONE.EXE` play a superset archive with the right palette, and like the film's own archive within recapture noise ([`linking.md`](../../../research/makeone-exe/linking.md) § 7.2 and open question 8)?

## Handoff

- Done: `superset-all --with-palettes`, `capture-ref --archive`, `make-all --out` and the bench of 12 captures in `<data root>/bench/vault-{ctry,tod}/301/` (journal).
- Not run: TOD on Patch 3, whose `make-all` stalled twice.
- Left: why the superset's pages differ, by an own archive padded with the superset's extra shapes (`linking.md` open question 8, [#348](https://github.com/neilsh/stunt-reel/issues/348)).
