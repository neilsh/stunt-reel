---
summary: "Records how the parity metrics behave: the planted-fault metric bench, recapture noise of the reference films (with and without sound), and error categories graded by a vision model."
---

# Parity Method: Metric Bench, Recapture Noise and Error Categories

How the scores of [`method.md`](method.md) section 2 behave under planted faults, recapture and grading. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md); what a score cannot yet prove is in [`evidence-limits.md`](evidence-limits.md).

## 2.2 The metric bench

`mise run parity-bench -- run --film <film>` (`python/stunt_reel/bench/`) plants 16 render faults (besides the unchanged control) in memory on every scored frame and scores ten candidate metrics against the reference. Its numpy SSIM reproduces the Rust `ssim` of `report.json` to within 1e-4 on every frame, and a synthetic fixture with golden values from the Rust scorer pins the two together (`tests/fixtures/parity/bench/`). The yardstick σ is the standard deviation, over the scored ticks two captures both hold, of (metric against one) − (metric against the other) with the unchanged render: per-frame variation no render change caused. A fault is detected when the metric falls by at least 3σ on average.

What it found (`[Bounded Observation]`; unless a bullet gives its own date and commit, 2026-10-31, one render per film at `2461289`, `CTRY.FLM` and `INTRO.FLM`, references `004` against recaptures `005`):

* **No metric detects every fault**, because a fault can move the render towards the capture (shown at `2461289`). There, removing the actors raised `ssim` (15σ on `CTRY.FLM`, 11σ on `INTRO.FLM`) and the differential score on the windows the removal touches was +0.18 on `CTRY.FLM`: our actors then matched the capture worse than the ground behind them.
* **Removing the actors no longer raises `ssim`** (`[Bounded Observation]`, 2026-11-12, renders at `9bc0fb78` against the stubbed Patch 3 references of section 2.2.1, the fault planted on every scored tick of `CTRY.FLM` and `INTRO.FLM`). Mean `ssim` falls by 0.029 on `CTRY.FLM` (6 of 114 ticks rise) and by 0.051 on `INTRO.FLM` (26 of 209 rise); index agreement falls by 0.015 and 0.040. Both the render and the references changed since `2461289`, and which change reversed the sign is not separated. Only this fault was re-tested; the bench's other faults have not been re-scored. _Source: [2026-11-12: second-round results: A1b, F1b and R2](../../work/2026-11/440_target-frame-adoption/journal.md#2026-11-12-second-round-results-a1b-f1b-and-r2)._
* **Drawn objects may sit left of `PLAYONE`'s.** Shifting the render right raises `ssim_actors` at every magnitude tried on `CTRY.FLM`; not yet measured directly.
* **Detection is not monotone in magnitude.** On `CTRY.FLM`, whole-frame `ssim` misses a 3-tick advance but detects 1 and 5, and `ssim_props` detects a 1-column shift but misses 2, 4 and 8: read the bench's row per fault, not its smallest detected magnitude.
* **Index agreement** is the most sensitive per layer but reads layers differently: on `CTRY.FLM`, `index_terrain` *improves* by about 240σ under any advance; unexplained.
* **Build floor:** on `CTRY.FLM` a second build of the same revision (`mise run build-at`) rendered all 1,337 ticks with no `.idx` or luma pixel different.
* **`INTRO.FLM`'s σ units are inflated**: its two captures agree so closely (σ 1.7e-5 for `ssim_structured`) that they are not comparable with `CTRY.FLM`'s.

