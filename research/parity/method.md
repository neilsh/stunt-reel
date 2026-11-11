---
summary: "Defines the parity loop that judges a render change against PLAYONE.EXE: capture, render, SSIM and IoU scoring with the fade floor, compare verdicts, dead ends and how to read the legacy parity log."
---

# Parity Method: the Fidelity Loop

How a rendering change is judged against `PLAYONE.EXE`. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md) (parity, captured frame, film clock); capture mechanics are in [`../playone-exe/capture.md`](../playone-exe/capture.md); the commands are [`docs/howto/score-a-render-change.md`](../../docs/howto/score-a-render-change.md); each film's expected scores are its expected tables in [`references.toml`](references.toml); dated results are journal entries (step 7) or, before them, rows of the parity log (section 5). Metric behaviour and recapture noise are in [`metric-bench.md`](metric-bench.md); what a score cannot yet prove is in [`evidence-limits.md`](evidence-limits.md).

## 1. The loop

0. **Baseline and expected scores.** `references.toml` names, by film slug and content hash, the capture under `<data root>/captures/<slug>/frames` each film is scored against. `mise run parity` prints, under each film's summary line, its expected line: the expected score of the film's table for the renderer class the render was drawn on (`[<film>.expected.gpu]` or `.lavapipe`) with the SSIM delta, or what is missing (no adapter in the report, or no table for the class yet); the adoption noise note comes last. The line judges drift, a delta beyond the film's `noise_sigma` or, on a row without one, beyond `1e-7`, only when the report names an adapter whose name matches the table's, a frame scored, the run scored its own render (not `--retime` or `--reuse`), the git tree hash of the checkout's `crates/` (tracked files as they are on disk and untracked ones git does not ignore) is the table's `crates`, the film's pins (`sha256`, `all_sha256`) are the ones the table records; otherwise it says why. The check reads the checkout, not the binary (with `--no-build` or `--no-render` it assumes the render came from the checkout), and assumes builds of the same `crates/` render identically; `noise_sigma` is the recapture noise borrowed as a tolerance, not a measured bound on build-to-build variation ([section 3](evidence-limits.md#3-what-is-not-yet-evidence), adoption floor). The table pins a tree, not a commit, because PRs land as new commits (squash or rebase): a branch commit never reaches `main`, but its `crates/` tree does when no other `crates/` change lands first, so a clone without the branch commit still compares (#308's branch commit `d01a3c4f` and its squash `fa8b9a0` share the `crates/` tree `641cffd`). `commit`, the commit measured, is optional and only says where; nothing compares it.
1. **Capture on the film clock.** Each captured frame is tagged in `meta.json` with `film_tick` (the film clock: the tick the frame shows) and `global_tick`. Matching uses the film clock because a captured frame is a distinct rendered page grabbed at retrace, so capture ordinals do not map to ticks (`[Supported Inference]`; § 4.2).
2. **Keep the previous render** to compare against (`build/parity/previous/<film>`, or a pinned `_base` tree).
3. **Render every captured tick** into a render store ([ADR 0027](../../docs/adr/0027-renders-store-planes-in-per-second-zstd-chunks.md)). It holds each tick's index plane, layer plane and palette, and its picture is its palette over its index plane (unlit palette index; layer ids 0 none, 1 ocean, 2 terrain, 3 props, 16+n for actor draw n of the frame).
4. **Score** (section 2). The masks come from index planes, not colours: a capture pixel is sky when its index is in the sky bands 227..=238 (`sky_indices`; [`palette-and-shading.md`](../formats/concepts/palette-and-shading.md)), and a render pixel is sky where its stored layer plane is empty. `render` still clears to 233 (`CTRY`'s sky) when given an `.ALL`, which does not affect the score. `report.json` also carries `mean_index_agreement_scored` and `mean_loss_by_class_scored`, the SSIM loss split by layer: read it as where the loss is, not what is wrong.
5. **Compare.** `--compare` joins two reports by `film_tick`. The basis is `scored` when both reports carry `scored` (SSIM over frames scored in both runs) and `all` otherwise (SSIM over all common frames), recorded on the first `[compare]` line and as `"basis"` in `compare.json`. With `--compare-test` it also gives a verdict on the windows the change touched. A frame is changed where its `.idx` or luma differs; Δ is the capture SSIM of *after* minus *before* over the 11x11 windows holding a changed pixel, so unchanged flat ground drops out. `--noise-sigma <σ>` (the film's `noise_sigma`) buckets |Δ| < σ as within noise; without it only a Δ of exactly 0 is. No reference row carries a σ since its recaptures agreed page for page ([§ 2.2.1](metric-bench.md#221-recapture-noise-of-the-reference-films)), so the caveats below apply only to a film given one. That σ is the recapture noise of the *whole-frame* SSIM ([§ 2.2](metric-bench.md#22-the-metric-bench), [§ 2.2.1](metric-bench.md#221-recapture-noise-of-the-reference-films)), not of Δ, which averages a few touched windows and so should vary at least as much: σ is a lower bound for Δ's spread (not measured), and on a heavy-tailed film one σ misdescribes a typical frame ([#305](https://github.com/neilsh/stunt-reel/issues/305)). "Within noise" is therefore conservative, and a frame called closer or further may still be noise. The verdict judges every matched frame, including the ones the fade floor leaves unscored (§ 2.1), so it can move on faded frames the headline mean ignores. `compare.json` gains `"verdict"`, and the worst-mover sheets follow Δ. `--build-floor <N>` labels frames with at most N changed pixels as build noise; 0 suffices where builds of one revision have been measured, since they rendered identically (§ 2.2, § 3).
6. **Look at the worst movers before trusting the mean.** A mean can hide a regression or an improvement: the axis fix (`82ea965`) made the biplane upright like `PLAYONE` yet lowered mean SSIM 0.571 -> 0.567, because size and position error remain (`[Bounded Observation]`). _Source: [2026-10-21: a worst mover the mean hid](../../work/2026-11/distill-method/journal.md#2026-10-21-a-worst-mover-the-mean-hid)._ Diagnose one discrepancy with the probes in [`probes.md`](probes.md).
7. **Write a journal entry** in the work item's `journal.md` ([`work/README.md`](../../work/README.md#journal-entries)): commit hash, matched frames, means, the reason for any movement, and the verdict. An adopted change updates each reference film's expected table for the class it measured (step 0).

### 1.1 Extracting frames and video

Tier `[Established]`. A render samples the authored 50 Hz timeline and stores each tick under its own number, which is the film clock `stuntreel parity` looks up. Samples that fall off whole ticks (`--sample-count`, `--video`) are not parity inputs. A `--video` export resamples the timeline at `--fps` with 4:3 correction (320x240, `[I6]`), interpolating between slice keyframes, trimmed to the authored span. Flags: [how-to § 4](../../docs/howto/score-a-render-change.md#4-render-by-hand). _Source: ticket `T11` in the frozen [`TEAM_SHEET.md`](../../work/2026-10/team-sheet/TEAM_SHEET.md)._

### 1.2 Scoring another captured film

Render the whole captured span at 320x200 into a render store, then score it ([how-to § 4 and § 5](../../docs/howto/score-a-render-change.md#5-score-and-compare-by-hand)); a tick outside the rendered range counts as missing on one side.

### 1.3 Fields of `report.json` and `compare.json`

Each documented key of both files, its JSON type and its meaning, checked against reports written from synthetic fixtures: [`report-fields.md`](report-fields.md).

## 2. Scoring in one paragraph

Both sides become Rec. 601 luminance, are stretched 320x200 -> 320x240, and are scored with the shared 11x11-window SSIM (`compute_frame_ssim`, window 11, stride 8; `[I6]`: >= 0.88 initial, >= 0.90 sign-off; `[Established]`). IoU compares each side's non-sky mask and measures framing independent of shading. Neither is a perceptual judgement. Windows touching the **UI overlay** are left out: capture rows 185 and below, and index 255 (the cursor) on ticks whose render record says the film shows no credits (`credits` in `render.json`, from the film's schedule, not the render's pixels), so credits ink is scored wherever the film shows it. A frame that expects credits the render did not draw is still scored on the ink and counted in `credits_missing_frames`.

### 2.0 Sky mask and IoU scale

Tier `[Bounded Observation]`. The mask counts every index 227 to 238 as sky and reads the render's sky from its layer plane (commits `b9a2b93`, `2fc0ca2`, 2026-10-23). The mask before it counted only the capture's single most common sky index as sky, so it mostly measured how much of the capture's sky lay outside that one band: on the same renders `mean_iou_scored` went from 0.856 to 0.978 on `CTRY.FLM` and from 0.802 to 0.919 on `INTRO.FLM`, while SSIM and index agreement, which do not read the masks, did not move. IoU figures recorded before that change are on the old scale and are not comparable with it. _Source: [2026-10-23: the sky mask becomes the 227 to 238 band](../../work/2026-11/distill-method/journal.md#2026-10-23-the-sky-mask-becomes-the-227-to-238-band)._

### 2.1 Fade floor

`PLAYONE.EXE` fades its palette linearly to black near the end of `CTRY.FLM`, from about tick 990 to 1337. For each captured frame, the **fade level** is the median, over a fixed index set, of (captured palette entry R+G+B) / (static Mode 13h palette entry R+G+B). The index set is the indices present in the first captured frame whose static R+G+B is above 60. A frame with no fade reads about 1.0 (1.011 for `CTRY`, from DAC 6->8-bit expansion). Cursor and button-bar entries do not fade; they are a minority of the set, so the median ignores them.

The renderer applies the same fade from the film's palette variables, so renders are scored as drawn. Frames below `--min-fade-level` (default 0.25) are computed and reported but not scored, because SSIM of near-black frames says little. The headline is `mean_ssim_scored` with its scored-frame count; `mean_ssim`, `min_ssim` and `mean_iou` cover all matched frames.

The floor tests the authored brightness (var 14), not the captured fade level, which is reported beside it as a cross-check. That keeps night frames scored: the night is var 13 ([`palette-fade.md` § 3.1](../playone-exe/palette-fade.md#31-night-term-var-13)), which the floor does not read. `COL3-2.FLM` scores 26 of 30 frames ([`col3-2-studio.md`](col3-2-studio.md#1-col3-2flm-the-studio-interior)); the 4 excluded are at ticks 168–201, where var 14 is 0 ([`palette-fade.md` § 5.1](../playone-exe/palette-fade.md#51-night-capture-col3-2flm)). `TOD.FLM` keys var 14 only at tick 0 (32768) and tick 1416 (0) while var 13 changes through the film (35544 at tick 0, 5506 at its last key, tick 1359; `mise run flm-events`, `[Bounded Observation]`), so by the floor's rule its frames stay scored until its last slice; no `TOD.FLM` scoring run confirms it yet.

The comparator reads var 14 from the palette controls `render.json` records for every tick. Each tick also records `credits`, whether the film shows credits there (`0x99` until `0x98`); on such a tick the UI-overlay mask keeps capture index 255 as credits ink instead of masking it as the cursor, so a render that drops its credits scores the loss. The field is required from `render.json` schema 3; an older render is refused with the re-render message. The render also records the `adapter` its frames were drawn on (`name` as its driver reports it, `class` `hardware` or `cpu`), which `report.json` copies; the field is optional, so a schema-3 render without it still scores, with a null `adapter`. `--compare` reads reports of the retired fade-compensated scoring (§ 4.1) for their raw `ssim`.

## 4. Dead ends

Approaches that were tried and dropped. Each is recorded so it is not tried again without new evidence.

### 4.1 Fade scoring

* **Fade level from the frame's own indices.** On faded frames the only entries bright enough to qualify are the cursor and button-bar entries 240–255, which do not fade, so the median reads about 1.0; the set is fixed from the first captured frame instead (`[Bounded Observation]`).
* **Compensating a render's luminance by the fade level.** Once the renderer applied var 14 this counted the fade twice; retired in `8cabb2a` (`[Bounded Observation]`). _Source: [2026-10-22: fade-compensated scoring, retired](../../work/2026-11/distill-method/journal.md#2026-10-22-fade-compensated-scoring-retired)._
* **Scoring the black tail.** Without a floor, near-black frames score high against each other (about 0.92), which inflates the mean without saying anything about the scene; the `CTRY.FLM` tail at ticks 1337–1342 has 6 distinct RGB values (59,929 black pixels plus 2,480 of (130,105,101)) and mean luminance 7.1. Hence `--min-fade-level` (`[Bounded Observation]`).
* **Fitting the fade ramp to the captures.** Fitting brightness to the frames then scored is circular; the ramp comes from the film's `var_set` keys ([`palette-fade.md` § 5](../playone-exe/palette-fade.md)).
* **The captured fade level as the floor.** It misreads a night film as faded: about 0.24 on most `COL3-2.FLM` frames, which excluded 29 of 30 until `7b8e536`; the floor tests the authored var 14 (`[Bounded Observation]`).

### 4.2 Clock matching

* **Capture order or a fixed offset.** Matching by capture ordinal, or ordinal plus a constant (`TICK_TO_FRAME_OFFSET = 1`, since removed), fails because ordinals are distinct pages, not ticks.
* **The global clock.** `global_tick - film_tick` is 2 or 3 in every frame of the `CTRY.FLM` and `COL3-2.FLM` sets (122 of 140 and 30 of 30) except the 18 `CTRY.FLM` end-hold frames, where the film clock stops at 1342 and the global clock runs on to 7140 (`[Bounded Observation]`), so no offset can stand in for the film clock.
* **The "6-tick lag".** A ramp that looked 6–11 ticks late was the slice-start reading of `var_set` keys, not a delay in `PLAYONE` (section 3, *Fade mechanism*).

### 4.3 Masks

* **Credits by the render's pixels.** Keeping index 255 on ticks whose render drew any `LAYER_OVERLAY` pixel let a render that lost its credits mask the captured ink and lose nothing, and let `--compare` read a lost title card as an improvement; replaced by the per-tick `credits` flag (section 2.1).
* **Sky IoU from one modal index.** It understated IoU by about 0.12 on both `CTRY` and `INTRO`; replaced by the band mask (section 2.0).

### 4.4 Per-second scoring of a video capture

A prototype of `stuntreel parity` (commit `d80e29e`, branch `feat/video-parity-scorer`, not merged) scored a whole-film video capture ([`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.6) per film second, searching a window of render ticks for each sample's best SSIM and fitting one film-wide offset. It was validated on 2026-10-31 and not adopted (`[Bounded Observation]`, one render, `CTRY.FLM` and `INTRO.FLM`). It is fast (2.0 s and 4.8 s) and agreed with the per-frame headline on `CTRY.FLM` (0.782 against 0.781), but at SSIM near 0.75 its per-sample offsets are noise, and its refitted film offset is unstable: changing six seconds of the render moved unaltered seconds by up to 0.071, where the per-frame scorer moved them by 0.000. Planted errors stood out in neither scorer. It does find what frame captures skip: `INTRO.FLM` seconds 0–14 show a static black title card, "DISNEY INTRO REEL", of which the frame capture holds no frame. Before trying again it needs a significance margin on its slip flag (about 0.03), a film offset fixed rather than refitted per render, and a metric that registers geometric error at this parity level. _Source: [2026-10-31: per-second scoring of a video capture](../../work/2026-11/distill-method/journal.md#2026-10-31-per-second-scoring-of-a-video-capture)._

## 5. Reading the legacy parity log

How to read the rows of the [parity log](../../work/2026-10/parity-log/log.md), frozen history whose rows are mostly dated figures; journal entries (step 7) replace it.

* **Superseded captures.** Reports made from `ctry_pre_filmclock` captures were keyed by capture ordinal and are not comparable to any row; the comparator rejects a `meta.json` without `film_tick`. Recapture instead of converting.
* **The `5799a53` row.** The overall mean fell only because 18 end-hold captures entered the average; over the 122 animated ticks the score equals the earlier rows. Compare rows over the same frame set.
* **Frames per `film_tick`.** All 18 end-hold captures share tick 1342; `--compare` keeps the first per tick, so a comparison covers 123 distinct ticks for that capture set.
* **Which headline a row quotes.** Rows before 2026-10-22 are over all frames. Until the renderer modelled the fade (`5bf6afe`) rows headline `mean_ssim_compensated`; from the retire-compensation row the headline is `mean_ssim_scored`, quoted with its scored-frame count. Every row is `[Bounded Observation]`.

## Ruled out

None recorded here. Rejected measurement approaches are in [`metric-bench.md`](metric-bench.md#ruled-out) and [`evidence-limits.md`](evidence-limits.md#ruled-out).

## Open questions

None recorded here. The open lavapipe and GPU question is in [`evidence-limits.md`](evidence-limits.md#open-questions).
