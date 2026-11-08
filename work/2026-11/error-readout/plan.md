# Error Readout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A repeatable per-film error readout: a script builds comparison sheets and a grading brief,
one Haiku subagent grades them against `research/parity/error-categories.toml`, and a scorer writes a
readout, compares it with an earlier one, and calibrates against controls and planted faults.

**Architecture:** One new module, `python/stunt_reel/bench/errors.py`, beside `judge.py`, which it
replaces: taxonomy loading, sheet planning and drawing, grade parsing, readout, compare and calibrate,
plus `make_run` / `score_run` that the script calls. `python/scripts/parity_bench.py` gains
`errors-make`, `errors-score` and `errors-example` and loses `judge-make` / `judge-score`. The
`improving-render-parity` skill gains the grading step, since only an agent can dispatch the subagent.

**Tech Stack:** Python 3.15 with `tomllib` (stdlib), numpy and Pillow (already in the dev group).

**Spec:** [`error-readout-2026-11-01.md`](error-readout-2026-11-01.md). The probe it follows is
[`error-category-probe-2026-10-31.md`](error-category-probe-2026-10-31.md); its results are
`research/parity/method.md` § 2.3.

## Global Constraints

- No new dependency; TOML is read with `tomllib` and written only by `add_example`'s line edit.
- Every agent-facing script runs through `mise run parity-bench`; its task description lists the
  subcommands.
- `mise run check` passes at the end of every task (AGENTS.md Directive 2); tests are offline and use
  `tests/fixtures/parity/bench/` and temp files only.
- Committed text files are written with `encoding="utf-8"` and `newline="\n"`.
- A research note never links into `docs/process/`; never write a capitalised word in square
  brackets in Markdown (the tier check reads it as an evidentiary tier; in signatures below, `Seq(Sheet)` means
  `Sequence[...]` of that type, written so for the same reason).
- Errors the user can cause raise `stunt_reel.bench.planes.BenchError`, which `parity_bench.main`
  prints and turns into exit code 1.
- Commit subjects are Conventional Commits with a body that says why; end with the gate line and
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Rulings on the spec

- **Planted faults** are the keys of the `[faults]` table, 6 frames each (`FAULT_FRAMES = 6`):
  `actors_removed` on the first 6 picked ticks whose render has actor pixels (`.layer >= 16`), the
  others on `random.Random(seed).sample(ticks, 6)`, as the probe did. A fault key the table names but
  `faults.ALL_FAULTS` lacks is already rejected by `load_categories`.
- **Pass bars scale with the sheet counts**: controls pass at `clean >= ceil(10/12 * n)`, actors
  removed at `detected >= ceil(5/6 * n)`, so a window with fewer than 12 ticks still calibrates.
- **The run record (`run.json`) sits beside the sheets** but holds no id-to-kind mapping, so the
  grader learns nothing from it; the key is recomputed by `plan_sheets` at scoring time.
- **Example sheets are never overwritten**: `errors-example` reuses an existing file of the same
  name and only adds the name to the category.

## Review Focus

1. The render tree changed between `errors-make` and `errors-score` (a new `mise run parity`):
   scoring must refuse, naming both hashes, rather than score grades against different pictures.
2. Haiku's `grades.txt` wraps lines in a code fence, backticks the ids, uses CRLF or leaves blank
   lines: all tolerated; a sheet id graded twice is an error naming the id.
3. A film window holding fewer than 12 scored, unfaded ticks yields fewer sheets; none yields a
   `BenchError` naming the film and window.
4. `--against` names a readout made before a category was added: `compare` refuses, naming both
   categories hashes; a category added since a run shows as ungraded, never 0.
5. `--calibrate` with a recapture that lacks some picked ticks: ticks are picked from those both
   captures hold, so every control sheet has a recapture frame.

---

### Task 1: The categories file and its loader

**Files:**
- Modify: `research/parity/error-categories.toml`
- Create: `python/stunt_reel/bench/errors.py`
- Create: `tests/test_bench_errors.py`

