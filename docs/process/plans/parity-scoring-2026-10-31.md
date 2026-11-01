# Parity scoring: a metric bench, a regression verdict, a sign-off scale and fault readouts

Status: spec, awaiting review. Sections 1 to 4 agreed in conversation 2026-10-31; revised after self-review
the same day. Follows [`scoring-failures-2026-10-31.md`](scoring-failures-2026-10-31.md), which explains
why the current score cannot carry the work below.

## Intent

The headline parity score, SSIM against the captured frame, mostly measures flat sky and ground. On
`CTRY.FLM` a uniform grey frame scores 0.78 against the capture and the render 0.76; 67–82% of windows are
flat on both sides and score about 0.97 whatever they hold; of three planted errors (actors removed, a
4-column shift, a 5-tick advance) only the advance moved the per-frame score, by −0.024. The [I6] gates
(0.88 initial, 0.90 sign-off) are read against that number.

The score has three jobs (stages 2–4), preceded by a bench that measures the candidates. Each stage lands
on its own and passes `mise run check`:

1. **Bench:** measure which metrics see which render faults, before choosing any.
2. **Regression verdict:** say whether a render change moved the render closer to the game or further.
3. **Sign-off scale:** a headline that measures closeness to `PLAYONE`, with [I6] restated on it.
4. **Fault readouts:** say what is wrong in a frame, so the next render fix is evident.

What was said and what is assumed: the user chose all three jobs, staged, in this order; numpy for the
bench (adding it as a dependency is acceptable); a Haiku judge as an experimental arm; a random other tick
as a fault and as the scale's floor. The capture stays the reference. The fault list, magnitudes, the 3σ
pass bar and the actor search are this spec's proposals, agreed in conversation.

## Shared rules

- **Paired ticks.** Every comparison between two captures uses the film ticks both hold exactly.
  `vault-ctry/frames/004` and `005` hold 121 frames each and share 74 ticks (106 within one tick); the
  bench uses the 74.
- **Region masks come from the control render.** Per-layer and actor-region metrics take their windows
  from the unchanged render's `.layer` plane at that tick, for every variant scored: faults, the grey
  frame, the wrong tick and capture against capture. A fault that moves or removes actors is then scored
  over the region where the actors should be, and the capture, which has no layer plane, can be scored
  at all.
- **Recapture noise σ.** For a metric, the standard deviation over the paired ticks of
  (score of the control against `004`) − (score of the control against `005`): per-frame variation that
  no render change caused. The bench writes it per film and metric; the chosen metric's σ is copied into
  [`research/parity/references.toml`](../../../research/parity/references.toml) beside the reference by a
  reviewed commit, like the reference itself.

## 1. The metric bench

`python/scripts/parity_bench.py`, run as `mise run parity-bench`; numpy joins the dev dependency group.

**Inputs.** The film's reference capture from `references.toml` (`vault-ctry/frames/004`), the tear-free
recapture `vault-ctry/frames/005`, and a render tree with `.idx` and `.layer` planes
(`build/parity/ours/ctry_current` by default). `CTRY.FLM` first; `INTRO.FLM` is a second column once the
first works.

**Faults are planted in memory**, on every scored frame, never written as altered render trees. Each fault
states what it does to the RGB, `.idx` and `.layer` planes; where a plane is left undefined, metrics that
need it report `n/a` for that fault.

| Fault | RGB and `.idx` | `.layer` | Magnitudes |
|---|---|---|---|
| none | unchanged (control) | unchanged | — |
| actors removed | pixels on layers 16 and up take the nearest non-actor pixel to their left | same rule | — |
| horizontal shift | rows moved right, the left edge repeating column 0 | same | 1, 2, 4, 8 columns |
| vertical shift | columns moved down, the top edge repeating row 0 | same | 1, 2, 4 rows |
| time advance | tick *t* takes all planes of *t* + *k*; ticks past the end are skipped | same | 1, 3, 5 ticks |
| flat terrain | terrain pixels take the frame's mean terrain colour; `.idx` its modal terrain index | unchanged | — |
| flicker | luma ±*a* on alternate ticks; `.idx` unchanged | unchanged | 3, 10 |
| wrong tick | all planes of a random tick at least 100 ticks away whose `.idx` differs in at least 10% of pixels; fixed seed | same | — |
| grey frame | uniform grey at the render's mean luma; `.idx` undefined | unchanged | — |

