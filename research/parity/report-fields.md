---
summary: "The keys and JSON types of the parity reports `report.json` and `compare.json`, checked against `stuntreel parity` output on synthetic fixtures by the `report_doc.rs` test."
---
# Parity report fields: `report.json` and `compare.json`

What each key of the two JSON reports `stuntreel parity` writes holds. How the loop that writes them works is [`method.md`](method.md) § 1; the commands are [`docs/howto/score-a-render-change.md`](../../docs/howto/score-a-render-change.md).

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
| `archive_conflict_waived` | bool, optional | Present, and true, only when the render read another archive than the capture played and the run passed `--waive-archive-conflict` (a deliberate stand-in, such as a superset archive): the score was made across archives. Absent when the archives agree or either side records no archive hash. |
| `crates` | string or null, optional | The `crates/` git tree the render was built from, as `stuntreel parity --crates` was given it. `mise run parity` passes `git rev-parse HEAD:crates` when it built the binary and made the render itself on a clean `crates/`, and nothing for a `crates/` with uncommitted changes or a `--no-build`, `--no-render`, `--reuse` or `--retime` run, so the field is null there. Absent in older reports, which read as null. `mise run parity-repin` refuses a report whose `crates` is not the current tree. |
| `sha256` | string or null, optional | The reference capture's content hash (`references.toml` `sha256`) the score was made against, as `stuntreel parity --sha256` was given it. `mise run parity` passes the row's pin, so a report of a capture that was promoted since then records the old pin. Absent in older reports, which read as null. `mise run parity-repin` refuses a report whose pins are missing or differ from the row's. |
| `all_sha256` | string or null, optional | The reference film's archive pin (`references.toml` `all_sha256`) the score was made against, as `stuntreel parity --all-sha256` was given it; null when the row pins no archive. Absent in older reports, which read as null. |
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

**`verdict`** of `compare.json` (the regression verdict of [`method.md`](method.md) § 1, step 5):

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
