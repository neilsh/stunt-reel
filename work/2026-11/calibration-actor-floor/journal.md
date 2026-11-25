# Journal

## 2026-11-25: an INTRO calibration fails on actors too small to see

**Question**: why did the first `INTRO.FLM` calibration under the 20-category taxonomy fail, when the `CTRY.FLM` one made the same day passed?

**Method**:
Both runs grade the same renders: `build/parity/ours/<film>_current`, rendered on WSL Ubuntu 24.04's lavapipe (`llvmpipe (LLVM 20.1.2, 256 bits)`) at `dd7e76eb`, whose `crates/` tree `4b5c69c` is unchanged at `124c5034` and `9be3e2cb`.
Both use the categories committed in `9be3e2cb` (digest `5838a280…`); the `CTRY.FLM` run was made at `124c5034` with that edit not yet committed, so its `run.json` records `revision` `124c5034`, and the `INTRO.FLM` run at `9be3e2cb`.
`mise run parity-bench -- errors-make --film <film> --calibrate --recapture <dir> --out <dir>` wrote 42 sheets each: `CTRY.FLM` (`--out build/parity/bench/ctry/calibrate-2026-11-25`) and `INTRO.FLM` seed 1 (`--seed 1 --out build/parity/bench/intro/calibrate-2026-11-25-seed1`).
The recaptures were the data root's `backup/pre-305/vault-ctry/frames` and `backup/pre-305/vault-intro/frames`, whose `all_sha256` equals the pinned captures' (`cb58d95b…`, `2dc8f628…`).
Two Haiku passes graded each run and a Sonnet tie-break graded the 11 sheets each run's passes disputed.
[`actor_pixels.py`](actor_pixels.py), run from the checkout root as `mise exec -- uv run python work/2026-11/calibration-actor-floor/actor_pixels.py`, wrote [`actor-pixels.csv`](actor-pixels.csv): each calibration tick's actor-layer pixel count in the 320×200 render (`layer >= 16`, summed over every actor), and whether the merged grades caught its actors-removed sheet, under the any-pixel rule the runs were planned with.

**Result**:
`CTRY.FLM` passed: actors removed 6 of 6, `shift_y:4` 6 of 6, `advance:5` 3 of 6, controls clean 12 of 12.
`INTRO.FLM` seed 1 failed: actors removed 4 of 6 against the 5-of-6 bar, `shift_y:4` 4 of 6, `advance:5` 4 of 6, controls clean 12 of 12.
The sheet plan took the first six ticks with any actor pixel, and two of `INTRO.FLM`'s held 1 pixel (tick 2058) and 33 pixels (tick 2223); on their sheets the actors are a few specks on the horizon.
Each Haiku pass graded each of those two planted sheets exactly as it graded the same tick's real sheet (all categories 0 or 1: at 2058 the first pass gave `scenery-missing` 1 and the second `actors-missing` 1, to both sheets), so neither pass detected either removal and the tie-break did not see them.
Every caught sheet removed 852 pixels or more: `CTRY.FLM` 852 to 2452, `INTRO.FLM` 4248 to 16093.
Neither new category is in `actors_removed`'s detection list, so the categories did not cause the failure.

**Verdict**: adopted two changes; seed 1 stays a FAIL.
A frame needs 64 actor pixels, summed over its actors, to carry an actors-removed sheet (`MIN_ACTOR_PIXELS` in `python/stunt_reel/bench/sheets.py`): an 8×8 block, chosen as a convention, not measured.
These two runs leave 34 to 851 pixels untested, and any floor in that range picks the same `INTRO.FLM` ticks (1002, 1167, 1321, 2410, 2564, 2718) and the same `CTRY.FLM` ones; a lower floor in it can keep more frames eligible on a film with small actors.
The 5-of-6 bar was measured on six sheets, so a calibration with fewer than six actors-removed sheets is now inconclusive (`ACTORS_BAR` in `python/stunt_reel/bench/workflow.py`); before, 2 of 2 passed.
Seed 1 is not rescored under the new plan, whose ticks 2564 and 2718 it never graded.
The actors-removed ticks do not depend on the seed, so two `INTRO.FLM` calibrations under the new plan grade the same six removals on differently named sheets.

**Lives in**: [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3, calibration rules.
