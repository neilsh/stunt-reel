# Capture store deepening

Status: agreed in conversation 2026-11-01, from an architecture review of the last 80 commits; not
started. Decisions: [ADR 0028](../../adr/0028-a-film-has-one-capture-of-each-kind.md) (one capture of
each kind) and [ADR 0029](../../adr/0029-references-name-each-films-builds-and-reference.md)
(`references.toml` names each film's builds and reference capture).

## Intent

The review found three shallow places in the capture tooling, each with open issues that it makes
more expensive:

- **The run store has no owner.** Six modules each work out which runs exist, which are complete
  and which is newest, and the batch survey can score a half-written run. Blocks #79.
- **The capture run lifecycle is copied into each script.** Frame capture, video capture and
  `make-all` each hand-write the same steps around the plan: film identity, claim, stage, always
  unstage, provenance, and the mapping from failures to exit codes. Tests reach that wiring through
  35 monkeypatches, and nothing tests video capture. Blocks #95.
- **The parity pipeline is built twice.** `batch_stages` rebuilds the `stuntreel` command lines,
  skips `check_render`, and picks "the capture" differently from `parity_pipeline`. Blocks #80 and
  #82.

## Order

1. **[#76](https://github.com/neilsh/stunt-reel/issues/76)**: `make-all` keeps an archive that has
   stopped changing while `MAKEONE` stays in graphics mode. Patch3 being the default (ADR 0029)
   depends on this.
2. **Store reader and migration** (ADR 0028; [#139](https://github.com/neilsh/stunt-reel/issues/139), implemented). Add one reader beside `parity_layout`: the film's
   complete capture of a kind, or none. Delete `runs.py`, `batch_stages._latest_capture` and
   `parity_bench._batch_capture`. Migration moves the two pinned references (`vault-ctry` and
   `vault-intro` 004) into the new layout unchanged and deletes every other run. `references.toml`
   drops `capture`; `parity-bench --recapture` takes a path.
3. **Capture run lifecycle.** One module takes a film, a kind and a plan. It owns film identity,
   build choice (the `references.toml` row, then patch3, then the stall fallback that prints a
   suggested row), staging with an unstage that always runs, replacing the old capture by swap,
   provenance including the engine build ([#95](https://github.com/neilsh/stunt-reel/issues/95)),
   and the mapping from failures to exit codes. Replacing a capture must also drop
   `references.capture_digest`'s path-keyed `lru_cache` entry (or remove the cache), or a process
   that digested the old capture validates a stale pin after the swap. Frame capture, video capture and `make-all` run
   through it. `play` writes no capture, so it uses only its build choice, staging and failure
   mapping, and never falls back. Its build choice is the pair a capture would use: the row's
   `playone` for the executable and the archive the row's `makeone` wrote, so a film whose builds
   differ on purpose plays as it is captured. An explicit `--game-root` overrides the executable
   only; `play` refuses a pair the row does not name rather than stage a sibling archive the
   other build wrote (ADR 0029). The light probe reads the unpatched `PLAYONE.EXE` only and refuses any other layout,
   so it takes only staging and failure mapping. Tests go
   through the `ScriptRunner` seam with `MockAutomation` and a temporary data root, and replace the
   monkeypatch tests rather than sit beside them. `UNPATCHED_CAPTURES` is deleted.
   Implemented in [`capture_run.py`](../../../python/stunt_reel/capture_run.py)
   ([#140](https://github.com/neilsh/stunt-reel/issues/140)): `capture_playone_reference.py`,
   `capture_video.py` and `make_all.py` are plans run through `execute`; the probe and `play` use
   `staged_play`/`staged_film` and `report_failure`. Two points differ from the text above.
   `references.capture_digest` has had no cache since ADR 0028, so there was nothing to drop, and a
   test holds that a swap leaves no stale digest. `play` still takes its engine from the film's
   tree (or `--game-root`) and keeps its row check; choosing the row's pair for it is left open.
   Not implemented: ADR 0029's "if the unpatched `PLAYONE` then fails on a patch3 archive, both move"
   (the fallback moves one executable). The fallback retries only a real stall (the instruction
   budget, a film clock that never advances, a dead guest, MAKEONE writing no archive), so a stalling
   film now runs twice within the one stage timeout of the batch survey.
4. **Film parity operation** ([#141](https://github.com/neilsh/stunt-reel/issues/141), implemented in `parity_pipeline`, which the loop already imported). One module renders a film over a tick range, checks the render and
   scores it against a capture: the reference capture or the film's current one. It owns the
   `stuntreel` command lines, the SIDATA path and the `report.json` location. Run it through a
   single subprocess adapter, `(argv, env, timeout) -> (code, tail)`, used by both callers. The
   parity loop takes its films from rows that have `sha256`
   ([#80](https://github.com/neilsh/stunt-reel/issues/80)), and `FILMS` is deleted. The batch survey
   gains `check_render`, so some rows may change from a score to an error; note this in
   [`batch.md`](../../../research/parity/batch.md).
5. **[#82](https://github.com/neilsh/stunt-reel/issues/82)**: `--tick-range A..=B` (0-based, inclusive)
   replaced `--frames`. After step 4 it is built in one place.
6. **Batch re-survey** under the new rules: recapture and re-archive every film, and commit the rows
   the fallback suggests.
7. **Reference recapture**: recapture `ctry` and `intro` on patch3 with patch3 archives, repin
   their digests, re-measure `noise_sigma`, and log the shift in
   [`log.md`](../../../research/parity/log.md).

## Not doing

- **Parked, until something else changes the module.** Generating and decoding each Lua recording
  script in one module (`tac/luagen.py`, the decoders in `plan.py` and `video.py`, and
  `tests/tac_mock.py`, which recovers its inputs by regex over generated Lua); pick it up with the
  next change to `luagen`. Moving the render store layout into `crates/stunt-parity` (a
  conformance test already pins it). A reference capture module in Rust parity (the same frame
  load at three call sites in `parity/mod.rs` and `compare.rs`).
- **Dropped.** One operand table for the SOD display-list VM: `run_vm` is where the fidelity fixes
  land, and `CENSUS_SKIPS` is guarded by a test. A local tidy-up is fine inside a fix that already
  edits it.
- **Separate cleanup.** Retire the Seam 2 oracle (`tac/streamer.py`, `transport.py`, `client.py`,
  `vsync.py` and the retired constants in `playone.py`). Only tests import them.

## Glossary

Updated with this plan: **Captured frame** (no retrace trap), **Game build** (unpatched and
patch3), **Capture** (one of each kind, replaced by a new one).
