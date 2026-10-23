# Parity Method: the Fidelity Loop

How a rendering change is judged against `PLAYONE.EXE`. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md) (parity, captured frame, film clock); capture mechanics are in [`../playone-exe/capture.md`](../playone-exe/capture.md); results are in [`log.md`](log.md).

## 1. The loop

1. **Capture once per `PLAYONE` build** (`mise run capture-ref`). Each frame is tagged in `meta.json` with `film_tick` (the film clock: the tick the frame shows) and `global_tick`. Matching uses the film clock because the capture ordinal is not a time axis: a captured frame is a distinct rendered page grabbed at retrace, so ordinals do not map to ticks (`[Supported Inference]`). The tags are read from DGROUP at the player's `DS`, which differs per build, so `DS` (`0x1575` for the demo) is a capture parameter, not a constant.
2. **Snapshot a baseline before the change.** Keep the current render directory and `report.json` (for example `build/parity/ours/ctry_base`, `build/parity/report/ctry_base`). A report without its render directory cannot produce the before panels.
3. **Render every tick including the final one:** `--frames 1..1344 --sidata <SIDATA> --width 320 --height 200 --viewport-rows 185` (the 3D view fills 185 rows; see `playone-exe/capture.md` § 4) writes `tick_00000.png`-`tick_01342.png`.
3a. **Planes:** each render also writes `tick_NNNNN.idx` and `tick_NNNNN.layer` beside the PNG (unlit palette index; layer ids 0 none, 1 world, 2+n for actor draw n of the frame). `parity` uses them for mask IoU and reports `mean_index_agreement_scored`.
4. **Score:** `stuntreel parity --reference ... --test ... --output ... --clear-index 233`. Always pass `--clear-index`: `render` picks 233 itself when given an `.ALL` (`stunt-cli/src/main.rs`, clear-index fallback), but `parity` defaults to 180, an olive green (121,138,32), so leaving the flag off scores against the wrong clear colour. 233 is `CTRY`'s sky, (138,194,227) live. The sky index is per film (`COL3-2`'s top rows are 228); `parity` measures the reference's own sky index (`sky_index` in `report.json`) separately from `--clear-index`.
5. **Compare:** add `--compare <previous report.json> --compare-test <previous render dir>`. It prints means over the frames present in both reports, the 5 most improved/regressed frames, and the count moved by more than 0.005, and writes `compare.json`. The basis is `scored` when both reports carry `scored` (SSIM over frames scored in both runs) and `all` otherwise (SSIM over all common frames), recorded on the first `[compare]` line and as `"basis"` in `compare.json`.
6. **Look at the worst movers before trusting the mean.** Open `compare_regressed_*.png` and `compare_improved_*.png` (`reference | before | after | |ref-before| | |ref-after|`). A mean can hide a regression or an improvement: the axis fix (`82ea965`) made the biplane upright like `PLAYONE` yet lowered mean SSIM 0.571 -> 0.567, because size and position error remain (`[Bounded Observation]`: worst frames about ticks 426-492, -0.02).
7. **Record a row in [`log.md`](log.md):** commit hash, matched frames, means, and the reason for any movement.

## 2. Scoring in one paragraph

Both sides become Rec. 601 luminance, are stretched 320x200 -> 320x240, and are scored with the shared 11x11-window SSIM (`[I6]`: >= 0.88 initial, >= 0.90 sign-off). IoU compares each side's non-sky mask and measures framing independent of shading. Neither is a perceptual judgement.

### 2.1 Fade floor

`PLAYONE.EXE` fades its palette linearly to black near the end of `CTRY.FLM`. For each captured frame, the **fade level** is the median, over a fixed index set, of (captured palette entry R+G+B) / (static Mode 13h palette entry R+G+B). The index set is the indices present in the first captured frame whose static R+G+B is above 60. A frame with no fade reads about 1.0 (1.011 for `CTRY`, from DAC 6->8-bit expansion). Cursor and button-bar entries do not fade; they are a minority of the set, so the median ignores them.

The renderer applies the same fade from the film's palette variables, so renders are scored as drawn. Frames below `--min-fade-level` (default 0.25) are computed and reported but not scored, because SSIM of near-black frames says little. `report.json` per frame adds `fade_level` and `scored`; the run level adds `min_fade_level`, `mean_ssim_scored`, `mean_iou_scored` (both null if no frame is scored), `scored_frames`, and `excluded_frames`. The headline is `mean_ssim_scored` with its scored-frame count; `mean_ssim`, `min_ssim` and `mean_iou` cover all matched frames.

Headless renders write the palette controls of every rendered tick to `palette_controls.json` beside the PNGs. The comparator rebuilds that palette to get the render's clear colour per tick, so the IoU sky mask follows the fade; a render directory without the file uses the static clear colour.

