# Batch Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mise run batch-parity` takes every distinct `.FLM` in the corpus through four stages (generate `.ALL`, capture `PLAYONE.EXE`, render, score), keeps the example frames, and records every failure in a ledger it can resume from.

**Architecture:** Three small pure modules (ledger, film manifest, stage runners) and one driver script. The driver runs each stage for each film as the existing tool would (`make_all.py`, `capture_playone_reference.py` as subprocesses with a timeout; the release `stuntreel` binary for render and score), writes one ledger line per stage, and skips a stage whose latest ledger line is `ok`. No Rust change. Nothing is added to `references.toml`: a batch score is a survey, not a pinned reference.

**Tech Stack:** Python 3.12, pytest, `uv` through `mise`, DOSBox-X through the existing `tac` package.

**Spec:** none; this plan is the design. Background: [ADR 0023](../../adr/0023-make-all-generates-archives-with-makeone.md), [ADR 0024](../../adr/0024-captures-are-filed-by-film-then-kind.md), [`research/parity/method.md`](../../../research/parity/method.md) section 1.2.

## Global Constraints

- Offline tests only: nothing under `tests/` reads `corpus/` or starts DOSBox-X. Build files in `tmp_path` and inject fake runners (AGENTS.md directive 1).
- Nothing writes under `corpus/`. Archives and captures go only where `make_all.py` and `capture_playone_reference.py` already put them (`captures/<slug>/archives|frames/<run>/`, ADR 0024).
- Path literals `build/parity` and `build/scratch` appear only in `python/stunt_reel/parity_layout.py`. Add the batch directory there, and add each new module to `CALLERS` in `tests/test_parity_layout.py`.
- Keep `__all__` lists sorted. Use `encoding="utf-8"` on every text read and write.
- Run `mise run check-py` while iterating and `mise run check` once before the last commit. Stage files by name; never `git add -A`; never anything under `corpus/` (AGENTS.md SOP 3).
- Commits: Conventional Commit subject, a body that says why, `mise run check passes.`, then the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Render flags are `RENDER_FLAGS` from `python/stunt_reel/parity_pipeline.py`; the SIDATA directory is `corpus/siarchive/Developer/FreeFlight/SIDATA` (as in `parity_pipeline.FILMS`). Score with `stuntreel parity --reference <capture dir> --test <render dir> --output <report dir>`.
- A real run costs minutes per film (MAKEONE plays the film in real time, and so does the capture). One DOSBox-X at a time. Never run the full batch in the foreground: use `run_in_background`.

## Review Focus

1. A film whose `MAKEONE` run never returns or fails (custom shapes missing from `RES`): the stage records `error` with the message, and the next film still runs.
2. The same film present in several corpus folders (`NewPLAY`, `OldPLAY`, `Morganroth`): it is processed once, chosen by content hash.
3. Two different films with the same folder and stem (same slug): the second gets a distinct `--name`, so it never becomes run 002 of the first.
4. A film that already has a sibling `.ALL`: the archive stage is `skipped`, not run, and later stages use that `.ALL`.
5. A rerun after a crash: finished stages are not repeated; a stage whose latest line is `error` is retried only with `--retry-errors`.

---

## File Structure

- Create `python/stunt_reel/batch_ledger.py`: append-only JSONL ledger of stage outcomes and its summary.
- Create `python/stunt_reel/batch_films.py`: finds the corpus films, drops duplicates, assigns each a slug and archive status.
- Create `python/stunt_reel/batch_stages.py`: the four stage functions, each taking an injected runner.
- Create `python/scripts/batch_parity.py`: command line, loop, resume, summary; mise task `batch-parity`.
- Modify `python/stunt_reel/parity_layout.py`: `batch_root()` and `batch_film_dir(slug)`.
- Modify `mise.toml`: task `batch-parity`.
- Create `research/parity/batch.md` and add one row to `research/parity/log.md` (Task 5).
- Tests: `tests/test_batch_ledger.py`, `tests/test_batch_films.py`, `tests/test_batch_stages.py`, `tests/test_batch_parity_script.py`.

