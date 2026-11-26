---
title: "Find why mise run ab spreads one binary's lavapipe runs by 32%"
started: 2026-11-24
issue: 1018
outcome: ""
---

# Find why mise run ab spreads one binary's lavapipe runs by 32%

Issue #1018: why `mise run ab` spread one binary's Span B lavapipe runs `32.2%`.
Other processes' CPU load slows the loop, so the runner now records each run's `other_load`, waits for a quiet machine before each timed run, stops after a loaded run, and runs one untimed warm-up round ([`journal.md`](journal.md), [`load_probe.py`](load_probe.py) and its `probe-*.csv`).
The A/A check with those changes stopped after 5 of 8 runs on a loaded run ([`aa-span-b.csv`](aa-span-b.csv), [`aa-span-b-log.txt`](aa-span-b-log.txt)), so its bar is unjudged.
The owner-approved re-run stopped on the load check after 2 of 8 runs, at `10.2%` other load ([`aa-span-b-rerun.csv`](aa-span-b-rerun.csv), [`aa-span-b-rerun-log.txt`](aa-span-b-rerun-log.txt)), so it has no verdict either; a further run waits on the owner.