From `36a7305` to `5bf6afe` the comparator also reported `ssim_compensated` (the render's luminance scaled by the fade level, later by the ratio of capture to render fade level) and headlined `mean_ssim_compensated`. That stood in for the fade before the renderer modelled it and was retired once it did; `--compare` reads such reports for their raw `ssim`.

## 3. What is not yet evidence

* **Single film.** Only `CTRY.FLM` has been captured; the rows say nothing about other films, cameras, or actors (`[Unknown]`).
* **Metric caveats.** SSIM is sensitive to a misplaced thin object and to flat-area luminance; mask IoU is blind to shading and to anything inside the mask. A disagreement between the two is a prompt to read the sheets, not a verdict (`[Supported Inference]`).
* **End hold.** The 18 end-hold captures are the faded tail (fade level 0 at tick 1337), not the scene. Unfaded renders pulled the 140-frame mean to 0.495; with the modelled fade it is 0.667. The fade floor (section 2.1) scores only frames at or above fade level 0.25, which excludes them; quote `mean_ssim_scored` with its scored-frame count.
* **Fade mechanism.** The fade is authored as film variable 14 (palette brightness) and applied by `PLAYONE` to palette entries 0–239 ([`../playone-exe/palette-fade.md`](../playone-exe/palette-fade.md), Q-FLM-09). The renderer applies vars 13–15 itself and reproduces the live DAC exactly in 128 of 140 `CTRY.FLM` captures; the other 12 are one 6-bit level off, which is clock jitter and rounding, not a lag ([`palette-fade.md` § 5](../playone-exe/palette-fade.md)). The "6-tick lag" in earlier notes came from reading keys at slice starts. Raw IoU over all frames falls in the near-black tail, where the render shows no shapes to mask; those frames are not scored.
* **Sparse sampling.** 140 captures over 1,342 ticks is roughly one frame per 11 ticks (`[Bounded Observation]`); motion between samples is unobserved.
* **One capture set.** Taken on one machine on 2026-10-21; recapture variance has not been measured (`[Unknown]`).

## 4. Dead ends

Approaches that were tried and dropped. Each is recorded so it is not tried again without new evidence.

### 4.1 Fade scoring

* **Fade level from the frame's own indices.** Choosing the index set from the frame being measured fails on faded frames: the only entries still bright enough to qualify are the cursor and button-bar entries 240–255, which do not fade, so the median reads about 1.0. The set is fixed from the first captured frame instead (section 2.1) (`[Bounded Observation]`).
* **Compensating a render that already models the fade.** Once the renderer applied var 14, scaling its luminance by the fade level counted the fade twice: compensated SSIM stayed at 0.617 while raw SSIM rose from 0.495 to 0.667. Compensation was retired in `8cabb2a` (section 2.1) (`[Bounded Observation]`).
* **Scoring the black tail.** Without a floor, near-black frames score high against each other (about 0.92), which inflates the mean without saying anything about the scene. The `CTRY.FLM` tail at ticks 1337–1342 has 6 distinct RGB values (59,929 black pixels plus 2,480 of (130,105,101)) and mean luminance 7.1. Hence `--min-fade-level` (`[Bounded Observation]`).
* **Fitting the fade ramp to the captures.** Fitting brightness to the same frames that are then scored is circular; the ramp comes from the film's `var_set` keys instead ([`palette-fade.md` § 5](../playone-exe/palette-fade.md)).
* **The fade floor at night.** The brightness heuristic misreads a night film as faded and excluded 29 of 30 `COL3-2.FLM` frames ([`parity-findings.md` § 4](../parity-findings.md)).

### 4.2 Clock matching

* **Capture order or a fixed offset.** Matching captures to renders by capture ordinal, or by ordinal plus a constant (`TICK_TO_FRAME_OFFSET = 1`, since removed), does not work, because ordinals are distinct pages, not ticks (section 1, step 1). Matching uses `film_tick`.
* **The three clocks.** A capture carries the global clock (`DS:0x22B8`), the film clock (`DS:0x4896`) and its capture ordinal. `global_tick - film_tick` is 2 or 3 in every frame of both capture sets (122 of 140 `CTRY.FLM` frames, 30 of 30 `COL3-2.FLM`), except the 18 `CTRY.FLM` end-hold frames, where the film clock stops at 1342 and the global clock runs on to 7140 (`[Bounded Observation]`). Neither offset can stand in for the film clock.
* **The "6-tick lag".** A ramp that looked 6–11 ticks late was the slice-start reading of `var_set` keys, not a delay in `PLAYONE` (section 3, *Fade mechanism*).