---

### Task 1: Batch directory and ledger

**Files:**
- Modify: `python/stunt_reel/parity_layout.py`, `tests/test_parity_layout.py` (`CALLERS`)
- Create: `python/stunt_reel/batch_ledger.py`, `tests/test_batch_ledger.py`

**Interfaces:**
- Produces, in `parity_layout.py`: `batch_root() -> Path` (`build/parity/batch`), `batch_film_dir(slug: str) -> Path` (`batch_root() / slug`, validated with `require_slug`).
- Produces, in `batch_ledger.py`:
  - `STAGES = ("archive", "capture", "render", "score")`
  - `@dataclass(frozen=True) class Record: slug: str; stage: str; status: str; message: str; seconds: float; at: str; ssim: float | None = None; iou: float | None = None`, where `status` is `"ok"`, `"error"` or `"skipped"`.
  - `append(path: Path, record: Record) -> None` (one JSON line, opened in append mode).
  - `read(path: Path) -> list[Record]` (missing file gives `[]`; a malformed line is skipped, not fatal).
  - `latest(records: list[Record], slug: str, stage: str) -> Record | None`.
  - `summarize(records: list[Record]) -> str`: counts of ok/error/skipped per stage, then one line per slug whose latest record for any stage is `error`, as `slug  stage  message`, then the 5 lowest and 5 highest SSIM among latest `score` records.

- [ ] **Step 1: Write failing tests** in `tests/test_batch_ledger.py`: `test_append_then_read_roundtrips`, `test_read_missing_file_is_empty`, `test_read_skips_a_malformed_line`, `test_latest_returns_the_last_record_for_slug_and_stage`, `test_summarize_lists_each_failed_slug_once_with_its_stage` (two errors for one slug at different stages, the later ok on the first stage: only the still-failing stage is listed).
- [ ] **Step 2: Run** `mise run test-py -- tests/test_batch_ledger.py`; expect FAIL (module missing).
- [ ] **Step 3: Implement** the interfaces above. Add `batch_root`/`batch_film_dir` to `parity_layout.py` next to `sweep_root`, and add `batch_ledger.py` to `CALLERS`.
- [ ] **Step 4: Run** the same command plus `tests/test_parity_layout.py`; expect PASS.
- [ ] **Step 5: Commit** `feat(parity): add the batch ledger`.

---

### Task 2: Film manifest

**Files:**
- Create: `python/stunt_reel/batch_films.py`, `tests/test_batch_films.py`

**Interfaces:**
- Consumes: `parity_layout.slug_for(film: Path, name: str | None = None) -> str`.
- Produces:
  - `@dataclass(frozen=True) class BatchFilm: slug: str; name: str | None; flm: Path; sha256: str; has_sibling_all: bool`. `name` is the `--name` override, `None` unless the slug collided.
  - `discover(corpus: Path) -> list[BatchFilm]`.

- [ ] **Step 1: Write failing tests** (build a fake corpus in `tmp_path` with small byte files): `test_finds_flm_files_of_any_case` (`a.FLM`, `b.flm`), `test_identical_content_is_listed_once_keeping_the_first_path_in_sorted_order`, `test_same_slug_different_content_gets_a_name_with_the_hash_suffix` (name is `f"{slug}-{sha256[:8]}"`; the first film keeps `name=None`), `test_sibling_all_is_detected_in_any_case` (`x.ALL`, `x.all`), `test_result_is_sorted_by_slug`.
- [ ] **Step 2: Run** `mise run test-py -- tests/test_batch_films.py`; expect FAIL.
- [ ] **Step 3: Implement** `discover`: walk `corpus` with `Path.rglob("*")` and a lower-cased suffix test, sort paths, hash with `hashlib.sha256`, skip repeated hashes, detect collisions on the slug.
- [ ] **Step 4: Run** the test file; expect PASS.
- [ ] **Step 5: Commit** `feat(parity): list the corpus films for the batch`.

