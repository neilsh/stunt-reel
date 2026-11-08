# Captures layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the shared data root's captures to `captures/<film>/{frames,archives}/<run>/`, with film slugs derived from the source path and counter run ids.

**Architecture:** `parity_layout.py` stays pure and gains the slug and path functions; a new `runs.py` owns the one filesystem act, an atomic claim of the next run number. `references.toml` gains a `film` slug per entry, so the parity pipeline keeps asking for `ctry` and `intro`. A migration script moves the existing data and re-pins it.

**Tech Stack:** Python 3.x, pytest, ruff, mypy, `mise run` tasks. No Rust change.

**Spec:** [captures-layout-2026-10-29.md](captures-layout-2026-10-29.md)

## Global Constraints

- Tests are synthetic and offline; never commit anything from `corpus/` or the data root (AGENTS.md directive 1).
- `mise run check` passes before the last commit; iterate with `mise run check-py` (SOP 5).
- Stage files by name, never `git add -A`; Conventional Commit subjects with a body that answers why, ending `mise run check passes.` on the last task and with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- A capture or archive is written once into a new directory and never changed (ADR 0022).
- Slugs match `^[a-z0-9][a-z0-9_-]*$`; run ids are `NNN` (three digits, zero-padded, numeric order).
- Layout functions in `parity_layout.py` stay free of filesystem access.

## Review Focus

- Two captures of one film started together get different runs and neither overwrites the other (Task 2).
- A film path with spaces, punctuation or no parent folder makes a valid slug or is refused with a message naming `--name` (Task 1).
- The same film reached through a different corpus copy (`stisldem/VAULT` vs `stuntisl/VAULT`) gets the same slug (Task 1).
- Run `100` sorts after `099`, and `resolve_all` skips `.lock` and `.partial` entries (Task 4).
- A capture that fails before `meta.json` leaves no claimed directory behind (Task 5).
- The migration run twice is a no-op the second time, and aborts untouched when a pin does not match before it starts (Task 8).

---

### Task 1: Slug and path functions

**Files:**
- Modify: `python/stunt_reel/parity_layout.py`
- Test: `tests/test_parity_layout.py`

**Interfaces:**
- Produces: `film_slug(film: Path) -> str` (resolved path in; `<parent dir>-<stem>`, lower case, runs of characters outside `[a-z0-9_]` become `-`, ends trimmed; `ValueError` naming `--name` when the parent has no name or the result is empty), `require_slug(slug: str) -> str` (returns it, or `ValueError` when it fails the pattern), `run_id(number: int) -> str` (`7` becomes `"007"`), `RUN_WIDTH = 3`, `frames_path(slug: str, run: str) -> Path` (`build/parity/captures/<slug>/frames/<run>`), `archive_path(slug: str, run: str) -> Path` (`.../archives/<run>`), `frames_root(slug)` and `archives_root(slug)` (the same without the run). Old functions stay until Task 7.

- [ ] **Step 1: Write failing tests** `test_slug_is_parent_and_stem`, asserting `film_slug(Path("/d/corpus/stisldem/VAULT/CTRY.FLM")) == "vault-ctry"`, `film_slug(Path("/d/corpus/stuntisl/SIFILMS/VAULT/CTRY.FLM")) == "vault-ctry"`, `film_slug(Path("/d/x/MultiFLM/LaborDay/FLAGDAY1.FLM")) == "laborday-flagday1"`, `film_slug(Path("/d/x/Labor Day/My Film!.flm")) == "labor-day-my-film"`; `test_slug_without_a_parent_is_refused` (`Path("/FILM.FLM")` raises `ValueError` matching `--name`); `test_require_slug` (accepts `"vault-ctry"`, rejects `"All Films"`, `""`, `"-x"`); `test_run_id_and_paths` (`run_id(7) == "007"`, `frames_path("vault-ctry", "001") == Path("build/parity/captures/vault-ctry/frames/001")`, `archive_path(...)` ends in `archives/001`).
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_parity_layout.py -q`. Expected: the new tests FAIL (names undefined).
- [ ] **Step 3: Implement** the Interfaces above in `parity_layout.py`, add them to `__all__`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(layout): derive a film slug from its source path`.