**Interfaces:**
- Produces:
  - `Category(id: str, definition: str, examples: tuple[str, ...])` (frozen dataclass)
  - `FilmWindow(start: int, end: int | None)`; `FilmWindow.holds(tick: int) -> bool` (`end` exclusive)
  - `Taxonomy(categories: tuple[Category, ...], faults: dict[str, tuple[str, ...]], films: dict[str, FilmWindow], min_change: int, digest: str)`; `Taxonomy.ids -> tuple[str, ...]`
  - `load_categories(path: Path, examples_dir: Path | None = None) -> Taxonomy` (`examples_dir` defaults to `path.parent / "error-examples"`; `digest` is the SHA-256 hex of `"
".join(f"{id}	{definition}")` over the categories in order, so it changes with what graders are shown and not with examples, comments or `min_change`)
  - `add_example(path: Path, category: str, name: str) -> None`

- [ ] **Step 1: Extend the TOML.** Append, after `[faults]`:

```toml
# Tick windows the readout picks frames from (end exclusive; omitted = to the end of the film).
[films.ctry]
start = 0
end = 990

[films.intro]
start = 1000

# compare reports a category only when its count of frames graded 2+ moves by at least this much.
# Set by the repeatability run (research/parity/method.md section 2.3).
[readout]
min_change = 2
```

  Then edit the header comment's last paragraph to say the file also holds the films' windows and
  the readout's `min_change`.

- [ ] **Step 2: Write the failing tests** in `tests/test_bench_errors.py`:
  - `test_committed_categories_load`: `load_categories(REPO / "research/parity/error-categories.toml")`
    returns 15 categories, `ids[0] == "aircraft-parts-missing"`, `ids[-1] == "explosion-missing"`,
    `films["intro"] == FilmWindow(1000, None)`, `min_change == 2`, `len(digest) == 64`.
  - `test_digest_ignores_examples`: on a temp copy, `add_example` leaves `digest` unchanged; editing
    one definition changes it.
  - `test_rejects_bad_files` (parametrised over four minimal temp files, each built from a valid
    two-category file): a duplicate id; a `[faults]` key `"wobble:3"`; a fault naming
    `"no-such-category"`; an example `"ctry-0001"` with no PNG in `examples_dir`. Each raises
    `BenchError` whose message contains the offending id, key or example name.
  - `test_add_example_edits_one_block`: on a temp copy holding categories `a` (`examples = []`) and
    `b` (`examples = ["x"]`), `add_example(path, "b", "y")` leaves `a`'s line unchanged, makes `b`'s
    `examples = ["x", "y"]`, keeps every comment line, and adding `"y"` again changes nothing;
    `add_example(path, "zzz", "y")` raises `BenchError`.

- [ ] **Step 3: Run them to see them fail**

Run: `mise exec -- uv run pytest tests/test_bench_errors.py -q`
Expected: FAIL, `ModuleNotFoundError: stunt_reel.bench.errors`

- [ ] **Step 4: Implement** the Task's interfaces in `errors.py`, with a module docstring saying what
  the readout is and that the key is recomputed from the seed. `add_example` edits text, not TOML: it
  finds the line `id = "<category>"` and rewrites the first `examples = [...]` line after it, before
  the next `[[category]]`.

- [ ] **Step 5: Run the tests to see them pass**, then `mise run check-py`.

- [ ] **Step 6: Commit** `feat(bench): load the render-error categories`.

### Task 2: Planning and drawing the sheets

**Files:**
- Modify: `python/stunt_reel/bench/errors.py`
- Modify: `tests/test_bench_errors.py`

**Interfaces:**
- Consumes: `Taxonomy`, `FilmWindow` (Task 1); `faults.ALL_FAULTS`, `faults.plant`, `planes.RenderTree`,
  `planes.load_capture`, `planes.CapturePlanes`, `ssim.stretch`, `parity_artifacts.read_report`.
