# Expected-score layout: recommendation

Status: decided at triage on 2026-11-13: option (d), with the decisions under **Decisions** below. The PR that closes #436 implements it.

## The problem

Render changes repin the `ssim`, `iou` and `crates` lines of the seven `[<film>.expected.gpu]`
tables in `research/parity/references.toml`. `git log -- research/parity/references.toml` on
`origin/main` lists #350, #402, #417, #419, #420, #424, #427, #429 and #431 as commits that changed
those tables; #417 is a docs change and repinned too. No listed commit changed a `sha256` line. A
repin changes at most 21 lines (7 tables x 3 fields): #429 changed 21 lines, and #402 changed 27,
including `commit` lines that #427 has since removed. Two render PRs open at once therefore conflict
on the same lines. The same per-film score lists were also written as prose into
`research/playone-exe/sod-vm.md` (sections 8.10 and 8.11 hold seven-film score lists) and work
journals.

## How the tooling reads the file

- `python/stunt_reel/references.py`: `_read_document` reads `parity_layout.REFERENCES_FILE`
  (`research/parity/references.toml`), the data root's copy first, else the checkout's
  (references.py:168-176; parity_layout.py:78). `read_reference` fills `Reference.expected` through
  `_expected` (references.py:218-243, 286-302), one table per renderer class (`gpu`, `lavapipe`).
  `reference_films` returns the rows that have `film` and `sha256` (references.py:206-215).
- `python/stunt_reel/expected_scores.py`: `CLASS_KEYS` (line 32) maps adapter classes to table
  names. `comparison_line` (line 129) picks the class from the report's `adapter.adapter_class`,
  checks the adapter name and run kind, then calls `changed_since` (lines 137-143).
  `changed_since` (lines 94-111) checks `crates_tree()` and the row's two pins, and opens no file.
- Other readers: `python/scripts/parity_run.py` (lines 35 and 165) is the only non-test caller of
  `comparison_line`. Many other parity and capture scripts import `references`, among them
  `parity_pipeline.py` and `all_archive.py`. `python/scripts/migrate_captures.py` (`read_pins`),
  `python/scripts/capture_digest.py` (prints a row to paste), `python/stunt_reel/cloud_assets.py`
  (the `captures` pin must match each row, ADR 0039), `capture_run.py`, `make_all.py` and `play.py`
  (builds, ADR 0029) read only the pins and builds.
- Tests: `tests/test_expected_scores.py` builds `Reference` objects in memory (line 46), and its
  git tests use a scratch repository (from line 225); `tests/test_references.py` parses scratch
  files; `tests/test_committed_reads.py` guards tests that read the committed file.
- Docs that name the layout: the file's own header, `research/parity/method.md` step 0 (line 11),
  `.agents/skills/improving-render-parity/loop-rules.md` (line 22), ADR 0041's table ("The current
  baseline", line 69), ADR 0029, `docs/ARCHITECTURE.md` (lines 25 and 27).

## Why a different layout does not remove the conflict

Two render PRs that both change `crates/` each measure their own tree. Once the first merges, the
second's `crates` value is no longer the tree `main` will have after it merges, so its scores are
stale: they must be measured again on the merged tree, whatever file they live in. The textual
conflict is the signal that a re-measurement is due. A layout that merged silently would let the
second PR land with a `crates` that no checkout of `main` has. `changed_since` would then print
"not comparable: crates/ changed" for renders on the table's adapter name, without `--retime` or
`--reuse`, until someone repinned. Other renders print an earlier reason instead
(expected_scores.py:137-141). That is honest but loses the drift guard until then.

What a layout can change is which edits collide, and how cheap the resolution is.

## Options

| Option | Render PR vs render PR | GPU PR vs lavapipe PR | Pin PR vs score PR | Code and doc cost | ADR |
|---|---|---|---|---|---|
| (a) one file per film and class, `research/parity/expected/<film>.<class>.toml` | still conflicts, in 7 files instead of 1 | separate files | separate files | `_expected` reads a directory; new path constant; tests write files; docs and ADR 0041's table change; 7 files to review per repin (one class per repin, loop-rules.md:22) | yes: changes where the baseline lives |
| (b) one file per class, `expected/gpu.toml`, `expected/lavapipe.toml` | still conflicts, in 1 file | separate files | separate files | same as (a), smaller; `sha256`/`all_sha256` duplicated in a second file, so a pin change touches 2-3 files | yes |
| (c) scores derived from `report.json` files committed under a work folder; `references.toml` keeps only pins | no textual conflict on scores, but `references.toml` (or the reader) must still name which report is current, and that pointer conflicts | depends on the pointer | separate | the drift check would read `work/`, a dated record, as its baseline, against ADR 0041 (records under `work/` are not a source of truth) and its "no shared file" rule; reports carry absolute paths and adapter detail; largest code change | yes, and it supersedes part of ADR 0041 |
| (d) keep the layout, make the resolution mechanical, stop restating the numbers | still conflicts, resolved by a rerun | not tested: a gpu repin and a lavapipe table inserted after it may conflict where they touch adjacent lines | same file, usually distinct hunks | one script and task; a rule in `loop-rules.md` | no: tooling and a working rule, no change to where the baseline lives |