_Source: [2026-10-31: the metric bench](../../work/2026-11/distill-method/journal.md#2026-10-31-the-metric-bench), which holds the table of every metric against every fault._

## 2.2.1 Recapture noise of the reference films

`[Bounded Observation]`, 2026-11-09, one pair per film on the Patch 3 `PLAYONE` from the `MAKEONE` archive its row pins, both captures with the archive's sound range stubbed (ADR 0043), the second started 0.1 s after the first: every film replayed page for page, so these references showed no recapture noise in one pair per film, and no row carries a `noise_sigma`. Identical pages are ticks both captures hold whose index pages match pixel for pixel; palettes matched on every page too.

| Film | Identical / shared ticks |
|---|---|
| `vault-ctry` | 121 / 121 |
| `vault-intro` | 347 / 347 |
| `vault-land` | 103 / 103 |
| `vault-balloon` | 108 / 108 |
| `vault-traintnl` | 112 / 112 |
| `vault-bomb` | 339 / 339 |
| `vault-location` | 745 / 745 |

One pair per film bounds this: a rarer divergence than one pair can show is not ruled out. _Source: [2026-11-09: the seven reference films recaptured stubbed](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-the-seven-reference-films-recaptured-stubbed)._

**With sound, before #305.** `[Bounded Observation]`, 2026-11-08, renders and scores at `ff576ba`, one recapture per film on the Patch 3 `PLAYONE` from the Patch 3 `MAKEONE` archive its `references.toml` row pins. σ is the bench's whole-frame `ssim` σ of section 2.2 over the scored ticks the reference and the recapture both hold; identical pages are paired ticks whose index pages match pixel for pixel. `mise run parity-bench -- run --films <films>` prints a table of this shape (to four significant figures) for the films named, reading each recapture from `<data root>/bench/<slug>/recapture/`; `bench.json` also records p90.

| Film | Paired | Identical pages | σ (`ssim`) | Median \|Δ\| | p95 | Largest \|Δ\| |
|---|---|---|---|---|---|---|
| `vault-ctry` | 104 | 77 | 0.0052 | 0 | 0.0143 | 0.026 |
| `vault-intro` | 172 | 94 | 0.0194 | 0 | 0.0529 | 0.113 |
| `vault-land` | 88 | 61 | 0.0051 | 0 | 0.0132 | 0.024 |
| `vault-balloon` | 95 | 56 | 0.0109 | 0 | 0.0264 | 0.063 |
| `vault-traintnl` | 102 | 71 | 0.0062 | 0 | 0.0053 | 0.040 |
| `vault-bomb` | 265 | 153 | 0.0124 | 0 | 0.0230 | 0.087 |
| `vault-location` | 732 | 729 | 0.00012 | 0 | 0 | 0.003 |

* **The noise is heavy-tailed.** On every film the median |Δ| is 0: σ comes from the minority of pages that differ, so it overstates the noise of a typical frame and understates the worst. As `noise_sigma` it would make `--noise-sigma` call a Δ below 0.005 to 0.019 within noise on six films, which their identical pages argue is mostly not noise (`[Supported Inference]`), so only `vault-location`'s row carried one (0.00012) until the stubbed recapture ([#305](https://github.com/neilsh/stunt-reel/issues/305)).
* **On `BALLOON.FLM` the noise comes from the archive's chunks in `0xC000`–`0xCFFF`** (`[Bounded Observation]`, 2026-11-09): with each cut to one byte, two captures agree page for page. On `CTRY.FLM` a stubbed pair agreed on 121 of 121 pages, against 27 differing of 104 here, and the demo archive, whose samples are shortened, also replays identically. That `CTRY`'s and the other films' noise has the same cause is `[Supported Inference]`; `vault-location` replays nearly identically with such chunks kept ([`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.4). Stubbing also changes what the pages show, so a stubbed capture is a different recording of the film, not a cleaner copy of the one it replaced; the seven headline scores moved by -0.0032 to +0.0034 when the references were swapped. _Source: [2026-11-09: sound samples in the archive](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-sound-samples-in-the-archive-make-replays-differ); [references swapped and repinned](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-references-swapped-and-repinned)._
* **`CTRY.FLM`'s `ssim` σ rose from 0.00030 to 0.0052.** The 0.00030 is section 2.2's pair (`004` against `005`, the demo's unpatched `PLAYONE` and shipped `.ALL`); on Patch 3, 27 of 104 CTRY paired pages differ. INTRO's 2026-10 figure (σ 1.7e-5) is for `ssim_structured` and is not directly comparable. The demo archive replays identically on either build under the current harness, so the build and harness are not the change; the demo `.ALL` shortens its sound samples and the `MAKEONE` archive carries them, though the two differ in other chunks as well.
* **Unpatched figures, for comparison** (2026-11-07 at `740c608`, unpatched builds, the five `VAULT` films only): σ 0.0154 / 0.0168 / 0.0094 / 0.0126 / 0.00038 for LAND / BALLOON / TRAINTNL / BOMB / LOCATION, with 56 / 76 / 65 / 168 / 731 identical pages of 89 / 100 / 99 / 273 / 732 paired. CTRY and INTRO were not measured on the unpatched build: their 2026-10-31 captures sat 3 ticks off the stride plan's goals and shared too few scored ticks with a recapture.
* **Two pages with one label may show different moments** (`[Hypothesis]`, one page checked: unpatched `vault-balloon` tick 265), against [`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.4; open question 15 there. None of the seven has an error-readout calibration (section 2.3).

_Source: [2026-11-08: recapture noise on Patch 3](../../work/2026-11/300_patch3-references/journal.md#2026-11-08-recapture-noise-on-patch-3); unpatched figures from [the issue 242 journal](../../work/2026-11/242_vault-parity-films/journal.md#2026-11-07-recapture-noise-and-build-floor)._

## 2.3 Error categories graded by a vision model

This readout names and grades the large differences. Each sheet shows capture, render, their luma difference and a close-up of the actors, and a grader gives it a grade 0–3 per category of [`error-categories.toml`](error-categories.toml) (adding one is one block there). It runs as `mise run parity-bench -- errors-make`, `errors-disputes` and `errors-score` by the [`error-readout`](../../.agents/skills/improving-render-parity/error-readout.md) procedure. What it established (`[Bounded Observation]`, 2026-10-31 to 2026-11-01, renders at `2461289`, `CTRY.FLM` and `INTRO.FLM`):

* **It finds missing or wrong objects, not misregistration.** In the first grading neither Haiku nor Sonnet invented an error on a control, both caught most removed aircraft, and neither came near the 4-of-6 bar on a 4-row shift or a 5-tick advance (0 or 1 of 6) at this scale; section 2.2's metrics remain the check for those.
* **Haiku grades as well as Sonnet**: the two agreed within one grade on 610 and 577 of 630 (sheet, category) cells.
* **A category's grade can fall when the error gets worse** (a removed aircraft moved from `aircraft-parts-missing` 3 to `aircraft-absent` 3), so detection compares each category, not the highest grade.
* **One Haiku pass is not reliable on `INTRO.FLM`.** Two of four single-pass calibrations failed, their graders marking identical control panels dirty. Each sheet is therefore graded twice by Haiku, and the sheets the passes dispute (some category 2 or more in one and not the other) go to one Sonnet grader. Two `INTRO.FLM` calibrations graded that way both passed; Sonnet graded half or more of each (21 and 30 of 42 sheets), at roughly twice the subagent cost of one Haiku pass.
* **Calibration rules.** A control's difference panel is black, which no real sheet's is, so the control count is reported but does not gate: a calibration passes on actors removed alone (5 of 6), a run with no actors-removed sheet is inconclusive, and an `INTRO.FLM` calibration is a lead until it passes twice in a row. Two Haiku passes over the same sheets moved a category's count of frames graded 2 or more by up to 3, so `compare` reports a category only when it moves by 4 or more (`min_change`).

_Source: [2026-10-31: error categories graded by a vision model](../../work/2026-11/distill-method/journal.md#2026-10-31-error-categories-graded-by-a-vision-model) and [2026-11-01: calibrating the error readout](../../work/2026-11/distill-method/journal.md#2026-11-01-calibrating-the-error-readout)._

## Ruled out

* **Pairing each reference tick with the nearest recapture tick to measure recapture noise** (2026-11-07). On `vault-ctry`, whose pinned capture sits off the current plan's ticks (§ 2.2.1 above), pairing within 5 ticks gave σ 0.0121 over 112 pairs, 85 of them 3 ticks apart: that measures how the score changes over a few ticks of motion, not recapture noise. _Source: [2026-11-07: recapture noise and build floor](../../work/2026-11/242_vault-parity-films/journal.md#2026-11-07-recapture-noise-and-build-floor)._
* **A forced-choice Haiku judge** (capture beside two renders, which is closer?): it scored 0.67 on the wrong-tick control, below the 0.9 bar (2026-10-31). _Source: [2026-10-31: the metric bench](../../work/2026-11/distill-method/journal.md#2026-10-31-the-metric-bench)._

## Open questions

None recorded here. Open lavapipe and GPU questions are in [`evidence-limits.md`](evidence-limits.md#open-questions).