- Produces:
  - `Sheet(id: str, kind: Literal["real", "control", "planted"], tick: int, fault: str | None)`
  - `pick_ticks(report: Report, held: Collection[int], window: FilmWindow, n: int = 12) -> list[int]`
  - `sheet_id(seed: int, kind: str, fault: str | None, tick: int) -> str`
  - `plan_sheets(ticks: Sequence[int], tree: RenderTree, taxonomy: Taxonomy, seed: int, calibrate: bool) -> Seq(Sheet), a list`
  - `build_sheet(capture_rgb: NDArray[np.uint8], render_rgb: NDArray[np.uint8], layer: NDArray[np.uint8]) -> Image.Image`
  - `render_brief(taxonomy: Taxonomy, sheet_dir: Path, count: int) -> str`
  - `idx_digest(render: Path, ticks: Sequence[int]) -> str`

- [ ] **Step 1: Write the failing tests:**
  - `test_pick_ticks_spreads_and_filters`: a synthetic `Report` with scored ticks 0..99, `fade_level`
    0.5 on ticks 40–49 and `scored=False` on 50; `held` = all; window `FilmWindow(10, 90)`; n=12 →
    12 ticks, all in 10–89, none in 40–50, first 10, sorted, deterministic across calls. With
    `held={20, 30}` → `[20, 30]`. With window `FilmWindow(200, None)` → `[]`.
  - `test_sheet_id_is_stable_and_distinct`: equal inputs give equal 12-hex ids; changing seed, kind,
    fault or tick changes it.
  - `test_plan_sheets_counts`: on the bench fixture's render (ticks 10 and 20) with the committed
    taxonomy: `calibrate=False` gives 2 real sheets; `calibrate=True` gives 2 real, 2 control and,
    per fault key, `min(6, eligible)` planted sheets with `fault` set to that key.
  - `test_build_sheet_layout`: from the fixture's tick-10 capture and render: size `(1288, 1020)`;
    the button bar (rows 222–239 of each 240-row panel, i.e. image rows `26 + 2*222` to `26 + 480`)
    is grey 128 in both top panels.
  - `test_render_brief_lists_categories`: every category id appears in the table and in the example
    line, in file order; the text names `sheet_dir / "grades.txt"` and the count.
  - `test_idx_digest_changes_with_render`: equal for the same tree, different after one byte of a
    copied tree's `tick_00010.idx` changes.

- [ ] **Step 2: Run them to see them fail** (`mise exec -- uv run pytest tests/test_bench_errors.py -q`).

- [ ] **Step 3: Implement.** `pick_ticks`: frames with `scored` and `fade_level` (None counts as 1)
  `>= 0.95`, in the window and in `held`, sorted; return all if fewer than n, else
  `ticks[round(i * (len - 1) / (n - 1))]` for i in range(n). `plan_sheets` lists every sheet the
  key holds; `make_run` (Task 4) skips a planted sheet whose `plant` returns `None`, so it is
  missing from `ids.txt` and scored as ungraded. `sheet_id`: first 12 hex characters of
  SHA-256 of `f"{seed}:{kind}:{fault}:{tick}"`. `idx_digest`: SHA-256 over the bytes of
  `tick_{tick:05d}.idx` in tick order. The sheet layout, copied from the probe:

```text
panels: capture and render, each stretch()ed to 320x240, the rows from 222 down set to 128,
        enlarged 2x (nearest), with a 26-pixel white label strip above:
        "CAPTURE (the original game)" and "RENDER (our reimplementation)"; font
        ImageFont.load_default(size=20), black, at (4, 2)
row 1:  capture panel | 8-pixel gap | render panel                       -> 1288 wide
row 2:  8 pixels below row 1. Left: the difference panel, |luma(cap) - luma(ren)| * 3 clipped
        to 255 (luma = 0.299 R + 0.587 G + 0.114 B), grey, labelled "DIFFERENCE |capture -
        render| (brighter = more different; grey band = UI bar, ignore)".
        Right: the close-up, 640x506 white, labelled "CLOSE-UP of <aircraft/actors|props>:
        CAPTURE (left) | RENDER (right), <k>x": box = bounding box of layer240 >= 16, else of
        layer240 == 3, padded 32 and clipped to x 0..320, y 0..222; k = max(1, min((320 - 8)
        // width, 480 // height)); capture crop at x 0, render crop at x 324, both at y 26.
        With no box, the label reads "CLOSE-UP: no aircraft or props in frame".
```

  `render_brief` returns exactly this text, with `{table}` one `| \`id\` | definition |` row per
  category and `{example}` the ids joined as `id=0`:

