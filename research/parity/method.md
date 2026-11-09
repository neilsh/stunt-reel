---
summary: "Defines the parity loop that judges a render change against PLAYONE.EXE: capture, render, SSIM and IoU scoring with the fade floor, compare verdicts, `report.json` fields and the metric bench."
---
# Parity Method: the Fidelity Loop

How a rendering change is judged against `PLAYONE.EXE`. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md) (parity, captured frame, film clock); capture mechanics are in [`../playone-exe/capture.md`](../playone-exe/capture.md); the commands are [`docs/howto/score-a-render-change.md`](../../docs/howto/score-a-render-change.md); each film's expected scores are its expected tables in [`references.toml`](references.toml); dated results are journal entries (step 7) or, before them, rows of the parity log (section 5).

## 1. The loop

0. **Baseline and expected scores.** `references.toml` names, by film slug and content hash, the capture under `<data root>/captures/<slug>/frames` each film is scored against. `mise run parity` prints, under each film's summary line, its expected line: the expected score of the film's table for the renderer class the render was drawn on (`[<film>.expected.gpu]` or `.lavapipe`) with the SSIM delta, or what is missing (no adapter in the report, or no table for the class yet); the adoption noise note comes last. The line judges drift, a delta beyond the film's `noise_sigma`, only when the report names an adapter whose name matches the table's, a frame scored, the run scored its own render (not `--retime` or `--reuse`), the git tree hash of the checkout's `crates/` (tracked files as they are on disk and untracked ones git does not ignore) is the table's `crates`, the film's pins (`sha256`, `all_sha256`) are the ones the table records, and the row names a `noise_sigma` (INTRO's does not yet, so its line gives the delta without a verdict); otherwise it says why. The check reads the checkout, not the binary (with `--no-build` or `--no-render` it assumes the render came from the checkout), and assumes builds of the same `crates/` render identically; `noise_sigma` is the recapture noise borrowed as a tolerance, not a measured bound on build-to-build variation ([section 3](#3-what-is-not-yet-evidence), adoption floor). The table pins a tree, not a commit, because PRs land as new commits (squash or rebase): a branch commit never reaches `main`, but its `crates/` tree does when no other `crates/` change lands first, so a clone without the branch commit still compares (#308's branch commit `d01a3c4f` and its squash `fa8b9a0` share the `crates/` tree `641cffd`). `commit`, the commit measured, is optional and only says where; nothing compares it.
1. **Capture on the film clock.** Each captured frame is tagged in `meta.json` with `film_tick` (the film clock: the tick the frame shows) and `global_tick`. Matching uses the film clock because a captured frame is a distinct rendered page grabbed at retrace, so capture ordinals do not map to ticks (`[Supported Inference]`; § 4.2).
2. **Keep the previous render** to compare against (`build/parity/previous/<film>`, or a pinned `_base` tree).
3. **Render every captured tick** into a render store ([ADR 0027](../../docs/adr/0027-renders-store-planes-in-per-second-zstd-chunks.md)). It holds each tick's index plane, layer plane and palette, and its picture is its palette over its index plane (unlit palette index; layer ids 0 none, 1 ocean, 2 terrain, 3 props, 16+n for actor draw n of the frame).
4. **Score** (section 2). The masks come from index planes, not colours: a capture pixel is sky when its index is in the sky bands 227..=238 (`sky_indices`; [`palette-and-shading.md`](../formats/concepts/palette-and-shading.md)), and a render pixel is sky where its stored layer plane is empty. `render` still clears to 233 (`CTRY`'s sky) when given an `.ALL`, which does not affect the score. `report.json` also carries `mean_index_agreement_scored` and `mean_loss_by_class_scored`, the SSIM loss split by layer: read it as where the loss is, not what is wrong.
5. **Compare.** `--compare` joins two reports by `film_tick`. The basis is `scored` when both reports carry `scored` (SSIM over frames scored in both runs) and `all` otherwise (SSIM over all common frames), recorded on the first `[compare]` line and as `"basis"` in `compare.json`. With `--compare-test` it also gives a verdict on the windows the change touched. A frame is changed where its `.idx` or luma differs; Δ is the capture SSIM of *after* minus *before* over the 11x11 windows holding a changed pixel, so unchanged flat ground drops out. `--noise-sigma <σ>` (the film's `noise_sigma`) buckets |Δ| < σ as within noise; without it only a Δ of exactly 0 is. That σ is the recapture noise of the *whole-frame* SSIM (§ 2.2, § 2.2.1), not of Δ, which averages a few touched windows and so should vary at least as much: σ is a lower bound for Δ's spread (not measured), and on a heavy-tailed film one σ misdescribes a typical frame ([#305](https://github.com/neilsh/stunt-reel/issues/305)). "Within noise" is therefore conservative, and a frame called closer or further may still be noise. The verdict judges every matched frame, including the ones the fade floor leaves unscored (§ 2.1), so it can move on faded frames the headline mean ignores. `compare.json` gains `"verdict"`, and the worst-mover sheets follow Δ. `--build-floor <N>` labels frames with at most N changed pixels as build noise; 0 suffices where builds of one revision have been measured, since they rendered identically (§ 2.2, § 3).
6. **Look at the worst movers before trusting the mean.** A mean can hide a regression or an improvement: the axis fix (`82ea965`) made the biplane upright like `PLAYONE` yet lowered mean SSIM 0.571 -> 0.567, because size and position error remain (`[Bounded Observation]`). _Source: [2026-10-21: a worst mover the mean hid](../../work/2026-11/distill-method/journal.md#2026-10-21-a-worst-mover-the-mean-hid)._ Diagnose one discrepancy with the probes in [`probes.md`](probes.md).
7. **Write a journal entry** in the work item's `journal.md` ([`work/README.md`](../../work/README.md#journal-entries)): commit hash, matched frames, means, the reason for any movement, and the verdict. An adopted change updates each reference film's expected table for the class it measured (step 0).

### 1.1 Extracting frames and video

Tier `[Established]`. A render samples the authored 50 Hz timeline and stores each tick under its own number, which is the film clock `stuntreel parity` looks up. Samples that fall off whole ticks (`--sample-count`, `--video`) are not parity inputs. A `--video` export resamples the timeline at `--fps` with 4:3 correction (320x240, `[I6]`), interpolating between slice keyframes, trimmed to the authored span. Flags: [how-to § 4](../../docs/howto/score-a-render-change.md#4-render-by-hand). _Source: ticket `T11` in the frozen [`TEAM_SHEET.md`](../../work/2026-10/team-sheet/TEAM_SHEET.md)._

### 1.2 Scoring another captured film

Render the whole captured span at 320x200 into a render store, then score it ([how-to § 4 and § 5](../../docs/howto/score-a-render-change.md#5-score-and-compare-by-hand)); a tick outside the rendered range counts as missing on one side.

### 1.3 Fields of `report.json` and `compare.json`

Read these before indexing either file in a one-off script. A count and a list often differ by one word: in `report.json`, `frames` is a **number** and `per_frame` is the **list**; in `compare.json`, `verdict.counts` is an **object** keyed by class and `verdict.frames` is the list. Types are JSON types: `number`, `string`, `bool`, `list`, `object`; `or null` means the value can be `null` (a mean over no frame, a field a legacy report lacks), and `, optional` means the key can be absent. A measured value is never missing without being `null`, so test for `null` rather than for the key.

The tables are checked: `report_doc.rs` in `crates/stunt-cli/src/parity/` runs `stuntreel parity` over the synthetic fixtures, parses the tables below (the rows between the `fields` markers, key and type columns) and fails when the output has a key the note does not list, lacks one it lists, or holds a value of another type. Change a serializer and this note in the same commit. The structs are `Report` and `FrameReport` in [`crates/stunt-parity/src/report.rs`](../../crates/stunt-parity/src/report.rs) (`report.json`), `Comparison::to_json` in `report_diff.rs` (`compare.json`) and `Verdict::to_json` in `verdict.rs` (its `verdict` object).

**`report.json`** (top level; written by every run):

<!-- fields: report -->
| Key | Type | Meaning |
|---|---|---|
| `reference_frames` | number | Frames the capture holds. Equals `frames` + `unmatched`. |
| `frames` | number | Frames matched to a render (a count, not the list). |
| `unmatched` | number | Captured frames skipped: no render of that `film_tick`, or the capture's frame or palette file is missing. |
| `sky_indices` | list | `[low, high]`, the inclusive palette-index range counted as sky (227, 238). |
| `mean_ssim` | number | Mean SSIM over every matched frame. |
| `min_ssim` | number | Lowest SSIM of any matched frame. |
| `mean_iou` | number | Mean mask IoU over every matched frame. |
| `min_fade_level` | number | The `--min-fade-level` floor the run used (default 0.25). |
| `mean_ssim_scored` | number or null | Mean SSIM over scored frames (the headline); null when none scored. |
| `i6_gate` | object | Whether `mean_ssim_scored` reaches each `[I6]` threshold. |
| `mean_iou_scored` | number or null | Mean IoU over scored frames. |
| `mean_index_agreement_scored` | number or null | Mean of `index_agreement` over scored frames (each over its frame's non-overlay pixels). |
| `mean_loss_by_class_scored` | object or null | Mean SSIM loss per layer class over scored frames; keys are the classes below. |
| `scored_frames` | number | Frames whose `scored` is true: authored fade at or above the floor, or no authored fade. |
| `excluded_frames` | number | Matched frames whose authored fade is below the floor (reported, not scored). `frames` = `scored_frames` + `excluded_frames`. |
| `credits_missing_frames` | number, optional | Matched frames whose render record says the film shows credits but whose render drew no credits pixel (no `PFONT.BIN`, or a drawing fault); their captured ink is still scored. At most `frames`; absent in older reports (read as 0). |
| `adapter` | object or null, optional | The adapter the render was drawn on, from `render.json`: `name` as its driver reports it and `class` `hardware` or `cpu`. Null when the render does not record one; absent in older reports. |
| `per_frame` | list | One object per matched frame, in capture order (next table). |
<!-- /fields -->

**`per_frame[]`** of `report.json`:

<!-- fields: report.per_frame -->
| Key | Type | Meaning |
|---|---|---|
| `ordinal` | number | 1-based capture order of the frame (`tick_NNNN.idx`); not a time axis. |
| `film_tick` | number | The film clock the frame was matched on; the key `--compare` joins reports by. |
| `ssim` | number | SSIM against the capture. |
| `iou` | number | Mask IoU against the capture. |
| `index_agreement` | number or null | Fraction of non-overlay pixels whose palette index equals the capture's (overlay pixels leave both counts; 1.0 if every pixel is overlay). |
| `loss_by_class` | object or null | This frame's SSIM loss split by layer class; keys are the classes below. |
| `fade_level` | number or null | Fade level measured from the captured palette (about 1.0 when unfaded). |
| `authored_fade_level` | number or null | Fade level the film authored at this tick, when the render recorded it. |
| `scored` | bool or null | True when `authored_fade_level` reaches `min_fade_level`, or when it is null (no authored entry); the measured `fade_level` is only a cross-check (ADR 0005). Scored frames count in the `*_scored` means. |
<!-- /fields -->

**`i6_gate`** of `report.json`:

<!-- fields: report.i6_gate -->
| Key | Type | Meaning |
|---|---|---|
| `initial` | bool | `mean_ssim_scored` is at least 0.88. |
| `sign_off` | bool | `mean_ssim_scored` is at least 0.90. |
<!-- /fields -->

**Keys of `loss_by_class`** (per frame and `mean_loss_by_class_scored`; each value is a number, the SSIM loss attributed to that class):

<!-- fields: report.loss_classes -->
| Key | Type | Meaning |
|---|---|---|
| `sky` | number | Neither side draws: render layer empty, capture sky. |
| `reference_only` | number | Capture shows non-sky where the render's layer is empty. |
| `ocean` | number | Both draw; the render's layer is ocean. |
| `terrain` | number | Both draw; the render's layer is terrain. |
| `props` | number | Both draw; the render's layer is a prop. |
| `actors` | number | Both draw; the render's layer is an actor. |
| `ocean_render_only` | number | Render draws ocean where the capture shows sky. |
| `terrain_render_only` | number | Render draws terrain where the capture shows sky. |
| `props_and_actors_render_only` | number | Render draws a prop or actor where the capture shows sky. |
| `overlay` | number | The render's layer holds the credits text, whatever the capture shows there (the key is the render's layer name; this is not the UI overlay). |
<!-- /fields -->

**`compare.json`** (top level; written with `--compare`):

<!-- fields: compare -->
| Key | Type | Meaning |
|---|---|---|
| `basis` | string | `"scored"` (SSIM over frames scored in both reports) or `"all"` (every common frame; a report predates fade scoring). |
| `common_frames` | number | Frames (by `film_tick`) in both reports among those `basis` selects (with `"scored"`, scored in each report); the means cover only these. |
| `before_only_frames` | number | Frames selected by `basis` in the previous report but not the fresh one; a tick in both but scored only before counts here. |
| `after_only_frames` | number | Frames selected by `basis` in the fresh report but not the previous one. |
| `changed_threshold` | number | SSIM change beyond which a frame counts as improved or regressed (0.005). |
| `mean_ssim` | object | Mean SSIM before, after and their difference over the common frames. |
| `mean_iou` | object | The same for IoU. |
| `improved_count` | number | Common frames whose SSIM rose by more than `changed_threshold`. |
| `regressed_count` | number | Common frames whose SSIM fell by more than `changed_threshold`. |
| `most_improved` | list | Up to 5 frames with the largest SSIM gain, best first. |
| `most_regressed` | list | Up to 5 frames with the largest SSIM loss, worst first. |
| `verdict` | object, optional | The regression verdict; present only with `--compare-test` and a readable previous render store. |
<!-- /fields -->

**`mean_ssim` and `mean_iou`** of `compare.json`:

<!-- fields: compare.mean -->
| Key | Type | Meaning |
|---|---|---|
| `before` | number | The previous report's mean. |
| `after` | number | The fresh report's mean. |
| `delta` | number | `after` minus `before`. |
<!-- /fields -->

**`most_improved[]` and `most_regressed[]`** of `compare.json`:

<!-- fields: compare.delta -->
| Key | Type | Meaning |
|---|---|---|
| `film_tick` | number | The frame's film clock. |
| `before` | number | Its SSIM in the previous report. |
| `after` | number | Its SSIM in the fresh report. |
| `delta` | number | `after` minus `before`. |
<!-- /fields -->

**`verdict`** of `compare.json` (the regression verdict of section 1, step 5):

<!-- fields: compare.verdict -->
| Key | Type | Meaning |
|---|---|---|
| `frames` | list | One object per matched frame of the fresh report, in capture order (next table). |
| `counts` | object | Frames per class, keyed by the class names below (an object, not a list). |
| `mean_delta` | number or null | Mean `delta` over the judged frames (closer, further, within noise); null when none. |
<!-- /fields -->

**`verdict.frames[]`**:

<!-- fields: compare.verdict.frame -->
| Key | Type | Meaning |
|---|---|---|
| `film_tick` | number | The frame's film clock (there is no `ordinal` here). |
| `changed_idx` | number | Fraction of the 320x200 frame whose palette index changed. |
| `changed_luma` | number | Fraction whose luminance changed. |
| `changed_by_layer` | object | Changed fraction (index or luminance) by the fresh render's layer; keys are the layers below. |
| `before_after_ssim` | number or null | SSIM of the previous render against the fresh one (stretched, unmasked); null for a missing tick. |
| `delta` | number or null | Capture SSIM of *after* minus *before* over the scored windows holding a changed pixel; null when no scored window holds one (including when nothing changed) or the tick is missing. |
| `class` | string | The frame's class: one of the keys of `counts`. |
<!-- /fields -->

**Keys of `verdict.counts`** (each value is a number of frames; the keys are also the values `class` takes):

<!-- fields: compare.verdict.counts -->
| Key | Type | Meaning |
|---|---|---|
| `unchanged` | number | No changed pixel lies in a scored window: nothing changed, or every change sits under the overlay or outside the windows. |
| `build_noise` | number | `delta` is present and at most `--build-floor` pixels changed. |
| `within_noise` | number | The change on the touched windows is below `--noise-sigma` (or exactly zero). |
| `closer` | number | The touched windows moved closer to the capture. |
| `further` | number | The touched windows moved away from the capture. |
| `missing` | number | The previous render has no such tick. |
<!-- /fields -->

**Keys of `changed_by_layer`** (each value is a number: changed pixels in that layer as a fraction of the 320x200 frame):

<!-- fields: compare.verdict.layers -->
| Key | Type | Meaning |
|---|---|---|
| `ocean` | number | Changed pixels the fresh render draws as ocean. |
| `terrain` | number | Changed pixels drawn as terrain. |
| `props` | number | Changed pixels drawn as props. |
| `overlay` | number | Changed pixels drawn as credits text. |
| `actors` | number | Changed pixels drawn as actors. |
| `none` | number | Changed pixels no layer claims (sky and undrawn). |
<!-- /fields -->

## 2. Scoring in one paragraph

Both sides become Rec. 601 luminance, are stretched 320x200 -> 320x240, and are scored with the shared 11x11-window SSIM (`compute_frame_ssim`, window 11, stride 8; `[I6]`: >= 0.88 initial, >= 0.90 sign-off; `[Established]`). IoU compares each side's non-sky mask and measures framing independent of shading. Neither is a perceptual judgement. Windows touching the **UI overlay** are left out: capture rows 185 and below, and index 255 (the cursor) on ticks whose render record says the film shows no credits (`credits` in `render.json`, from the film's schedule, not the render's pixels), so credits ink is scored wherever the film shows it. A frame that expects credits the render did not draw is still scored on the ink and counted in `credits_missing_frames`.

### 2.0 Sky mask and IoU scale

Tier `[Bounded Observation]`. The mask counts every index 227 to 238 as sky and reads the render's sky from its layer plane (commits `b9a2b93`, `2fc0ca2`, 2026-10-23). The mask before it counted only the capture's single most common sky index as sky, so it mostly measured how much of the capture's sky lay outside that one band: on the same renders `mean_iou_scored` went from 0.856 to 0.978 on `CTRY.FLM` and from 0.802 to 0.919 on `INTRO.FLM`, while SSIM and index agreement, which do not read the masks, did not move. IoU figures recorded before that change are on the old scale and are not comparable with it. _Source: [2026-10-23: the sky mask becomes the 227 to 238 band](../../work/2026-11/distill-method/journal.md#2026-10-23-the-sky-mask-becomes-the-227-to-238-band)._

### 2.1 Fade floor

`PLAYONE.EXE` fades its palette linearly to black near the end of `CTRY.FLM`, from about tick 990 to 1337. For each captured frame, the **fade level** is the median, over a fixed index set, of (captured palette entry R+G+B) / (static Mode 13h palette entry R+G+B). The index set is the indices present in the first captured frame whose static R+G+B is above 60. A frame with no fade reads about 1.0 (1.011 for `CTRY`, from DAC 6->8-bit expansion). Cursor and button-bar entries do not fade; they are a minority of the set, so the median ignores them.

The renderer applies the same fade from the film's palette variables, so renders are scored as drawn. Frames below `--min-fade-level` (default 0.25) are computed and reported but not scored, because SSIM of near-black frames says little. The headline is `mean_ssim_scored` with its scored-frame count; `mean_ssim`, `min_ssim` and `mean_iou` cover all matched frames.

The floor tests the authored brightness (var 14), not the captured fade level, which is reported beside it as a cross-check. That keeps night frames scored: the night is var 13 ([`palette-fade.md` § 3.1](../playone-exe/palette-fade.md#31-night-term-var-13)), which the floor does not read. `COL3-2.FLM` scores 26 of 30 frames ([`film-segments.md`](film-segments.md#1-col3-2flm-the-studio-interior)); the 4 excluded are at ticks 168–201, where var 14 is 0 ([`palette-fade.md` § 5.1](../playone-exe/palette-fade.md#51-night-capture-col3-2flm)). `TOD.FLM` keys var 14 only at tick 0 (32768) and tick 1416 (0) while var 13 changes through the film (35544 at tick 0, 5506 at its last key, tick 1359; `mise run flm-events`, `[Bounded Observation]`), so by the floor's rule its frames stay scored until its last slice; no `TOD.FLM` scoring run confirms it yet.

The comparator reads var 14 from the palette controls `render.json` records for every tick. Each tick also records `credits`, whether the film shows credits there (`0x99` until `0x98`); on such a tick the UI-overlay mask keeps capture index 255 as credits ink instead of masking it as the cursor, so a render that drops its credits scores the loss. The field is required from `render.json` schema 3; an older render is refused with the re-render message. The render also records the `adapter` its frames were drawn on (`name` as its driver reports it, `class` `hardware` or `cpu`), which `report.json` copies; the field is optional, so a schema-3 render without it still scores, with a null `adapter`. `--compare` reads reports of the retired fade-compensated scoring (§ 4.1) for their raw `ssim`.

### 2.2 The metric bench

`mise run parity-bench -- run --film <film>` (`python/stunt_reel/bench/`) plants 16 render faults (besides the unchanged control) in memory on every scored frame and scores ten candidate metrics against the reference. Its numpy SSIM reproduces the Rust `ssim` of `report.json` to within 1e-4 on every frame, and a synthetic fixture with golden values from the Rust scorer pins the two together (`tests/fixtures/parity/bench/`). The yardstick σ is the standard deviation, over the scored ticks two captures both hold, of (metric against one) − (metric against the other) with the unchanged render: per-frame variation no render change caused. A fault is detected when the metric falls by at least 3σ on average.

What it found (`[Bounded Observation]`, 2026-10-31, one render per film at `2461289`, `CTRY.FLM` and `INTRO.FLM`, references `004` against recaptures `005`):

* **No metric detects every fault**, because some faults move the render towards the capture. Removing the actors raises `ssim` (15σ on `CTRY.FLM`, 11σ on `INTRO.FLM`) and the differential score on the windows the removal touches is +0.18 on `CTRY.FLM`: our actors match the capture worse than the ground behind them.
* **Drawn objects may sit left of `PLAYONE`'s.** Shifting the render right raises `ssim_actors` at every magnitude tried on `CTRY.FLM`; not yet measured directly.
* **Detection is not monotone in magnitude.** On `CTRY.FLM`, whole-frame `ssim` misses a 3-tick advance but detects 1 and 5, and `ssim_props` detects a 1-column shift but misses 2, 4 and 8: read the bench's row per fault, not its smallest detected magnitude.
* **Index agreement** is the most sensitive per layer but reads layers differently: on `CTRY.FLM`, `index_terrain` *improves* by about 240σ under any advance; unexplained.
* **Build floor:** on `CTRY.FLM` a second build of the same revision (`mise run build-at`) rendered all 1,337 ticks with no `.idx` or luma pixel different.
* **`INTRO.FLM`'s σ units are inflated**: its two captures agree so closely (σ 1.7e-5 for `ssim_structured`) that they are not comparable with `CTRY.FLM`'s.

_Source: [2026-10-31: the metric bench](../../work/2026-11/distill-method/journal.md#2026-10-31-the-metric-bench), which holds the table of every metric against every fault._

### 2.2.1 Recapture noise of the reference films

`[Bounded Observation]`, 2026-11-08, renders and scores at `ff576ba`, one recapture per film on the Patch 3 `PLAYONE` from the Patch 3 `MAKEONE` archive its `references.toml` row pins. σ is the bench's whole-frame `ssim` σ of section 2.2 over the scored ticks the reference and the recapture both hold; identical pages are paired ticks whose index pages match pixel for pixel.

| Film | Paired | Identical pages | σ (`ssim`) | Median \|Δ\| | p95 | Largest \|Δ\| |
|---|---|---|---|---|---|---|
| `vault-ctry` | 104 | 77 | 0.0052 | 0 | 0.0143 | 0.026 |
| `vault-intro` | 172 | 94 | 0.0194 | 0 | 0.0529 | 0.113 |
| `vault-land` | 88 | 61 | 0.0051 | 0 | 0.0132 | 0.024 |
| `vault-balloon` | 95 | 56 | 0.0109 | 0 | 0.0264 | 0.063 |
| `vault-traintnl` | 102 | 71 | 0.0062 | 0 | 0.0053 | 0.040 |
| `vault-bomb` | 265 | 153 | 0.0124 | 0 | 0.0230 | 0.087 |
| `vault-location` | 732 | 729 | 0.00012 | 0 | 0 | 0.003 |

* **The noise is heavy-tailed.** On every film the median |Δ| is 0: σ comes from the minority of pages that differ, so it overstates the noise of a typical frame and understates the worst. As `noise_sigma` it would make `--noise-sigma` call a Δ below 0.005 to 0.019 within noise on six films, which their identical pages argue is mostly not noise (`[Supported Inference]`), so only `vault-location`'s row carries one (0.00012). How the verdict should treat this noise is [#305](https://github.com/neilsh/stunt-reel/issues/305).
* **`CTRY.FLM`'s `ssim` σ rose from 0.00030 to 0.0052.** The 0.00030 is section 2.2's pair (`004` against `005`, the demo's unpatched `PLAYONE` and shipped `.ALL`); on Patch 3, 27 of 104 CTRY paired pages differ. INTRO's 2026-10 figure (σ 1.7e-5) is for `ssim_structured` and is not directly comparable. Build, archive and harness all changed between the two, and which of them causes this has not been tested.
* **Unpatched figures, for comparison** (2026-11-07 at `740c608`, unpatched builds, the five `VAULT` films only): σ 0.0154 / 0.0168 / 0.0094 / 0.0126 / 0.00038 for LAND / BALLOON / TRAINTNL / BOMB / LOCATION, with 56 / 76 / 65 / 168 / 731 identical pages of 89 / 100 / 99 / 273 / 732 paired. CTRY and INTRO were not measured on the unpatched build: their 2026-10-31 captures sat 3 ticks off the stride plan's goals and shared too few scored ticks with a recapture.
* **Two pages with one label may show different moments** (`[Hypothesis]`, one page checked: unpatched `vault-balloon` tick 265), against [`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.4; open question 15 there. Why `vault-location` alone replays nearly bit for bit is its open question 16. None of the seven has an error-readout calibration (section 2.3).

_Source: [2026-11-08: recapture noise on Patch 3](../../work/2026-11/300_patch3-references/journal.md#2026-11-08-recapture-noise-on-patch-3); unpatched figures from [the issue 242 journal](../../work/2026-11/242_vault-parity-films/journal.md#2026-11-07-recapture-noise-and-build-floor)._

### 2.3 Error categories graded by a vision model

This readout names and grades the large differences. Each sheet shows capture, render, their luma difference and a close-up of the actors, and a grader gives it a grade 0–3 per category of [`error-categories.toml`](error-categories.toml) (adding one is one block there). It runs as `mise run parity-bench -- errors-make`, `errors-disputes` and `errors-score` by the [`error-readout`](../../.agents/skills/improving-render-parity/error-readout.md) procedure. What it established (`[Bounded Observation]`, 2026-10-31 to 2026-11-01, renders at `2461289`, `CTRY.FLM` and `INTRO.FLM`):

* **It finds missing or wrong objects, not misregistration.** In the first grading neither Haiku nor Sonnet invented an error on a control, both caught most removed aircraft, and neither came near the 4-of-6 bar on a 4-row shift or a 5-tick advance (0 or 1 of 6) at this scale; section 2.2's metrics remain the check for those.
* **Haiku grades as well as Sonnet**: the two agreed within one grade on 610 and 577 of 630 (sheet, category) cells.
* **A category's grade can fall when the error gets worse** (a removed aircraft moved from `aircraft-parts-missing` 3 to `aircraft-absent` 3), so detection compares each category, not the highest grade.
* **One Haiku pass is not reliable on `INTRO.FLM`.** Two of four single-pass calibrations failed, their graders marking identical control panels dirty. Each sheet is therefore graded twice by Haiku, and the sheets the passes dispute (some category 2 or more in one and not the other) go to one Sonnet grader. Two `INTRO.FLM` calibrations graded that way both passed; Sonnet graded half or more of each (21 and 30 of 42 sheets), at roughly twice the subagent cost of one Haiku pass.
* **Calibration rules.** A control's difference panel is black, which no real sheet's is, so the control count is reported but does not gate: a calibration passes on actors removed alone (5 of 6), a run with no actors-removed sheet is inconclusive, and an `INTRO.FLM` calibration is a lead until it passes twice in a row. Two Haiku passes over the same sheets moved a category's count of frames graded 2 or more by up to 3, so `compare` reports a category only when it moves by 4 or more (`min_change`).

_Source: [2026-10-31: error categories graded by a vision model](../../work/2026-11/distill-method/journal.md#2026-10-31-error-categories-graded-by-a-vision-model) and [2026-11-01: calibrating the error readout](../../work/2026-11/distill-method/journal.md#2026-11-01-calibrating-the-error-readout)._

## 3. What is not yet evidence

* **Films covered.** Seven films are reference films (`references.toml`); rows before 2026-11-07 are `CTRY.FLM` alone unless they say otherwise, and no row says anything about films outside those seven (`[Unknown]`).
* **Metric caveats.** SSIM is sensitive to a misplaced thin object and to flat-area luminance; mask IoU is blind to shading and to anything inside the mask. A disagreement between the two is a prompt to read the sheets, not a verdict (`[Supported Inference]`).
* **End hold.** The 18 `CTRY.FLM` end-hold captures are the faded tail (fade level 0 at tick 1337), not the scene: unfaded renders pulled the 140-frame mean to 0.495, and with the modelled fade it is 0.667. The fade floor excludes them; quote `mean_ssim_scored` with its scored-frame count.
* **Fade mechanism.** The fade is authored as film variable 14 (palette brightness) and applied by `PLAYONE` to palette entries 0–239 ([`../playone-exe/palette-fade.md`](../playone-exe/palette-fade.md), Q-FLM-09). The renderer applies vars 13–15 itself and reproduces the live DAC exactly in 128 of 140 `CTRY.FLM` captures; the other 12 are one 6-bit level off, which is clock jitter and rounding, not a lag ([`palette-fade.md` § 5](../playone-exe/palette-fade.md)). Raw IoU over all frames falls in the near-black tail, where the render shows no shapes to mask; those frames are not scored.
* **Sparse sampling.** 140 captures over 1,342 ticks is roughly one frame per 11 ticks (`[Bounded Observation]`); motion between samples is unobserved.
* **The reference is not deterministic at a fixed tick (`[Bounded Observation]`, 2026-10-22, four DOSBox-X capture sets of `CTRY.FLM`, one machine).** On frames sharing an exact `film_tick` the sets agreed with each other at SSIM 0.939 to 0.997; the cause is not identified (`[Hypothesis]`: state that is not the film clock, such as the cursor or wall-clock effects). A parity score above about 0.95 cannot be told from that noise, so the 0.88 and 0.90 gates are reachable but the ceiling is not 1.0. The sets also started 9 or 10 ticks in and drifted by 0 to 2 ticks from each other, so always match on `film_tick`, never by ordinal across sets. Our headline moved by 0.006 across the four sets (0.001 after the unlit change); the same capture set and render give identical scores. Quote SSIM to two decimals and treat differences under 0.01 between runs as noise only when the capture set differs. _Source: [2026-10-22: recapture variance of four CTRY.FLM capture sets](../../work/2026-11/distill-method/journal.md#2026-10-22-recapture-variance-of-four-ctryflm-capture-sets)._
* **The 0.002 adoption floor is a policy bound, not a noise model (`[Bounded Observation]`, 2026-11-07, `740c608`).** Three binaries of one revision rendered all seven reference films to byte-identical render trees on one machine and GPU (RTX 4070), as the bench's build floor (§ 2.2) found on `CTRY.FLM`. The 2026-10 spread of 0.7706 to 0.7718 on `CTRY.FLM` ([`probes.md`](probes.md) § 5) has not recurred; its cause is unknown. Recapture noise (§ 2.2.1) is the larger term. _Source: [2026-11-07](../../work/2026-11/distill-method/journal.md#2026-11-07-recapture-noise-the-build-floor-and-lavapipe)._
* **Render start-up is the GPU instance (`[Bounded Observation]`, 2026-11-06, one Windows machine, RTX 4070).** An every-backend wgpu instance took about 1.9 s of a headless render. The offscreen path tries a Vulkan-only instance first (`OFFSCREEN_BACKENDS` in `renderer.rs`), going on to every backend when Vulkan finds no adapter or only a CPU one, which it keeps if no backend has hardware. A one-tick CTRY render then took a median 1.39 s against 3.15 s (six alternating runs each); a full CTRY render was byte-identical either way. A GL-only instance picked the integrated GPU. _Source: [2026-11-06](../../work/2026-11/distill-method/journal.md#2026-11-06-render-start-up-parallel-runs-and-the-references-archive)._
* **Parallel parity runs are GPU-bound (`[Bounded Observation]`, 2026-11-06, `48f5d49`, 16 threads, RTX 4070 Laptop GPU).** A render costs about 300 MiB of RAM and 200 MiB of VRAM whatever the film's length. Render-and-score pairs per second rose from about 0.2 at one job to 0.8 at 8 and 1.0–1.16 at 16, noisy at 32 with the GPU saturated, so `mise run parity` and `mise run sweep` default `--jobs` to 8; `--jobs 1` and `--jobs 8` print identical scores. _Source: [2026-11-06](../../work/2026-11/distill-method/journal.md#2026-11-06-render-start-up-parallel-runs-and-the-references-archive)._
* **A reference pins its archive.** Each row pins `all_sha256`, and the render and `capture-ref` resolve the `.ALL` by it ([ADR 0037](../../docs/adr/0037-a-reference-pins-its-archive.md)). Before it, CTRY and INTRO rendered `.ALL` copies other than the ones their captures recorded and scored the same to four decimals, so no recorded score was affected (`[Bounded Observation]`, 2026-11-06, `48f5d49`). _Source: [2026-11-06](../../work/2026-11/distill-method/journal.md#2026-11-06-render-start-up-parallel-runs-and-the-references-archive)._
* **Lavapipe and GPU (`[Bounded Observation]`, 2026-11-07, `aa76d1e`).** The same commit scored CTRY and INTRO 0.23 lower on Mesa lavapipe than on the RTX 4070 machine, with identical IoU and scored counts: lavapipe wrote other palette indices inside the same silhouettes, from its software clipper interpolating the `linear` shade varying to NaN on near ground polygons (`[Supported Inference]`). With the guard in `fragment_index`, lavapipe scores less than the 0.002 adoption margin from those GPU figures, and whether the two backends are equivalent is still open. Until a GPU run confirms the guard leaves GPU output unchanged ([#265](https://github.com/neilsh/stunt-reel/issues/265)), an adoption decision needs a GPU run. Mechanism, evidence and candidate fixes: [`lavapipe.md`](lavapipe.md). _Source: [2026-11-07](../../work/2026-11/distill-method/journal.md#2026-11-07-recapture-noise-the-build-floor-and-lavapipe)._
* **One captured palette is not like the others (`[Bounded Observation]`).** In the `INTRO.FLM` set, ordinal 69 (tick 1516) carries a palette with 126 of 253 entries live: indices 0 to 135 black while 136 to 255 keep their normal colours, between two normal neighbours. The only other blacked-out palettes in either set are the end-fade tails (`CTRY` ordinals 122 to 140, `INTRO` 213), which the fade floor excludes. The frame agrees with the render on 0.642 of its palette indices yet scores SSIM 0.019, which only a palette difference explains, since the render's surface choice (sand, index 91) is the capture's. Whether `PLAYONE` blanks its palette for one retrace during a page switch, or the harness read a half-updated palette, is `[Unknown]`; the frame stays scored and the anomaly is recorded rather than repaired.

### 3.1 Captures from dosbox-automation

`[Bounded Observation]`, 2026-10-30. `capture-ref` plans a run rather than stepping a halted guest ([`../playone-exe/capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md)). Two consequences for reading a score:

* **Palette.** A page's palette is the working palette at `DS:0x2768` (6-bit, expanded as `round(v * 255 / 63)`), not a DAC read. `PLAYONE` writes the DAC in two retrace-gated halves, so the DAC shown with the page read at frame *f* is the working palette of *f* - 1 in its low half (indices below 128) and of *f* - 2 in its high half (one `CTRY.FLM` fade, five steps, exact; [`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.5). It equals the working palette of *f* unless the palette changed at *f* or *f* - 1, and `pick` skips those two frames ([`plan.usable`](../../python/stunt_reel/tac/plan.py)), so every kept page's working palette is its DAC. `meta.json` counts the palette steps (`palette_steps`).
* **Tears.** The page is read between emulated frames without waiting for retrace, so it can land inside `PLAYONE`'s copy of a composed page to `A000`. The game keeps two composed pages (segments at `DS:0x22CA` and `0x22CC`), and rows 0–191 of a finished page equal one of them; a page whose 8-row bands match only one in some places and only the other in others is torn. The trace tests every frame this way and `pick` passes over a torn frame, so the next changed frame (*f* + 1 in practice) takes its place, and a page whose own dump pass marks it unusable (replay jitter can move a tear onto it) is dropped. The earlier rule, matching a video frame in *f* - 2 to *f* + 4, needed an AVI per film and decoded ambiguously. `meta.json` counts torn frames (`torn_frames`).

The first plan-run capture of `CTRY.FLM` agreed with the DOSBox-X reference on 0.951 of the first 60,000 page indices over the 37 ticks the two share within one tick (8 exactly), with five frames under 0.90: at the low edge of the 0.95 to 0.99 index equality between that reference's own capture sets (section 3). _Source: [2026-10-30: the first plan-run capture of CTRY.FLM](../../work/2026-11/distill-method/journal.md#2026-10-30-the-first-plan-run-capture-of-ctryflm)._

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

* **Pairing each reference tick with the nearest recapture tick to measure recapture noise** (2026-11-07). On `vault-ctry`, whose pinned capture sits off the current plan's ticks (§ 2.2.1), pairing within 5 ticks gave σ 0.0121 over 112 pairs, 85 of them 3 ticks apart: that measures how the score changes over a few ticks of motion, not recapture noise. _Source: [2026-11-07: recapture noise and build floor](../../work/2026-11/242_vault-parity-films/journal.md#2026-11-07-recapture-noise-and-build-floor)._
* **A renderer change after `48f5d49` that moves the GPU score.** The RTX 4070 machine scores the logged figures at `aa76d1e`, the commit lavapipe scored 0.23 lower (section 3).
* **A forced-choice Haiku judge** (capture beside two renders, which is closer?): it scored 0.67 on the wrong-tick control, below the 0.9 bar (2026-10-31). _Source: [2026-10-31: the metric bench](../../work/2026-11/distill-method/journal.md#2026-10-31-the-metric-bench)._

## Open questions

1. Whether lavapipe rows may stand for GPU rows, and the other lavapipe questions: [`lavapipe.md`](lavapipe.md) Open questions ([#265](https://github.com/neilsh/stunt-reel/issues/265)).
