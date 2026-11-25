# Journal

## 2026-11-25: an INTRO calibration fails on actors too small to see

**Question**: why did the first `INTRO.FLM` calibration under the 20-category taxonomy fail, when the `CTRY.FLM` one made the same day passed?

**Method**:
Both runs grade the same renders: `build/parity/ours/<film>_current`, rendered on WSL Ubuntu 24.04's lavapipe (`llvmpipe (LLVM 20.1.2, 256 bits)`) at `dd7e76eb`, whose `crates/` tree `4b5c69c` is unchanged at `124c5034` and `9be3e2cb`.
Both use the categories committed in `9be3e2cb` (digest `5838a280…`); the `CTRY.FLM` run was made at `124c5034` with that edit not yet committed, so its `run.json` records `revision` `124c5034`, and the `INTRO.FLM` run at `9be3e2cb`.
`mise run parity-bench -- errors-make --film <film> --calibrate --recapture <dir> --out <dir>` wrote 42 sheets each: `CTRY.FLM` (`--out build/parity/bench/ctry/calibrate-2026-11-25`) and `INTRO.FLM` seed 1 (`--seed 1 --out build/parity/bench/intro/calibrate-2026-11-25-seed1`).
The recaptures were the data root's `backup/pre-305/vault-ctry/frames` and `backup/pre-305/vault-intro/frames`, whose `all_sha256` equals the pinned captures' (`cb58d95b…`, `2dc8f628…`).
Two grading passes graded each run and a tie-break pass the 11 sheets each run's passes disputed; the run folders do not record the model, and the coordinator reported Gemini Hydrogen for the `INTRO.FLM` run (the `CTRY.FLM` run's model is unconfirmed).
[`actor_pixels.py`](actor_pixels.py), run from the checkout root as `mise exec -- uv run python work/2026-11/calibration-actor-floor/actor_pixels.py`, wrote [`actor-pixels.csv`](actor-pixels.csv): each calibration tick's actor-layer pixel count in the 320×200 render (`layer >= 16`, summed over every actor), and whether the merged grades caught its actors-removed sheet, under the any-pixel rule the runs were planned with.

**Result**:
`CTRY.FLM` passed: actors removed 6 of 6, `shift_y:4` 6 of 6, `advance:5` 3 of 6, controls clean 12 of 12.
`INTRO.FLM` seed 1 failed: actors removed 4 of 6 against the 5-of-6 bar, `shift_y:4` 4 of 6, `advance:5` 4 of 6, controls clean 12 of 12.
The sheet plan took the first six ticks with any actor pixel, and two of `INTRO.FLM`'s held 1 pixel (tick 2058) and 33 pixels (tick 2223); on their sheets the actors are a few specks on the horizon.
Each grading pass graded each of those two planted sheets exactly as it graded the same tick's real sheet (all categories 0 or 1: at 2058 the first pass gave `scenery-missing` 1 and the second `actors-missing` 1, to both sheets), so neither pass detected either removal and the tie-break did not see them.
Every caught sheet removed 852 pixels or more: `CTRY.FLM` 852 to 2452, `INTRO.FLM` 4248 to 16093.
Neither new category is in `actors_removed`'s detection list, so the categories did not cause the failure.

**Verdict**: adopted two changes; seed 1 stays a FAIL.
A frame needs 64 actor pixels, summed over its actors, to carry an actors-removed sheet (`MIN_ACTOR_PIXELS` in `python/stunt_reel/bench/sheets.py`): an 8×8 block, chosen as a convention, not measured.
These two runs leave 34 to 851 pixels untested, and any floor in that range picks the same `INTRO.FLM` ticks (1002, 1167, 1321, 2410, 2564, 2718) and the same `CTRY.FLM` ones; a lower floor in it can keep more frames eligible on a film with small actors.
The 5-of-6 bar was measured on six sheets, so a calibration with fewer than six actors-removed sheets is now inconclusive (`ACTORS_BAR` in `python/stunt_reel/bench/workflow.py`); before, 2 of 2 passed.
Seed 1 is not rescored under the new plan, whose ticks 2564 and 2718 it never graded.
The actors-removed ticks do not depend on the seed, so two `INTRO.FLM` calibrations under the new plan grade the same six removals on differently named sheets.

**Lives in**: [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3, calibration rules.

## 2026-11-25: INTRO calibrations under the actor floor, and the first new-category example

**Question**: does `INTRO.FLM` pass calibration twice in a row under the 64-pixel floor, and does any graded sheet qualify as an example of the two new categories?

**Method**:
Three `INTRO.FLM` calibrations were made as in the entry above, with the floor: seed 2 and seed 3 at `c2a8f30d`, seed 4 at `b99bc589` (`--out build/parity/bench/intro/calibrate-2026-11-25-floor-seed<N>`).
Their actors-removed ticks do not depend on the seed, so all three plant the same six removals (1002, 1167, 1321, 2410, 2564, 2718) on differently named sheets.
The coordinator reported the graders: Gemini Hydrogen for seed 2, and DSH for both passes and the tie-break of seeds 3 and 4, after Hydrogen's quota ran out; the run folders do not record the model.
[`calibrations.py`](calibrations.py), run from the checkout root as `mise exec -- uv run python work/2026-11/calibration-actor-floor/calibrations.py`, rescores every 2026-11-25 calibration from its saved grades with `calibrate()` and lists each real sheet some pass graded 2 or more in a new category; its output is [`calibrations.txt`](calibrations.txt).

**Result**:
Seed 2 (Hydrogen) passed: actors removed 6 of 6, `shift_y:4` 2 of 6, `advance:5` 2 of 6, controls clean 11 of 12, 9 sheets disputed.
Seed 3 (DSH) passed: actors removed 6 of 6, `shift_y:4` 5 of 6, `advance:5` 3 of 6, controls clean 12 of 12, 20 sheets disputed.
Seed 4 (DSH) passed: actors removed 6 of 6, `shift_y:4` 3 of 6, `advance:5` 3 of 6, controls clean 11 of 12, 20 sheets disputed.
`propeller-solid` at tick 3466 was graded 2 by both passes and the tie-break of seed 2 (Hydrogen) and by both passes of seed 3 (DSH); in seed 4 DSH's passes split 2 and 0 and its tie-break gave 2.
No real sheet was graded 2 or more for `aircraft-colour-wrong` by both passes of any run: one pass of seed 3 at tick 2564 and the tie-break of seed 4 at tick 3246, each alone.

**Verdict**: `INTRO.FLM` passed twice in a row under the floor with one model (DSH, seeds 3 and 4), on the same six removals, so this shows DSH grades those removals repeatably, not that it catches removals on other frames.
`intro-3466` is `propeller-solid`'s example, graded 2 or more by two models (Hydrogen and DSH), in place of the Haiku and Sonnet pair earlier examples had.
`aircraft-colour-wrong` has no example yet; the frames that motivated it (`LAND.FLM`'s exhaust ring) have not been graded under the new categories.

**Lives in**: [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3, calibration rules; [`error-categories.toml`](../../../research/parity/error-categories.toml).
