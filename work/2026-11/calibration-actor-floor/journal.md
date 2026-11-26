# Journal

## 2026-11-25: an INTRO calibration fails on actors too small to see

**Question**: why did the first `INTRO.FLM` calibration under the 20-category taxonomy fail, when the `CTRY.FLM` one made the same day passed?

**Method**:
Both runs grade the same renders: `build/parity/ours/<film>_current`, rendered on WSL Ubuntu 24.04's lavapipe (`llvmpipe (LLVM 20.1.2, 256 bits)`) at `dd7e76eb`, whose `crates/` tree `4b5c69c` is unchanged at `124c5034` and `9be3e2cb`.
Both use the categories committed in `9be3e2cb` (digest `5838a280…`); the `CTRY.FLM` run was made at `124c5034` with that edit not yet committed, so its `run.json` records `revision` `124c5034`, and the `INTRO.FLM` run at `9be3e2cb`.
`mise run parity-bench -- errors-make --film <film> --calibrate --recapture <dir> --out <dir>` wrote 42 sheets each: `CTRY.FLM` (`--out build/parity/bench/ctry/calibrate-2026-11-25`) and `INTRO.FLM` seed 1 (`--seed 1 --out build/parity/bench/intro/calibrate-2026-11-25-seed1`).
The recaptures were the data root's `backup/pre-305/vault-ctry/frames` and `backup/pre-305/vault-intro/frames`, whose `all_sha256` equals the pinned captures' (`cb58d95b…`, `2dc8f628…`).
Two grading passes graded each run and a tie-break pass the 11 sheets each run's passes disputed; the run folders do not record the model, and the coordinator reported Gemini Hydrogen for both the `CTRY.FLM` and `INTRO.FLM` runs.
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
No real sheet in these `INTRO.FLM` calibration runs was graded 2 or more for `aircraft-colour-wrong` by both passes of a run: one pass of seed 3 at tick 2564 and the tie-break of seed 4 at tick 3246, each alone.

