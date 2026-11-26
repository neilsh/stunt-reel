## 2026-11-26: pairs needed at the measured spread

- **Question**: how many alternating pairs does `mise run ab` need to resolve a ±1% or ±2% loop bar at the measured spread of one binary on Span B on lavapipe, and how often does a perfect runner pass at 4 pairs?
- **Method**: no timing run.
  [`pairs.py`](pairs.py), on `main` at `c2b23b4`, read the committed loop times of `1018_lavapipe-ab-variance/aa-span-b-rerun2.csv` (8 runs), `aa-span-b.csv` (5), `aa-span-b-rerun.csv` (2) and `probe-baseline.csv` (8, of which runs 1 to 7 are the quiet seven), `probe-after-idle.csv` (3) and `1004_ab-timing-runner/aa-span-b.csv` (8).
  It took each file's `sd(log)`, pooled the three A/A files by degrees of freedom, and simulated A/As with numpy seed `1089` and 200,000 draws per cell: each side's loop times drawn as `exp(Normal(0, sd(log)))` (a bootstrap of the 22 runs of the four named files, each divided by its median, as a second model), each variant's median taken, the change `median(b) / median(a) - 1` as `summarize` in `python/stunt_reel/ab_timing.py` computes it, and a pass counted when `|change|` is within the bar and `b` is strictly faster than `a` in at least one pair but not all.
  Command, from the repository root: `mise exec -- uv run python work/2026-11/1089_ab-pair-count/pairs.py > work/2026-11/1089_ab-pair-count/pairs-output.txt`.
- **Result**: [`pairs-output.txt`](pairs-output.txt) is the whole output.
  Spread (`sd(log)`): `2.21%` (rerun2, 8 runs), `3.12%` (quiet probe runs 1 to 7), `4.76%` (the three A/A files pooled, 15 runs); the per-pair log-ratio spread (`sqrt(2) * sd(log)`) is `3.13%` and `4.41%` at the first two; the completed A/A's wall median is `3869.9 ms`.
  Probability a perfect runner passes at 4 pairs: `43.3%`, `31.7%`, `21.4%` at ±1% and `71.4%`, `57.4%`, `40.7%` at ±2%; the bootstrap `40.7%` and `65.8%`; the direction clause alone `87.4%`.
  Pairs for 90% pass: ±1% `42`, `82`, `192` and ±2% `10`, `20`, `48` (95%: `58`, `116`, `272` and `14`, `28`, `68`); bootstrap `35`, `56`, `14`, `18`.
  The standard deviation of the 4-pair median change is `1.71%`, `2.40%`, `3.68%`.
- **Verdict**: control; a calculation on committed data, `[Bounded Observation]` on 2 to 8 runs a file, one machine, Span B, under `#1089`'s two-sided rule with a direction clause (not `#999`'s whole-film one-sided gate).
- **Lives in**: [`lavapipe-ab-pair-count.md`](../../../research/parity/lavapipe-ab-pair-count.md).
