# Parity Method: the Fidelity Loop

How a rendering change is judged against `PLAYONE.EXE`. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md) (parity, captured frame, film clock); capture mechanics are in [`../playone-exe/capture.md`](../playone-exe/capture.md); results are in [`log.md`](log.md).

## 1. The loop

1. **Capture once per `PLAYONE` build** (`mise run capture-ref`). Each frame is tagged in `meta.json` with `film_tick` (the film clock: the tick the frame shows) and `global_tick`. Matching uses the film clock because the capture ordinal is not a time axis: a captured frame is a distinct rendered page grabbed at retrace, so ordinals do not map to ticks (`[Supported Inference]`). The tags are read from DGROUP at the player's `DS`, which differs per build, so `DS` (`0x1575` for the demo) is a capture parameter, not a constant.
2. **Snapshot a baseline before the change.** Keep the current render directory and `report.json` (for example `build/parity/ours/ctry_base`, `build/parity/report/ctry_base`). A report without its render directory cannot produce the before panels.
3. **Render every tick including the final one:** `--frames 1..1344 --sidata <SIDATA>` writes `tick_00000.png`-`tick_01342.png`.
4. **Score:** `stuntreel parity --reference ... --test ... --output ... --clear-index 233`.
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
* **Fade mechanism.** The fade is authored as film variable 14 (palette brightness) and applied by `PLAYONE` to palette entries 0–239 ([`../playone-exe/palette-fade.md`](../playone-exe/palette-fade.md), Q-FLM-09). The renderer applies vars 13–15 itself; the remaining mismatch inside the fade is chiefly the 6-tick lag between the authored ramp and the captured one, and it counts against the score. Raw IoU over all frames falls in the near-black tail, where the render shows no shapes to mask; those frames are not scored.
* **Sparse sampling.** 140 captures over 1,342 ticks is roughly one frame per 11 ticks (`[Bounded Observation]`); motion between samples is unobserved.
* **One capture set.** Taken on one machine on 2026-10-21; recapture variance has not been measured (`[Unknown]`).
