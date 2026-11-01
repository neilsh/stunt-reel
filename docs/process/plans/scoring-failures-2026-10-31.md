# Why per-second video scoring failed: investigation notes

Status: working notes, 2026-10-31. The scorer they examine is not merged; it is kept on branch
`feat/video-parity-scorer`. Follows part 3 of
[`video-parity-2026-10-31.md`](video-parity-2026-10-31.md), recorded in
[`research/parity/method.md`](../../../research/parity/method.md) § 4.4. Two read-only investigations ran
on `CTRY.FLM` only, each with its own Python reimplementation of the scorer: 11x11 windows, stride 8,
Rec. 601 luma, rows stretched from 200 to 240, the bar overlay masked, and the constants of
`crates/stunt-render/src/parity.rs`. They are cross-checked against the Rust scorer's numbers but are
not the binary itself. The scripts and raw arrays are in the session scratchpad (`inv/metric/`,
`inv/offset/`). The metric investigation left only a summary, so its section carries fewer numbers.

## The three failures

1. Planted render errors barely moved SSIM, in both scorers. Painting out the actors raised it by
   0.015, a 4-pixel shift moved it by about 0, and a 5-tick advance lowered it by 0.02.
2. Each sample's best time offset was noise. The best offset beat the film offset by a median of
   0.009, 23 of 27 seconds were flagged `slip`, and 20 of 81 samples sat on a window bound.
3. Refitting the film offset (−1 to −2) moved unaltered seconds by up to 0.071.

## 1. The metric: SSIM against the capture is dominated by flat areas

- **SSIM can see the planted errors, but the capture comparison hides them.** `[Bounded Observation]`
  - The reimplementation reproduces the effect: altered minus unaltered at the same tick is +0.015
    for actors removed, −0.002 for the shift and −0.005 for the advance.
  - Scoring the altered render against the unaltered render instead gives SSIM 0.96 for actors
    removed, 0.91–0.92 for the shift and 0.72–0.91 for the advance, about the size of 1 to 5 ticks
    of normal motion.
- **A constant grey frame outscores the render.** `[Bounded Observation]`
  - Against the capture, a uniform grey frame scores 0.78 and the real render 0.76. A render from
    400 ticks later still scores about 0.65.
  - 67–82% of windows are flat in both images and score about 0.97 whatever they contain.
  - Horizontal shifts of up to 8 pixels change the score by 0.006 or less, and the render's
    gradients correlate with the capture's at only 0.15.
  - So the headline SSIM of about 0.75 to 0.78 says little about the scene ([I6] thresholds are read
    against this number).
- **The render's actors do not match the game's.** `[Bounded Observation]`
  - The windows around the actors score about 0.11 against the capture, and painting the actors out
    raises them to about 0.43.
  - SSIM restricted to those windows is the only capture-based score that registers the actor change
    (z about 12). No capture-based score registers the shift or the advance (|z| < 0.5).
- **Render faults the investigator named:** `[Supported Inference]` actor shape and shadow, terrain
  texture, and a vertical offset of about 2 rows.

## 2. The time offset: the film barely moves, and the log is the better clock

- **A single sample's SSIM-against-offset curve is flat and jagged.** `[Bounded Observation]`, 80
  samples, offsets −12 to +6.
  - The peak sits a median 0.017 above the curve's median (10th–90th percentile 0.010–0.033).
  - The mean step between adjacent offsets is 0.011, as large as the peak.
  - Curves have 5.2 local maxima on average (white noise on 19 points gives about 6), and none of
    the 80 is monotone.
  - The winning offsets spread over the whole range: 9 of 80 sit on an end, with modes at +5 (14)
    and −1 (11).
- **Averaged over the film the curve is a plateau.** `[Bounded Observation]`, 636 video frames (every
  third row).
  - Mean SSIM is 0.763 at −12, 0.781 at −6, 0.788 at −3, 0.789 at every offset from −2 to +2 (within
    0.001), and 0.786 at +6.
  - A 12-tick lead costs 0.026 and a 6-tick lag 0.003, so averaging can rule out large errors but
    cannot resolve ±5 ticks.
  - Taking the best offset per second (about 13 frames each) wanders from −11 to +6.
- **Why: the film barely moves, so SSIM is mostly error that does not depend on time.**
  `[Bounded Observation]`
  - 1.4% of pixels change per video frame (median 1,047 of 64,000).
  - The capture compared with itself scores 0.964 one tick apart and 0.894 four ticks apart.
  - The camera shifts −1.0 to +1.8 pixels over 6 ticks (5th–95th percentile), and phase-correlation
    peaks are weak (median 0.21).
  - How sharp a sample's peak is barely tracks how much the render or the capture changes (Spearman
    0.24 and 0.15).
- **The video log's ticks are trustworthy; the expected offset is 0 ± 1.** `[Bounded Observation]`
  - Each of the 121 pages of `vault-ctry/frames/004`, converted to RGB with its own palette, was
    matched to the best video frame within ±12 of `emu_frame − 1275`.
    - 35 match exactly and 110 differ by under 400 pixels (median 19, maximum 3,920). The
      differences fall in rows 0–182, which fits torn pages or DAC lag (§ 4.5 of the capture note),
      not tick errors.
    - Of the 110, the match is at `emu_frame − 1275` in 55 cases and `− 1276` in 53, so log rows
      and video frames agree to within one frame.
  - The page's film tick equals the log's tick at the matched frame in 86 of 121, is one lower in 34
    and three higher in one. A page that matches two adjacent frames makes the 34 ambiguous between
    a real lag and the earlier match winning.
