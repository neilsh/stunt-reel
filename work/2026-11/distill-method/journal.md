# Journal: distilling `method.md`

The dated rounds of [`method.md`](../../../research/parity/method.md) as of commit `5458030`, moved here verbatim when the note was distilled to current truth. Only relative link paths changed; a `§` or section number in the moved text names a section of the note as it stood at `5458030` (`git show 5458030:research/parity/method.md`). Each round's figures were first logged in the frozen [parity log](../../2026-10/parity-log/log.md) or the journal the text cites.

## 2026-10-21: a worst mover the mean hid

6. **Look at the worst movers before trusting the mean.** Open `compare_regressed_*.png` and `compare_improved_*.png` (`reference | before | after | |ref-before| | |ref-after|`). A mean can hide a regression or an improvement: the axis fix (`82ea965`) made the biplane upright like `PLAYONE` yet lowered mean SSIM 0.571 -> 0.567, because size and position error remain (`[Bounded Observation]`: worst frames about ticks 426-492, -0.02).

**Lives in** [`method.md`](../../../research/parity/method.md) § 1 (step 6).

## 2026-10-22: fade-compensated scoring, retired

From `36a7305` to `5bf6afe` the comparator also reported `ssim_compensated` (the render's luminance scaled by the fade level, later by the ratio of capture to render fade level) and headlined `mean_ssim_compensated`. That stood in for the fade before the renderer modelled it and was retired once it did; `--compare` reads such reports for their raw `ssim`.

* **Compensating a render that already models the fade.** Once the renderer applied var 14, scaling its luminance by the fade level counted the fade twice: compensated SSIM stayed at 0.617 while raw SSIM rose from 0.495 to 0.667. Compensation was retired in `8cabb2a` (section 2.1) (`[Bounded Observation]`).

**Lives in** [`method.md`](../../../research/parity/method.md) § 2.1 and § 4.1.

## 2026-10-22: recapture variance of four CTRY.FLM capture sets

* **Recapture variance (`[Bounded Observation]`, 2026-10-22, one machine, four capture sets of `CTRY.FLM`).** Sets `ctry`, `ctry_r2`, `ctry_r3`, `ctry_r4`; the render and scorer were identical for all four. (Figures below are from the lit render; after the unlit change the spread over the same four sets is 0.001, 0.766 to 0.767.)
  * *Our headline barely moves.* `mean_ssim_scored` over 114 frames is 0.689, 0.694, 0.695, 0.690 (spread 0.006); mean index agreement 0.390, 0.370, 0.363, 0.383 (spread 0.027). Quote SSIM to two decimals and treat differences under 0.01 between runs as noise only when the capture set differs; the same capture set and render give identical scores.
  * *Captures start at different ticks.* The first frame's `film_tick` is 9 or 10 and later frames drift by 0 to 2 ticks from run to run (mean absolute difference 0.4 to 1.7 ticks between sets), so two sets share only 19 to 72 of 114 film ticks. Always match on `film_tick`; never pair captures by ordinal across sets.
  * *The reference is not deterministic at a fixed tick.* Reference-vs-reference SSIM over the 114 scored ordinals is 0.938 to 0.990, and over frames sharing an exact `film_tick` 0.939 to 0.997 (index equality 0.95 to 0.99 above the button bar). `ctry` and `ctry_r3` (140-frame runs) sit at 0.94 against the others while `ctry_r2` against `ctry_r4` (124-frame runs) is 0.997. The cause is not identified (`[Hypothesis]`: state that is not the film clock, such as the cursor or wall-clock effects). Practical reading: a parity score above about 0.95 cannot be told apart from the capture's own noise, so the 0.88 and 0.90 gates are reachable but the ceiling is not 1.0.
  * Method: palette to Rec. 601 luminance, 320x200 stretched to 320x240, the comparator's 11x11 windows with stride 8, rows 0 to 221 only (above the button bar), windows with no variance on either side counted as 1.0.

**Lives in** [`method.md`](../../../research/parity/method.md) § 3.

## 2026-10-23: the sky mask becomes the 227 to 238 band

Tier `[Bounded Observation]`. Since 2026-10-23 (commits `b9a2b93`, `2fc0ca2`) the mask counts every index 227 to 238 as sky and reads the render's sky from its layer plane. Before, only the capture's single most common sky index (`sky_index`, 233 for `CTRY`) was sky, so the other bands counted as filled. SSIM and index agreement do not depend on the masks and did not move. Same renders (`main` at `19c0365`) scored at `f64b64b` (before, `--clear-index 233`) and `19c0365` (after):

| Film | Scored / matched | `mean_ssim_scored` | `mean_index_agreement_scored` | `mean_iou_scored` before / after | `mean_iou` (all) before / after |
|---|---|---|---|---|---|
| `CTRY.FLM` (sky index 233) | 114 / 140 | 0.771 | 0.475 | 0.856 / **0.978** | 0.826 / 0.978 |
| `INTRO.FLM` (229) | 209 / 213 | 0.676 | 0.481 | 0.802 / **0.919** | 0.803 / 0.921 |
| `COL3-2.FLM` (228) | 26 / 30 | 0.636 | 0.061 | 0.022 / 0.021 | 0.019 / 0.018 |

The old IoU mostly measured how much of the capture's sky lay outside its one modal band. The new value says the non-sky silhouette is close on `CTRY.FLM` and less so on `INTRO.FLM`, in line with SSIM. IoU figures recorded before this change are on the old scale and are not comparable with it. Golden reports for the scoring-call extraction are the `after_<film>/report.json` files under `build/scratch/rebase/` (not committed).

**Lives in** [`method.md`](../../../research/parity/method.md) § 2.0.

## 2026-10-30: the first plan-run capture of CTRY.FLM

* **Same film, new capture.** A full `CTRY.FLM` run on the new path (`captures/vault-ctry/frames/002`, 113 frames, stride 11 ticks) agrees with the DOSBox-X reference `001` on 0.951 of the first 60,000 page indices over the 37 film ticks the two share within one tick (8 exactly), with five frames under 0.90; that is inside the capture's own reference-versus-reference noise above. `references.toml` still names `001`: promoting `002` waits for a rescore that shows it is no worse. Captures now run at 45,000 cycles rather than `002`'s 7,000, so the page sits closer to its tick ([`../playone-exe/capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4); a reference to promote should be captured at the current profile.

**Lives in** [`method.md`](../../../research/parity/method.md) § 3.1.

## 2026-10-31: the metric bench

`[Bounded Observation]`, one render per film at `2461289`, references `vault-ctry/frames/004` and `vault-intro/frames/004`, recaptures `005`. `mise run parity-bench -- run --film <film>` (`python/stunt_reel/bench/`) plants 16 render faults (besides the unchanged control) in memory on every scored frame and scores ten candidate metrics against the reference. Its numpy SSIM reproduces the Rust `ssim` of `report.json` to within 1e-4 on every frame, and a synthetic fixture with golden values from the Rust scorer pins the two together (`tests/fixtures/parity/bench/`). The yardstick σ is the standard deviation, over the scored ticks both captures hold, of (metric against `004`) − (metric against `005`) with the unchanged render: per-frame variation no render change caused. A fault is detected when the metric falls by at least 3σ on average.

`CTRY.FLM`, 114 scored frames. Each cell is the mean fall in units of σ; positive is worse, so 3 or more is a detection, and a negative cell means the fault moved the render *closer* to the capture:

| Metric | σ | actors removed | x 1 | x 2 | x 4 | x 8 | y 1 | y 2 | y 4 | adv 1 | adv 3 | adv 5 | flat terrain | flicker 3 | flicker 10 | wrong tick | grey |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ssim` | 0.00030 | -15 | 1.1 | 1.9 | 4.6 | 9.4 | 22 | 44 | 82 | 5.9 | -1.7 | 5.3 | 30 | 3.3 | 30 | 562 | 43 |
| `ssim_structured` | 0.00269 | -1.0 | 0.8 | 1.3 | 2.6 | 4.6 | 4.3 | 8.1 | 12 | 1.0 | -1.2 | -1.5 | 5.2 | 0.1 | 1.1 | 37 | 12 |
| `grey_skill` | 0.00095 | -22 | 1.7 | 3.0 | 7.0 | 14 | 28 | 58 | 109 | 6.5 | -3.7 | 6.8 | 44 | 4.9 | 44 | 829 | 53 |
| `index_ocean` | 0.01361 | 0 | 19 | 18 | 17 | 15 | 17 | 17 | 17 | 11 | 13 | 12 | 0 | 0 | 0 | 22 | n/a |
| `index_terrain` | 0.00079 | 0 | -1.3 | -1.4 | -0.8 | 2.2 | 2.6 | 7.6 | 21 | -251 | -247 | -233 | 147 | 0 | 0 | 315 | n/a |
| `index_props` | 0.00019 | 0 | 33 | 46 | 78 | 140 | 193 | 319 | 492 | 1147 | 1183 | 1515 | 0 | 0 | 0 | 2833 | n/a |
| `index_actors` | 0.00049 | -241 | -48 | -77 | -116 | -180 | -34 | -60 | -116 | -16 | -42 | -61 | 0 | 0 | 0 | -5.1 | n/a |
| `edge_f` | 0.00112 | 34 | -0.2 | -0.1 | 2.2 | 4.6 | 20 | 41 | 90 | 0.4 | -6.5 | -6.2 | 38 | 0.0 | 0.3 | 261 | 420 |
| `ssim_actors` | 0.00159 | -113 | -6.1 | -14 | -25 | -45 | 10 | 20 | 21 | -1.0 | -1.3 | -0.8 | 18 | 0.1 | 1.1 | -46 | -136 |
| `ssim_props` | 0.00024 | -13 | 3.7 | 1.5 | -0.2 | -33 | 67 | 135 | 213 | 28 | -7.8 | 52 | 53 | 3.3 | 35 | 420 | -36 |

Reading:

* **No metric passes**, because some faults improve the render; a metric cannot detect a fault that moves the render towards the capture. Removing the actors raises `ssim` by 0.0044 (15σ) and the actor-window SSIM by 113σ, and the differential score on the windows the removal touches is +0.18: our actors match the capture worse than the ground behind them. Shifting the render right raises `ssim_actors` at every magnitude and `ssim_props` at 8 columns, which suggests drawn objects sit left of where `PLAYONE` puts them; not yet measured directly.
* **Smallest magnitude detected** (horizontal shift / vertical shift / advance / flicker): `ssim` 4 / 1 / 1 / 3; `grey_skill` 4 / 1 / 1 / 3; `ssim_props` 1 / 1 / 1 / 3; `ssim_structured` 8 / 1 / none / none; `edge_f` 8 / 1 / none / none. A 3-tick advance is not detected by any SSIM metric while 1 and 5 are. "Smallest magnitude detected" is not monotone: `ssim_props` detects a 1-column shift (3.7σ) but misses 2, 4 and 8, so read the row of the table, not the minimum.
* **Index agreement** is the most sensitive per layer but reads layers differently: `index_terrain` *improves* by about 240σ under any advance, which no other metric shows; unexplained.
* **Differential check** (section 2's verdict, numpy): the mean Δ of the unchanged render as *before* and the fault as *after* is negative for every fault except actors removed (+0.180) and advance 3 (+0.0023), the same two that improve the whole-frame score.
* **Build floor:** a second build of the same revision (`mise run build-at`) renders all 1,337 ticks with no `.idx` or luma pixel different, so the verdict needs no build-noise allowance.
* **`INTRO.FLM`**, 278 scored frames: same picture (removing actors improves `ssim` by 11σ, no metric passes). Its two captures agree so closely that σ is 1.7e-5 for `ssim_structured` and 1.3e-6 for `ssim_props`, so σ units there are inflated and not comparable with `CTRY.FLM`; `index_ocean` is `n/a` throughout.
* **Haiku judge** (spec experiment): 310 composites (capture | A | B, both orders, 10 control pairs) over five Haiku subagents; one returned no answers, declining to guess. On the 248 answered, accuracy per fault ran from 0.24 (flat terrain) to 0.71 (1-column shift) and the wrong-tick control scored 0.67, below the 0.9 bar, so the arm is dropped. Control pairs read A 56% of the time. The judges reported most pairs as indistinguishable at 320x240.

**Lives in** [`method.md`](../../../research/parity/method.md) § 2.2.

## 2026-10-31: error categories graded by a vision model

`[Bounded Observation]`, the same renders and captures as section 2.2. Where the forced-choice judge asked which of two near-identical renders was closer, this asks a model to name and grade the large differences. Each sheet shows capture and render side by side at 2x (the button bar painted grey), their absolute luma difference, and a close-up of the actors' bounding box. Frames: 12 per film spread over the scored ticks below any fade, `CTRY.FLM` ticks 4–499 and `INTRO.FLM` 1009–2687 (its first 20 seconds skipped).

* **Discovery.** Haiku, Sonnet and Opus each listed every difference on the 12 `CTRY.FLM` sheets and proposed categories; all three named the aircraft drawn as bare wing shapes, without fuselage, propeller or wheels, in 12 of 12 frames, and the missing shadow in the same 5. Merged, that gave ten categories. A second pass on `INTRO.FLM`, given the ten, added five: an aircraft not drawn at all (10–11 of 12 frames), a shadow of the wrong shape, missing ground actors, the wrong terrain surface, and a missing explosion. Haiku found what the larger models found but filed new kinds under existing names. The categories are [`error-categories.toml`](../../../research/parity/error-categories.toml); adding one is one block there.
* **Grading.** Per film, 42 sheets in shuffled order: the 12 real frames, 12 controls (recapture `005` in the render's place) and 18 planted faults (actors removed, a 4-row shift, a 5-tick advance, 6 frames each). Each sheet gets a grade 0–3 per category. A planted sheet is detected when any category that fault should raise grades higher than on the same frame unplanted:

| Check | `CTRY.FLM` Haiku | Sonnet | `INTRO.FLM` Haiku | Sonnet | Bar |
|---|---|---|---|---|---|
| Controls with every grade ≤ 1 | 12/12 | 12/12 | 12/12 | 12/12 | 10/12 |
| Actors removed | 6/6 | 5/6 | 5/6 | 5/6 | 5/6 |
| 4-row shift | 0/6 | 0/6 | 0/6 | 0/6 | 4/6 |
| 5-tick advance | 0/6 | 1/6 | 0/6 | 1/6 | 4/6 |

Reading:

* **Haiku grades as well as Sonnet**, so Haiku does the grading. The two agree within one grade on 610 of 630 (sheet, category) cells for `CTRY.FLM` and 577 of 630 for `INTRO.FLM`.
* **The grades find missing or wrong objects, not misregistration.** Neither model invents errors on a control or misses a removed aircraft, and neither sees a 4-row shift or a 5-tick advance at this scale; section 2.2's metrics remain the check for those.
* **A category's grade can fall when the error gets worse.** With the aircraft removed, the graders moved `aircraft-parts-missing=3` to `aircraft-absent=3`; taking the highest grade among the matching categories hid that, so detection compares each category.
* **What the render gets wrong, real frames:** `CTRY.FLM`, aircraft parts missing in 11–12 of 12 and its shape broken in 8–10, the shadow, sea band and scenery in 3–5 each; `INTRO.FLM`, aircraft absent in 7–10, shadow shape wrong in 7, ground actors missing in 6, scenery (the fence) in 3–7.

**Lives in** [`method.md`](../../../research/parity/method.md) § 2.3.

## 2026-10-31: per-second scoring of a video capture

A prototype of `stuntreel parity` (commit `d80e29e`, kept on branch `feat/video-parity-scorer`, not merged) scored a whole-film video capture ([`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.6) per film second. Each second contributed three samples, at film-second offsets 0, 17 and 33 ticks. Each sample searched render ticks −8 to +2 around its own tick for the best SSIM, the median of those local offsets became one film-wide offset, and every sample was then rescored at that offset. It was validated on 2026-10-31 and not adopted (`[Bounded Observation]`, one render, `CTRY.FLM` and `INTRO.FLM`):

* **It is fast and agrees on the headline.** Scoring takes 2.0 s for `CTRY.FLM` and 4.8 s for `INTRO.FLM`. The `CTRY.FLM` mean of 0.782 over 26 seconds matches the per-frame 0.781 against `004`.
* **Local offsets are noise.** At SSIM near 0.75 the score varies little across the window: the best offset beats the film offset by a median 0.009 and at the 90th percentile 0.029. The winning offset wanders over the whole window, 20 of 81 `CTRY.FLM` samples sit on a bound (`edge`) and 23 of 27 seconds are flagged `slip`. The `slip` and `edge` flags carry no information at this parity level.
* **The film offset is unstable, so unaltered seconds move.** Changing six seconds of the render moved the film offset from −1 to −2 ticks, and unaltered seconds then moved by up to 0.071 (second 26, a fade). The per-frame scorer, which matches ticks exactly, moved them by 0.000.
* **Planted errors do not stand out, in either scorer.** In a copy of the `CTRY.FLM` render, three pairs of seconds were altered:
  * Actors painted over with the background (seconds 5–6): per second +0.012 and +0.016, per frame +0.015.
  * Every pixel shifted 4 columns (10–11): per second −0.003 and +0.002, per frame +0.000.
  * Each tick replaced by the picture 5 ticks later (15–16): per second +0.004 and −0.021, per frame −0.024.

  So against this render SSIM is blind to a 4-pixel shift and rewards removing actors. That is a limit of the metric at about 0.75, not of the video path.
* **It finds what frame captures skip.** `INTRO.FLM` seconds 0–14 score about 0.0002. The game shows a static black title card, "DISNEY INTRO REEL", while the render draws the sky. The frame capture keeps only changed pages, so it holds none of these frames.

What would have to change before trying again: a significance margin on `slip` (best minus film-offset SSIM above the noise, about 0.03), a film offset fixed by a run over unaltered seconds or from the log rather than refitted per render, and a metric that registers geometric error at this parity level.

**Lives in** [`method.md`](../../../research/parity/method.md) § 4.4.

## 2026-11-01: calibrating the error readout

The readout now runs as `mise run parity-bench -- errors-make` and `errors-score`: the first writes the sheets and the grading brief, one Haiku subagent writes the grades, and the second writes `readout.json`, compares it with an earlier one and, on a calibrating run, checks controls and planted faults against the bars above. The procedure is the "Error readout" section of the [`improving-render-parity`](../../../.agents/skills/improving-render-parity/SKILL.md) skill. Its first calibration (2026-11-01, same renders) passed on both films: controls clean on 12/12 (`CTRY.FLM`) and 10/12 (`INTRO.FLM`), actors removed caught on 5/6 and 6/6, the shift on 0/6 and the advance on 2/6 and 0/6; two of those eight checks moved two sheets from the probe's Haiku column, so a check that moves by one or two between calibrations is noise. Haiku grading the same 12 real sheets twice agreed within one grade on 174 of 180 cells (`CTRY.FLM`, ticks 4–983) and 171 of 180 (`INTRO.FLM`, 1009–3116), and a category's count of frames graded 2 or more moved by up to 3 between the two passes, so `compare` reports a category only when its count moves by 4 or more (`min_change`). A second calibration of `INTRO.FLM` on the same 42 sheets, by a fresh Haiku grader, failed: controls clean 9/12, actors removed 4/6, shift 1/6, advance 1/6. The control sheets graded dirty were different ones each time (ticks 1009 and 2687 first; 1108, 1317 and 2068 the second time), and on every one the two panels are identical and the difference panel black: on four of the five Haiku graded `aircraft-absent` 3, three of them with the aircraft plainly drawn and one (2068) with no aircraft in either panel. So `aircraft-absent` now requires an aircraft in the capture, and the brief says a black difference panel means every grade is 0. Two more calibrations of `INTRO.FLM` under that brief split: one passed (controls 10/12, actors removed 5/6, shift 0/6, advance 0/6), one failed (9/12, 3/6, 2/6, 1/6), the failing grader still marking identical panels dirty (ticks 1009 and 1416). One Haiku pass therefore misreads about one `INTRO.FLM` control in four whatever the brief says. A control's recapture is pixel-identical to the reference, so its difference panel is black, which no real sheet's is; the control count is therefore reported but no longer gates a calibration, which now passes on actors removed alone (5 of 6). A run with no actors-removed sheet is reported inconclusive, not passed; a planted sheet counts as caught only when its paired real sheet was graded; the scorer counts only the sheets `errors-make` wrote; and the render check hashes each graded tick's PNG, index and layer planes. On that bar the two runs still split (5/6 and 3/6), so a calibration of `INTRO.FLM` is a lead until it passes twice in a row. The readout therefore grades each sheet twice with Haiku (`brief.md`, `brief-2.md`), and `errors-disputes` sends the sheets the two passes disagree on, where some category is 2 or more in one pass and not the other, to one Sonnet grader (`brief-tiebreak.md`); `errors-score` takes those sheets from Sonnet and the rest from the first pass. Two `INTRO.FLM` calibrations graded that way both passed: actors removed 6/6 and 5/6, controls 12/12 and 12/12, shift 1/6 and 0/6, advance 1/6 and 2/6. The passes disagreed on 21 and 30 of 42 sheets: with 18 categories one category crossing 2 is enough, so Sonnet grades half or more of a run, at roughly twice the subagent cost of one Haiku pass.

**Lives in** [`method.md`](../../../research/parity/method.md) § 2.3.

## 2026-11-06: render start-up, parallel runs and the reference's archive

* **Render start-up is the GPU instance (`[Bounded Observation]`, 2026-11-06).** A headless render on a Windows machine with an RTX 4070 spends about 9 ms building the scene and about 1.9 s creating its wgpu instance with every backend: about 0.95 s in the Vulkan loader, then 0.95 s enumerating DX12 adapters before picking the same Vulkan adapter. Opening the device takes about 30 ms. The offscreen path now tries a Vulkan-only instance first (`OFFSCREEN_BACKENDS` in `renderer.rs`), and goes on to every backend when Vulkan finds no adapter or only a CPU one, which it keeps if no backend has hardware. A one-tick CTRY render then takes a median 1.39 s against 3.15 s for the previous build (six alternating runs each), and a full CTRY render is byte-identical either way. A GL-only instance starts in 0.26 s but picks the integrated AMD GPU, so it was ruled out.
* **Parallel parity runs are GPU-bound (`[Bounded Observation]`, 2026-11-06, `48f5d49`).** On a machine with 16 threads, 31 GiB of RAM and an RTX 4070 Laptop GPU (8 GiB), headless renders run on the GPU (the `HighPerformance` adapter) and keep 0.4 to 0.65 of a core busy each. A render costs about 300 MiB of RAM and 200 MiB of VRAM whatever the film's length (`BOMB.FLM` and `LOCATION.FLM` as much as CTRY), and a score about 35 MiB. Render-and-score pairs per second, CTRY and INTRO alternating: 0.19–0.25 at one job, 0.80–0.86 at 8 (2.1 GiB of RAM, 1.8 GiB of VRAM), 1.0–1.16 at 16 (4.1 GiB, 3.2 GiB), and a noisy 0.83–1.30 at 32 with the GPU saturated (6.4 GiB of VRAM). `mise run parity` and `mise run sweep` therefore default `--jobs` to 8; `--jobs 1` and `--jobs 8` print identical scores.
* **The render does not play the reference's archive (`[Bounded Observation]`, 2026-11-06, `48f5d49`).** `reference_job` takes the first non-duplicate copy of a slug in sorted path order (`batch_films.find`) and its sibling `.ALL` (`all_archive.resolve_all`). For both references that copy is `siarchive/Films/NewPLAY/Vault/`, whose `CTRY.ALL` (`3e93b739…`) and `INTRO.ALL` (`412ac365…`) differ from the demo archives the captures recorded in `meta.json` `all_sha256` (`9de1bc1e…`, `27935a36…`). Renders from either archive score the same to four decimals (CTRY 0.8725 / IoU 0.9897 over 114 of 121 frames scored, INTRO 0.8273 / 0.9856 over 209 of 346), so no recorded score is affected. Nothing checks the render's archive against the capture's, and `references.archive_makeone_build` calls a `.ALL` shipped under `siarchive/` `unknown`, which `require_builds` refuses for any film whose row names a `makeone`; `SPLANES.FLM` has no other copy, so it cannot be captured against a row until the archive is pinned by hash. Closed by [ADR 0037](../../../docs/adr/0037-a-reference-pins-its-archive.md): each row pins `all_sha256`, the render and `capture-ref` resolve the archive by it, and `parity` refuses a capture that recorded another; `[ctry]` and `[intro]` now render the demo archives, at the same scores.

**Lives in** [`method.md`](../../../research/parity/method.md) § 3.

## 2026-11-07: recapture noise, the build floor and lavapipe

`[Bounded Observation]`, 2026-11-07, renders and scores at `740c608`, one recapture per film on the build its `references.toml` row names (unpatched), stored in `<data root>/bench/<slug>/recapture/` (`mise run capture-ref -- --out`). σ is the bench's whole-frame `ssim` σ of section 2.2, over the scored ticks the reference and the recapture both hold. Identical pages counts paired ticks whose index pages match pixel for pixel; the percentiles are of the per-frame |Δ| of `ssim` between reference and recapture against the one render.

| Film | Scored | Paired | Identical pages | σ (`ssim`) | Median \|Δ\| | p90 | p95 | Largest \|Δ\| |
|---|---|---|---|---|---|---|---|---|
| `vault-ctry` | 114 | 7 | — | not measured | — | — | — | — |
| `vault-intro` | 209 | 11 | — | not measured | — | — | — | — |
| `vault-land` | 97 | 89 | 56 | 0.0154 | 0 | 0.0229 | 0.0275 | 0.089 |
| `vault-balloon` | 107 | 100 | 76 | 0.0168 | 0 | 0.0022 | 0.0251 | 0.137 |
| `vault-traintnl` | 112 | 99 | 65 | 0.0094 | 0 | 0.0049 | 0.0144 | 0.080 |
| `vault-bomb` | 316 | 273 | 168 | 0.0126 | 0 | 0.0043 | 0.0185 | 0.111 |
| `vault-location` | 732 | 732 | 731 | 0.00038 | 0 | 0 | 0 | 0.010 |

Reading:

* **CTRY and INTRO cannot be measured against their pinned captures.** Those were captured on 2026-10-31; they start 3 ticks after the window goals of the stride plan ([`plan.py`](../../../python/stunt_reel/tac/plan.py) `choose_windows`: goals 1, 12, 23, ...), at ticks 4, 15, 26, ..., and drift off them later (90 of 121 CTRY frames and 86 of 346 INTRO frames sit at +3). The `VAULT` captures and recaptures made since land on the goal or up to 3 ticks after it, mostly on it (12, 23, 34, ...). Their recaptures share 7 and 11 scored ticks with the reference, below the bench's 20; pairing by nearest tick instead is ruled out (Ruled out, below). CTRY keeps the 2026-10 figure of section 2.2 (0.00030, captures `004` against `005`). INTRO's row has no `noise_sigma`: its 2026-10 bench σ (section 2.2) was never adopted as one. Both will be measured on their Patch 3 recaptures ([#300](https://github.com/neilsh/stunt-reel/issues/300)).
* **The noise is heavy-tailed.** On all five measured films the median |Δ| is 0: most paired pages are identical. σ comes from the minority of pages that differ (24 to 39% of paired pages on the four short films), some by thousands of pixels (`vault-balloon` tick 265: 27,960 pixels, Δ +0.137; `vault-bomb` tick 2971: 14,437 pixels), so it overstates the noise of a typical frame and understates the worst. As `noise_sigma`, σ would make `--noise-sigma` call a frame whose Δ on the touched windows is below about 0.01 to 0.017 within noise on the four short `VAULT` films, which the identical pages argue is mostly not noise (`[Supported Inference]`), so their rows carry none. `vault-location` is as heavy-tailed (one differing page), but its σ is small enough that `--noise-sigma` would call only a Δ below 0.00038 within noise (no verdict has been run with it), so its row carries it. How the verdict should treat this noise is [#305](https://github.com/neilsh/stunt-reel/issues/305).
* **Two pages with one label may show different moments** (`[Hypothesis]`, one page checked). Scored by index agreement against the render at nearby ticks, `vault-balloon`'s reference page at tick 265 agrees best with the render at tick 264 (0.580) and the recapture's page at tick 265 with tick 267 (0.530). That would put the two pages about 3 ticks apart in content despite the shared label, though both agreement curves have more than one peak (the reference also reads 0.409 at 267), against [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4, which says jitter moves a sample but never mislabels it. `vault-land` tick 551 (7,767 pixels) shows no such clear peak. Untested on the other outliers; open question 15 there.
* **`vault-location` replays nearly bit for bit**: 731 of 732 pages identical, the one exception 259 pixels at tick 8009. Why it alone does is open question 16 of [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md).
* **No error-readout calibration.** The calibrating error readout (section 2.3) was not run on these five films, for its subagent cost, so none of them has a calibration.

_Source: [2026-11-07: recapture noise and build floor](../242_vault-parity-films/journal.md#2026-11-07-recapture-noise-and-build-floor)._

* **The 0.002 adoption floor is a policy bound, not a noise model (`[Bounded Observation]`, 2026-11-07, `740c608`).** Three binaries of one revision, the gate's release build and two `mise run build-at` builds from an emptied `target/build-at` (three different SHA-256 hashes), rendered all seven reference films to byte-identical render trees (`frames.zst`, `layers.zst`, `palettes.zst`, previews and `render.json`) and so scored them identically, as the bench's build floor (§ 2.2) found on `CTRY.FLM`: on this machine and GPU (RTX 4070), builds of one revision added no spread. The 2026-10 spread of 0.7706 to 0.7718 on `CTRY.FLM` ([`probes.md`](../../../research/parity/probes.md) § 5) has not recurred; its cause is unknown. The floor is a policy choice, not a statistical confidence interval; recapture noise (§ 2.2.1) is the larger term. _Source: [2026-11-07: recapture noise and build floor](../242_vault-parity-films/journal.md#2026-11-07-recapture-noise-and-build-floor)._

* **Lavapipe does not score like a GPU (`[Bounded Observation]`, 2026-11-07, `aa76d1e`).** The same commit scored CTRY 0.6446 / INTRO 0.6040 `mean_ssim_scored` on Mesa lavapipe in a cloud session ([ADR 0039](../../../docs/adr/0039-cloud-sessions-fetch-pinned-game-archives.md)) and CTRY 0.8725 / INTRO 0.8273 on the RTX 4070 machine, the logged figures, with identical IoU (0.9897, 0.9856) and scored counts (114, 209). Index agreement fell to 0.663 and 0.612 against 0.890 and 0.830, so lavapipe writes other palette indices inside the same silhouettes; the loss is in the props class. The renderer commits after `48f5d49` keep the GPU score. The cause is Mesa's software clipper, not a renderer commit ([`lavapipe.md`](../../../research/parity/lavapipe.md)), and the guard in `fragment_index` leaves lavapipe less than the 0.002 adoption margin from these GPU figures (a policy bound, not a noise model; see the adoption-floor bullet above), so whether the two backends are equivalent is still open. Until a GPU run confirms the guard leaves GPU output unchanged ([#265](https://github.com/neilsh/stunt-reel/issues/265)), an adoption decision still needs a GPU run.

* **Lavapipe interpolated the `linear` shade varying to NaN on near ground polygons (`[Supported Inference]`, 2026-11-07, fixed by a guard in `fragment_index`).** Mesa's software clipper divides 0 by 0 when it weights a `noperspective` varying on some clipped edges, so large ground decals near the eye drew palette index 0. With the guard, lavapipe scores less than the 0.002 adoption margin from the GPU; backend equivalence is still open. Mechanism, evidence, candidate fixes and open questions: [`lavapipe.md`](../../../research/parity/lavapipe.md).

**Lives in** [`method.md`](../../../research/parity/method.md) § 2.2.1 and § 3.