```text
# Brief: grade the render errors

You are comparing frames from *Stunt Island* (1992), a DOS game that replays filmed aircraft stunts. Each
image is one moment of a film shown two ways: **CAPTURE** (top left) is the original game's screen, and
**RENDER** (top right) is a reimplementation that should match it exactly. Below them: a **DIFFERENCE**
image (brighter = more different) and a **CLOSE-UP** of the aircraft area, capture left, render right.
The grey band at the bottom of each panel is the game's button bar, masked out: ignore it. Some RENDER
panels may match the capture closely; grade what you see, not what you expect.

Folder: `{sheet_dir}/` (written with `as_posix()`). `ids.txt` lists {count} image ids; each image is `<id>.png` in that folder.
Read only `ids.txt` and those images, in the listed order. Do not read any other file and do not
dispatch subagents.

## Categories

| Category | Definition |
|---|---|
{table}

## Grades

0 = absent; 1 = minor, seen only on a close look; 2 = clear; 3 = dominates the frame.

## Output

One line per image, in `ids.txt` order, every category present, then `| other:` and either `none` or
a few words on any error no category covers:

`<id> {example} | other: none`

Write the lines, and nothing else, to `{sheet_dir}/grades.txt`.
Your final message is only the number of lines written.
```

- [ ] **Step 4: Run the tests to see them pass**, then `mise run check-py`.

- [ ] **Step 5: Commit** `feat(bench): plan and draw error-readout sheets`.

### Task 3: Grades, readout, compare and calibration

**Files:**
- Modify: `python/stunt_reel/bench/errors.py`
- Modify: `tests/test_bench_errors.py`

**Interfaces:**
- Consumes: `Taxonomy` (Task 1), `Sheet` (Task 2).
- Produces:
  - `SheetGrades(grades: dict[str, int | None], unknown: dict[str, int], other: str)`
  - `parse_grades(text: str, taxonomy: Taxonomy) -> dict[str, SheetGrades]`
  - `CategoryReadout(category: str, ticks_2plus: tuple[int, ...], mean: float | None, ungraded: int)`
  - `Readout(film: str, ticks: tuple[int, ...], categories_digest: str, render_digest: str, categories: tuple[CategoryReadout, ...], other: dict[int, str], missing: int, unknown: tuple[str, ...])` with `to_json() -> dict[str, Any]` and `Readout.from_json(doc: dict[str, Any]) -> Readout`
  - `readout(grades: dict[str, SheetGrades], sheets: Seq(Sheet), film: str, categories_digest: str, render_digest: str) -> Readout` (real sheets only)
  - `Change(category: str, before: int, after: int, added: tuple[int, ...], removed: tuple[int, ...])`
  - `compare(before: Readout, after: Readout, min_change: int) -> list of Change`
  - `Calibration(controls_clean: int, controls: int, faults: dict[str, tuple[int, int]], passes: bool)` (fault key to (detected, sheets))
  - `calibrate(grades: dict[str, SheetGrades], sheets: Seq(Sheet), taxonomy: Taxonomy) -> Calibration`