**Candidate metrics:**

- current SSIM (11x11 windows, stride 8, Rec. 601 luma, rows stretched 200 to 240, bar masked);
- structured-window SSIM: only windows where the capture's luma range exceeds 3 grey levels;
- grey-baseline skill: (SSIM − SSIM of the grey frame) / (1 − SSIM of the grey frame);
- per-layer index agreement (ocean, terrain, props, actors);
- edge match: an F-score of edge maps with a 1-pixel tolerance;
- actor-region SSIM: windows overlapping layers 16 and up;
- the Haiku judge (section 1.1).

**Fidelity to the real scorer.** The bench's current SSIM must reproduce the Rust scorer's per-frame
`ssim` in `report.json` to within 1e-4 on every frame, or the bench refuses to run. A test pins the numpy
SSIM against golden values from the Rust scorer on a synthetic fixture in `tests/fixtures/`.

**Result per metric and fault:** the mean per-frame change from the control, its sign, and that change in
units of σ. A fault is **detected** when the mean change is worse by at least 3σ; a metric's **detectable
magnitude** for a fault is the smallest magnitude detected. A metric **passes** when it detects every
fault, the wrong tick and the grey frame included, with no `n/a`. A metric with an `n/a` or a miss can
still enter section 3 as part of a mix. Output `bench.json` and a printed table; the result is recorded in
[`research/parity/method.md`](../../../research/parity/method.md) and a
[`log.md`](../../../research/parity/log.md) row.

**Build floor.** A second build of the same revision (`mise run build-at`) renders the film once; the
bench reports how many `.idx` pixels per frame differ between the two builds. Section 2 uses it.

### 1.1 The Haiku judge (experimental)

- **Task.** One composite image, capture | A | B, where one of A and B is the unchanged render and the
  other carries a planted fault, in random order. Prompt: "Which of A or B matches the reference more
  closely? Answer A or B, then one sentence on the difference you see."
- **Blindness.** Composites are named by a random id. The answer key is not written to disk: the bench
  derives it from a seed given on the command line, and the scoring step takes the same seed.
- **Mechanics.** Haiku subagents read their composites and write their answers to a file through the
  shell; where that is refused, they return the answers as their final text and the controller saves it.
  A script scores the answers. No API key, no new dependency.
- **Controls.** Every pair is shown in both orders (position bias); some pairs show the unchanged render
  twice (a good judge splits them evenly); the wrong tick is the easy control, without which the other
  answers mean nothing.