## Recommendation: (d)

1. **Add a repin task** (for example `mise run parity-repin -- [--class gpu|lavapipe]`) that writes
   each film's table for the class the reports were drawn on from
   `build/parity/report/<film>_current/report.json` (`mean_ssim_scored`, `mean_iou_scored`,
   `adapter.name`, rounded to 7 decimals), `crates` from `crates_tree()` (refusing when it is
   dirty), and `sha256`/`all_sha256` copied from the row. It refuses a report whose adapter class
   does not match `--class`, so software scores cannot land under `gpu`. Resolving a conflict is
   then: take `main`'s `references.toml`, rerun `mise run parity`, run the repin task, commit.
2. **Rule in `loop-rules.md`**: on a conflict in an expected table, never hand-merge numbers;
   re-measure on the merged tree and repin. Expected tables change only when the measured `crates`
   tree changes. #417 changed no file under `crates/`, yet its tables' `crates` moved from
   `3c28cd6` to `c4e373a`: it was a catch-up repin, measuring `main`'s newer tree, not a repin
   without a tree change.
3. **Stop restating the baseline in notes.** A research note states the mechanism and cites the
   journal entry for before/after scores (AGENTS.md: cite sources of truth, never restate them);
   the per-film score lists in `sod-vm.md` (sections 8.10 and 8.11) are the other recurring conflict
   and add nothing the journal and `references.toml` lack.

## Decisions

Settled at triage (issue #436, 2026-11-13):

1. **Layout (d).** `references.toml` keeps its tables; (a), (b) and (c) are out of scope.
2. **The report records its tree.** `report.json` gains `crates`: the `crates/` git tree the
   render was built from, or null when that is unknown or `crates/` had uncommitted changes.
   `mise run parity` passes it to `stuntreel parity --crates` only when it built the binary and
   made the render itself on a clean `crates/`. A report without the field reads as null.
3. **Repin task.** `mise run parity-repin -- [--class gpu|lavapipe]`, `gpu` by default,
   rewrites every reference film's table for the class:
   - `ssim` and `iou` from `mean_ssim_scored` and `mean_iou_scored` to 7 decimals;
   - `adapter` from the report;
   - `crates` from the current tree;
   - `sha256` and `all_sha256` from the row.

   It keeps the file's comments and row order. It writes nothing, and says why, when `crates/`
   is dirty, any film has no report, a report's `crates` is missing or not the current tree, or
   a report's adapter class is not the one asked for. It never repins a subset.
4. **Rules** in `loop-rules.md` and `method.md` step 0:
   - expected tables change only when the measured tree changes;
   - a conflict is resolved by taking `main`'s file, re-measuring the merged tree and repinning,
     never by hand-merging;
   - a catch-up repin is allowed in any PR, as its own commit;
   - notes cite journal entries for scores and never copy expected scores.
5. **#417** was a catch-up repin (recommendation item 2), so the rules allow it.
6. **Glossary.** *Expected score* and *Repin* are added under Evidence.

If the gpu and lavapipe tables are ever measured by different people on different schedules
often enough that (d)'s single file still collides, (b) is the smallest layout change and can
follow with an ADR; the repin task would write either layout.

## Risk to the drift check

- (d) leaves `comparison_line` and `changed_since` unchanged. The repin task must refuse a dirty
  `crates/` and a class mismatch, or it would pin a tree no commit has, or a CPU score as `gpu`.
- (a) and (b) keep the check's logic but split pins from scores; a pin change that misses the
  expected file makes `changed_since` print "reference pin changed", which is safe but noisy.
- (c) moves the baseline into dated records; a stale or missing pointer silently selects an old
  report, the one failure the current check is built to rule out.

## Migration cost

- (d): one script with tests (a scratch repository and fake reports, as
  `tests/test_expected_scores.py` already builds), a `mise.toml` task, a paragraph in
  `loop-rules.md` and `research/parity/method.md` step 0. No data moves.
- (a)/(b): the above reader change, `parity_layout` constant, rewrite of the scratch-file tests in
  `tests/test_references.py` and `tests/test_expected_scores.py`, the file header moved to a README
  in `research/parity/expected/`, every doc listed above, and an ADR amending ADR 0041's table.
- (c): all of (a)/(b) plus a report schema, a pointer format and an ADR superseding part of ADR 0041.
