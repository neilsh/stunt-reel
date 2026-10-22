# Parity Results Log

Dated results of `stuntreel parity` for `CTRY.FLM` against captured `PLAYONE.EXE` frames, newest last. From 2026-10-22 the headline figure is fade-compensated (`mean_ssim_compensated`, see notes); rows above it are raw. The loop that produces each row is in [`method.md`](method.md); reports and renders live under `build/parity/` (gitignored), so only the figures are recorded here.

**Capture set:** 140 frames, film clock 10 -> 1342, `DS = 0x1575`, captured 2026-10-21 on `main` at `a5e9897`. Frames are matched to renders by `film_tick` (SSIM and IoU as defined by `[I6]` and `crates/stunt-cli/src/parity.rs`; clear index 233).

| Date | Commit | Matched frames | Mean SSIM | Mean IoU | Notes |
|---|---|---|---|---|---|
| 2026-10-21 | `a5e9897` | 122 (18 end-hold unmatched: render stopped at tick 1341) | 0.571 | 0.830 | Baseline, film-clock matching; world via `corpus/si_archive/.../SIDATA`. |
| 2026-10-21 | `82ea965` | 122 | 0.567 | 0.830 | DOS axes -> `[I1]`, including actor orientation: the biplane is now upright like `PLAYONE`. Small SSIM drop (size/position error remains); worst-moving frames 39-45 (about ticks 426-492), -0.02 each. |
| 2026-10-21 | `1f673d9` / `935834a` / `ced1d06` | 122 | 0.567 | 0.830 | Refactors; renders byte-identical to `82ea965`. |
| 2026-10-21 | `5799a53` | 140 | 0.495 overall; 0.567 over the 122 animated ticks | 0.812 | Default range now renders tick 1342. The 18 end-hold captures are `PLAYONE`'s blank screen (reference black + cursor + button bar) against our final camera view: SSIM about 0.005. The scoring policy for the end hold is undecided. |
| 2026-10-22 | `36a7305` | 140 | 0.617 compensated over 114 scored (raw 0.495) | 0.840 over 114 scored (raw 0.812) | Fade-compensated scoring (`ssim_compensated`, `mean_ssim_compensated`); renders identical to `5799a53` (a raw `--compare` moved 0 frames); 26 frames below fade level 0.25 (ticks 1260 onward) excluded. |

## Notes

* **Superseded captures.** Reports made from `ctry_pre_filmclock` captures were keyed by capture ordinal, not film clock, and are superseded: they are not comparable to any row above, and the comparator now rejects a `meta.json` without `film_tick`. Recapture instead of converting.
* **Reading the `5799a53` row.** The overall mean fell only because 18 end-hold captures entered the average; over the 122 animated ticks the score equals the earlier rows. Compare rows over the same frame set (`--compare` reports the delta over the frames present in both).
* **Frames per `film_tick`.** All 18 end-hold captures share tick 1342; `--compare` keeps the first per tick, so a comparison covers 123 distinct ticks for this capture set (122 animated plus 1342).
* **Fade scoring (from 2026-10-22).** The 18 end-hold captures are the faded tail of `CTRY.FLM`, not a blank scene: `PLAYONE` fades its palette to black from about tick 990 and reaches zero at tick 1337, so the render is scaled by the measured fade level before scoring. The headline is `mean_ssim_compensated`, always quoted with its scored-frame count; rows before 2026-10-22 are raw.
* Evidentiary status of these figures: `[Bounded Observation]` (one film, one capture set, one machine); see [`method.md` section 3](method.md#3-what-is-not-yet-evidence).
