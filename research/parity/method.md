# Parity Method: the Fidelity Loop

How a rendering change is judged against `PLAYONE.EXE`. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md) (parity, captured frame, film clock); capture mechanics are in [`../playone-exe/capture.md`](../playone-exe/capture.md); results are in [`log.md`](log.md).

## 1. The loop

0. **Baseline and captures.** The captures under `build/parity/captures/<film>/<id>` are a prerequisite: `mise run capture-ref` writes a new one and never changes an existing one, `research/parity/references.toml` names the one a film is scored against by id and content hash (promoting is a reviewed commit), `meta.json` tags every frame with its `film_tick`, and both parity tools name the missing directory and that command when a capture is absent. `mise run parity` renders both films with the current release binary, scores them, and prints two lines: `ctry  ssim 0.7732  iou 0.9783  idx 0.505  scored 114/140` and the same for INTRO, then the adoption noise note. Its render and report are the latest render and report, `build/parity/ours/<film>_current` and `build/parity/report/<film>_current`; step 2 keeps the one before them. `--no-build` reuses the release binary (a parallel session may hold it), `--no-render` re-scores the existing `_current` trees, and `--retime N` re-scores them relabelled by N ticks (probes.md section 6), writing a `_retime<N>` report instead of overwriting the baseline.
1. **Capture once per `PLAYONE` build** (`mise run capture-ref`; another film: `mise run capture-ref -- --film corpus/stisldem/VAULT/INTRO.FLM`, see `playone-exe/capture.md` § 4). Each frame is tagged in `meta.json` with `film_tick` (the film clock: the tick the frame shows) and `global_tick`. Matching uses the film clock because the capture ordinal is not a time axis: a captured frame is a distinct rendered page grabbed at retrace, so ordinals do not map to ticks (`[Supported Inference]`). The tags are read from DGROUP at the player's `DS`, which differs per build, so `DS` (`0x1575` for the demo) is a capture parameter, not a constant.
2. **The previous render is kept automatically.** To compare the **binary** rather than the renders, `mise run build-at -- <rev> <out>` builds a revision in a detached worktree with an isolated `target/build-at` and copies the binary to `<out>`; it never touches the current checkout. Before a render replaces it, `mise run parity` renames the outgoing `build/parity/ours/<film>_current` to `build/parity/previous/<film>` — a rename, not a copy, because a render tree is about 250 MB — and prints the re-score command. Comparing without re-rendering then costs `--reuse build/parity/previous`. Only one prior tree per film is kept: the next render replaces it. For a *pinned* baseline you want across many changes, copy the tree yourself to a name ending `_base` (`build/parity/ours/ctry_base` with `build/parity/report/ctry_base`); a report without its render directory cannot produce the before panels, and `_base` is protected from the rotation below. `mise run clean -- --parity --keep N --yes` reports the scratch trees that accumulate in `build/parity/ours` and `build/scratch/sweep` (~19.7 GB at one point) and removes all but the newest N per root, never `_current` or `_base`; the previous render lives in `build/parity/previous/<film>`, a root the rotation does not scan.
3. **Render every tick including the final one:** `--frames 1..1344 --sidata <SIDATA> --width 320 --height 200 --viewport-rows 185` (the 3D view fills 185 rows; see `playone-exe/capture.md` § 4) writes `tick_00000.png`-`tick_01342.png`.
3a. **Planes:** each render also writes `tick_NNNNN.idx` and `tick_NNNNN.layer` beside the PNG (unlit palette index; layer ids 0 none, 1 ocean, 2 terrain, 3 props, 16+n for actor draw n of the frame). `report.json` carries `mean_loss_by_class_scored`, the SSIM loss split by layer (read it as 'where the loss is', not 'what is wrong'). `parity` uses them for mask IoU and reports `mean_index_agreement_scored`.
4. **Score:** `stuntreel parity --reference ... --test ... --output ...`. The masks come from index planes, not colours: a capture pixel is sky when its index is in the sky bands 227..=238 (`sky_indices` in `report.json`; [`palette-and-shading.md`](../formats/concepts/palette-and-shading.md)), and a render pixel is sky where its `.layer` plane is empty. `--headless` writes the `.idx`/`.layer` planes beside every frame; a render directory without them is an error, so re-render rather than score old PNGs. `render` still clears to 233 (`CTRY`'s sky) when given an `.ALL`, but that no longer affects the score. Output is `report.json` plus `contact_NNNN.png` sheets (`reference | rendered | |difference|`).
5. **Compare:** add `--compare <previous report.json> --compare-test <previous render dir>`. It prints means over the frames present in both reports, the 5 most improved/regressed frames, and the count moved by more than 0.005, and writes `compare.json`. The basis is `scored` when both reports carry `scored` (SSIM over frames scored in both runs) and `all` otherwise (SSIM over all common frames), recorded on the first `[compare]` line and as `"basis"` in `compare.json`. With `--compare-test` it also prints a verdict on the windows the change touched: `[verdict] changed 27/121 frames: 15 closer, 12 further, 0 within noise; mean Δ +0.101 on changed windows`. A frame is changed where its `.idx` or luma differs; Δ is the capture SSIM of *after* minus *before* over the 11x11 windows holding a changed pixel, so unchanged flat ground drops out. `--noise-sigma <σ>` (the film's `noise_sigma` in `references.toml`) buckets |Δ| < σ as within noise. That σ is the recapture noise of the *whole-frame* SSIM (`004` against `005`, § 2.2), not a measurement of the noise of Δ: Δ averages a few touched windows rather than the whole frame, so it should vary at least as much between captures, and σ is a lower bound for it (not measured). "Within noise" is therefore conservative: it labels only changes smaller than that lower bound, and a frame called closer or further may still be noise. Without `--noise-sigma` the sign of Δ decides, and only a Δ of exactly 0 counts as within noise. The verdict judges every matched frame, including the ones the fade floor leaves unscored (§ 2.1), so it can move on faded frames the headline mean ignores. `--build-floor <N>` labels frames with at most N changed pixels as build noise (0 suffices: two builds of one revision render identically, § 2.2). `compare.json` gains `"verdict"`, and the worst-mover sheets follow Δ.
6. **Look at the worst movers before trusting the mean.** Open `compare_regressed_*.png` and `compare_improved_*.png` (`reference | before | after | |ref-before| | |ref-after|`). A mean can hide a regression or an improvement: the axis fix (`82ea965`) made the biplane upright like `PLAYONE` yet lowered mean SSIM 0.571 -> 0.567, because size and position error remain (`[Bounded Observation]`: worst frames about ticks 426-492, -0.02).
6a. **Diagnose one discrepancy** with the probes in [`probes.md`](probes.md) (crop, silhouette offset, actor-window IoU, candidate sweeps).
7. **Record a row in [`log.md`](log.md):** commit hash, matched frames, means, and the reason for any movement. `mise run parity-probe -- summary --report build/parity/report/ctry_current/report.json` prints those columns in order, the worst frames and the row ready to paste, so the numbers are never retyped by hand.

### 1.1 Extracting frames and video

Tier `[Established]`. `stuntreel --out-dir <dir> --frame-step <N>` samples the 50 Hz timeline every N ticks, which keeps long films from filling the disk. `--frames A..B` is a half-open range of 1-based tick ordinals; files are `tick_%05d.png`, named by the 0-based tick rendered, which is the film clock `stuntreel parity` looks up (`--frames 459..460` writes `tick_00458.png`). With `--sample-count` or `--video` the samples need not fall on whole ticks, so they are written as `sample_%04d.png` (1-based sample index) and are not parity inputs. When `--video` is present, sampling at `--fps` drives the loop and `--frame-step` is ignored.

`stuntreel --video <path>` (`.mp4`, `.webm`, `.mkv`, `.avi`) pipes frames asynchronously to `ffmpeg`, sampled at `--fps` (default 30) from the authored 50 Hz timeline with 4:3 correction (320x240, `[I6]`), interpolating between slice keyframes. The container is trimmed to the authored span with `-t`: `CTRY.FLM` (140 slices, 1,342 ticks, 26.84 s) samples 806 frames at 30 fps, ffmpeg encodes 805 and reports 26.833 s (26.84 s exactly at `--fps 50`). Without `ffmpeg` on `PATH` the command exits with a diagnostic. Ticket: `T11` in [`TEAM_SHEET.md`](../../docs/process/TEAM_SHEET.md).

### 1.2 Scoring another captured film

`--frames a..b` is 1-based, so render the whole captured span (`--frames 160..730` for the `COL3-2.FLM` capture): frames outside the range count as missing on one side. Render at `--width 320 --height 200` (the parity command rejects 320x240 input) with `--headless`, so the directory holds the `.idx`/`.layer` planes. Then:

```bash
stuntreel parity --reference build/parity/captures/<film>/<id> --test build/parity/ours/<film> --output build/parity/report/<film>
```

For a side-by-side look, decode a reference `.idx` page (64000 bytes, 320x200) with its `palettes_NNNN.json` and paste it beside our PNG; `contact_*.png` shows only the first frame.

## 2. Scoring in one paragraph

Both sides become Rec. 601 luminance, are stretched 320x200 -> 320x240, and are scored with the shared 11x11-window SSIM (`compute_frame_ssim`, window 11, stride 8; `[I6]`: >= 0.88 initial, >= 0.90 sign-off; `[Established]`). IoU compares each side's non-sky mask and measures framing independent of shading. Neither is a perceptual judgement.

### 2.0 Sky mask and IoU scale

Tier `[Bounded Observation]`. Since 2026-10-23 (commits `b9a2b93`, `2fc0ca2`) the mask counts every index 227 to 238 as sky and reads the render's sky from its layer plane. Before, only the capture's single most common sky index (`sky_index`, 233 for `CTRY`) was sky, so the other bands counted as filled. SSIM and index agreement do not depend on the masks and did not move. Same renders (`main` at `19c0365`) scored at `f64b64b` (before, `--clear-index 233`) and `19c0365` (after):

| Film | Scored / matched | `mean_ssim_scored` | `mean_index_agreement_scored` | `mean_iou_scored` before / after | `mean_iou` (all) before / after |
|---|---|---|---|---|---|
| `CTRY.FLM` (sky index 233) | 114 / 140 | 0.771 | 0.475 | 0.856 / **0.978** | 0.826 / 0.978 |
| `INTRO.FLM` (229) | 209 / 213 | 0.676 | 0.481 | 0.802 / **0.919** | 0.803 / 0.921 |
| `COL3-2.FLM` (228) | 26 / 30 | 0.636 | 0.061 | 0.022 / 0.021 | 0.019 / 0.018 |

The old IoU mostly measured how much of the capture's sky lay outside its one modal band. The new value says the non-sky silhouette is close on `CTRY.FLM` and less so on `INTRO.FLM`, in line with SSIM. IoU figures recorded before this change are on the old scale and are not comparable with it. Golden reports for the scoring-call extraction are the `after_<film>/report.json` files under `build/scratch/rebase/` (not committed).

### 2.1 Fade floor

`PLAYONE.EXE` fades its palette linearly to black near the end of `CTRY.FLM`. For each captured frame, the **fade level** is the median, over a fixed index set, of (captured palette entry R+G+B) / (static Mode 13h palette entry R+G+B). The index set is the indices present in the first captured frame whose static R+G+B is above 60. A frame with no fade reads about 1.0 (1.011 for `CTRY`, from DAC 6->8-bit expansion). Cursor and button-bar entries do not fade; they are a minority of the set, so the median ignores them.

The renderer applies the same fade from the film's palette variables, so renders are scored as drawn. Frames below `--min-fade-level` (default 0.25) are computed and reported but not scored, because SSIM of near-black frames says little. `report.json` per frame adds `fade_level` and `scored`; the run level adds `min_fade_level`, `mean_ssim_scored`, `mean_iou_scored` (both null if no frame is scored), `scored_frames`, and `excluded_frames`. The headline is `mean_ssim_scored` with its scored-frame count; `mean_ssim`, `min_ssim` and `mean_iou` cover all matched frames.

The fade level is a brightness heuristic built for `CTRY.FLM`'s day sky. On a night film (`COL3-2.FLM`) it reads about 0.24 for most frames, so 29 of 30 are excluded and the scored headline rests on one frame (tick 705, fade 1.012, SSIM 0.479); for that film read the unscored `mean_ssim`. `PLAYONE` fades `CTRY.FLM` from about tick 990 to 1337.

Headless renders write the palette controls of every rendered tick to `palette_controls.json` beside the PNGs. The comparator rebuilds that palette to get the render's clear colour per tick, so the IoU sky mask follows the fade; a render directory without the file uses the static clear colour.

From `36a7305` to `5bf6afe` the comparator also reported `ssim_compensated` (the render's luminance scaled by the fade level, later by the ratio of capture to render fade level) and headlined `mean_ssim_compensated`. That stood in for the fade before the renderer modelled it and was retired once it did; `--compare` reads such reports for their raw `ssim`.

### 2.2 The metric bench

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

### 2.3 Error categories graded by a vision model

`[Bounded Observation]`, the same renders and captures as section 2.2. Where the forced-choice judge asked which of two near-identical renders was closer, this asks a model to name and grade the large differences. Each sheet shows capture and render side by side at 2x (the button bar painted grey), their absolute luma difference, and a close-up of the actors' bounding box. Frames: 12 per film spread over the scored ticks below any fade, `CTRY.FLM` ticks 4–499 and `INTRO.FLM` 1009–2687 (its first 20 seconds skipped).

* **Discovery.** Haiku, Sonnet and Opus each listed every difference on the 12 `CTRY.FLM` sheets and proposed categories; all three named the aircraft drawn as bare wing shapes, without fuselage, propeller or wheels, in 12 of 12 frames, and the missing shadow in the same 5. Merged, that gave ten categories. A second pass on `INTRO.FLM`, given the ten, added five: an aircraft not drawn at all (10–11 of 12 frames), a shadow of the wrong shape, missing ground actors, the wrong terrain surface, and a missing explosion. Haiku found what the larger models found but filed new kinds under existing names. The categories are [`error-categories.toml`](error-categories.toml); adding one is one block there.
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

## 3. What is not yet evidence

* **Single film.** Only `CTRY.FLM` has been captured; the rows say nothing about other films, cameras, or actors (`[Unknown]`).
* **Metric caveats.** SSIM is sensitive to a misplaced thin object and to flat-area luminance; mask IoU is blind to shading and to anything inside the mask. A disagreement between the two is a prompt to read the sheets, not a verdict (`[Supported Inference]`).
* **End hold.** The 18 end-hold captures are the faded tail (fade level 0 at tick 1337), not the scene. Unfaded renders pulled the 140-frame mean to 0.495; with the modelled fade it is 0.667. The fade floor (section 2.1) scores only frames at or above fade level 0.25, which excludes them; quote `mean_ssim_scored` with its scored-frame count.
* **Fade mechanism.** The fade is authored as film variable 14 (palette brightness) and applied by `PLAYONE` to palette entries 0–239 ([`../playone-exe/palette-fade.md`](../playone-exe/palette-fade.md), Q-FLM-09). The renderer applies vars 13–15 itself and reproduces the live DAC exactly in 128 of 140 `CTRY.FLM` captures; the other 12 are one 6-bit level off, which is clock jitter and rounding, not a lag ([`palette-fade.md` § 5](../playone-exe/palette-fade.md)). The "6-tick lag" in earlier notes came from reading keys at slice starts. Raw IoU over all frames falls in the near-black tail, where the render shows no shapes to mask; those frames are not scored.
* **Sparse sampling.** 140 captures over 1,342 ticks is roughly one frame per 11 ticks (`[Bounded Observation]`); motion between samples is unobserved.
* **Recapture variance (`[Bounded Observation]`, 2026-10-22, one machine, four capture sets of `CTRY.FLM`).** Sets `ctry`, `ctry_r2`, `ctry_r3`, `ctry_r4`; the render and scorer were identical for all four. (Figures below are from the lit render; after the unlit change the spread over the same four sets is 0.001, 0.766 to 0.767.)
  * *Our headline barely moves.* `mean_ssim_scored` over 114 frames is 0.689, 0.694, 0.695, 0.690 (spread 0.006); mean index agreement 0.390, 0.370, 0.363, 0.383 (spread 0.027). Quote SSIM to two decimals and treat differences under 0.01 between runs as noise only when the capture set differs; the same capture set and render give identical scores.
  * *Captures start at different ticks.* The first frame's `film_tick` is 9 or 10 and later frames drift by 0 to 2 ticks from run to run (mean absolute difference 0.4 to 1.7 ticks between sets), so two sets share only 19 to 72 of 114 film ticks. Always match on `film_tick`; never pair captures by ordinal across sets.
  * *The reference is not deterministic at a fixed tick.* Reference-vs-reference SSIM over the 114 scored ordinals is 0.938 to 0.990, and over frames sharing an exact `film_tick` 0.939 to 0.997 (index equality 0.95 to 0.99 above the button bar). `ctry` and `ctry_r3` (140-frame runs) sit at 0.94 against the others while `ctry_r2` against `ctry_r4` (124-frame runs) is 0.997. The cause is not identified (`[Hypothesis]`: state that is not the film clock, such as the cursor or wall-clock effects). Practical reading: a parity score above about 0.95 cannot be told apart from the capture's own noise, so the 0.88 and 0.90 gates are reachable but the ceiling is not 1.0.
  * Method: palette to Rec. 601 luminance, 320x200 stretched to 320x240, the comparator's 11x11 windows with stride 8, rows 0 to 221 only (above the button bar), windows with no variance on either side counted as 1.0.
* **The 0.002 adoption floor is a policy bound, not a noise model (`[Bounded Observation]`).** Three binaries built separately from the same code scored 0.7706, 0.7708 and 0.7718 `mean_ssim_scored` on `CTRY.FLM`, while two separate processes rendering the same ticks wrote byte-identical `.idx` planes. Identical builds therefore render identically, so the spread is build-level floating-point variation, and a margin under 0.002 SSIM between two runs is not attributable to a render change. The floor is a policy choice derived from that spread, not a statistical confidence interval.
* **One captured palette is not like the others (`[Bounded Observation]`).** In the `INTRO.FLM` set, ordinal 69 (tick 1516) carries a palette with 126 of 253 entries live: indices 0 to 135 are black while 136 to 255 keep their normal colours, and both neighbours are normal. The only other blacked-out palettes in either set are the end-fade tails (`CTRY` ordinals 122 to 140, `INTRO` 213), which the fade floor already excludes. That frame agrees with the render on 0.642 of its palette indices yet scores SSIM 0.019, which only a palette difference explains, since the render's surface choice (sand, index 91) is the capture's. Whether `PLAYONE` blanks its palette for one retrace during a page switch, or the harness read a half-updated palette, is `[Unknown]`; the frame stays scored and the anomaly is recorded rather than repaired.

### 3.1 Captures from dosbox-automation

`[Bounded Observation]`, 2026-10-30. `capture-ref` now plans a run rather than stepping a halted guest ([`../playone-exe/capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md)). Three consequences for reading a score:

* **Palette.** A page's palette is the working palette at `DS:0x2768` (6-bit, expanded as `round(v * 255 / 63)`), not a DAC read. `PLAYONE` writes the DAC in two retrace-gated halves, so the DAC shown with the page read at frame *f* is the working palette of *f* - 1 in its low half (indices below 128) and of *f* - 2 in its high half (one `CTRY.FLM` fade, five steps, exact; [`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.5). It equals the working palette of *f* unless the palette changed at *f* or *f* - 1, and `pick` skips those two frames ([`plan.usable`](../../python/stunt_reel/tac/plan.py)), so every kept page's working palette is its DAC. `meta.json` counts the palette steps (`palette_steps`).
* **Tears.** The page is read between emulated frames without waiting for retrace, so the callback can land inside `PLAYONE`'s copy of a composed page to `A000`. The game keeps two composed pages (segments at `DS:0x22CA` and `0x22CC`), and rows 0–191 of a finished page equal one of them; a page whose 8-row bands match only one in some places and only the other in others is torn. The trace tests every frame this way and `pick` passes over a torn frame, so the next changed frame (*f* + 1 in practice) takes its place, and a page whose own dump pass marks it unusable (replay jitter can move a tear onto it) is dropped. `meta.json` counts torn frames (`torn_frames`). The earlier rule, matching a video frame in *f* - 2 to *f* + 4, needed an AVI per film and decoded ambiguously, because the video is scanned out while the emulator runs (§ 4.5 of the capture note).
* **Same film, new capture.** A full `CTRY.FLM` run on the new path (`captures/vault-ctry/frames/002`, 113 frames, stride 11 ticks) agrees with the DOSBox-X reference `001` on 0.951 of the first 60,000 page indices over the 37 film ticks the two share within one tick (8 exactly), with five frames under 0.90; that is inside the capture's own reference-versus-reference noise above. `references.toml` still names `001`: promoting `002` waits for a rescore that shows it is no worse. Captures now run at 45,000 cycles rather than `002`'s 7,000, so the page sits closer to its tick ([`../playone-exe/capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.4); a reference to promote should be captured at the current profile.

## 4. Dead ends

Approaches that were tried and dropped. Each is recorded so it is not tried again without new evidence.

### 4.1 Fade scoring

* **Fade level from the frame's own indices.** Choosing the index set from the frame being measured fails on faded frames: the only entries still bright enough to qualify are the cursor and button-bar entries 240–255, which do not fade, so the median reads about 1.0. The set is fixed from the first captured frame instead (section 2.1) (`[Bounded Observation]`).
* **Compensating a render that already models the fade.** Once the renderer applied var 14, scaling its luminance by the fade level counted the fade twice: compensated SSIM stayed at 0.617 while raw SSIM rose from 0.495 to 0.667. Compensation was retired in `8cabb2a` (section 2.1) (`[Bounded Observation]`).
* **Scoring the black tail.** Without a floor, near-black frames score high against each other (about 0.92), which inflates the mean without saying anything about the scene. The `CTRY.FLM` tail at ticks 1337–1342 has 6 distinct RGB values (59,929 black pixels plus 2,480 of (130,105,101)) and mean luminance 7.1. Hence `--min-fade-level` (`[Bounded Observation]`).
* **Fitting the fade ramp to the captures.** Fitting brightness to the same frames that are then scored is circular; the ramp comes from the film's `var_set` keys instead ([`palette-fade.md` § 5](../playone-exe/palette-fade.md)).
* **The fade floor at night.** The brightness heuristic misreads a night film as faded and excluded 29 of 30 `COL3-2.FLM` frames (section 2.1). No replacement; read the unscored mean.

### 4.2 Clock matching

* **Capture order or a fixed offset.** Matching captures to renders by capture ordinal, or by ordinal plus a constant (`TICK_TO_FRAME_OFFSET = 1`, since removed), does not work, because ordinals are distinct pages, not ticks (section 1, step 1). Matching uses `film_tick`.
* **The three clocks.** A capture carries the global clock (`DS:0x22B8`), the film clock (`DS:0x4896`) and its capture ordinal. `global_tick - film_tick` is 2 or 3 in every frame of both capture sets (122 of 140 `CTRY.FLM` frames, 30 of 30 `COL3-2.FLM`), except the 18 `CTRY.FLM` end-hold frames, where the film clock stops at 1342 and the global clock runs on to 7140 (`[Bounded Observation]`). Neither offset can stand in for the film clock.
* **The "6-tick lag".** A ramp that looked 6–11 ticks late was the slice-start reading of `var_set` keys, not a delay in `PLAYONE` (section 3, *Fade mechanism*).

### 4.3 Masks

* **Sky IoU from one modal index.** Counting only the capture's most common sky index as sky inflated the filled area and understated IoU by about 0.12 on both `CTRY` and `INTRO`; replaced by the 227 to 238 band mask (section 2.0).

### 4.4 Per-second scoring of a video capture

A prototype of `stuntreel parity` (commit `d80e29e`, kept on branch `feat/video-parity-scorer`, not merged) scored a whole-film video capture ([`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.6) per film second. Each second contributed three samples, at film-second offsets 0, 17 and 33 ticks. Each sample searched render ticks −8 to +2 around its own tick for the best SSIM, the median of those local offsets became one film-wide offset, and every sample was then rescored at that offset. It was validated on 2026-10-31 and not adopted (`[Bounded Observation]`, one render, `CTRY.FLM` and `INTRO.FLM`):

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

## 5. Reading the results log

How to read the rows of [`log.md`](log.md), which holds only dated figures.

* **Superseded captures.** Reports made from `ctry_pre_filmclock` captures were keyed by capture ordinal, not film clock, and are superseded: they are not comparable to any row in [`log.md`](log.md), and the comparator now rejects a `meta.json` without `film_tick`. Recapture instead of converting.
* **Reading the `5799a53` row.** The overall mean fell only because 18 end-hold captures entered the average; over the 122 animated ticks the score equals the earlier rows. Compare rows over the same frame set (`--compare` reports the delta over the frames present in both).
* **Frames per `film_tick`.** All 18 end-hold captures share tick 1342; `--compare` keeps the first per tick, so a comparison covers 123 distinct ticks for this capture set (122 animated plus 1342).
* **Which headline a row quotes.** Rows before 2026-10-22 are over all frames. Until the renderer modelled the fade (`5bf6afe`) rows headline `mean_ssim_compensated`; from the retire-compensation row the headline is `mean_ssim_scored` over frames above the fade floor (section 2.1), always quoted with its scored-frame count. Every row is `[Bounded Observation]` (section 3).