### Task 2: Atomic run claim

**Files:**
- Create: `python/stunt_reel/runs.py`
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: `parity_layout.run_id`, `parity_layout.RUN_WIDTH`.
- Produces: `claim_run(parent: Path, suffix: str = "") -> str` — creates `parent/<NNN><suffix>` with a non-`exist_ok` `mkdir` for the lowest number above every existing `NNN`, `NNN.lock` and `NNN.partial` entry, retrying on `FileExistsError`, and returns the run id (`"001"`, without the suffix). `run_numbers(parent: Path) -> list[int]` — the numbers of finished runs (directories named exactly `NNN`), ascending.

- [ ] **Step 1: Write failing tests** `test_first_claim_is_001`, `test_claims_skip_lock_and_partial_entries` (with `002.lock` present the next claim is `003`), `test_concurrent_claims_are_distinct` (16 threads call `claim_run` on one `tmp_path`; the ids are 16 distinct values), `test_run_numbers_ignore_suffixed_entries`, `test_numbers_past_999_keep_numeric_order` (`run_numbers` with directories `099` and `1000` returns `[99, 1000]`).
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_runs.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** both functions; `claim_run` creates `parent` first with `parents=True, exist_ok=True`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(runs): claim the next run number atomically`.

### Task 3: References carry the film slug

**Files:**
- Modify: `python/stunt_reel/references.py`, `research/parity/references.toml` (shape only; Task 8 changes the values), `tests/test_references.py`, `tests/test_parity_pipeline.py:112,164,498`
- Test: `tests/test_references.py`

**Interfaces:**
- Consumes: `parity_layout.frames_path`, `parity_layout.require_slug`.
- Produces: `Reference` gains `slug: str` (field order `film, slug, capture_id, sha256`); `read_reference` requires a `film` string in the entry and validates it with `require_slug`; `reference_dir(root, film)` resolves `root / frames_path(pointer.slug, pointer.capture_id)`. The key and the `film` argument stay the parity short name (`ctry`).

- [ ] **Step 1: Write failing tests** in `tests/test_references.py`: `test_reference_dir_uses_the_slug` (entry `[ctry] film = "vault-ctry"`, capture `001`; the helper writes `frames_path("vault-ctry", "001")`; `reference_dir(tmp_path, "CTRY")` returns it), `test_entry_without_a_film_is_refused` (`ReferenceCaptureError` matching `film`), `test_invalid_slug_is_refused`. Update the existing helper and `test_parity_pipeline.py` call sites to write entries with `film` and to build paths with `frames_path`.
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_references.py tests/test_parity_pipeline.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the Interfaces; in `references.toml` add `film = "vault-ctry"` and `film = "vault-intro"` to the two entries now (values of `capture` and `sha256` unchanged until Task 8; the repo's own `test_references` must not read the real file).
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(references): name the capture directory by film slug`.

### Task 4: Archives under the slug

**Files:**
- Modify: `python/stunt_reel/all_archive.py:103-178`, `python/scripts/make_all.py:86-114`
- Test: `tests/test_all_archive.py`, `tests/test_make_all_script.py`

**Interfaces:**
- Consumes: `parity_layout.film_slug`, `archive_path`, `archives_root`, `runs.claim_run`, `runs.run_numbers`.
- Produces: `publish_archive(root: Path, slug: str, film: str, data: bytes, meta: ArchiveMeta) -> Path` — claims `claim_run(root/archives_root(slug), ".lock")`, writes `NNN.partial` (`<FILM>.ALL`, then `meta.json`), renames it to `NNN`, removes the lock in `finally`; returns the directory. `resolve_all(flm: Path, root: Path, slug: str | None = None) -> Path` — slug defaults to `film_slug(flm.resolve())`; scans `run_numbers` newest first; a sibling `.ALL` still wins. `make_all` gains `--name` (slug override, validated); its refusal message for a taken id goes (ids are always new). `ArchiveTaken` is kept only for a lock that cannot be created.