---

### Task 3: Stage runners

**Files:**
- Create: `python/stunt_reel/batch_stages.py`, `tests/test_batch_stages.py`

**Interfaces:**
- Consumes: `BatchFilm`, `batch_ledger.Record`, `parity_layout.frames_root(slug)`, `parity_layout.archives_root(slug)`, `all_archive.resolve_all(flm: Path, root: Path, slug: str | None = None) -> Path` (raises `ArchiveMissing`), `parity_pipeline.RENDER_FLAGS`, `parity_pipeline.binary_path()`, `parity_artifacts.read_capture(path)` and `frames_for_captured_ticks(ticks)`, `report.json` reader `read_report(path).headline() -> (ssim, iou)` (find its module with `grep -n "def read_report" python/stunt_reel/*.py`).
- Produces: `Runner = Callable[[list[str], float], tuple[int, str]]` (command, timeout seconds, returns exit code and last 400 characters of combined output), and four functions, each returning a `Record` and never raising:
  - `run_archive(film: BatchFilm, root: Path, run: Runner, timeout: float) -> Record`: `skipped` when `has_sibling_all`; otherwise runs `python/scripts/make_all.py --film <flm> [--name <name>] --timeout <timeout>`.
  - `run_capture(film, root, run, timeout) -> Record`: runs `python/scripts/capture_playone_reference.py --film <flm> [--name <name>]`.
  - `run_render(film, root, run, timeout) -> Record`: latest capture dir for the slug, then `stuntreel --headless <flm> --all <resolve_all(...)> --frames <frames_for_captured_ticks> --sidata <SIDATA> --out-dir <batch_film_dir/render> + RENDER_FLAGS`.
  - `run_score(film, root, run, timeout) -> Record`: `stuntreel parity --reference <capture dir> --test <batch_film_dir/render> --output <batch_film_dir/report>`; on success the record carries `ssim` and `iou` from `report.json`.
  - Exit code non-zero, a timeout, a missing capture, or `ArchiveMissing` give `status="error"` with a one-line `message`. Exceptions inside a stage are caught and become `error` records.
- Use `sys.executable` for the two Python scripts and `Record.at = datetime.now(UTC).isoformat()`.

- [ ] **Step 1: Write failing tests** with a fake `Runner` that records commands: `test_archive_is_skipped_when_a_sibling_all_exists` (runner never called), `test_archive_command_carries_name_only_when_set`, `test_nonzero_exit_becomes_an_error_record_with_the_output_tail`, `test_a_runner_exception_becomes_an_error_record`, `test_capture_command_uses_the_film_path`, `test_render_without_a_capture_is_an_error_naming_capture`, `test_score_record_carries_ssim_and_iou` (write a minimal `report.json` fixture by copying the shape an existing test uses: `grep -rn "report.json" tests | head`).
- [ ] **Step 2: Run** `mise run test-py -- tests/test_batch_stages.py`; expect FAIL.
- [ ] **Step 3: Implement** the four functions in `batch_stages.py`. Add the module to `CALLERS`.
- [ ] **Step 4: Run** the test file; expect PASS.
- [ ] **Step 5: Commit** `feat(parity): add the batch stage runners`.

---

### Task 4: Driver script, summary, example frames

**Files:**
- Create: `python/scripts/batch_parity.py`, `tests/test_batch_parity_script.py`
- Modify: `mise.toml` (task `batch-parity`: `run = "uv run python python/scripts/batch_parity.py"`, description naming the flags)