- [ ] **Step 1: Write the failing tests:**
  - `test_parse_grades_tolerates_fences_and_backticks`: lines inside a ```` ``` ```` fence, a
    backticked id, CRLF endings and blank lines parse; a line without `| other:` gives `other == ""`.
  - `test_parse_grades_missing_category_is_ungraded`: a line lacking `aircraft-absent` gives
    `grades["aircraft-absent"] is None`; `wobble=2` lands in `unknown`, not `grades`.
  - `test_parse_grades_rejects` (parametrised): `=4`, `=x`, a line starting with `=`, and the same id
    twice each raise `BenchError` whose message contains the line or the id.
  - `test_calibrate_counts_a_moved_grade`: real sheet at tick 5 with `aircraft-parts-missing=3`,
    planted `actors_removed` at tick 5 with `aircraft-parts-missing=0 aircraft-absent=3` → detected;
    a planted sheet equal to its real sheet → not detected; a planted sheet with a new `other` note
    → detected.
  - `test_calibrate_pass_bars`: 12 controls of which 10 clean and actors removed 5 of 6 → `passes`;
    9 clean → not; 2 controls with 2 clean and 2 of 2 actors → `passes` (bars scale).
  - `test_readout_counts_and_roundtrips`: three real sheets graded 2, 1 and missing for one category
    → `ticks_2plus` the first tick, `mean == 1.5`, `missing == 1`; `Readout.from_json(r.to_json()) == r`.
  - `test_compare_reports_past_min_change`: counts 3 → 6 reported with `added` ticks; 3 → 4 with
    `min_change=2` not reported; differing `categories_digest` or `ticks` raise `BenchError`
    naming both digests or the tick difference.

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.** Parsing: skip blank lines and lines starting with ```` ``` ````; strip
  backticks; split at the first `| other:`; the first token is the id; each further token is
  `name=digit` (else error). Detection compares, per category the fault names in `[faults]`, the
  planted grade with the same tick's real grade, counting only categories graded on both; a non-empty
  `other` other than `none` (case-insensitive) that differs from the real sheet's counts too. A
  control is clean when every graded value is at most 1. Missing sheets count against neither side's
  numerator but stay in the denominators.

- [ ] **Step 4: Run the tests to see them pass**, then `mise run check-py`.

- [ ] **Step 5: Commit** `feat(bench): score error-readout grades`.

### Task 4: Commands, and the judge goes

**Files:**
- Modify: `python/stunt_reel/bench/errors.py` (add `make_run`, `score_run`, `write_example`)
- Modify: `python/scripts/parity_bench.py`
- Modify: `python/stunt_reel/bench/__init__.py` (docstring, if it names the judge)
- Modify: `mise.toml` (`[tasks.parity-bench]` description)
- Delete: `python/stunt_reel/bench/judge.py`, `tests/test_bench_judge.py`
- Modify: `tests/test_bench_errors.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces:
  - `make_run(film: str, capture: Path, recapture: Path | None, render: Path, report: Path, out: Path, taxonomy_path: Path, seed: int, revision: str) -> int` (sheets written; `recapture` given means calibrate). Writes `out/<id>.png`, `out/ids.txt` (ids shuffled by `random.Random(seed)`), `out/brief.md`, `out/run.json` = `{film, ticks, seed, calibrate, revision, categories_digest, render_digest}`; clears stale `*.png`, `grades.txt` and `readout.json` from `out` first.
  - `score_run(out: Path, render: Path, taxonomy_path: Path, against: Path | None) -> tuple[Readout, list of Change | None, Calibration | None]`; writes `out/readout.json`. Refuses (`BenchError`) when `idx_digest(render, ticks)` differs from `run.json`'s, or `categories_digest` differs from the current file's, naming both values.
  - `write_example(film: str, tick: int, category: str, capture: Path, render: Path, taxonomy_path: Path) -> Path`

- [ ] **Step 1: Write the failing tests** (on the bench fixture and a synthetic report, as
  `test_bench_judge.py` builds one):
  - `test_make_then_score_roundtrip`: `make_run` writes 2 sheets, `ids.txt`, `brief.md`, `run.json`
    and no file mapping ids to kinds; a `grades.txt` written from the ids scores to a `Readout` with
    those ticks, and `readout.json` exists.
  - `test_score_refuses_changed_render`: after `make_run`, copy the render, change one byte of
    `tick_00010.idx`, score against the copy → `BenchError` naming both digests.
  - `test_make_run_empty_window`: a taxonomy copy whose film window holds no fixture tick →
    `BenchError` naming the film and window.
  - `test_calibrate_run_picks_ticks_both_captures_hold`: with a recapture holding only tick 10, a
    calibrating `make_run` plans sheets for tick 10 only.
  - `test_write_example_keeps_existing_file`: writes `<film>-<tick:04d>.png` into a temp examples dir
    and adds the name; a second call leaves the file's bytes unchanged.

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement** the three functions, then the subcommands in `parity_bench.py`,
  resolving paths as `run()` does (`references.reference_dir`, `parity_layout.frames_path` for
  `--recapture`, default `005`, `parity_layout.render_dir`, `report_dir`), out dir default
  `REPO_ROOT / "build/parity/bench" / film / "errors"`, taxonomy default
  `REPO_ROOT / "research/parity/error-categories.toml"`, revision from `git rev-parse HEAD`:
  - `errors-make --film F [--calibrate] [--recapture ID] [--seed N] [--out DIR] [--render DIR] [--report FILE] [--data-root DIR]`, printing `[bench] wrote N sheets and brief.md into OUT`;
  - `errors-score --film F [--against FILE] [--out DIR] [--render DIR]`, printing one row per
    category (`id`, frames graded 2+ of total, mean), the `other` notes, then the changes or the
    calibration when there are any;
  - `errors-example --film F --tick T --category ID [--data-root DIR] [--render DIR]`.
  Add `errors-make` and `errors-example` to the commands that call `ensure_links_or_report`; remove
  `judge-make`, `judge-score`, their imports and the docstring lines; rewrite the docstring's
  subcommand list and the `mise.toml` description to name `run`, `plant`, `errors-make`,
  `errors-score` and `errors-example`. Delete `judge.py` and its test.

- [ ] **Step 4: Check nothing else uses the judge**

Run: `git grep -n "judge" -- python tests mise.toml`
Expected: only `tests/test_prek_hooks.py` (unrelated wording) and `metrics.py`'s "to be judged on".

- [ ] **Step 5: Run the tests**, then `mise run check`.

- [ ] **Step 6: Commit** `feat(bench): error-readout commands replace the forced-choice judge`.

### Task 5: The grading step in the parity skill, and the docs

**Files:**
- Modify: `.agents/skills/improving-render-parity/SKILL.md`
- Modify: `research/parity/method.md` (§ 2.3, last paragraph)

- [ ] **Step 1: Add a section** `## Error readout` before `## Finishing an item`, at most 12 lines:
  when to run it (after an adopted render change, both films); the checklist
  `errors-make` → dispatch one Haiku subagent whose whole prompt is
  "Read `build/parity/bench/<film>/errors/brief.md`: it is your whole instruction" →
  `errors-score --against <the previous readout.json, copied aside before errors-make>`;
  calibrate (`--calibrate`, 42 sheets) only when the categories, the sheet layout or the model
  change; a new kind named in `other` on two or more frames becomes a category plus an
  `errors-example`. Follow the `writing-for-agents` skill for wording.