**Verdict**: `INTRO.FLM` passed twice in a row under the floor with one model (DSH, seeds 3 and 4), on the same six removals, so this shows DSH grades those removals repeatably, not that it catches removals on other frames.
`intro-3466` is `propeller-solid`'s example, graded 2 or more by two models (Hydrogen and DSH), in place of the Haiku and Sonnet pair earlier examples had.
`aircraft-colour-wrong` has no example yet; the frames that motivated it (`LAND.FLM`'s exhaust ring) are not among the sheets graded 2 or more for it, and the 20-category readout's only candidate is `traintnl-0683`, one model (next entry).

**Lives in**: [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3, calibration rules; [`error-categories.toml`](../../../research/parity/error-categories.toml).

## 2026-11-25: the 20-category readouts, DSH repeatability and the missing example

**Question**: what do the seven 20-category readouts show, does DSH grade the same sheets repeatably, and does any sheet qualify as an example of the two new categories?

**Method**:
`mise run parity-bench -- errors-make --film <film>` wrote 12 sheets per film for the seven references at `baebfd96`, the lavapipe render of `crates/` `4b5c69c` (`llvmpipe (LLVM 20.1.2, 256 bits)`), into `build/parity/bench/<film>/errors-20cat`.
Two DSH passes graded each film and a DSH tie-break graded the disputed sheets; the coordinator's delegated-task records name DSH for every pass, and the run folders do not record the model.
[`readout_repeat.py`](readout_repeat.py), run from the checkout root, rescores each pass with `readout()` and compares the two; its output is [`readout-repeat.txt`](readout-repeat.txt).
`TRAINTNL`'s tick 683 is the only real sheet both DSH passes graded 2 or more for `aircraft-colour-wrong`; `propeller-solid`'s `intro-3466` is from the calibration runs in the entry above.

**Result**:
Two DSH passes over the same 12 sheets per film moved a category's count of frames graded 2 or more by at most 1 on every film: one frame on CTRY (`ground-shade-edges`, `background-misregistration`), INTRO (`background-misregistration`, `propeller-solid`, `aircraft-colour-wrong`), LAND (`scenery-missing`, `background-misregistration`) and LOCATION (`propeller-solid`), and none on BALLOON, BOMB and TRAINTNL.
The saved `readout.json` of every film matches the readout rebuilt from its two passes and tie-break on its 2+ ticks and `other` notes.
That largest move, 1, is below the 3 that set `min_change` from two Haiku passes, so `min_change` stays 4.
No real sheet was graded 2 or more for `aircraft-colour-wrong` by two models: `traintnl-0683` has both DSH passes at 2, one model, and no other model graded it.
`propeller-solid`'s `intro-3466` was graded 2 by both passes of the Hydrogen seed 2 run and both passes of the DSH seed 3 run; the DSH seed 4 run split 2 and 0, its tie-break 2.

**Verdict**: the 20-category readouts are repeatable to within one frame on these sheets, below the 4-frame floor, and `min_change` 4 exceeds that run?s largest observed difference; the 19-category result below does not support that as a general DSH bound.
`aircraft-colour-wrong` has no qualifying example, so it stays `examples = []`.
The seven-film baseline refresh is not prepared: the categories changed, but the new category has no two-model example, the CTRY calibration under the 20 categories is Hydrogen's while the readouts are DSH's, and INTRO passed under Hydrogen seed 2 and DSH seeds 3 and 4 after Hydrogen seed 1 failed; refresh all seven in their own PR after those are resolved.

**Lives in**: [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3; [`error-categories.toml`](../../../research/parity/error-categories.toml).

## 2026-11-25: a Sonnet pass denies the colour category an example, and the file drops to 19 categories

**Question**:
Does `aircraft-colour-wrong` have a sheet that two different grading models each graded 2 or more, and if not, what becomes of the category and of the calibration and readout evidence that graded it?

**Method**:
The coordinator ran a Claude Sonnet grading pass, independent of the earlier DSH and Gemini Hydrogen passes, over three real sheets an earlier pass had graded 2 or more for the category: `TRAINTNL` tick 683 (both DSH passes of the 20-category readout), `INTRO` tick 2564 (the DSH seed 3 second pass) and `INTRO` tick 3246 (the DSH seed 4 tie-break).
It graded them 1, 0 and 0.
The run folders record no model; the coordinator's delegated-task record names Claude Sonnet, as it named the grader for the earlier runs.
The example rule needs 2 or more from two different grading models ([`error-categories.toml`](../../../research/parity/error-categories.toml)), so none of the three qualified, and the category was removed.
The file now holds 19 categories; its digest moved from `5838a280…` (20 categories, `9be3e2cb`) to `5f8b01d6d891a51dcf197d3d3c5afca8cd5229648d22823a7add5fa9df7eb91e` (19).
Because `score_run` refuses a run whose recorded digest differs, the 20-category calibrations and readouts cannot be rescored as 19-category ones, so fresh inputs were made under the 19-category file with `errors-make`, from the same lavapipe renders (`build/parity/ours/<film>_current`) and reports as the 20-category runs:

```
mise run parity-bench -- errors-make --film ctry --calibrate --recapture E:/git/stunt-reel.data/backup/pre-305/vault-ctry/frames --out build/parity/bench/ctry/calibrate-2026-11-25-19cat
mise run parity-bench -- errors-make --film intro --calibrate --seed 3 --recapture E:/git/stunt-reel.data/backup/pre-305/vault-intro/frames --out build/parity/bench/intro/calibrate-2026-11-25-19cat-seed3
mise run parity-bench -- errors-make --film intro --calibrate --seed 4 --recapture E:/git/stunt-reel.data/backup/pre-305/vault-intro/frames --out build/parity/bench/intro/calibrate-2026-11-25-19cat-seed4
mise run parity-bench -- errors-make --film <ctry|intro|land|balloon|traintnl|bomb|location> --out build/parity/bench/<film>/errors-19cat
```

They were made at the commit that added the 19-category file, so each run's `run.json` names it as `revision`; the absolute recapture paths are used because `--recapture` resolves only `corpus/` and `captures/` against the data root.
[`prepared_inputs.py`](prepared_inputs.py), run from the checkout root as `mise exec -- uv run python work/2026-11/calibration-actor-floor/prepared_inputs.py`, reads those runs back and writes [`prepared-inputs.txt`](prepared-inputs.txt).

**Result**:
`TRAINTNL` 683 was graded 2 by both DSH passes and 1 by Sonnet; `INTRO` 2564, 2 by the DSH seed 3 second pass and 0 by Sonnet; `INTRO` 3246, 2 by the DSH seed 4 tie-break and 0 by Sonnet.
One more real sheet, `INTRO` 2421, was graded 2 by the first pass of the INTRO 20-category readout and cleared by that run's tie-break: one pass of one model, and the Sonnet pass did not grade it.
`propeller-solid` retains its earlier 20-category evidence: `intro-3466` keeps its two-model example, and the category's 12 real sheets per run and per film are unchanged.
Nineteen categories remain, `propeller-solid` last.
At preparation time the new inputs held 42 sheets each for `CTRY` seed 1 and `INTRO` seeds 3 and 4, and 12 sheets per film for the seven readouts; every `run.json` records digest `5f8b01d6…`, the render and report digests, the seed and the revision.
At preparation time none had grades; the later results are recorded below.
The saved [`calibrations.txt`](calibrations.txt) and [`readout-repeat.txt`](readout-repeat.txt) keep the 20-category figures; re-running their scripts against the current file reads the removed id as unknown, so they no longer reproduce those files.

**Verdict**:
The colour category is removed for want of a qualifying example; the example rule is not loosened to keep it.
The 20-category calibrations and readouts remain the record of the 20-category file, and none of them is a calibration pass or a readout of the 19-category file.
`errors-score` on the `CTRY` 20-category run now refuses it with `categories 5838a2800757eaac... then, 5f8b01d6d891a51d... now`, so no older grade can pass for the new file by accident.
The new calibration inputs needed grading: two passes and a tie-break per run, then `CTRY` and both `INTRO` runs must print `calibration PASS`, the two `INTRO` runs supplying the twice-in-a-row requirement.
The seven readout runs then need two passes and a tie-break each, before a baseline refresh that writes `research/parity/readouts/` and `baseline.toml` with `categories_digest = 5f8b01d6…`, all seven together in its own PR.

**Next steps**:
Grade each new run twice from `brief.md` and `brief-2.md`, then run `errors-disputes` and grade `brief-tiebreak.md`, then score it:

```
mise run parity-bench -- errors-disputes --film ctry --out build/parity/bench/ctry/calibrate-2026-11-25-19cat
mise run parity-bench -- errors-score --film ctry --out build/parity/bench/ctry/calibrate-2026-11-25-19cat
mise run parity-bench -- errors-disputes --film intro --out build/parity/bench/intro/calibrate-2026-11-25-19cat-seed3
mise run parity-bench -- errors-score --film intro --out build/parity/bench/intro/calibrate-2026-11-25-19cat-seed3
mise run parity-bench -- errors-disputes --film intro --out build/parity/bench/intro/calibrate-2026-11-25-19cat-seed4
mise run parity-bench -- errors-score --film intro --out build/parity/bench/intro/calibrate-2026-11-25-19cat-seed4
mise run parity-bench -- errors-disputes --film <film> --out build/parity/bench/<film>/errors-19cat
mise run parity-bench -- errors-score --film <film> --out build/parity/bench/<film>/errors-19cat
```

`errors-score` takes no `--against` here: the committed baseline is an 18-category readout, and a calibrating run is not compared at all.

**Lives in**: [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3; [`error-categories.toml`](../../../research/parity/error-categories.toml); this item's [`README.md`](README.md).

## 2026-11-25: 19-category calibration and readout repeatability

**Question**: do the new categories calibrate and how much do the two readout passes differ?

**Method**:
The prepared 19-category runs above were graded with two DSH passes; Claude Sonnet graded the disputed sheets.
`mise run parity-bench -- errors-score --film <film> --out <run>` scored the saved grades.
`mise exec -- uv run python work/2026-11/calibration-actor-floor/readout_repeat_19.py` compares the passes and the saved readouts; its output is [readout-repeat-19.txt](readout-repeat-19.txt).
The first INTRO seed 3 tie-break file was missing when rechecked, so Sonnet graded its 23 disputed sheets again before scoring.

**Result**:
The score output is saved in [calibrations-19.txt](calibrations-19.txt).
CTRY passed with 6/6 actor removals, 12/12 controls, and 16 disputed sheets.
INTRO tick 3466 was graded 1, 0, 1 in seed 3 and 0, 0, 1 in seed 4 (passes 1, 2 and tie-break), below 2 under the 19-category file.
INTRO seed 3 passed with 6/6 actor removals, 12/12 controls, and 23 disputed sheets; seed 4 passed with 6/6, 11/12 controls, and 25 disputed sheets.
Both INTRO runs plant the same six removals, so they are not independent frame samples.
Across the seven readouts the largest difference in a category's count of frames graded 2 or more is 12: BOMB background misregistration was 12 in one DSH pass and 0 in the other.
LAND differed by 3 for that category, INTRO by at most 2, CTRY by at most 1, and BALLOON, LOCATION and TRAINTNL by 0.
The saved merged readouts match the reconstruction from the two passes and any tie-break on 2+ ticks and other notes.

**Verdict**: the calibration passes on these sheets, but the BOMB disagreement exceeds the four-frame `min_change` and leaves DSH repeatability for background misregistration unresolved.
On BOMB this is a severity threshold flip: the first pass graded every sheet 2, the second graded each 0 or 1, and the tie-break graded three 2 (ticks 1585, 1904, 2850).
A tie-break scores the disputed sheets; it does not measure repeatability of the final result.
The earlier Sonnet colour grades are transcribed in [sonnet-colour-grades.txt](sonnet-colour-grades.txt) from the coordinator messages; the original grader did not write an artifact.

**Lives in**: [metric-bench.md](../../../research/parity/metric-bench.md) section 2.3.
