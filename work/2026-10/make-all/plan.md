# `make-all` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mise run make-all -- --film X.FLM` runs `MAKEONE.EXE` in DOSBox-X to produce `X.ALL`, stores it add-only under `captures/all/`, and `capture-ref` finds it without extra flags.

**Architecture:** `run_session` gains a `Profile` (stage function and key function) so one session driver serves `PLAYONE` and `MAKEONE`. A new `all_archive` module owns the archive check, the add-only publish and `resolve_all`. `make_all` waits for the guest to return to text mode (a new `video_mode()` transport operation), copies the `.ALL` out of the private mount, and publishes it.

**Tech Stack:** Python 3 with pytest, `uv` through `mise`, DOSBox-X through the existing `tac` package. No Rust change.

**Spec:** [`make-all-2026-10-29.md`](make-all-2026-10-29.md). Read it first: its section 2 holds the spike evidence and section 3 decisions D1 to D10 (cited below as D#).

## Global Constraints

- Offline tests only; nothing in `tests/` reads `corpus/` or starts DOSBox-X. Use `MockEmulator`/`MockTransport` and files built in `tmp_path` (AGENTS.md directive 1).
- Nothing writes under `corpus/`; the archive goes to `captures/all/<film lower case>/<date>-<checkout>-<flm sha256[:8]>/` and is written once (ADR 0022, D4).
- Copies only, never symlinks (D2, D3). A `MAKEONE` mount is new every run and holds exactly: `MAKEONE.EXE`, `DRIVER1.BIN`, `DRIVER2.BIN`, `DRIVER3.BIN`, `GAME.CFG`, `INSTALL.CFG`, `PFONT.BIN`, `VDATA.BIN`, `RES\`, `VAULT\<film>.FLM`.
- `MAKEONE` keys are `<first letter of the film name>`, Enter, no Down. Completion is `VGA MODE` reporting `M_TEXT` after a graphics mode was seen (D6); default cap 600 s.
- Layout path literals (`build/parity`, `build/scratch`) appear only in `parity_layout.py`; add each new module to `CALLERS` in `tests/test_parity_layout.py` so that is enforced.
- Keep `__all__` lists sorted (ruff). Run `mise run check` before each commit; stage the paths you changed by name; never `git add -A`, never anything under `corpus/` (AGENTS.md SOP 3).
- Commit messages: Conventional Commit subject, a body that says why, then `mise run check passes.` and the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- **Branch:** this work builds on ADR 0022 (branch `docs/data-root-split`). Cut a new branch from it, or from `main` once it has merged, and commit the spec and this plan as the first commit there.

## Review Focus

Inputs and conditions the spec implies and a happy-path test would miss; each has a test in the named task.

1. A film stem of `ALL` (it would share `captures/all/`): both scripts refuse it (Tasks 1, 7, 8).
2. A sibling archive spelled `x.all` or `X.All` on a case-sensitive filesystem: `resolve_all` still finds it (Task 3).
3. The guest never returns to text mode (hang), or is in text mode before the film starts: timeout error; early text mode alone does not complete (Task 6).
4. A stored archive whose bytes changed, or an id that already exists: the first is an error naming the id, the second a refusal, and neither touches the existing files (Tasks 3, 7).
5. `--game-root` without `RES\`, or a missing `.FLM`: fails before launch and leaves no mount or conf behind (Task 4).

---

### Task 1: Layout paths and the reserved stem

**Files:**
- Modify: `python/stunt_reel/parity_layout.py`
- Test: `tests/test_parity_layout.py`

**Interfaces:**
- Produces: `parity_layout.all_root() -> Path` (`build/parity/captures/all`), `parity_layout.all_path(film: str, capture_id: str) -> Path` (`all_root()/<film lower>/<capture_id>`), `parity_layout.require_film_stem(stem: str) -> None` (raises `ValueError` whose message contains `ALL` when `stem.lower() == "all"`), constant `RESERVED_FILM_STEMS: tuple[str, ...] = ("all",)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_parity_layout.py`: `test_all_layout_sits_under_the_capture_root` asserts `all_root() == Path("build/parity/captures/all")` and `all_path("BALLOON", "2026-10-29-wt-abcd1234") == Path("build/parity/captures/all/balloon/2026-10-29-wt-abcd1234")`; `test_the_all_stem_is_reserved` asserts `require_film_stem("ALL")` and `("all")` raise `ValueError` matching `ALL` and `("BALLOON")` returns `None`.
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_parity_layout.py -q`. Expected: the two new tests FAIL (`AttributeError`).
- [ ] **Step 3: Implement** the three names above in `parity_layout.py` using `_CAPTURE / "all"` and `_film_name`; add them and `RESERVED_FILM_STEMS` to `__all__`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(layout): name the archive root under captures` after `mise run check`; stage `python/stunt_reel/parity_layout.py tests/test_parity_layout.py` and the spec and this plan if they are not yet committed.

---

### Task 2: Archive check and add-only publish

**Files:**
- Create: `python/stunt_reel/all_archive.py`
- Create: `tests/test_all_archive.py`
- Modify: `tests/test_parity_layout.py` (add `STUNTS / "all_archive.py"` to `CALLERS`)

**Interfaces:**
- Consumes: `parity_layout.all_path`.
- Produces:
  - `class ArchiveError(RuntimeError)`; `class ArchiveMissing(ArchiveError)`; `class ArchiveTaken(ArchiveError)`.
  - `@dataclass(frozen=True) class ArchiveMeta`: `film: str`, `flm_bytes: int`, `flm_sha256: str`, `all_bytes: int`, `all_sha256: str`, `makeone_sha256: str = ""`, `game_files: tuple[tuple[str, int], ...] = ()`, `wall_seconds: float = 0.0`, `created: str = ""`; methods `to_json() -> str`, classmethod `from_json(text: str) -> ArchiveMeta` (unknown keys ignored, absent optional keys take their defaults).
  - `check_archive(data: bytes) -> int`: returns the chunk count; raises `ArchiveError` unless `len(data) >= 2`, count `n >= 1`, `len(data) >= 6n + 6`, first offset (u32 little-endian at `2 + 2n`) equals `6n + 6`, offsets are non-decreasing, and the last offset equals `len(data)` (D7, [`all.ksy`](../../../research/formats/all.ksy)).
  - `publish_archive(root: Path, film: str, capture_id: str, data: bytes, meta: ArchiveMeta) -> Path`: returns the id directory under `root`; writes to `<id>.partial`, then `meta.json` last, then renames to `<id>` (D4, D7); raises `ArchiveTaken` if the id directory already holds `meta.json`; a leftover `.partial` or a directory without `meta.json` is removed first.

- [ ] **Step 1: Write the failing tests** in `tests/test_all_archive.py` with a local helper `build_all(chunks: list[bytes]) -> bytes` that builds a valid archive (ids `1..n`, header `6n+6`, sentinel offset). Tests: `test_check_accepts_a_built_archive` (returns `len(chunks)`); `test_check_rejects` parametrised over empty bytes, count 0, truncated by one byte, first offset off by one, an offset that decreases, and a sentinel that is not the file size (each `ArchiveError`); `test_meta_round_trips_and_defaults_missing_fields` (`from_json('{"film": "A.FLM", "flm_bytes": 1, "flm_sha256": "x", "all_bytes": 2, "all_sha256": "y"}')` has `makeone_sha256 == ""`); `test_publish_writes_meta_last_and_renames` (the id directory holds `BALLOON.ALL` bytes equal to `data` and `meta.json`; no `.partial` remains); `test_publish_refuses_an_existing_id` (second call raises `ArchiveTaken`, the first files are byte-identical afterwards); `test_publish_clears_a_partial_without_meta` (a pre-made `<id>` directory holding only `BALLOON.ALL` is replaced and the call succeeds).
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_all_archive.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the module. The archive file name inside the id directory is `<film stem upper case>.ALL`; `film` is the `.FLM` file name, so `meta.film` and the directory key off `Path(film).stem`.
- [ ] **Step 4: Run** the same command plus `mise exec -- uv run pytest tests/test_parity_layout.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(captures): check and publish generated .ALL archives` after `mise run check`.

---

### Task 3: `resolve_all`

**Files:**
- Modify: `python/stunt_reel/all_archive.py`
- Modify: `tests/test_all_archive.py`

**Interfaces:**
- Consumes: `check_archive`, `publish_archive`, `ArchiveMeta`, `parity_layout.all_root`.
- Produces: `resolve_all(flm: Path, root: Path) -> Path` (D5). Order: (1) a sibling of `flm` with the same stem and suffix `.ALL`, matched case-insensitively against the directory listing; (2) else, among `root / all_root() / <flm stem lower> / <id>/` directories that hold `meta.json` whose `flm_sha256` equals the SHA-256 of `flm`'s bytes, the greatest id; its archive must exist and hash to `all_sha256`, else `ArchiveError` whose message contains the id; (3) else `ArchiveMissing` whose message contains `mise run make-all -- --film` and the film path.

- [ ] **Step 1: Write the failing tests**: `test_a_sibling_wins_over_a_stored_archive`; `test_a_sibling_is_found_whatever_its_case` (files `x.flm`, `x.All`); `test_the_newest_stored_archive_for_the_film_hash_is_used` (two ids with the same `flm_sha256`, the later date returned; a third id with another hash ignored); `test_a_changed_stored_archive_is_an_error_naming_the_id` (bytes edited after publish; `pytest.raises(ArchiveError, match=<id>)`; it must not fall back to the older id); `test_nothing_found_names_make_all` (`ArchiveMissing`, message contains `mise run make-all -- --film`). Build stored archives with `publish_archive` under `tmp_path`.
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_all_archive.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `resolve_all`; hash with `hashlib.sha256`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(captures): resolve a film's .ALL from a sibling or the store` after `mise run check`.

---

### Task 4: Staging for both programs

**Files:**
- Modify: `python/stunt_reel/tac/staging.py`
- Modify: `tests/test_tac_capture_session.py` (new staging tests beside the existing ones near line 675)

**Interfaces:**
- Consumes: `ENGINE_FILES`, `_replace_once`, `_stage_label`, `parity_layout.stage_dir/stage_conf`.
- Produces:
  - `MAKEONE_FILES: tuple[str, ...]` (the `MAKEONE.EXE` mount list in Global Constraints, minus `RES`).
  - `stage_play(film: Path, archive: Path, conf: Path) -> StagedMount`: today's `stage_film` with the archive an explicit path; both files are copied to `VAULT\<film.name>` and `VAULT\<film.stem>.ALL` (the film's own stem and the archive's `.ALL` suffix, so the names match whatever the source spelling was).
  - `stage_film(film: Path, conf: Path) -> StagedMount` stays, delegating to `stage_play(film, film.with_suffix(".ALL"), conf)`; existing callers and tests are unchanged.
  - `stage_makeone(film: Path, game_root: Path, conf: Path) -> StagedMount`: a mount with `MAKEONE_FILES` and the whole `RES\` tree copied from `game_root`, and `VAULT\<film.name>` only; the generated conf replaces the three literals the parity conf carries (the `mount c "corpus/stisldem"` line, `VAULT\CTRY.FLM` and the autoexec line `\nplayone.exe` becoming `\nmakeone.exe`), each through `_replace_once` (D9). On any failure the mount and conf are removed and the error re-raised, as `stage_film` does.

- [ ] **Step 1: Write the failing tests**: `test_stage_play_takes_an_explicit_archive` (archive in another directory and with a different name case; mount `VAULT` holds `CTRY.FLM` and `CTRY.ALL` with the archive's bytes); `test_stage_makeone_holds_exactly_the_makeone_tree` (build a synthetic `game_root` in `tmp_path` with the `MAKEONE_FILES`, `RES/a.bin`, `RES/sub/b.bin`, `VAULT/OTHER.FLM`, `VAULT/OTHER.TKE`; assert the mount's file set equals `MAKEONE_FILES` + the two `RES` files + `VAULT/<film>.FLM`, and no `.ALL`, `.TKE` or `OTHER.FLM` is present); `test_stage_makeone_rewrites_the_conf` (using the real `tools/dosbox/dosbox-parity.conf` text: the staged conf contains `makeone.exe`, does not contain `playone.exe`, mounts the staged directory and names the film in its title); `test_stage_makeone_rejects_a_conf_without_the_playone_line` (a fixture conf lacking it raises `RuntimeError` and leaves no mount or conf under the stage root); `test_stage_makeone_without_res_leaves_nothing_behind` (game root lacking `RES\` raises `FileNotFoundError`; no stage mount or conf remains); `test_stage_makeone_missing_film` (same cleanup assertion).
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_tac_capture_session.py -q -k "stage"`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** the functions; factor the shared mount/conf/cleanup code into one private helper both builders call rather than duplicating the `try/except BaseException` block.
- [ ] **Step 4: Run** `mise exec -- uv run pytest tests/test_tac_capture_session.py -q`. Expected: all PASS (existing staging tests untouched).
- [ ] **Step 5: Commit** `refactor(tac): stage a PLAYONE mount from an explicit archive, add the MAKEONE mount` after `mise run check`.

---

### Task 5: `video_mode()` on the transports

**Files:**
- Modify: `python/stunt_reel/tac/transport.py`
- Test: `tests/test_tac_transport.py` (create if no transport test file exists; otherwise the existing one)

**Interfaces:**
- Produces:
  - `parse_video_mode(lines: Sequence[str]) -> str`: the first `mode=(M_[A-Z0-9_]+)` match in the reply (a real reply line is `VGA mode info: | mode=M_VGA vref=70.087Hz href=31468.750Hz …`); raises `ValueError` if none.
  - `Transport.video_mode(self) -> str` in the protocol; `_FramedTransport.video_mode` returns `parse_video_mode(self.request("VGA MODE"))`.
  - `MockTransport.video_mode_name: str = "M_VGA"` and `MockTransport.video_mode_source: Callable[[], str] | None = None`; `video_mode()` returns the source's value when set, else the name; it requires the transport open.

- [ ] **Step 1: Write the failing tests**: `test_parse_video_mode_reads_the_mode_token` (the real reply line above gives `"M_VGA"`; a line with `mode=M_TEXT` gives `"M_TEXT"`); `test_parse_video_mode_rejects_a_reply_without_a_mode` (`ValueError`); `test_mock_video_mode_follows_its_source` (a source returning `M_VGA` then `M_TEXT`); `test_a_closed_mock_refuses_video_mode` (`ConnectionError`).
- [ ] **Step 2: Run** the new tests. Expected: FAIL.
- [ ] **Step 3: Implement** the four additions. Any other class in `tests/` that is checked with `isinstance(x, Transport)` and lacks `video_mode` fails the gate: add the method there.
- [ ] **Step 4: Run** `mise exec -- uv run pytest tests -q -k "transport or session or emulator"`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(tac): read the VGA mode through the transport` after `mise run check`.

---

### Task 6: Session profile, `MAKEONE` profile and `make_all`

**Files:**
- Modify: `python/stunt_reel/tac/session.py`
- Create: `python/stunt_reel/tac/makeone.py`
- Create: `tests/test_tac_makeone.py`
- Modify: `tests/test_parity_layout.py` (add `STUNTS / "tac" / "makeone.py"` to `CALLERS`)

**Interfaces:**
- Consumes: `staging.stage_makeone`, `Transport.video_mode`, `bda.char_to_key`, `bda.KEY_ENTER`, `Emulator`, `SessionEvent`.
- Produces in `session.py`:
  - `@dataclass(frozen=True) class Profile: stage: Callable[[Path, Path], staging.StagedMount]; keys: Callable[[str], list[tuple[int, int]]]`.
  - `PLAYONE_PROFILE = Profile(stage=staging.stage_film, keys=playone.film_selection_keys)`.
  - `run_session(..., profile: Profile = PLAYONE_PROFILE)`: stages with `profile.stage(film_path, conf_path)` and types `profile.keys(film_path.name)`; nothing else about it changes.
  - `Session.video_mode(self) -> str` on the protocol and `_LiveSession`, translating `TimeoutError`/`ConnectionError` through `_guest_errors("reading the video mode")` and `ValueError` into `SessionError`.
- Produces in `makeone.py`:
  - `film_selection_keys(name: str) -> list[tuple[int, int]]` = `[char_to_key(name[:1].lower()), KEY_ENTER]`.
  - `TEXT_MODE = "M_TEXT"`, `POLL_SECONDS = 2.0`, `DEFAULT_TIMEOUT = 600.0`.
  - `class MakeOneError(RuntimeError)`, `class MakeOneTimeout(MakeOneError)`, `class NoArchive(MakeOneError)`.
  - `wait_for_text(session: Session, *, timeout: float, poll: float = POLL_SECONDS, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None`: polls `session.video_mode()`; returns on the first `M_TEXT` after a non-text mode was seen; text mode before that does not complete; raises `MakeOneTimeout` once `clock() - start > timeout`.
  - `make_all(film: Path, *, game_root: Path, conf: Path = Path("tools/dosbox/dosbox-parity.conf"), timeout: float = DEFAULT_TIMEOUT, emulator: Emulator | None = None, progress: Callable[[SessionEvent], None] | None = None) -> bytes`: runs `run_session` with `Profile(stage=<stage_makeone with game_root, remembering the returned mount>, keys=film_selection_keys)` and a sampler that calls `wait_for_text`, then returns the bytes of `<mount>/VAULT/<film stem>.ALL` (matched case-insensitively), raising `NoArchive` if absent or empty. The bytes are read inside the sampler because the session removes the mount at teardown.

- [ ] **Step 1: Write the failing tests** in `tests/test_tac_makeone.py` with a fake clock/sleep (a list-backed counter; no real sleeping): `test_keys_are_the_letter_then_enter` (`film_selection_keys("BALLOON.FLM") == [char_to_key("b"), KEY_ENTER]`); `test_text_mode_before_graphics_does_not_complete` (modes `M_TEXT, M_TEXT, M_VGA, M_TEXT` return after four polls, not two); `test_the_timeout_fires` (always `M_VGA`; `MakeOneTimeout`); `test_make_all_returns_the_archive_written_into_the_mount` (use the `staged_repo` fixture plus a synthetic `game_root`, a `MockEmulator` over a `MockTransport` whose `dump_source` is the dialog-settling pattern from `CaptureGuest` and whose `video_mode_source` yields `M_VGA` twice then writes `VAULT/BALLOON.ALL` into the staged mount and yields `M_TEXT`; assert the returned bytes and that the injected keys equal the profile's keys); `test_make_all_without_an_archive_raises` (text mode reached, no file: `NoArchive`); `test_the_mount_is_gone_afterwards` (also after `NoArchive` and after `MakeOneTimeout`: nothing remains under `parity_layout.stage_root()`); `test_playone_sessions_are_unchanged` is covered by the existing `tests/test_tac_capture_session.py`, which must pass untouched.
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_tac_makeone.py tests/test_tac_capture_session.py -q`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** the `Profile` change first and run the capture-session tests (PASS), then `makeone.py`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(tac): drive MAKEONE through the capture session` after `mise run check`.

---

### Task 7: The `make-all` command

**Files:**
- Create: `python/scripts/make_all.py`
- Create: `tests/test_make_all_script.py`
- Modify: `mise.toml` (task `make-all`)
- Modify: `tests/test_parity_layout.py` (add `SCRIPTS / "make_all.py"` to `CALLERS`)

**Interfaces:**
- Consumes: `makeone.make_all`, `all_archive.{check_archive, publish_archive, ArchiveMeta, ArchiveTaken, ArchiveError}`, `parity_layout.{new_capture_id, all_path, require_film_stem}`, `dataroot.ensure_links_or_report`.
- Produces: `parse_args() -> argparse.Namespace` with `--film` (required `Path`), `--game-root` (`Path`, default `corpus/stuntisl`), `--conf` (default `tools/dosbox/dosbox-parity.conf`), `--timeout` (`float`, default `makeone.DEFAULT_TIMEOUT`); `run(args, emulator: Emulator | None = None) -> int`; `main() -> int`. Exit codes follow `capture_playone_reference.py`: 0 success, 1 emulator/session/MAKEONE failure, 2 refused (reserved stem, existing id, missing links). `run` computes the id with `new_capture_id(today UTC, checkout name, flm sha256)`, refuses an existing id before launching, validates the bytes with `check_archive`, fills `ArchiveMeta` (`makeone_sha256` of `game_root/MAKEONE.EXE`, `game_files` from `staging.MAKEONE_FILES` sizes, `wall_seconds`, `created` ISO date), publishes under `dataroot.REPO_ROOT`, prints `[make-all] wrote <path>`.
- mise task: `[tasks.make-all]` with `description = "Generate a film's .ALL with MAKEONE.EXE in DOSBox-X into captures/all/ (mise run make-all -- --film corpus/stuntisl/VAULT/BALLOON.FLM)"` and `run = "uv run python python/scripts/make_all.py"`.

- [ ] **Step 1: Write the failing tests** (load the script as `tests/test_tac_capture_session.py` loads `capture_playone_reference.py`; use `staged_repo`, a synthetic game root and the Task 6 emulator setup): `test_a_run_publishes_the_archive_with_meta` (valid synthetic archive from `build_all` in `tests/test_all_archive.py` imported or duplicated in a shared test helper; the id directory under `staged_repo.root` holds it and `meta.json` carries the film hash and `all_sha256`); `test_the_all_stem_is_refused_before_launch` (film `ALL.FLM`; exit 2; the emulator was never started); `test_an_existing_id_is_refused_before_launch` (second run the same day; exit 2; first files unchanged); `test_a_non_archive_is_rejected_and_publishes_nothing` (the mount's `.ALL` is `b"junk"`; exit 1; no id directory); `test_timeout_exits_1` (exit 1, mount removed).
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_make_all_script.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the script and the mise task.
- [ ] **Step 4: Run** `mise exec -- uv run pytest tests/test_make_all_script.py -q`, then `mise tasks`. Expected: PASS and `make-all` listed.
- [ ] **Step 5: Commit** `feat(captures): add the make-all command` after `mise run check`.

---

### Task 8: `capture-ref` resolves the archive

**Files:**
- Modify: `python/scripts/capture_playone_reference.py`
- Modify: `tests/test_tac_capture_session.py`

**Interfaces:**
- Consumes: `all_archive.resolve_all`, `ArchiveError`, `staging.stage_play`, `session.Profile`, `playone.film_selection_keys`, `parity_layout.require_film_stem`.
- Produces: `run(args)` refuses a reserved stem (exit 2); unless `args.no_launch`, resolves the archive with `resolve_all(film, dataroot.REPO_ROOT)`, printing the `ArchiveError` text to stderr and returning 2 on failure; passes `profile=Profile(stage=lambda f, c: staging.stage_play(f, archive, c), keys=playone.film_selection_keys)` to `run_session`. Behaviour for a film with a sibling archive (`CTRY`, `INTRO`) is unchanged. The `--film` help text gains one sentence naming `make-all` for a film without an archive.

- [ ] **Step 1: Write the failing tests**: `test_capture_ref_uses_a_stored_archive_for_a_film_without_a_sibling` (no sibling `.ALL`; a stored archive published under `staged_repo.root`; the staged mount's `VAULT` holds its bytes); `test_capture_ref_without_any_archive_names_make_all` (exit 2, stderr contains `mise run make-all -- --film`); `test_capture_ref_refuses_the_all_stem` (exit 2).
- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_tac_capture_session.py -q`. Expected: new tests FAIL, existing PASS.
- [ ] **Step 3: Implement** the change.
- [ ] **Step 4: Run** the same command. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(capture): find the film's archive through resolve_all` after `mise run check`.

---

### Task 9: Documentation

**Files:**
- Create: `docs/adr/0023-make-all-generates-archives-with-makeone.md`
- Create: `research/makeone-exe/driving.md` (the new subject note: behaviour of `MAKEONE.EXE` as observed under DOSBox-X)
- Modify: `research/README.md` (a `makeone-exe/` row in the Layout table), `research/formats/all.md` (how an archive is produced and what the spike measured), `research/playone-exe/capture.md` (a short pointer: `MAKEONE` shares the harness and the `VGA MODE` read; no duplicated findings), `docs/development.md` (the two commands), `corpus/README.md` (full-game films have no `.ALL`), `GLOSSARY.md` (entry for the generated archive), `AGENTS.md` (SOP 6 item 3 names `captures/all/`; Documentation Directory row for `research/makeone-exe/`), `docs/process/plans/make-all-2026-10-29.md` (status line)

**Interfaces:**
- Consumes: spec D1 to D10 and section 2.

Routing follows [`research/README.md`](../../../research/README.md): a fact goes to the note for its subject, not to the plan.

- [ ] **Step 1: Write `research/makeone-exe/driving.md`** in the shape of [`playone-exe/startup.md`](../../../research/playone-exe/startup.md): the spec's section 2 table as the body (screens, keys, completion signal, minimal mount, timings), the exact `VGA MODE` reply line, a Mermaid flowchart of the run (caching box, requester, `b` Enter, film plays, text mode), the evidentiary tier in each section's first line (`[Bounded Observation]`, one film, 2026-10-29), headings without tier tags, and the closing **Ruled out** (running without `RES\`, relying on `.TKE`, `autotype` at boot as the primary route) and **Open questions** (spec Q1 to Q6). The note stays under about 20 KB.
- [ ] **Step 2: Update `research/formats/all.md`**: under the packaging-origin row, state that `MAKEONE` writes `<film>.ALL` into the mount's `VAULT\` next to the `.FLM`, that five runs on `BALLOON.FLM` produced identical bytes (46,702 bytes, 62 ids, header 378 bytes, md5 `1db59e1edd4d3debaca5e6188ead38df`), and that this matches [`all.ksy`](../../../research/formats/all.ksy); note on Q-ALL-05 only what the runs add (none yet), and link `makeone-exe/driving.md`. Add the `makeone-exe/` row to `research/README.md` and the `AGENTS.md` documentation table.
- [ ] **Step 3: Edit** the remaining documents. Write **ADR 0023** in the form of [ADR 0022](../../adr/0022-captures-are-add-only-beside-a-read-only-corpus.md): Status, Context (no `.ALL` for most films), Decision (D1 to D9 in one page), What will enforce this (the tests named by file), Considered Options (the spec's section 7), Consequences (90 s and more per film, scoring deferred per D10); it links the research note for the evidence instead of repeating it.
- [ ] **Step 4: Run** `mise run check`. Expected: PASS, including the doc-anchor, link and research-note checks (`python/scripts/verify_formats_docs.py` for evidentiary tiers); fix whatever they flag.
- [ ] **Step 5: Commit** `docs: record make-all and the MAKEONE findings` after `mise run check`.

---

### Task 10: Live verification (manual, not in the gate)

**Files:**
- Modify: `research/parity/log.md` (rows appended at the end only), `research/makeone-exe/driving.md` and `research/formats/all.md` (what the live runs add), `docs/process/plans/make-all-2026-10-29.md` (resolved questions)

- [ ] **Step 1: Run** `mise run make-all -- --film corpus/stuntisl/VAULT/BALLOON.FLM`. Expected: exit 0 in about 90 s; `captures/all/balloon/<id>/BALLOON.ALL` is 46,702 bytes with md5 `1db59e1edd4d3debaca5e6188ead38df` (the spike's five runs agreed); if the dialog settle in `run_session` never settles on `MAKEONE`'s screens (spec Q1), keep the 10 s pause the spike used as a documented fallback and record that.
- [ ] **Step 2: Run** `mise run capture-ref -- --film corpus/stuntisl/VAULT/BALLOON.FLM --max-frames 30`. Expected: 30 frames written to a new `captures/balloon/<id>/`, film ticks from about 10, 43 to 72 distinct indices per frame; no `.ALL` beside the `.FLM` is needed.
- [ ] **Step 3: Run** the same two commands on one longer film from `corpus/stuntisl/VAULT` (for example `TRAINTNL.FLM`), noting `wall_seconds` from `meta.json`; if a digit-named film is at hand, try it (spec Q2).
- [ ] **Step 4: Record the findings where they belong** (`research/README.md` routing): append one row per run to `research/parity/log.md` in its existing columns with a link to the note that now holds the finding; promote or correct the tiers in `research/makeone-exe/driving.md` (a second and third film turn single-film observations into wider ones, and the settle outcome closes or restates its Q1); add any new `.ALL` fact to `research/formats/all.md`; replace, not append beside, anything the runs supersede; update the spec's open questions. Commit `docs(research): record the first make-all runs` after `mise run check`.