- **Size.** About 10 frames per fault and magnitude, both orders: 300–500 judgements over 4–8 subagents of
  about 60 composites each (SOP 5's limit of about 8 per task).
- **Pass bar.** At least 90% correct at a magnitude after removing position bias, reported beside the
  numeric metrics' detectable magnitudes.
- **Not in scope.** Running it inside `mise run check` or on every frame; moving it to the API is a later,
  separate decision.

## 2. The regression verdict

In `crates/stunt-cli/src/parity/compare.rs`, on every `--compare` run. Its tests use golden values that the
bench's numpy version computes on a synthetic fixture.

- **Render against render.** Per frame: the fraction of `.idx` pixels changed, by layer, and
  before-against-after SSIM. A frame with no changed pixel is unchanged. A frame whose changed-pixel count
  is within the bench's build floor is labelled `build noise`, not counted as changed.
- **Differential capture score.** Per changed frame, take the 11x11 windows containing any changed
  pixel, score the capture against *before* and against *after* on those windows only, and take the
  difference Δ as the frame's verdict. Flat windows that did not change drop out.
- **Noise.** `|Δ|` below the film's σ in `references.toml` is `within noise`. Without a recorded σ the
  verdict reports Δ only, with no noise bucket.
- **Metric.** The current SSIM until the bench names a better one; the machinery does not depend on the
  choice. The bench checks it: every planted fault, taken as the "after", must give a negative Δ.
- **Output.** One verdict line from `mise run parity`, for example
  `changed 37/114 frames: 29 closer, 6 further, 2 within noise; mean Δ +0.041 on changed windows`, a
  per-frame table in `compare.json`, and the worst-mover sheets ordered by Δ.

## 3. The sign-off scale

- **Headline metric.** Among passing metrics, the one detecting the smallest horizontal and vertical
  shifts, ties broken by the larger actors-removed change in σ. If none passes alone, the bench tests a
  weighted mix of the parts that detect faults the others miss; the weights are fixed once and recorded.
- **Scale.** 0 is the film's mean score for wrong-tick renders; 1 is capture `004` scored against capture
  `005` over the paired ticks, the game's own repeatability. `skill 0.42` reads as 42% of the way from a
  random moment to a recapture. A render below the floor reads negative and is reported as such. The raw
  value, the floor and the grey-frame score stay in `report.json`; a static film's wrong ticks look alike,
  so its floor sits higher, and the report prints the floor beside the headline.
- **[I6].** An ADR records why SSIM against the capture stopped being the gate; `docs/SPEC.md` [I6] and its
  `doc_anchors` entry move to the new scale. The gate values are the user's call, made with the bench
  results; the starting proposal is 0.8 initial and 0.9 sign-off, checked against where the render lands.
- **Continuity.** `mean_ssim_scored` stays in reports and log rows; new rows add the skill value in the
  notes column, since the log's columns do not change. A later ADR may retire the old SSIM once rows show
  both side by side.

## 4. Fault readouts

Each readout starts in the bench and is validated by recovering a planted magnitude, not just by
reacting: a 2-row shift must read `dy = 2`, a 5-tick advance +5, flicker ±10, each within one unit.
Readouts that recover their plants are ported to the Rust report.

- **Global offset `(dx, dy)`:** phase correlation of capture against render over structured windows, per
  frame and the film median; the investigation's roughly 2-row offset should show here if real.
- **Actors:** per actor draw (layer 16 + n), a search near its render box for the best-matching capture
  position by edge template, giving the offset and match quality. This is how the capture's actor boxes,
  which it has no layer plane for, get found; it builds on the silhouette-offset probe in
  [`probes.md`](../../../research/parity/probes.md).
- **Terrain:** the section 3 metric over terrain-layer windows only.
- **Flicker:** mean-luma deviation from a 5-tick running median, render against the whole-film video
  capture (`vault-ctry/video/001`), aligned at offset 0 ± 1 from its log; frame captures are too sparse
  (one per 11 ticks). The render tree holds every tick.
- **Haiku descriptions**, only if section 1.1 passes: its reasons on a regression run's worst frames, as a
  hint, never a score.

Output: a `faults` section in `report.json` and one summary line per film, for example
`offset dy +2.0 dx +0.1 | actors Δ(3,−1) match 0.41 | terrain 0.52 | flicker 3.3 vs 0.1`.

## Stop conditions

- If no metric or mix passes the bench, section 3 waits and the bench result is recorded. Section 2 still
  lands on the current SSIM, since its verdict comes from changed windows only. Section 4 lands without
  the terrain readout.
- If the Haiku judge misses the wrong-tick control, the arm is dropped and recorded.

## Open questions

- Is 3σ too strict for faults the capture itself blurs, such as actors near the frame edge?
- Does the wrong-tick floor need a minimum distance other than 100 ticks for very static films?
- Do the [I6] gate values stay at 0.8 and 0.9 once the render's position on the scale is known?
- `index_terrain` improves by about 240σ under every advance and a 3-tick advance improves every SSIM metric: does the render's terrain lag the capture's film tick? Not yet probed.

Bench result 2026-10-31 (`research/parity/method.md` § 2.2): no metric passes, because two faults
(actors removed, a 3-tick advance) move the current render *closer* to the capture; the pass rule assumed
a render near the game. Section 3 waits (Stop conditions). The Haiku judge missed the wrong-tick control
(0.67) and is dropped. Section 2 lands on the current SSIM; its differential check is negative for every
fault except those two, and the build floor is 0.
