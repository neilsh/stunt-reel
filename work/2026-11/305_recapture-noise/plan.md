# Sound-stubbed captures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Captures play each film with its archive's sound samples stubbed, so a recapture comes out identical to the reference and the parity verdict and headline score stop moving between recaptures.

**Architecture:**
- A pure function in `all_archive.py` replaces every sound chunk's payload with `0x04`.
- `staging.stage_play` writes the stubbed bytes into the mount, so every capture path gets them.
- A script exposes the function to #301, and `capture-compare` is adopted from #301.
- PR 2 recaptures the seven references, repins them, and makes the drift check judge a row that has no σ.

**Tech Stack:** Python 3 (stdlib `struct`, `argparse`), pytest, mise tasks, dosbox-automation captures, `gh stack`.

**Spec:** [`spec.md`](spec.md) (decisions Q1 to Q17). Read it before any task.

## Global Constraints

- Sound chunk ids are `0xC000`–`0xCFFF` inclusive. The stub payload is exactly `b"\x04"`.
- The option values are `stubbed` and `kept`, and the default is `stubbed`. The type is `SoundSamples = Literal["stubbed", "kept"]`, defined in `python/stunt_reel/tac/staging.py`.
- The `meta.json` key is `"sound_samples"`, valued `"stubbed"` or `"kept"`.
- `all_sha256` is always the hash of the archive as given, never of the stub.
- The new task names are `stub-sound-samples` and `capture-compare`, and the option names are `--sound-ids-from` and `--sound-samples`. Every name says sound samples.
- Without a σ, the drift threshold is `1e-7`.
- The ADR is number 0043.
- Repository rules come from [`AGENTS.md`](../../../AGENTS.md) § 3:
  - Stage files by name.
  - `mise run check` passes before every commit.
  - Commit subjects are Conventional Commits, and the body ends with the gate line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Nothing from `corpus/` is committed.
  - A fresh reviewer reads any `research/` diff before push.
  - Before running a `gh stack` command, read the `gh-stack` skill.
- Tests are offline, on synthetic archives built with `tests/archive_helpers.py`'s `build_all` or by hand with `struct`.

## Review Focus

1. **Stubbing twice.** Stubbing an archive that is already stubbed returns the same bytes (`stub(stub(x)) == stub(x)`). A user may stub the demo's `CTRY.ALL`, which ships stubbed. Task 1.
2. **Unsorted input with `--sound-ids-from`.** An input whose ids are out of order comes back with every id ascending. Without the option, the order is kept. Task 1.
3. **Malformed archive at capture time.** A capture whose resolved archive is malformed fails with the `ArchiveError` message, exits 1 or 2 (not a traceback), and leaves no stage behind. Task 4.
4. **`--sound-samples kept` with `--out`.** The capture's `meta.json` says `"kept"`, and the staged `.ALL` is the source byte for byte. Task 4.
5. **OUT in a missing directory.** `stub-sound-samples` refuses an OUT whose parent does not exist, with exit 2. It does not create directories or raise a traceback. Task 2.

---

## PR 1: tools and staging (branch `claude/reduce-capture-noise-8aa03a`)

### Task 1: `stub_sound_samples`

**Files:**
- Modify: `python/stunt_reel/all_archive.py`. Add the function after `check_archive`, at about line 108, and add its name to `__all__`.
- Test: `tests/test_all_archive.py`

**Interfaces:**
- Consumes: `check_archive(data: bytes) -> int` and `ArchiveError` from the same module.
- Produces:
  - `stub_sound_samples(archive: bytes, *, sound_ids_from: bytes | None = None) -> bytes`
  - `SOUND_IDS = range(0xC000, 0xD000)`
  - `SOUND_STUB = b"\x04"`