**Interfaces:**
- Consumes: everything from Tasks 1 to 3.
- Produces: `main(argv: list[str] | None = None) -> int` and `process(films: list[BatchFilm], root: Path, ledger: Path, run: Runner, *, stages: tuple[str, ...], retry_errors: bool, limit: int | None, timeouts: dict[str, float]) -> int` (returns the number of stage errors).
- Flags: `--only SLUG[,SLUG]`, `--limit N` (films, after filtering), `--stages archive,capture,render,score` (default all four), `--retry-errors`, `--summary` (print `summarize` and exit), `--archive-timeout` (default 900), `--capture-timeout` (default 900), `--data-root`.
- Behaviour: for each film, run the requested stages in order. Skip a stage whose latest ledger record is `ok` or `skipped`, or `error` without `--retry-errors`. Stop a film's remaining stages after its first error and continue with the next film. Append every record to `batch_root()/ledger.jsonl` as it happens. After a successful `score`, copy the files in `batch_film_dir(slug)/report/` that match `*.png` into `batch_film_dir(slug)/frames/` (these are the contact sheets the comparator writes; do not print them).

- [ ] **Step 1: Write failing tests** with a fake runner and `tmp_path` ledger: `test_a_second_run_repeats_nothing`, `test_an_error_stops_that_film_but_not_the_next`, `test_retry_errors_reruns_only_failed_stages`, `test_only_and_limit_filter_the_films`, `test_stages_flag_runs_just_those_stages`, `test_summary_prints_and_runs_no_stage`, `test_contact_sheets_are_copied_after_a_successful_score`.
- [ ] **Step 2: Run** `mise run test-py -- tests/test_batch_parity_script.py`; expect FAIL.
- [ ] **Step 3: Implement** the script. The real `Runner` uses `subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=...)`, mapping `TimeoutExpired` to `(124, "timeout after Ns")`. Render and score use a timeout of 600.
- [ ] **Step 4: Run** `mise run check-py`; expect all PASS with zero warnings. Then `mise run batch-parity -- --summary`; expect an empty-ledger summary, exit 0.
- [ ] **Step 5: Commit** `feat(parity): add the batch-parity driver`.

---

### Task 5: Pilot, full run, findings

No code unless the pilot finds a bug (fix it test-first in the owning task's file and commit separately). Run from the repository worktree; `mise run init` has already linked the corpus.

- [ ] **Step 1: Build the binary once:** `mise run parity -- --films ctry` builds the release binary, renders and scores CTRY. Expected: a `[parity]` line with no error.
- [ ] **Step 2: Pilot** the two films that already have archives in the data root: `mise run batch-parity -- --only vault-balloon,vault-traintnl`. Expected: archive stage `skipped` or `ok` without a new archive (the stored archive is resolved), capture, render and score `ok` with an SSIM. Read the summary with `mise run batch-parity -- --summary`.
- [ ] **Step 3: Pilot five unseen films** with `--limit 5` (the manifest sorts by slug). Expected: each stage has a record; failures show a one-line message in the summary. Fix nothing yet: if a failure repeats across films, note it for Step 5.
- [ ] **Step 4: Full run in the background:** `mise run batch-parity` with `run_in_background`. Expect hours. On interruption, rerun the same command; add `--retry-errors` only after the cause is understood.
- [ ] **Step 5: Write `research/parity/batch.md`:** how to run, ledger location, the summary table from `--summary`, and the errors grouped by message (counts, one example slug each) under **Ruled out** and **Open questions** headings (SOP 2 shape). Add one row to the end of `research/parity/log.md` linking it. Use evidentiary tiers only as `research/README.md` allows.
- [ ] **Step 6: Run `mise run check`**, then commit `docs(parity): record the batch parity survey`. Do not commit anything from `build/` or `captures/`.

---

## Self-Review

- Coverage: generate `.ALL` (Tasks 3, 4), capture (3, 4), render and score with saved example frames (3, 4), error tracking (1, 4, 5).
- Names match across tasks: `BatchFilm`, `Record`, `Runner`, `run_archive|capture|render|score`, `process`, `batch_film_dir`.
- Open choice for the reviewer: the default covers every distinct film, including the ones with a sibling `.ALL`, because those are captured and scored too. Restrict with `--only` if a first pass should cover only the films that need a generated archive.