- **There are about 1.4 frames per tick, and which one is scored does not matter.**
  `[Bounded Observation]`
  - 1,338 of 1,906 log steps advance one tick and 568 repeat it; no tick is skipped.
  - 1,756 of 1,907 frames differ from the frame before.
  - Scoring the second frame of a repeated tick instead of the first changes SSIM by −0.001 ± 0.004
    (86 ticks).
- **The planted 5-tick advance is detectable only by averaging, and only in second 16.**
  `[Bounded Observation]` The statistic is the average SSIM at −5 minus the average at 0, per
  second.
  - With no planted change (all seconds but 15 and 16), the 90th percentile is 0.0013 and the
    maximum 0.0033 at about 13 frames per second. At the scorer's 3 samples, the 90th percentile is
    0.0041 and the maximum 0.026.
  - In the altered render, second 16 gives +0.0274 averaged, 8 times that maximum, but only +0.011
    at 3 samples, which is inside the noise.
  - Second 15 gives +0.0059, while the unaltered render already gives +0.0065 there.
- **The film offset flips because the scorer picks a point on a plateau.** `[Supported Inference]`
  With the curve flat to 0.001 from −3 to +3, the median of about 80 noisy picks moves a tick under
  any change to the render. Every second rescored at the new offset moves with it, most in a fade,
  where SSIM changes fast with offset (second 26: 0.071).

### Ways of estimating the offset (CTRY, in ticks)

| Estimator | Whole film | Stability | Second 16 / 15 against the noise | Verdict |
|---|---|---|---|---|
| Scorer now: best offset per sample, median, window −8 to +2 | −1 (−2 on the altered render) | noise up to 0.026 at 3 samples | +0.011 / +0.024 against 0.026: lost in noise | noise |
| Fixed 0 from the log, no search | 0 | cannot drift | detects nothing | stable |
| Whole-film average SSIM | −2 on a plateau from −3 to +6; bootstrap over seconds 0 (5–95%: −1 to +2) | ±1 | n/a | stable to ±1 only |
| Average SSIM per second (about 13 frames) | best offset wanders from −11 to +6 | noise up to 0.0033 | +0.0274 / +0.0059 (second 15 already +0.0065 unaltered) | catches 16 only |
| SSIM over windows where the capture moves (more than 3 grey levels) | 0 (0.476 against 0.455 at −12); bootstrap 0.9 ± 1.0 | per second still wanders | +0.0496 against noise up to 0.035 (1.4×) / +0.015 | sharpest whole-film peak, weak per second |
| Correlation of 4-tick difference images | −1 (0.04 at the peak, 0.00 at −8) | gains up to 0.21 without any change | +0.207 against noise up to 0.051 (4×) / +0.023 | the render's flicker swamps it |
| Cross-correlating camera shift (phase correlation) | +1 | per second −9 to +6 | no | camera too static to use |
| Cross-correlating motion energy over time | −1 (0.17) | per second −12 to +5 | no | not locked to time |

## 3. A render defect found along the way: flicker

`[Bounded Observation]`

- The render changes far more from tick to tick than the game does: mean absolute luma change 4.25
  per tick against 0.98, tick-to-tick SSIM 0.934 against 0.964.
- At ticks 100, 300, 700 and 1100 the render changes 70–99% of its pixels (a global grey shift of
  about 10) while the capture changes 0–4%.
- The render's mean luma flickers: standard deviation 3.3 about a 5-tick median, 95th percentile
  8.5, for example 100.4, 109.2, 101.3, 111.8 at ticks 700–703. The capture's is 0.1.
- The flicker explains little of the jitter between offsets (correlation −0.10). It does defeat any
  estimator built on frame differences.

## Recommendations

1. **Take the time offset from the log: 0, with ±1 tolerance, never refitted per render.** If a film
   ever needs another value, fit it once over the whole film, using the windows where the capture
   moves, and store it with the reference as a reviewed change. Fail a run whose averaged estimate
   leaves that value by more than 1.
2. **Drop the per-sample search.** A `slip` check needs every frame of a second averaged (at least 13,
   ideally about 38) and a margin of about 0.01 between best and film-offset SSIM, three times the
   largest noise measured. Static seconds cannot show a slip at all.
3. **Report SSIM above a grey-frame baseline**, so the headline says how much better the render is
   than a blank picture.
4. **Add a render-against-render regression score** (a candidate render scored against a baseline
   render). It catches all three planted errors where the capture comparison catches none.
5. **Score actor regions separately**, since that is the only capture-based score that moved.
6. **Fix the render**: actor shape and shadow, terrain texture, the roughly 2-row vertical offset,
   and the luma flicker. Each makes every comparison sharper.

## Not determined

- What causes the jitter between adjacent offsets beyond the flicker (about 1% explained), and what
  changes 70–99% of render pixels at some ticks.
- Whether the true offset is 0 or −1: the page check cannot separate a tick lag from DAC lag.
- Why second 15 shows no −5 signal (assumed static content, not measured per layer).
- The capture's true actor boxes, chroma SSIM, and every `INTRO.FLM` result: only `CTRY.FLM` was
  studied, with one planted advance.
- Whether a geometry-sensitive score would make per-second alignment work.
