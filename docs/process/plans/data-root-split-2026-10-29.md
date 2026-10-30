# Data-root split plan (2026-10-29)

Status: **planned**, nothing landed. Source: the `/grill-with-docs` interview of
2026-10-29 (four rounds), starting from "why do we have `STUNT_DATA_WRITE`?". The durable
decision is [ADR 0022](../../adr/0022-captures-are-add-only-beside-a-read-only-corpus.md);
this note owns the landing steps and the log. It lands on its own branch and PR, before
the remaining steps of the [public release plan](public-release-2026-10-28.md), so the
release does not document a variable this removes.

## 1. Decisions

| # | Decision |
|---|---|
| D1 | Keep one `stunt-reel.data` per machine, split into `corpus\` (original game files, nothing writes it) and `captures\` (add-only). |
| D2 | `target_bin\` goes: `StuntIsl\` becomes `corpus\stuntisl\`, `patch\` becomes `corpus\patches\`, and the top-level `PLAYONE.EXE` (byte-identical to `StuntIsl\PLAYONE.EXE`) is dropped. `si_archive` is renamed `siarchive`, so the data root and the checkout spell it the same. |
| D3 | No read-only attribute for now. Nothing writes `corpus\`; SOP 6 item 3 says so in one line: "Nothing writes `corpus/`; a capture adds a new directory under `captures/` and never changes one." |
| D4 | `STUNT_DATA_WRITE`, `require_shared_write` and `is_shared` are removed with nothing in their place. |
| D5 | A capture writes a new `captures\<film>\<capture id>\` (date, session, short hash) by default, with no opt-in, and refuses an id that already exists. |
| D6 | `research/parity/references.toml` (committed) names each film's reference capture by id and content hash; promoting is a reviewed commit. Parity fails with a plain message when the named capture is absent on the machine. |
| D7 | The synthetic `intro_trajectory.json` becomes a per-worktree build output: `DEFAULT_ORACLE_PATH` moves to `build/oracle/intro_trajectory.json`, written when `stream_oracle_intro` runs. Nothing reads that path today, so no reader has to trigger generation. The docs mark it synthetic until a trajectory captured from `PLAYONE.EXE` replaces it. |
| D8 | `mise run init -- --migrate` gains a second job. Today it moves data a checkout holds into the shared root; it also converts an old-layout data root in one pass, before that move, and refuses a root holding both an old and a new name. `reap` recognises both the old and the new link sets. |
| D9 | Glossary: **Corpus** widened, **Capture** and **Reference capture** added, "recording" avoided (the game's word for filming a take). Landed with the interview. |

## 2. Facts found during the interview

1. `target_bin\PLAYONE.EXE` is the packed original, not the `unlzexe` output, which goes
   to each worktree's `build/re/`.
2. `corpus/oracle/intro_trajectory.json` comes from
   [`stream_oracle_intro`](../../../python/stunt_reel/tac/streamer.py) driving a
   `MockTransport` loaded with `generate_intro_trajectory()`: hand-written kinematics.
3. The DOSBox profiles mount `corpus/stisldem` only; the layout keeps that path.
4. `corpus/README.md` and `corpus/siarchive.md` are tracked, so each corpus folder stays
   its own link; `corpus/` cannot be one.
5. A capture session clears its `--out` before sampling
   ([ADR 0021](../../adr/0021-capture-chooses-its-control-port.md), Consequences); an
   add-only id makes that clear a no-op on a fresh directory, and D5's refusal replaces it.

## 3. Steps

Each step leaves `mise run check` green.

1. **Layout and links.** In [`dataroot.py`](../../../python/stunt_reel/dataroot.py),
   `LINK_TARGETS` becomes `corpus/stisldem`, `corpus/siarchive`, `corpus/stuntisl`,
   `corpus/patches` and `captures` → `build/parity/captures`; the `corpus/oracle` and
   `target_bin` entries go. Delete `WRITE_ENV`, `SharedWriteError`,
   `require_shared_write`, `is_shared` and their tests in `tests/test_dataroot.py`, and
   rewrite the module docstring and the `LINK_TARGETS` comment, which still explain the
   `si_archive`/`siarchive` mapping. Touch
   [`worktree_init.py`](../../../python/scripts/worktree_init.py),
   `tests/test_worktree_reap.py`, `tests/test_doc_invariants.py` (`LINK_SKIPPED_DIRS`),
   the `target_bin/` URL prefix in `verify_formats_docs.py`, `.gitignore`
   (`target_bin/`), and the `unlzexe` usage in `mise.toml` and `unlzexe.py`
   (`corpus/stuntisl/PLAYONE.EXE`).
2. **Migration and reap.** `--migrate` maps the old tree as in D2 and D8, moves
   `reference\{ctry,intro}` to `captures\<film>\legacy-2026-10-24\`, deletes `oracle\`,
   and refuses when both an old and a new name exist. `reap` unlinks either set. Tests use
   synthetic trees in `tmp_path`, as `test_dataroot.py` already does.
3. **Add-only captures.** [`parity_layout.py`](../../../python/stunt_reel/parity_layout.py)
   gains the capture-id directory; `capture_playone_reference.py`'s default `--out`
   becomes a new id; [`session.py`](../../../python/stunt_reel/tac/session.py) drops the
   write guard and refuses an existing directory. Update `tests/test_parity_layout.py`
   and `tests/test_tac_capture_session.py`.
4. **Reference pointer.** Add `research/parity/references.toml`, seeded with the two
   legacy ids and their hashes, and resolve it in `parity_layout.capture_dir` for
   `parity`, `sweep` and `parity-probe`. A missing or hash-mismatched capture is an error
   naming the id. Promoting is editing the file in a reviewed commit; no command.
5. **Oracle as build output.** `DEFAULT_ORACLE_PATH` moves as in D7; drop the
   `corpus/oracle` assertions in `tests/test_tac_adversarial.py`; fix the doc comment at
   `crates/stunt-core/src/contracts/trajectory.rs:178`; mark it synthetic where
   `research/` and SPEC cite it.
6. **Docs.** SOP 6 item 3 in `AGENTS.md`; `docs/development.md` § 3; ADR 0008 status;
   ADR 0021's `--out` paragraph (a status note, not an edit of its reasoning);
   `research/parity/method.md`, `research/playone-exe/capture.md` and the other notes
   that name `build/parity/reference` or `corpus/oracle`
   (`grep -rn "parity/reference\|corpus/oracle\|target_bin\|STUNT_DATA_WRITE"`).
7. **Migrate this machine.** Run `mise run init -- --migrate` in the primary checkout,
   then `mise run parity` on CTRY and INTRO and compare against the last
   `research/parity/log.md` rows: the scores must not move.

## 4. Open questions

None from the interview. Capture pruning, which must never remove a referenced capture,
is deferred until captures take noticeable space; its command is named then.

## 5. Log

| Date | Step | Result |
|---|---|---|
