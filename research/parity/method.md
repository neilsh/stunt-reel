# Parity Method: the Fidelity Loop

How a rendering change is judged against `PLAYONE.EXE`. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md) (parity, captured frame, film clock); capture mechanics are in [`../playone-exe/capture.md`](../playone-exe/capture.md); results are in [`log.md`](log.md).

## 1. The loop

1. **Capture once per `PLAYONE` build** (`mise run capture-ref`). Each frame is tagged in `meta.json` with `film_tick` (the film clock: the tick the frame shows) and `global_tick`. Matching uses the film clock because the capture ordinal is not a time axis: a captured frame is a distinct rendered page grabbed at retrace, so ordinals do not map to ticks (`[Supported Inference]`). The tags are read from DGROUP at the player's `DS`, which differs per build, so `DS` (`0x1575` for the demo) is a capture parameter, not a constant.
2. **Snapshot a baseline before the change.** Keep the current render directory and `report.json` (for example `build/parity/ours/ctry_base`, `build/parity/report/ctry_base`). A report without its render directory cannot produce the before panels.
3. **Render every tick including the final one:** `--frames 1..1344 --sidata <SIDATA>` writes `tick_00000.png`-`tick_01342.png`.
4. **Score:** `stuntreel parity --reference ... --test ... --output ... --clear-index 233`.
5. **Compare:** add `--compare <previous report.json> --compare-test <previous render dir>`. It prints means over the frames present in both reports, the 5 most improved/regressed frames, and the count moved by more than 0.005, and writes `compare.json`.
6. **Look at the worst movers before trusting the mean.** Open `compare_regressed_*.png` and `compare_improved_*.png` (`reference | before | after | |ref-before| | |ref-after|`). A mean can hide a regression or an improvement: the axis fix (`82ea965`) made the biplane upright like `PLAYONE` yet lowered mean SSIM 0.571 -> 0.567, because size and position error remain (`[Bounded Observation]`: worst frames about ticks 426-492, -0.02).
7. **Record a row in [`log.md`](log.md):** commit hash, matched frames, means, and the reason for any movement.

## 2. Scoring in one paragraph

Both sides become Rec. 601 luminance, are stretched 320x200 -> 320x240, and are scored with the shared 11x11-window SSIM (`[I6]`: >= 0.88 initial, >= 0.90 sign-off). IoU compares each side's non-sky mask and measures framing independent of shading. Neither is a perceptual judgement.

## 3. What is not yet evidence

* **Single film.** Only `CTRY.FLM` has been captured; the rows say nothing about other films, cameras, or actors (`[Unknown]`).
* **Metric caveats.** SSIM is sensitive to a misplaced thin object and to flat-area luminance; mask IoU is blind to shading and to anything inside the mask. A disagreement between the two is a prompt to read the sheets, not a verdict (`[Supported Inference]`).
* **End-hold policy undecided.** The 18 end-hold captures show `PLAYONE`'s blank screen (black, cursor, button bar), not the scene; they score about 0.005 and pull the 140-frame mean to 0.495. Until a policy exists, quote the 122-frame animated figure and say which.
* **Sparse sampling.** 140 captures over 1,342 ticks is roughly one frame per 11 ticks (`[Bounded Observation]`); motion between samples is unobserved.
* **One capture set.** Taken on one machine on 2026-10-21; recapture variance has not been measured (`[Unknown]`).
