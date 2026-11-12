---
title: "Explosion sprites are cut by the depth test where PLAYONE paints them over neighbouring objects"
started: 2026-11-12
issue: 407
outcome: "Not adopted: no depth test on the blit is read from PLAYONE, but the two tested orders did not match the capture at tick 871 and score below the baseline on CTRY. Recorded in sod-animate.md."
---

# Explosion sprites are cut by the depth test where PLAYONE paints them over neighbouring objects

Journal: [`journal.md`](journal.md). The finding lives in [`sod-animate.md`](../../../research/playone-exe/sod-animate.md) § 3 and § Open questions.