- [ ] **Step 2: Add to method.md § 2.3** one paragraph: the readout runs as
  `mise run parity-bench -- errors-make` / `errors-score` and its procedure is in the skill. No link
  into `docs/process/`.

- [ ] **Step 3:** `mise run check`, then commit `docs(parity): run the error readout from the parity skill`.

### Task 6: Calibration and repeatability (controller, needs the corpus)

Run by the controller, not an implementer: it needs the data root and dispatches Haiku subagents.

- [ ] **Step 1: Calibrate both films.** For `ctry` and `intro`: `mise run parity-bench --
  errors-make --film F --calibrate`, one Haiku subagent on the brief, `errors-score --film F`.
  Pass: controls and actors removed meet their bars, and each check is within one sheet of
  method.md § 2.3's Haiku column.
- [ ] **Step 2: Repeatability.** For each film: `errors-make --film F`, grade, `errors-score`, copy
  `readout.json` aside; grade the same sheets again with a fresh Haiku subagent (delete
  `grades.txt` first), `errors-score --against` the copy. Pass: the two `grades.txt` agree within
  one grade on at least 95% of graded cells (a few lines of Python in `build/scratch/`).
- [ ] **Step 3: Set `min_change`** in `error-categories.toml` to the larger film's largest change in a
  category's 2+ count between the two runs, plus one.
- [ ] **Step 4: Record.** A `log.md` row with the calibration and repeatability numbers per film and
  the new `min_change`; one sentence in method.md § 2.3. Then `mise run check` and commit
  `docs(parity): calibrate the error readout and set its noise floor`.
