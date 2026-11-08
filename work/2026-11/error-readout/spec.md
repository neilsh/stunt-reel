# Error readout: Haiku grades each render's errors per film

Status: spec, approved 2026-11-01 after self-review; implemented in [#42](https://github.com/neilsh/stunt-reel/pull/42). Follows the error-category
probe ([`error-category-probe-2026-10-31.md`](error-category-probe-2026-10-31.md); results in
`research/parity/method.md` § 2.3), which showed that Haiku grades the categories in
`research/parity/error-categories.toml` as well as Sonnet does. This is the parity-scoring spec's stage 4,
fault readouts ([`parity-scoring-2026-10-31.md`](parity-scoring-2026-10-31.md)), by another route.

## Intent

After a render change, say which kinds of error the render makes, on how many frames, and whether that
went up or down since the last render, cheaply enough to run on every change. The probe did this with
throwaway scratch scripts; this spec makes it a repeatable step: build the sheets, have one Haiku
subagent grade them, score the grades, and compare them with an earlier readout.

What was said: Haiku does the grading; the categories must be easy to extend; `INTRO.FLM` skips its
first 20 seconds; example sheets for the categories live in the repo (user, 2026-10-31 and 11-01).
Everything else below is this spec's proposal.

## What the probe settled

- **Sheet:** capture and render side by side at 2x, labelled, the button bar (rows 185 and below)
  painted grey; below them the absolute luma difference ×3 and a close-up of the actors' bounding box
  (props if there are no actors), padded by 32. 1288×1020 pixels, which models downscale to about 94%;
  enough for every category except misregistration.
- **Grade line:** `<id> <category>=<0-3> ... | other: <text>`, every category present; 0 absent,
  1 minor, 2 clear, 3 dominates the frame.
- **What grading can see:** controls (recapture `005` in the render's place) come back clean and a
  removed aircraft is caught; a 4-row shift and a 5-tick advance are not. The readout sits beside
  section 2.2's metrics and the regression verdict and replaces neither.
- **Detection compares each category**, not the highest grade among them: removing the aircraft
  moves its grade from `aircraft-parts-missing=3` to `aircraft-absent=3`.

## Design

### 1. One file holds the categories, the films and the noise floor

`research/parity/error-categories.toml` keeps its `[[category]]` blocks (`id`, `definition`,
`examples`, `found_by`, `since`) and `[faults]` table, and gains:

- `[films.<film>]` with `start` and `end` ticks (`ctry` 0 to 990, `intro` 1000 to the end), so
  adding a film or moving a window is one edit, like adding a category;
- `[readout] min_change`, the smallest change in a category's count of frames graded 2 or more that
  `compare` reports. It starts at 2 and is replaced by the repeatability measurement (Acceptance).

### 2. Library: `python/stunt_reel/bench/errors.py`

Mirrors `judge.py`, which already turns a render into sheets for a subagent and scores its answers:

- `load_categories(path) -> Taxonomy`: categories in file order, faults, films, `min_change`.
  Rejects a duplicate category id, a `[faults]` key that is not a fault in `faults.py`, a fault naming
  an unknown category, and an example with no file in `research/parity/error-examples/`.
- `pick_ticks(report, capture, window, n=12) -> list[int]`: scored ticks with `fade_level >= 0.95`,
  inside `window`, held by the capture (and the recapture, when calibrating), spread evenly.
  Deterministic, so successive readouts grade the same frames.
- `build_sheet(capture_rgb, render_rgb, layer) -> PIL.Image`: the probe's layout.
- `sheet_id(seed, kind, fault, tick) -> str`: 12 hex characters of a SHA-256, as `judge._item_id`.
  The key is recomputed from the seed when scoring, so no key file sits beside the sheets.
- `render_brief(taxonomy, sheet_dir) -> str`: the probe's grading brief, categories in file order,
  telling the grader to write `grades.txt` in `sheet_dir`.
- `parse_grades(text, taxonomy) -> Grades`: per sheet id, a grade or `None` per category. A missing
  category is ungraded (`None`, never 0); an unknown category is reported and kept apart; a grade
  outside 0–3 or a line without an id is an error naming the line; sheets with no line are counted.
- `readout(grades, key) -> Readout`: per category, the ticks graded 2 or more, the mean grade, and the
  `other` notes. `compare(before, after, min_change)` lists each category whose 2+ count moved by at
  least `min_change`, with the ticks that changed, and refuses two readouts made from different
  categories or ticks.
- `calibrate(grades, key, faults) -> Calibration`: pass bars from the probe, controls clean (every
  grade at most 1) on 10 of 12 and actors removed caught on 5 of 6; the shift and the advance are
  reported, not gated.

### 3. Commands, in `python/scripts/parity_bench.py`

- `errors-make --film <film> [--calibrate] [--recapture 005] [--seed N]`: writes
  `build/parity/bench/<film>/errors/` (beside `judge/`) with the sheets, `ids.txt`, `brief.md` and
  `run.json`. `run.json` records the film, ticks, seed, whether it calibrates, the revision
  (`git rev-parse HEAD`), a hash of the categories file, and a hash of the render's `.idx` files at
  those ticks, so a readout says which render and which categories it graded. Real frames only by
  default (12 sheets); `--calibrate` adds 12 controls and 18 planted faults (42).
- `errors-score --film <film> [--against <readout.json>]`: reads `grades.txt`, writes `readout.json`,
  and prints the table per category, the comparison when `--against` is given, and the calibration
  for a calibrating run.
- `errors-example --film <film> --tick <tick> --category <id>`: writes that tick's sheet to
  `research/parity/error-examples/<film>-<tick>.png` and adds it to the category's `examples`,
  which is how new examples are added under `NOTICE.md`'s rule.

All three run as `mise run parity-bench -- errors-…` and need the corpus; `mise run check` stays
corpus-free. The `parity-bench` task description lists them.

### 4. Grading: a step in the `improving-render-parity` skill

A script cannot dispatch a subagent, so grading is a skill step: after `errors-make`, dispatch one
Haiku subagent whose whole prompt is "Read `<brief.md>`: it is your whole instruction", then run
`errors-score`. A readout costs 12 image reads, a calibration 42. Calibrate again whenever the
categories, the sheet layout or the model change.

### 5. Recording and extending

A readout worth keeping (after a render change, or a calibration) gets a `log.md` row with its 2+
counts per category. When `other` notes name the same new kind of error on two or more frames, add a
category, give it an example with `errors-example`, and calibrate again.

### 6. The forced-choice judge goes

`judge.py`, `judge-make` and `judge-score` were the dropped arm of the metric bench (method.md
§ 2.2). The readout replaces them as the model-graded path, so they and their tests are removed;
method.md keeps the result. Cost if wrong: the judge is in git history.

## Tests (offline, synthetic)

- `load_categories` on the committed file passes; temp files with a duplicate id, an unknown fault
  key, a fault naming an unknown category, or a missing example file are each rejected.
- `parse_grades`: a missing category gives `None`; an unknown category is reported, not merged; a
  line without `| other:` is accepted; `=4`, `=x` and a line with no id are errors naming the line.
- `calibrate`: a planted sheet moving from `aircraft-parts-missing=3` to `aircraft-absent=3` counts
  as detected; one whose grades are unchanged does not.
- `compare`: synthetic readouts give the categories past `min_change` and none below it; readouts
  from different categories or ticks are refused.
- `build_sheet` on `tests/fixtures/parity/bench/`: 1288×1020, the bar rows grey in both panels.
- `render_brief`: every category id appears, in file order, in the table and in the example line.
- `sheet_id`: stable for the same inputs, distinct across kinds, faults and ticks.

## Acceptance

- **Calibration** on both films reproduces the probe within one sheet per check.
- **Repeatability:** Haiku grading the same 12 real sheets twice, per film, agrees within one grade
  on at least 95% of cells. The largest change in any category's 2+ count between the two runs, plus
  one, becomes `min_change`.

## Not in scope

- Calling the model through the Anthropic API from a script (needs a key and network; revisit if the
  readout should run in CI).
- Shrinking the sheet under the model's downscale limit, or sending the close-up as a second image;
  the probe worked at 94%.
- Grading misregistration; the numeric metrics cover it.

## Open questions

- Is 12 frames per film enough for a readout, or should it be 24 at twice the cost? Repeatability
  will show whether 12 leaves changes of 1–2 frames inside the noise.
- Should the batch survey (`batch.md`) run a readout on a few frames of each film?
