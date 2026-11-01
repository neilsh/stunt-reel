# Parity scoring: a metric bench, a regression verdict, a sign-off scale and fault readouts

Status: spec, awaiting review. Sections 1 to 4 agreed in conversation 2026-10-31. Follows
[`scoring-failures-2026-10-31.md`](scoring-failures-2026-10-31.md), which explains why the current score
cannot carry the work below.

## Intent

The headline parity score, SSIM against the captured frame, mostly measures flat sky and ground. On
`CTRY.FLM` a uniform grey frame scores 0.78 against the capture and the render 0.76; 67–82% of windows are
flat on both sides and score about 0.97 whatever they hold; of three planted errors (actors removed, a
4-column shift, a 5-tick advance) only the advance moved the per-frame score, by −0.024. The [I6] gates
(0.88 initial, 0.90 sign-off) are read against that number.

The score has three jobs, built in this order, each landing on its own and passing `mise run check`:

1. **Bench:** measure which metrics see which render faults, before choosing any.
2. **Regression verdict:** say whether a render change moved the render closer to the game or further.
3. **Sign-off scale:** a headline that measures closeness to `PLAYONE`, with [I6] restated on it.
4. **Fault readouts:** say what is wrong in a frame, so the next render fix is evident.

What was said and what is assumed: the user chose all three jobs, staged, in this order; numpy for the
bench (adding it as a dependency is acceptable); a Haiku judge as an experimental arm; a random other tick
as a fault and as the scale's floor. The capture stays the reference. The fault list, magnitudes, the 3x
pass bar and the actor search are this spec's proposals, agreed in conversation.

## 1. The metric bench

`python/scripts/parity_bench.py`, run as `mise run parity-bench`; numpy joins the dev dependency group.

**Inputs.** The film's reference capture from `research/parity/references.toml` (`vault-ctry/frames/004`),
the tear-free recapture `vault-ctry/frames/005`, and a render tree with `.idx` and `.layer` planes
(`build/parity/ours/ctry_current` by default). `CTRY.FLM` first; `INTRO.FLM` is a second column once the
first works.

**Faults are planted in memory**, on every scored frame, never written as altered render trees:

| Fault | Transform | Magnitudes |
|---|---|---|
| none | the render unchanged (control) | — |
| actors removed | pixels on layers 16 and up take the nearest non-actor pixel to their left | — |
| horizontal shift | every row moved right, the left edge repeating column 0 | 1, 2, 4, 8 columns |
| vertical shift | every column moved down, the top edge repeating row 0 | 1, 2, 4 rows |
| time advance | tick *t* shows the render of *t* + *k* | 1, 3, 5 ticks |
| flat terrain | terrain-layer pixels set to their mean colour in the frame | — |
| flicker | luma ±*a* on alternate ticks | 3, 10 |
| wrong tick | a random tick at least 100 ticks away, differing in at least 10% of pixels | — |
| grey frame | uniform grey at the render's mean luma | — |

**Noise yardstick.** The unchanged render scored against `004` and against `005`: the per-frame
difference between those two scores is variation no render change caused. A second build of the same
revision (`mise run build-at`) rendered once gives the build floor for section 2.

**Candidate metrics:**

- current SSIM (11x11 windows, stride 8, Rec. 601 luma, rows stretched 200 to 240, bar masked);
- structured-window SSIM: only windows where the capture's luma range exceeds 3 grey levels;
- grey-baseline skill: (SSIM − SSIM of the grey frame) / (1 − SSIM of the grey frame);
- per-layer index agreement (ocean, terrain, props, actors), from the render's `.layer` plane;
- edge match: an F-score of edge maps with a 1-pixel tolerance;
- actor-region SSIM: windows overlapping layers 16 and up;
- the Haiku judge, below.

**Fidelity to the real scorer.** The bench's current SSIM must reproduce the Rust scorer's per-frame
`ssim` in `report.json` to within 1e-4 on every frame, or the bench refuses to run. A test pins the numpy
SSIM against the Rust scorer on a synthetic fixture.

**Result per metric and fault:** the mean change from the control, whether its sign is "worse", and that
change divided by the recapture noise. A metric **passes** when every fault makes it worse by at least
3x the noise and the wrong tick and grey frame both score well below the control. Its **detectable
magnitude** per fault is the smallest one that clears 3x. Output `bench.json` and a printed table; the
result is recorded in [`research/parity/method.md`](../../../research/parity/method.md) and a
[`log.md`](../../../research/parity/log.md) row.

### 1.1 The Haiku judge (experimental)

- **Task.** One composite image, capture | A | B, where one of A and B is the unchanged render and the
  other carries a planted fault, in random order. Prompt: "Which of A or B matches the reference more
  closely? Answer A or B, then one sentence on the difference you see."
- **Mechanics.** The bench writes the composites and a separate answer key; Haiku subagents read the
  composites and write their answers to files; a script scores answers against the key. No API key, no
  new dependency.