- [ ] **Step 1: Write the failing tests.** Add a helper `_archive(chunks: list[tuple[int, bytes]]) -> bytes` that writes the given ids in the given order, plus a `_parse(data) -> list[tuple[int, bytes]]` helper. The fixture is `[(0x0001, b"shape"), (0xC302, b"\x10" * 40), (0xC307, b""), (0x0F00, b"pal")]`. Tests:
  - `test_stub_replaces_each_sound_payload_with_one_byte`: `_parse(stub_sound_samples(fx))` is the same list with each `0xC3xx` payload set to `b"\x04"`, and `check_archive` passes on the result.
  - `test_an_archive_without_sound_comes_back_byte_identical`: `stub_sound_samples(build_all(CHUNKS)) == build_all(CHUNKS)`.
  - `test_stubbing_twice_is_stubbing_once` (Review Focus 1).
  - `test_sound_ids_from_adds_the_missing_ids_as_stubs_ascending`: the input holds `0xC302`, and `sound_ids_from` holds `0xC302` and `0xC319`. The result's ids are sorted, `0xC319` is `b"\x04"`, and the non-sound payloads are unchanged.
  - `test_sound_ids_from_on_an_archive_without_sound_adds_them_all`: this is #301's superset arm.
  - `test_sound_ids_from_already_covered_gives_the_same_bytes`: on an ascending input that already holds those ids, the result equals the result without `sound_ids_from`.
  - `test_sound_ids_from_sorts_an_unsorted_input` (Review Focus 2). Without the option, the original order is kept.
  - `test_stub_rejects` and `test_sound_ids_from_rejects`: parametrize over `_bad_archives()`; each case raises `ArchiveError`.
  - `test_fixture_archives_keep_their_non_sound_chunks`: run it on `tests/fixtures/` `link_film.all` and `synthetic_minimal.all`, if both exist. Otherwise, drop this test and say so in the commit body.
- [ ] **Step 2: Run the tests and watch them fail.** Run `mise run test-py -- tests/test_all_archive.py -k "stub or sound_ids"`. Expected: they fail with an ImportError on `stub_sound_samples`.
- [ ] **Step 3: Implement.**
  - Call `check_archive` on each input.
  - Parse ids and payloads by offsets, and replace sound payloads with `SOUND_STUB`.
  - When `sound_ids_from` is given, add its missing sound ids and sort by id.
  - Rebuild with a `u16` count, `u16` ids, and `count + 1` `u32` offsets starting at `6n + 6`.
  - If nothing changed, return the input object itself.
- [ ] **Step 4: Run the tests and watch them pass.** Use the same command; expected: pass. Then run `mise run lint-py` and `mise run typecheck`.
- [ ] **Step 5: Commit.**
  - Stage `python/stunt_reel/all_archive.py` and `tests/test_all_archive.py`.
  - Subject: `feat(archive): stub the sound samples of an .ALL`.

### Task 2: `mise run stub-sound-samples`

**Files:**
- Create: `python/scripts/stub_sound_samples.py`
- Modify:
  - `mise.toml`: add `[tasks.stub-sound-samples]` next to `[tasks.superset-all]`, with `run = "uv run python python/scripts/stub_sound_samples.py"` and a description that shows the usage line.
  - `docs/development.md`: add a task-table row near `capture-digest` (line 190).
- Test: `tests/test_stub_sound_samples_script.py`. Load the script with `importlib`, the way `test_capture_compare_script.py` does in Task 3.

**Interfaces:**
- Consumes: `stub_sound_samples` and `ArchiveError` (Task 1), and `stunt_reel.hashing.file_sha256`.
- Produces: `main(argv: list[str] | None = None) -> int`, which returns 0 when written and 2 when refused or on an `ArchiveError`.
- CLI: `IN.ALL -o OUT.ALL [--sound-ids-from OWN.ALL]`.
- Stdout on success is two lines: `in  <sha256>  <IN>` and `out <sha256>  <OUT>`.

- [ ] **Step 1: Write the failing tests.** Exit codes:
  - A missing `-o` exits 2, through argparse `SystemExit`.
  - An existing OUT exits 2 and leaves the file untouched.
  - An OUT that resolves to IN exits 2.
  - An OUT whose parent directory is missing exits 2 and creates nothing (Review Focus 5).
  - A malformed IN exits 2, and stderr names the problem.
  - A good run exits 0. OUT equals `stub_sound_samples(IN)`, with `--sound-ids-from` passed through, and stdout's two hashes match the files.