- [ ] **Step 1: Write failing tests**: `test_publish_lands_in_the_next_run` (two publishes give `001` then `002` under `archives/`, each holding `<FILM>.ALL` and `meta.json`), `test_resolve_prefers_the_newest_matching_run` (runs `099` and `100` with the same film hash resolve to `100`), `test_resolve_skips_lock_and_partial`, `test_make_all_names_the_slug_from_the_path_or_flag` (script test with the existing fake emulator; with `--name custom-film` the archive appears under `custom-film/archives/001`). Update the existing assertions that used `all_path`.
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_all_archive.py tests/test_make_all_script.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; keep the write order and the final `meta.json`-last guarantee.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(archive): publish archives as numbered runs under the film slug`.

### Task 5: Frame captures as numbered runs

**Files:**
- Modify: `python/scripts/capture_playone_reference.py:60-70,119-132,145-226`, `python/stunt_reel/tac/framebuffer.py` (`capture`)
- Test: `tests/test_tac_capture_session.py`

**Interfaces:**
- Consumes: `film_slug`, `require_slug`, `frames_root`, `runs.claim_run`.
- Produces: `capture_playone_reference` takes `--name SLUG`; without `--out` it runs `claim_run(resolve(frames_root(slug)))` and captures into that directory; a failure before `meta.json` removes the directory it claimed (it never removes a directory it did not claim, so `--out` behaves as today). `framebuffer.capture(..., provenance: Mapping[str, str] | None = None)` merges the mapping into the `meta.json` diagnostics; the script passes `{"captured_on": <ISO date, UTC>, "checkout": <sanitised checkout name>}`.

- [ ] **Step 1: Write failing tests**: `test_capture_claims_the_next_run` (two scripted captures of one synthetic film land in `001` and `002`), `test_a_failed_capture_leaves_no_run_directory`, `test_meta_records_when_and_where` (`captured_on` and `checkout` present beside the hashes), `test_explicit_out_still_refuses_a_taken_directory` (existing behaviour kept).
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_tac_capture_session.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; remove the stale-partial sweep in `is_taken` only for the claimed-directory path.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(capture): write each capture as a numbered run`.

### Task 6: Numbered files under `frames/` (cut point)

> This task changes the file contract stated in `tac/framebuffer.py`'s docstring and changes `capture_digest` (it hashes relative paths), so it re-pins the references in Task 8. It is last before cleanup so it can be dropped: skip this task and the "move files" and "rewrite meta" parts of Task 8.

**Files:**
- Modify: `python/stunt_reel/tac/framebuffer.py:80-140`, `python/stunt_reel/parity_artifacts.py:909-910`
- Test: `tests/test_tac_framebuffer.py` (existing; locate with `grep -l framebuffer tests`)

**Interfaces:**
- Produces: `capture` writes `frames/tick_NNNN.idx` and `frames/palettes_NNNN.json` under its output directory and records `"frames/tick_NNNN.idx"` as `frame_file` (and likewise `palette_file`); `parity_artifacts` defaults for a capture without explicit names become `frames/tick_{ordinal:04d}.idx` and `frames/palettes_{ordinal:04d}.json`; reading a capture with explicit bare names (the old layout) still works unchanged.

- [ ] **Step 1: Write failing tests**: `test_capture_writes_frames_in_a_subdirectory` and `test_meta_names_the_subdirectory`; `test_old_layout_capture_still_reads`.
- [ ] **Step 2: Run** the file's tests. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; update the docstring's contract sentence.
- [ ] **Step 4: Run** the file's tests plus `tests/test_parity_pipeline.py`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(capture): keep numbered frames in a frames/ subdirectory`.

### Task 7: Remove the old API; docs and ADR

**Files:**
- Modify: `python/stunt_reel/parity_layout.py`, `python/stunt_reel/dataroot.py:87-91,375,401`, `mise.toml:94,98`, `docs/development.md`, `docs/adr/0022-…md`, `docs/adr/0023-…md`, `tests/test_parity_layout.py:45-110`, `tests/test_dataroot.py:336,371`
- Create: `docs/adr/0024-captures-are-filed-by-film-then-kind.md`