- **Controls.** Every pair is shown in both orders (position bias); some pairs show the unchanged render
  twice (a good judge splits them evenly); the wrong tick is the easy control, without which the other
  answers mean nothing.
- **Size.** About 10 frames per fault and magnitude, both orders: 300–500 judgements over 4–8 subagents of
  about 60 composites each (SOP 5's limit of about 8 per task).
- **Pass bar.** At least 90% correct at a magnitude after removing position bias, reported in the same
  table as the numeric metrics.
- **Not in scope.** Running it inside `mise run check` or on every frame; moving it to the API is a later,
  separate decision.

## 2. The regression verdict

In `crates/stunt-cli/src/parity/compare.rs`, on every `--compare` run, with the bench's numpy version as
its oracle.

- **Render against render.** Per frame: the fraction of index-plane pixels changed, by layer, and
  before-against-after SSIM. A frame with no changed pixel is unchanged. Separately built binaries of the
  same code differed by up to 0.0012 in mean SSIM (method.md § 3); the bench's two-build render sets the
  floor below which a pixel change is not counted.
- **Differential capture score.** Per changed frame, take the 11x11 windows containing any changed
  pixel, score the capture against *before* and against *after* on those windows only, and take the
  difference as the frame's verdict. Flat windows that did not change drop out.
- **Metric.** The current SSIM until the bench names a better one; the machinery does not depend on the
  choice. The bench checks it: every planted fault, taken as the "after", must give a negative Δ.
- **Output.** One verdict line from `mise run parity`, for example
  `changed 37/114 frames: 29 closer, 6 further, 2 within noise; mean Δ +0.041 on changed windows`, a
  per-frame table in `compare.json`, and the worst-mover sheets ordered by this Δ.

## 3. The sign-off scale

- **Headline metric.** The bench's passing metric with the smallest detectable actor and shift faults. If
  none passes alone, the bench tests a weighted mix of the passing parts; the weights are fixed once and
  recorded.
- **Scale.** 0 is the film's mean score for wrong-tick renders; 1 is capture `004` scored against capture
  `005`, the game's own repeatability. `skill 0.42` reads as 42% of the way from a random moment to a
  recapture. The raw value and the grey-frame score stay in `report.json`. A static film's wrong ticks look
  alike, so its floor sits higher; the report states the floor beside the headline.
- **[I6].** An ADR records why SSIM against the capture stopped being the gate; `docs/SPEC.md` [I6] and its
  `doc_anchors` entry move to the new scale. The gate values are the user's call, made with the bench
  results; the starting proposal is 0.8 initial and 0.9 sign-off, checked against where the render lands.
- **Continuity.** `mean_ssim_scored` stays in reports and log rows; new rows add the skill value in the
  notes column, since the log's columns do not change. A later ADR may retire the old SSIM once rows show
  both side by side.

## 4. Fault readouts

Each readout starts in the bench and is validated by recovering a planted magnitude, not just by
reacting: a 2-row shift must read `dy = 2`, a 5-tick advance +5, flicker ±10. Readouts that recover their
plants are ported to the Rust report.

- **Global offset `(dx, dy)`:** phase correlation of capture against render over structured windows, per
  frame and the film median; the investigation's roughly 2-row offset should show here if real.
- **Actors:** per actor draw (layer 16 + n), a search near its render box for the best-matching capture
  position by edge template, giving the offset and match quality. This is how the capture's actor boxes,
  which it has no layer plane for, get found; it builds on the silhouette-offset probe in
  [`probes.md`](../../../research/parity/probes.md).
- **Terrain:** the section 3 metric over terrain-layer windows only.
- **Flicker:** mean-luma deviation from a 5-tick running median, render against the whole-film video
  capture (`vault-ctry/video/001`), aligned at offset 0 ± 1 from its log; frame captures are too sparse
  (one per 11 ticks).
- **Haiku descriptions**, only if section 1.1 passes: its reasons on a regression run's worst frames, as a
  hint, never a score.

Output: a `faults` section in `report.json` and one summary line per film, for example
`offset dy +2.0 dx +0.1 | actors Δ(3,−1) match 0.41 | terrain 0.52 | flicker 3.3 vs 0.1`.

## Stop conditions

- If no numeric metric passes the bench, sections 3 and 4 wait; the bench result is recorded, and section 2
  still lands on the current SSIM, since its verdict comes from changed windows only.
- If the Haiku judge misses the wrong-tick control, the arm is dropped and recorded.

## Open questions

- Is a 3x recapture-noise bar too strict for faults the capture itself blurs (the actor faults near the
  frame edge)?
- Does the wrong-tick floor need a per-film minimum distance other than 100 ticks for very static films?
- Do the [I6] gate values stay at 0.8 and 0.9 once the render's position on the scale is known?