- [ ] **Step 2: Run the tests and watch them fail.** Run `mise run test-py -- tests/test_stub_sound_samples_script.py`.
- [ ] **Step 3: Implement** the script with argparse. Messages go to stderr. Write OUT with exclusive creation (`open(OUT, "xb")`), so an OUT that appears in the meantime is still refused.
- [ ] **Step 4: Run the tests and watch them pass.** Then run `mise run stub-sound-samples -- --help`.
- [ ] **Step 5: Commit** the four files. Subject: `feat(archive): add mise run stub-sound-samples`.

### Task 3: adopt `capture-compare` from #301

**Files:**
- Create, from commit `c52dae5d`:
  - `python/scripts/capture_compare.py`
  - `tests/test_capture_compare_script.py`
- Modify:
  - `mise.toml`: add only the `[tasks.capture-compare]` block from that commit. Its other `mise.toml` hunks belong to #301.
  - `docs/development.md`: add a task row.

**Interfaces:**
- Produces `mise run capture-compare -- A B`, which Task 7 uses. Its output format is whatever `c52dae5d` prints; do not change it (#301 drops its own copy when it rebases).

- [ ] **Step 1:** Run `git checkout c52dae5d -- python/scripts/capture_compare.py tests/test_capture_compare_script.py`. Then hand-add the mise block and the docs row.
- [ ] **Step 2:** Run `mise run test-py -- tests/test_capture_compare_script.py`. Expected: pass. If an import from `stunt_reel.parity_artifacts.capture` is missing on this branch, stop and report; do not port other #301 code.
- [ ] **Step 3: Commit as yourself** ([AGENTS.md](../../../AGENTS.md) § Committing rule 9).
  - Subject: `feat(capture): adopt capture-compare from #301`.
  - The body says it is taken unchanged from `c52dae5d` on `claude/grill-with-docs-301-74ba5b`.

### Task 4: stage with stubbed sound samples, options and `meta.json`

**Files:**
- Modify:
  - `python/stunt_reel/tac/staging.py:194-217` (`stage_play`)
  - `python/stunt_reel/capture_run.py`:
    - `Job` (lines 94-108): add the field.
    - `staged_play` and `staged_film` (lines 188-203).
    - `provenance` (line 358): add the key.
    - `_run_play` (line 439): pass the job's value.
  - `python/scripts/capture_playone_reference.py` and `python/scripts/capture_video.py`: add the option and pass it into `Job`.
- Test:
  - `tests/test_tac_staging.py`
  - `tests/test_capture_run.py`

**Interfaces:**
- Consumes `stub_sound_samples` (Task 1).
- Produces:
  - `SoundSamples = Literal["stubbed", "kept"]` in `staging`.
  - `stage_play(film: Path, archive: Path, engine_root: Path | None = None, *, sound_samples: SoundSamples = "stubbed") -> StagedMount`.
  - `capture_run.staged_play(film, archive, engine_root=None, *, sound_samples: SoundSamples = "stubbed")`.
  - `capture_run.staged_film(film, engine_root=None, *, sound_samples: SoundSamples = "stubbed")`.
  - `Job.sound_samples: SoundSamples = "stubbed"`.
  - The option is `--sound-samples {stubbed,kept}`, default `stubbed`, on both capture scripts.
- Callers that stay on the default with no option (Q17): `play.py` and `probe_playone_light.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_tac_staging.py`:
    - `test_stage_play_stubs_the_sound_samples_by_default`: archive = `_archive` from Task 1 with a `0xC302` chunk; the staged `CTRY.ALL` equals `stub_sound_samples(source)`.
    - `test_stage_play_keeps_the_sound_samples_when_asked`: byte for byte.
    - `test_a_malformed_archive_leaves_no_stage`: `pytest.raises(ArchiveError)`, then `_no_stage_left()`.
  - The existing `test_stage_play_takes_an_explicit_archive` writes `b"stored archive"`, which is not an archive. Pass `sound_samples="kept"` there.
  - `test_capture_run.py`, parametrized `@BOTH` like `test_a_run_records_when_and_by_whom_and_the_engine_it_ran`:
    - `meta["sound_samples"] == "stubbed"`, and `meta["all_sha256"]` is the sha256 of the unstubbed source archive.
    - A `--sound-samples kept` / `Job(sound_samples="kept")` run with `--out` records `"kept"` (Review Focus 4).
    - A run whose resolved archive is malformed returns nonzero, prints the `ArchiveError` text, and leaves no stage (Review Focus 3). If `ArchiveError` is not already in `_REFUSALS`, the run reports it through `report_failure`.
  - Any existing `capture_run` test whose fake archive is not a valid `.ALL` must either use `build_all` or set `"kept"`. Check `tac_mock` for what the fixture film's archive holds.
- [ ] **Step 2: Run the tests and watch them fail.** Run `mise run test-py -- tests/test_tac_staging.py tests/test_capture_run.py`.
- [ ] **Step 3: Implement.**
  - In `stage_play`'s `populate`, either write `stub_sound_samples(archive.read_bytes())` or `shutil.copy2` as today.
  - Thread `sound_samples` through `Job` → `_run_play` → `staged_play` → `stage_play`.
  - Put `"sound_samples": job.sound_samples` into `provenance`. It reaches `meta.json` through `framebuffer.py:194` and `video.py:249`.
- [ ] **Step 4: Run the tests and watch them pass.** Then run `mise run test-py -- tests/test_play_script.py tests/test_parity_probe.py` for the default callers.
- [ ] **Step 5: Commit** the changed files. Subject: `feat(capture): play films with their sound samples stubbed`.

### Task 5: records, ADR 0043 and PR 1

**Files:**
- Create: `docs/adr/0043-captures-play-with-the-archives-sound-samples-stubbed.md`. Follow the structure of ADR 0042. Content: the evidence (capture note § 4.4), the picture change (66 of 96 pages), the default, `--sound-samples kept` for a recording with sound, and a statement that ADR 0028 and ADR 0037 stand unchanged.
- Modify:
  - `research/playone-exe/capture-dosbox-automation.md` § 4.4: captures stub by default. State the stub byte, and what is known and not known about it (spec § 1.1).
  - `research/formats/all.md` § 3.3: the demo `CTRY.ALL` ships its sound chunks as stubs of 1 byte (`0xC302`), 1,839 bytes (`0xC319`) and 1 byte (`0xC31E`).
  - `GLOSSARY.md`: add "stubbed sound samples" unless an existing term covers it. Read the `domain-modeling` skill first.
  - `docs/ARCHITECTURE.md`: route `stub_sound_samples` only if the file lists `all_archive.py` entries.
  - `work/2026-11/305_recapture-noise/README.md`: update the Handoff.

- [ ] **Step 1:** Write the records and the ADR.
- [ ] **Step 2:** Run `mise run check -- --full`. It must pass with no warnings.
- [ ] **Step 3: Commit.** Subject: `docs(capture): record that captures stub sound samples (ADR 0043)`.
- [ ] **Step 4:** A fresh Opus reviewer reads the `research/` diff of `main...HEAD` and the notes it cites, and reports any claim broader than its evidence (AGENTS.md § Committing rule 7). Fix what it reports and commit.
- [ ] **Step 5:** Read the `gh-stack` skill. Run `gh stack init claude/reduce-capture-noise-8aa03a claude/recapture-sound-stubbed-305`, then submit PR 1 (`gh stack submit --auto`), with its body written by the `pr` skill. Bind it with `ccd_pr` and read its CI.
- [ ] **Step 6:** Send #301's session (`local_84a511f9-e0d6-450f-9d20-161e4d237dc0`) the PR 1 link (Q14).

---

## PR 2: recapture (branch `claude/recapture-sound-stubbed-305`)

### Task 6: drift check without a σ

**Files:**
- Modify: `python/stunt_reel/expected_scores.py:143-152`. Add `DRIFT_PRECISION = 1e-7` near the top.
- Test: `tests/test_expected_scores.py`. Replace `test_a_film_without_noise_sigma_prints_its_delta_unjudged` (line 167).

**Interfaces:**
- Produces lines for a row with no σ, keeping the existing `|delta| … >` shape:
  - `f"{head}  DRIFT: |delta| {abs(delta):.7f} > {DRIFT_PRECISION:.7f}"` above `1e-7`;
  - `f"{head}  no drift"` at or below it.
- Rows that have a σ keep today's lines.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_film_without_noise_sigma_judges_drift_at_the_tables_precision` is parametrized over:
    - expected `0.8986`, report `0.8987` → `DRIFT: |delta| 0.0001000 > 0.0000001`;
    - report `0.89860005` → `no drift`;
    - report `0.8986` → `no drift`.
  - The existing σ tests stay unchanged.
- [ ] **Step 2: Run the tests and watch them fail.** Run `mise run test-py -- tests/test_expected_scores.py`.
- [ ] **Step 3: Implement.** Without a σ, use `DRIFT_PRECISION` as the threshold.
- [ ] **Step 4: Run the tests and watch them pass.** Also update the `references.py` docstring (line 18) and `parity_run.py` (line 22) if they say that drift needs a `noise_sigma`.
- [ ] **Step 5: Commit.** Subject: `feat(parity): judge drift on a film without noise_sigma`.

### Task 7: back up, then recapture each film twice (operational; no unit tests)

The slugs are the seven `references.toml` rows. List them with `grep -n '^\[' research/parity/references.toml`, ignoring the `.expected` tables.

- [ ] **Step 1: Back up each film.** Copy `<data root>/captures/<slug>/frames` to `<data root>/backup/pre-305/<slug>/frames`. Check that the file counts match.
- [ ] **Step 2: Capture each film twice.**
  - Run `mise run capture-ref -- --film <row's film path> --out <data root>/bench/<slug>/stubbed-a`.
  - Start the same command 0.1 s later, with `--out …/stubbed-b`.
  - Both runs are in the background, with no `--name`.
  - Run one film's pair at a time.
- [ ] **Step 3: Compare each pair.** Run `mise run capture-compare -- <…>/stubbed-a <…>/stubbed-b`. Record the identical and paired page counts.
  - Expected: no page differs.
  - A film that still differs is recorded, with its count, and does not block the others.
- [ ] **Step 4: Write a journal entry** in `journal.md`, using the format of the existing entries: Question, Method (commit, commands), Result table, Verdict, and Lives in.

### Task 8: promote, repin, re-measure and records

**Files:**
- Modify:
  - `research/parity/references.toml`: the `sha256` of each row, `expected.gpu`, the removal of `noise_sigma` on `location`, and the header comment (lines 16-21).
  - `research/parity/method.md`:
    - Rewrite § 2.2.1 with the stubbed recapture table.
    - Narrow § 1 step 5's caveat that σ is a lower bound to the films that still differ, if any.
  - `research/playone-exe/capture-dosbox-automation.md` § 4.4: the seven films' results.
  - `work/2026-11/305_recapture-noise/README.md`: write `outcome`.

- [ ] **Step 1: Promote each film.** Swap `stubbed-a` in as `<data root>/captures/<slug>/frames` by the ADR 0028 swap. Use the store's own replace if `capture_store` exposes one; otherwise, ask.
- [ ] **Step 2: Repin each row.**
  - Run `mise run capture-digest -- <slug>` and paste the printed `sha256` into the row.
  - Expected: `all_sha256` is unchanged.
- [ ] **Step 3: Re-measure.**
  - Run `mise run parity` on all seven films and update each `expected.gpu` table.
  - Add a journal table with each film's headline before and after. This is not gated (Q7).
- [ ] **Step 4: Remove `noise_sigma`.**
  - Remove it from `location`, unless its pair still differs.
  - Rewrite the header comment.
  - Run `mise run parity` on `vault-location` and expect a `no drift` line.
- [ ] **Step 5: Make the PR evidence.** Produce the before-and-after capture-beside-render picture by following [`pr-evidence.md`](../../../.agents/skills/improving-render-parity/pr-evidence.md).
- [ ] **Step 6: Finish the records.**
  - Update `method.md` and § 4.4.
  - Write the README `outcome`.
  - Run `mise run check -- --full`.
  - Commit.
- [ ] **Step 7: Review and submit.**
  - A fresh Opus reviewer reads the `research/` diff.
  - Fix what it reports.
  - Run `gh stack submit --auto` for PR 2, with a body that closes #305.