**Interfaces:**
- Removes: `all_root`, `all_path`, `capture_path`, `new_capture_id`, `require_film_stem`, `RESERVED_FILM_STEMS`, `dataroot.LEGACY_CAPTURE_ID`. `convert_layout` files an old `reference/<film>` at `captures/vault-<film>/frames/001`.

- [ ] **Step 1:** `grep -rn "all_path\|all_root\|capture_path\|new_capture_id\|require_film_stem\|RESERVED_FILM_STEMS\|LEGACY_CAPTURE_ID\|captures/all\|captures\\\\all" python tests docs mise.toml research` and update every hit; delete the tests of removed functions and keep their intent in Task 1 tests. Change the two `test_dataroot.py` assertions to the new path.
- [ ] **Step 2:** Write ADR 0024 (Context, Decision, What will enforce this, Considered Options: kind-first, hash run ids, physical-path names), and add a "Superseded in part by 0024" line to ADRs 0022 and 0023 for the paths.
- [ ] **Step 3: Run** `mise run check-py`. Expected: no failures.
- [ ] **Step 4: Commit** `refactor(layout): drop the date-keyed ids and the all directory`.

### Task 8: Migration of the existing data

**Files:**
- Create: `python/scripts/migrate_captures.py`, `tests/test_migrate_captures.py`
- Modify: `mise.toml` (task `migrate-captures`), `research/parity/references.toml` (values)

**Interfaces:**
- Consumes: `references.capture_digest`, `parity_layout.frames_path`, `archive_path`.
- Produces: `migrate(root: Path, pins: Mapping[str, str], *, apply: bool) -> list[str]` — the plan of moves as text lines, executed only when `apply`. Rules: `captures/<stem>/<id>` becomes `captures/vault-<stem>/frames/001` for the four vault films (`ctry intro balloon traintnl`); `captures/all/<stem>/<id>` becomes `captures/vault-<stem>/archives/001`; before moving, a capture named in `pins` must hash to its pin or the whole run aborts with nothing moved; with Task 6 kept, numbered files move into `frames/` and `meta.json` entries are rewritten to `frames/…` names, `captured_on` is taken from the old id's date and `checkout` from its middle part when it has one; after moving, every file's SHA-256 is compared with the manifest taken before (renames excepted) and the new `capture_digest` is returned for `references.toml`. A target that already exists makes the run a no-op for that item; a second run changes nothing. The script prints the new `capture = "001"` and `sha256` for each pinned film and edits `references.toml` only when given `--write-pins`.

- [ ] **Step 1: Write failing tests** on a synthetic data root: `test_dry_run_moves_nothing`, `test_vault_captures_and_archives_are_filed_by_slug`, `test_a_wrong_pin_aborts_before_any_move`, `test_file_bytes_survive_the_move` (manifest equality), `test_second_run_is_a_no_op`, `test_meta_keeps_hashes_and_gains_provenance`.
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_migrate_captures.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `migrate` and a `main()` with `--root`, `--yes` (apply), `--write-pins`; add `mise run migrate-captures`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(captures): add a migration to the film-first layout`.
- [ ] **Step 6: Dry-run on the real data root**: `mise run migrate-captures` prints the planned moves for `ctry`, `intro`, `balloon`, `traintnl` and the two archives. Stop and show the user the output; apply with `mise run migrate-captures -- --yes --write-pins` only on their yes (it changes files outside the repository).
- [ ] **Step 7:** After applying, run `mise run check` once and confirm `reference_dir` verifies both pins (`mise run parity -- --no-render` or the references test). Commit `references.toml` as `chore(parity): re-pin the references at their new paths`, body: the digest changes because relative paths changed; the per-file manifest check proves the bytes did not. Close with `mise run check passes.`

## Notes for the reviewer

- Spec correction: the spec says the pinned hashes prove nothing changed. `capture_digest` hashes relative paths and `meta.json`, so moving files or adding provenance keys changes it. The plan keeps the integrity proof by a per-file manifest check and re-pins in a reviewed commit. Dropping Task 6 and the `meta.json` provenance edit for old captures would keep the old pins valid.
- Open branches naming `legacy-2026-10-24` break until they rebase; add a junction at the old path only if any exist.
