# Journal

## 2026-11-25: an INTRO calibration fails on actors too small to see

**Question**: why did the first `INTRO.FLM` calibration under the 20-category taxonomy fail, when the `CTRY.FLM` one made the same day passed?

**Method**:
Both runs grade the lavapipe render of `dd7e76eb` (WSL Ubuntu 24.04, `llvmpipe (LLVM 20.1.2, 256 bits)`) with the categories of `9be3e2cb` (digest `5838a280…`).
`mise run parity-bench -- errors-make --film <film> --calibrate --recapture <dir> --out <dir>` wrote 42 sheets each: `CTRY.FLM` (`--out build/parity/bench/ctry/calibrate-2026-11-25`) and `INTRO.FLM` seed 1 (`--seed 1 --out build/parity/bench/intro/calibrate-2026-11-25-seed1`).
The recaptures were the data root's `backup/pre-305/vault-ctry/frames` and `backup/pre-305/vault-intro/frames`, whose `all_sha256` equals the pinned captures' (`cb58d95b…`, `2dc8f628…`).
Two Haiku passes graded each run and a Sonnet tie-break graded the 11 sheets each run's passes disputed.
[`actor_pixels.py`](actor_pixels.py), run from the checkout root as `mise exec -- uv run python work/2026-11/calibration-actor-floor/actor_pixels.py`, wrote [`actor-pixels.csv`](actor-pixels.csv): each calibration tick's actor-layer pixel count in the 320×200 render (`layer >= 16`), and whether the merged grades caught its actors-removed sheet, under the any-pixel rule the runs were planned with.

**Result**:
`CTRY.FLM` passed: actors removed 6 of 6, `shift_y:4` 6 of 6, `advance:5` 3 of 6, controls clean 12 of 12.
`INTRO.FLM` seed 1 failed: actors removed 4 of 6 against the 5-of-6 bar, `shift_y:4` 4 of 6, `advance:5` 4 of 6, controls clean 12 of 12.
The sheet plan took the first six ticks with any actor pixel, and two of `INTRO.FLM`'s held 1 pixel (tick 2058) and 33 pixels (tick 2223); on their sheets the actors are a few specks on the horizon, and no pass graded any actors-removed category above the real sheet's grade there.
Every caught sheet removed 852 pixels or more: `CTRY.FLM` 852 to 2452, `INTRO.FLM` 4248 to 16093.
The passes agreed on both missed sheets, and the two new categories are not in `actors_removed`'s detection list, so neither the grading nor the categories caused the failure.

**Verdict**: adopted a floor of 64 actor pixels (an 8×8 block, 0.1% of the frame) for an actors-removed sheet, `MIN_ACTOR_PIXELS` in `python/stunt_reel/bench/sheets.py`.
It is set by what the categories already call absent ("at most dark specks"), not by these runs: any floor from 34 to 852 separates the two misses from every catch and picks the same `INTRO.FLM` ticks (1002, 1167, 1321, 2410, 2564, 2718), and 64 keeps the most frames eligible.
A film with no frame at the floor still gets no actors-removed sheet, so its calibration stays inconclusive.
Seed 1 stays a FAIL: its graded sheets are not rescored under the new plan, whose ticks 2564 and 2718 it never graded.

**Lives in**: [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3, calibration rules.
