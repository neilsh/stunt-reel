---
summary: "Pairs mise run ab needs on Span B lavapipe under #1018's A/A rule: ±2% about 20, ±1% 42 to 192 at 90%; at 4 pairs a perfect runner passes ±1% 21% to 43% of the time."
sidebar_label: "Pairs mise run ab needs"
---
# Parity: Pairs `mise run ab` Needs on Lavapipe

* **Scope**: the power of `mise run ab`'s A/A pass rule at the measured run-to-run spread of one binary on Span B on lavapipe, for a ±2% or ±1% bar under #1089's two-sided rule with a direction clause, the rule of `#1018`'s ±1% A/A; it does not size [`#999`](https://github.com/neilsh/stunt-reel/issues/999)'s gate (the whole `LOCATION` film, one-sided, no direction clause) or `#1001`'s (a median at least `5%` lower and faster in all 4 pairs); where the spread comes from is in [`lavapipe-render-time.md` § 3](lavapipe-render-time.md#3-where-loop-time-goes).
* **Sources**: the committed CSVs of `#1004` and `#1018`, each from one Windows machine (the owner's 16-thread laptop) on `mesa-dist-win 25.2.8`, Span B (`LOCATION 3680..=3979`).
  * **Evidence tier**: `[Bounded Observation]` throughout; every figure rests on the run counts in the table below and holds for that machine, span and those days.
* **Method**: `work/2026-11/1089_ab-pair-count/pairs.py` (numpy, seed `1089`, 200,000 simulated A/As per cell, its output in the journal entry cited below) drew each side's loop times, took each variant's median and the change `median(b) / median(a) - 1` as [`summarize`](../../python/stunt_reel/ab_timing.py) does, and counted a pass when `|change| <= bar` and `b` was strictly faster than `a` in at least one pair but not in all.

## 1. The spread

`sd(log)` is the standard deviation of the natural log of the loop times, close to the coefficient of variation at these sizes; spread is `max / min - 1`.

| Runs | n | Spread | `sd(log)` | CSV |
|---|---|---|---|---|
| `#1018` second re-run, a completed A/A at `8.9%..11.2%` other load | 8 | 6.2% | 2.21% | `1018_lavapipe-ab-variance/aa-span-b-rerun2.csv` |
| `#1018` quiet probe, runs 1 to 7 (the first, slow run left out) | 7 | 9.6% | 3.12% | `probe-baseline.csv` |
| `#1018` quiet probe, all runs | 8 | 13.8% | 4.36% | `probe-baseline.csv` |
| `#1018` first A/A, stopped on the load check, one run at `10.3%` load | 5 | 19.9% | 7.69% | `aa-span-b.csv` |
| `#1018` first re-run, stopped on the load check | 2 | 1.7% | 1.22% | `aa-span-b-rerun.csv` |
| `#1004` A/A before the load checks | 8 | 32.2% | 9.69% | `1004_ab-timing-runner/aa-span-b.csv` |

Three spreads size the calculation: `2.21%` (the completed A/A), `3.12%` (the seven quiet probe runs) and `4.76%` (the three A/A files pooled by degrees of freedom, 15 runs, which holds the `10.3%`-load outlier).
Eight runs fix a standard deviation to a factor of `0.66` to `2.04` at 95% (chi-square, 7 degrees of freedom), so the completed A/A's `2.21%` is consistent with `1.46%..4.50%`.
That is wider than the gap between the three scenarios, so the spread is measured too poorly to give one pair count; the counts below are conditional on each scenario.

## 2. What the pass rule does at 4 pairs

The rule is the issue's: median loop change within the bar and neither side faster in every pair.
`mise run ab` prints the change and the pairs `b` won but applies no verdict, so the rule is read off its summary; the simulation follows that summary (a change of the two variants' medians, not a median of per-pair changes, and "faster" strictly smaller in the same round).

The direction clause alone fails a perfect runner `2 / 2^n` of the time when the sides are exchangeable: `12.5%` at 4 pairs (simulated `12.6%`), `3.1%` at 6 and `0.8%` at 8.

Normal model, probability a perfect runner passes (the median bar alone differs by at most `0.046` at 4 pairs):

| Spread | Bar | 4 pairs | 6 | 8 | 12 | 20 | 40 |
|---|---|---|---|---|---|---|---|
| `2.21%` | ±1% | 43.3% | 50.9% | 56.5% | 64.9% | 76.3% | 90.0% |
| `3.12%` | ±1% | 31.7% | 37.6% | 42.1% | 49.3% | 59.8% | 75.7% |
| `4.76%` | ±1% | 21.4% | 25.0% | 28.2% | 33.7% | 41.7% | 55.2% |
| `2.21%` | ±2% | 71.4% | 82.2% | 87.9% | 93.7% | 98.1% | 99.9% |
| `3.12%` | ±2% | 57.4% | 67.0% | 73.1% | 81.5% | 90.6% | 98.1% |
| `4.76%` | ±2% | 40.7% | 47.7% | 53.2% | 61.4% | 72.8% | 87.3% |

A bootstrap that resamples 22 runs, those of `aa-span-b-rerun2.csv` (8), `aa-span-b.csv` (5), `aa-span-b-rerun.csv` (2) and the quiet probe's runs 1 to 7 (7; its slow first run left out), each file divided by its own median so the heavy tail of the outlier stays, gave `40.7%` at ±1% and `65.8%` at ±2% at 4 pairs.
The standard deviation of the 4-pair median change is `1.71%`, `2.40%` and `3.68%` at the three spreads; the completed A/A's `-1.07%` is `0.6` of the first.
The per-pair log-ratio spread (`sqrt(2) * sd(log)`) is `3.13%` at the first spread, `4.41%` at the second and `6.73%` at the third.

## 3. Pairs needed

Smallest pair count at which a perfect runner passes the whole rule with the stated probability (normal model; the bootstrap in brackets):

| Spread | ±1% at 90% | ±1% at 95% | ±2% at 90% | ±2% at 95% |
|---|---|---|---|---|
| `2.21%` | 42 | 58 | 10 | 14 |
| `3.12%` | 82 | 116 | 20 | 28 |
| `4.76%` | 192 | 272 | 48 | 68 |
| bootstrap, 22 runs | (35) | (56) | (14) | (18) |

A run's wall median in the completed A/A was `3.9 s`, and `mise run ab` waits a `2.0 s` quiet window before each timed run and runs one untimed warm-up round, so a pair takes about `12 s` and 58 pairs about 12 minutes before any load wait; cost is not the limit, the spread's stability is.

## 4. The triage estimate

The triage estimate of `29%..59%` at ±1% and 4 pairs was too high at its top: the three normal scenarios give `21%`, `32%` and `43%`, the bootstrap `41%`, so no scenario reaches `59%`.
Its low end sits inside the range.
"2% also out of reach" holds at 4 pairs, where a perfect runner passes `41%..71%` of the time; at `10` to `28` pairs it passes 90% to 95% on the two quieter spreads, so 2% is reachable with more pairs and out of reach at the pair count `#1018` used.

## 5. Recommendation

* **±2% on Span B**: use about 20 pairs, which gives a perfect runner `90.6%` to `98.1%` at the two quieter spreads and `72.8%` at the pooled one, under #1089's two-sided rule with the direction clause (not `#999`'s whole-film gate); 10 pairs is the least that reaches 90% even at the best spread.
* **±1%**: no pair count is recommended from this data.
  A perfect runner needs 42 to 192 pairs for 90% (58 to 272 for 95%) across the spreads, so a ±1% pass at 4 pairs is close to a coin toss and says little about a runner.
  A tool that gates at ±1% should first run an A/A at its intended pair count (for example 40) and read its spread, which the 8-run figures cannot fix.
* A gate on a real effect larger than the bar, such as `#1001`'s (whole film; the figures here are Span B's) median at least `5%` lower and faster in all 4 pairs, does not need such a count to sit above the bar: the 4-pair median change has a standard deviation of `1.7%..3.7%` here, so 5% is 1.4 to 2.9 of them from zero, but "faster in all 4 pairs" is met by a perfect runner `6.3%` of the time (`1/16`, one direction), which is that gate's false-pass rate on the direction clause alone.

## Ruled out

* **Running the A/A at 4 pairs to certify ±1%**: a perfect runner passes `21%..43%` of the time at the spreads above, so a pass or a miss at 4 pairs is mostly the draw; `#1018`'s completed A/A missed at `-1.07%`, `0.6` standard deviations at the best spread.

## Open questions

1. The standard deviation to 8 or 15 runs is too wide to pick a pair count; an A/A of 40 pairs on Span B would fix it to between `0.87` and `1.18` times itself (chi-square, 79 degrees of freedom), and says whether load drifts across a long run, which the iid model ignores.
2. Whether the spread differs on the whole `LOCATION` film, which `#999`'s one-sided gate (no direction clause) and `#1001`'s time, and what pair count those gates need: every spread here is Span B's, and a one-sided rule changes the pass probabilities.
3. Whether the spread differs on Span A or C, on the GPU, or on a cloud lavapipe: nothing here measures it.

_Source: [the simulation and its output](../../work/2026-11/1089_ab-pair-count/journal.md#2026-11-26-pairs-needed-at-the-measured-spread), [`#1018` journal, what spreads one binary's runs](../../work/2026-11/1018_lavapipe-ab-variance/journal.md#2026-11-24-what-spreads-one-binarys-span-b-lavapipe-runs), [the second A/A re-run](../../work/2026-11/1018_lavapipe-ab-variance/journal.md#2026-11-25-the-second-owner-approved-aa-re-run-at-a-15-load-bar-completed-missed-the-median-bar), [`#1004` journal](../../work/2026-11/1004_ab-timing-runner/journal.md#2026-11-23-the-same-binary-on-both-sides-of-mise-run-ab-span-b-on-lavapipe)._
