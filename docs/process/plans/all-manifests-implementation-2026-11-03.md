# `.ALL` Manifests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild a film's `.ALL` byte for byte from a committed TOML manifest and the game's `RES\`, so captures need no stored binary and no emulator run.

**Architecture:** `stunt-core` gains raw splitters for `.RES` and `.ALL`, a `.ALL` writer, and a pure `link` module (`extract`, `build`). The new `stuntreel link extract|build` subcommand does the file I/O, hashing and TOML. Python wraps the binary in `stunt_reel/link.py`; `resolve_all` rebuilds from a manifest before falling back to the stored archive; `make-all` writes the manifest after each run and can backfill it with `--manifest-only`.

**Tech Stack:** Rust (`stunt-core`, `stunt-cli`, `clap`, new `toml` and `sha2` in `stunt-cli`), Python ≥ 3.15 (`tomllib`, pytest), mise.

**Spec:** [`all-manifests-2026-11-03.md`](all-manifests-2026-11-03.md). Evidence: [`research/makeone-exe/linking.md`](../../../research/makeone-exe/linking.md).

**Branch:** create `feat/all-manifests` from `docs/all-manifests` (which holds the spec) and commit every task there.

## Global Constraints

- `stunt-core` does no I/O and gains no dependency (`[I7]`); manifest types derive serde only under its existing `serde` feature.
- `toml` and `sha2` are added to `stunt-cli` only, with `cargo add -p stunt-cli toml sha2`.
- Manifest path: `manifests/all/<slug>.toml`; rebuilt archive: `target/linked/<slug>/<FILM>.ALL` (film stem uppercased, `.ALL`).
- Item `n` of a source file is region `n - 1` of [`res.ksy`](../../../research/formats/res.ksy); chunk id is `(index << 8) | n`; ids ascend; header `6n + 6` bytes; no padding.
- `stuntreel link` exit codes: `0` written, `1` error, `3` not linkable (`NoSource` or `Mixed`).
- A matching manifest that fails to build is an error; it never falls back to the stored archive.
- Game file lookup is case-insensitive (`[I8]`); manifests record DOS-case names (`RES/SCENERY1.RES`).
- Fixtures are synthetic, never corpus bytes ([`NOTICE.md`](../../../NOTICE.md)).
- Iterate with `mise run check-rust` / `mise run check-py`; run the full `mise run check` once in Task 7 (AGENTS.md SOP 5).
- Commits: Conventional Commit subject, a "why" body, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; stage paths by name.

## Review Focus

1. **Lower-case game files** (`corpus/siarchive` trees use `scenery1.res`): `build` and `extract` find `RES/SCENERY1.RES` regardless of case. Test in Task 3.
2. **No game tree on this machine** (data-root link missing in a fresh worktree): the error names the missing path and `mise run init`. Test in Task 5.
3. **A hand-edited manifest** with items out of order or a repeated `index`: an `Unsorted`/`DuplicateIndex` error, not a silent re-sort. Test in Task 2.
4. **A failed or interrupted build** must not leave a half-written `.ALL` or temporary file that a later resolve picks up. Test in Task 3.
5. **The release binary is running** (Windows refuses to overwrite a running exe): `ensure_binary` skips `cargo build` when the binary is locked instead of failing the capture. Test in Task 4.

---

### Task 1: Raw `.RES`/`.ALL` splits and the `.ALL` writer

**Files:**
- Modify: `crates/stunt-core/src/vfs/res.rs` (add `res_regions`, move `parse_res` onto it)
- Modify: `crates/stunt-core/src/vfs/all.rs` (add `all_chunks`, `write_all`, move `parse_all` onto `all_chunks`)
- Modify: `crates/stunt-core/src/vfs/mod.rs` (exports, `VfsError::DuplicateId`)
- Test: `crates/stunt-core/tests/vfs_spec.rs`

**Interfaces:**
- Produces:
  - `pub struct ResRegions<'a> { pub index: u8, pub regions: Vec<&'a [u8]> }`
  - `pub fn res_regions(data: &[u8]) -> Result<ResRegions<'_>, VfsError>`: byte `0x0002` and every region, region 0 included. Same header checks and errors as today's `parse_res`.
  - `pub fn all_chunks(data: &[u8]) -> Result<Vec<(u16, &[u8])>, VfsError>`: ids and payloads in file order, the last payload running to EOF (today's `parse_all` policy).
  - `pub fn write_all(chunks: &[(u16, &[u8])]) -> Result<Vec<u8>, VfsError>`: sorts by id; `VfsError::DuplicateId { id: u16 }` on a repeat; `InvalidOffsetTable` if an offset would pass `u32::MAX`.
  - All re-exported from `stunt_core::vfs`.

- [ ] **Step 1: Write the failing tests** in `vfs_spec.rs`:
  - `res_regions_keeps_region_zero`: on `tests/fixtures/synthetic_minimal.res`, `regions.len()` is one more than the number of entries `parse_res` returns, `regions[0]` is the bytes from `ofs[0]` to `ofs[1]` (the name table), and `index` equals byte `0x0002` of the file.
  - `write_all_packs_sorted_without_padding`: `write_all(&[(0x0203, b"cc"), (0x0201, b"a")])` equals `[2,0, 0x01,0x02, 0x03,0x02, 18,0,0,0, 19,0,0,0, 21,0,0,0, b'a', b'c', b'c']` (count, ids ascending, three offsets with the sentinel, payloads).
  - `write_all_rejects_a_duplicate_id`: two chunks with id `0x0201` give `Err(VfsError::DuplicateId { id: 0x0201 })`.
  - `all_chunks_inverts_write_all`: a seeded loop (the `tests/common/rng.rs` generator, as in `vfs_fuzz.rs`) of 200 random unique-id chunk lists: `all_chunks(&write_all(&x)?)` equals `x` sorted by id.
  - `parse_all_unchanged_on_fixture`: `parse_all(synthetic_minimal.all)` gives the same entries as before the refactor (assert names and lengths currently produced).

- [ ] **Step 2: Run** `cargo test -p stunt-core --all-features --test vfs_spec`. Expected: FAIL, the new functions don't exist yet.

- [ ] **Step 3: Implement** `res_regions`, `all_chunks` and `write_all` with the signatures above. Rewrite `parse_res` and `parse_all` to call the splitters and keep only their naming policy. Add `DuplicateId { id: u16 }` to `VfsError` with message `duplicate chunk id 0x{id:04X}`.

- [ ] **Step 4: Run** `mise run check-rust`. Expected: PASS, with every existing VFS and fuzz test unchanged.

- [ ] **Step 5: Commit** `feat(core): split .RES/.ALL raw regions and write .ALL archives`.

### Task 2: The `link` module and its fixtures

**Files:**
- Create: `crates/stunt-core/src/link.rs`; add `pub mod link;` in `crates/stunt-core/src/lib.rs`
- Create fixtures: `tests/fixtures/link_scen.res`, `tests/fixtures/link_mus_xma.res`, `tests/fixtures/link_mus_ess.res`, `tests/fixtures/link_film.all`, `tests/fixtures/link_film.flm`, `tests/fixtures/link_film.toml`
- Modify: `tests/fixtures/README.md` (one entry per fixture, byte layout and purpose)
- Test: `crates/stunt-core/tests/link_spec.rs`

**Fixtures** (generate with a throwaway script, not committed; each `.res` is `RS`, index, item count, `ofs[0] = 4 * (count + 2)`, the offset table, then the regions):

| File | `res_index` | Regions (item 1, 2, 3) |
|---|---|---|
| `link_scen.res` | `0x02` | `0C 00 61 31`, `0C 00 61 32`, `0C 00 61 33` |
| `link_mus_xma.res` | `0xC0` | `78 31 78 31`, `78 32 78 32` |
| `link_mus_ess.res` | `0xC0` | `65 31 65 31`, `65 32 65 32` |

`link_film.all` = `write_all` of `0x0201`→scen item 1, `0x0203`→scen item 3, `0xC002`→ess item 2 (36 bytes). `link_film.flm` = the 4 bytes `FILM`. `link_film.toml` is the manifest `stuntreel link extract` would write for these files when copied into a tree as `RES/SCEN.RES`, `RES/MUS.XMA`, `RES/MUS.ESS`, with `game_root = "game"`, `makeone_sha256 = "0" * 64` and real SHA-256s.

**Interfaces:**
- Consumes: `ResRegions`, `all_chunks`, `write_all`, `VfsError` (Task 1).
- Produces:
  - `pub struct Manifest { pub film: String, pub flm_sha256: String, pub game_root: String, pub makeone_sha256: String, pub all_bytes: u64, pub all_sha256: String, pub sources: Vec<Source> }`, where `sources` is serialized as the TOML array of tables `source` (`#[serde(rename = "source")]`).
  - `pub struct Source { pub file: String, pub index: u8, pub sha256: String, pub items: Vec<u8> }`
  - `pub enum LinkError { NoSource { id: u16 }, Mixed { index: u8 }, ItemOutOfRange { file: String, item: u8, count: usize }, DuplicateIndex { index: u8 }, Unsorted { file: String }, Vfs(#[from] VfsError) }` (`thiserror`)
  - `impl LinkError { pub fn not_linkable(&self) -> bool }`: true for `NoSource` and `Mixed`.
  - `pub fn extract(all: &[u8], candidates: &[(&str, ResRegions<'_>)]) -> Result<Vec<Source>, LinkError>`: `sha256` left empty, sources ordered by `index`.
  - `pub fn build(sources, files) -> Result<Vec<u8>, LinkError>`, where `sources` is a slice of `Source` and `files` a `&BTreeMap<u8, ResRegions<'_>>`: validates order and ranges, then calls `write_all`.

- [ ] **Step 1: Write the failing tests** in `link_spec.rs` (load fixtures with `include_bytes!("../../../tests/fixtures/…")`):
  - `extract_picks_the_file_that_covers_every_chunk`: with candidates `SCEN.RES`, `MUS.XMA`, `MUS.ESS`, `extract(link_film.all)` gives `[Source{file:"SCEN.RES",index:2,items:[1,3]}, Source{file:"MUS.ESS",index:0xC0,items:[2]}]`.
  - `build_inverts_extract`: `build(&extract(..)?, &files)` equals `link_film.all` byte for byte.
  - `an_unknown_chunk_is_not_linkable`: an archive from `write_all` with an extra `0x7E01` chunk gives `NoSource { id: 0x7E01 }` and `not_linkable()` is true.
  - `one_index_from_two_files_is_mixed`: chunks `0xC001` = xma item 1 and `0xC002` = ess item 2 give `Mixed { index: 0xC0 }`.
  - `an_item_past_the_file_is_out_of_range`: source `SCEN.RES` with items `[4]` gives `ItemOutOfRange { file: "SCEN.RES", item: 4, count: 3 }`; items `[0]` gives the same with `item: 0`.
  - `hand_edited_order_is_refused` (Review Focus 3): items `[3, 1]` gives `Unsorted { file: "SCEN.RES" }`; two sources with `index` 2 give `DuplicateIndex { index: 2 }`; sources out of `index` order give `Unsorted`.
  - `manifest_fixture_round_trips_through_serde` (`#[cfg(feature = "serde")]`): `serde_json` round trip of a `Manifest` keeps every field, and the field name of `sources` is `source`.

- [ ] **Step 2: Run** `cargo test -p stunt-core --all-features --test link_spec`. Expected: FAIL, `link` doesn't exist yet.

- [ ] **Step 3: Implement** `link.rs`. In `extract`, group the chunks by high byte. For each index, the files whose index matches and whose item `id & 0xFF` equals every chunk's payload qualify; take the first by `file` name; if none qualify, report `NoSource` for the first chunk that matches no file at all, otherwise `Mixed`. In `build`, check `Unsorted`, `DuplicateIndex` and `ItemOutOfRange` before writing.

- [ ] **Step 4: Run** `mise run check-rust`. Expected: PASS.

- [ ] **Step 5: Commit** `feat(core): link .ALL chunks to their .RES items`, with the fixtures and README.

### Task 3: `stuntreel link extract|build`

**Files:**
- Create: `crates/stunt-cli/src/link.rs`
- Modify: `crates/stunt-cli/src/main.rs` (dispatch `"link"`, exit with `failure.exit_code()`), `crates/stunt-cli/src/config.rs` (`after_help` lists `link::usage()`), `crates/stunt-cli/Cargo.toml`

**Interfaces:**
- Consumes: `stunt_core::link::{Manifest, Source, extract, build, LinkError}`, `stunt_core::vfs::{res_regions, all_chunks}`.
- Produces (CLI contract used by Task 4):
  - `stuntreel link extract <ARCHIVE> --flm <FLM> --game <TREE> --makeone-sha256 <HEX> -o <MANIFEST>`. `--game` is written verbatim as `game_root` and resolved against the current directory. `--makeone-sha256` replaces the spec's `--makeone <exe>`, because Python already has the hash, including from `meta.json` during a backfill.
  - `stuntreel link build <MANIFEST> [--game <TREE>] -o <ARCHIVE>`, where `--game` defaults to the manifest's `game_root`.
  - `pub(crate) enum LinkFailure { NotLinkable(String), Error(String) }` with `exit_code()` → 3 / 1. `run(args) -> Result<(), LinkFailure>`, `usage() -> String`.
  - `fn extract_cmd(args: &ExtractArgs, cwd: &Path) -> Result<(), LinkFailure>` and `fn build_cmd(args: &BuildArgs, cwd: &Path) -> Result<(), LinkFailure>`. `cwd` resolves a relative `--game` or `game_root`; `run` passes `std::env::current_dir()`, and tests pass their temporary root.

- [ ] **Step 1: Write the failing tests** in `link.rs`'s `#[cfg(test)]` module. Each test copies the Task 2 fixtures into a fresh temporary tree (`<tmp>/game/RES/SCEN.RES`, `MUS.XMA`, `MUS.ESS`) and calls the command functions directly:
  - `extract_writes_the_fixture_manifest`: extract on `link_film.all` writes TOML that parses to the same `Manifest` as `link_film.toml`.
  - `build_reproduces_the_archive`: build from `link_film.toml` writes bytes equal to `link_film.all`.
  - `lower_case_game_files_are_found` (Review Focus 1): the tree holds `res/scen.res`, `res/mus.xma` and `res/mus.ess`; build still succeeds, and extract records `RES/SCEN.RES`.
  - `a_changed_source_is_refused_and_writes_nothing` (Review Focus 4): one byte of `MUS.ESS` flipped gives `LinkFailure::Error` whose message names `RES/MUS.ESS`, the expected hash and the tree. The output path does not exist, and the output directory holds no other file.
  - `an_existing_output_is_replaced_atomically` (Review Focus 4): a stale `out.ALL` holding `b"old"` is replaced by the right bytes, and the directory holds only `out.ALL`.
  - `an_add_on_chunk_exits_3`: extract on an archive with a `0x7E01` chunk gives `NotLinkable` with `exit_code() == 3`, and no manifest file.
  - `a_wrong_archive_hash_is_an_error`: a manifest whose `all_sha256` is edited gives `Error` with exit 1.

- [ ] **Step 2: Run** `cargo test -p stunt-cli link::`. Expected: FAIL, the module doesn't exist yet.

- [ ] **Step 3: Implement.** Run `cargo add -p stunt-cli toml sha2`. Use clap derive with an `Action` subcommand enum, as in `sod_census.rs`. Candidates are every file in `<game>/RES` (matched case-insensitively) that starts with `RS`. Write output to `<out>.<pid>.tmp` in the target directory, then rename it, removing the temporary file on every error path. `extract` builds in memory and refuses unless the result equals the input.

- [ ] **Step 4: Run** `mise run check-rust`. Expected: PASS.

- [ ] **Step 5: Commit** `feat(cli): add stuntreel link extract and build`.

### Task 4: Python wrapper for the binary

**Files:**
- Create: `python/stunt_reel/link.py`
- Modify: `python/stunt_reel/parity_layout.py` (paths), `python/stunt_reel/parity_pipeline.py` (`binary_path`, `binary_locked` come from `link`)
- Test: `tests/test_link.py`

**Interfaces:**
- Produces:
  - `parity_layout.manifest_path(slug: str) -> Path` = `Path("manifests/all") / f"{slug}.toml"`. `parity_layout.linked_path(slug: str, film: str) -> Path` = `Path("target/linked") / slug / f"{Path(film).stem.upper()}.ALL"`.
  - `link.LinkError(RuntimeError)` and `link.NotLinkable(LinkError)`. `link.py` must not import `all_archive`, which would create an import cycle.
  - `link.binary_path() -> Path` and `link.binary_locked(path: Path) -> bool`, moved from `parity_pipeline`, which re-exports both under the same names.
  - `link.Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]`
  - `link.ensure_binary(*, run: Runner = ...) -> Path`: runs `cargo build --release -p stunt-cli` in the repo root unless `binary_locked(binary_path())`.
  - `link.build_archive(manifest: Path, game: Path, out: Path, *, cwd: Path, run: Runner = ...) -> None`
  - `link.extract_manifest(archive: Path, flm: Path, game: str, makeone_sha256: str, out: Path, *, cwd: Path, run: Runner = ...) -> None`
  - Exit 0 returns; exit 3 raises `NotLinkable(stderr)`; any other exit raises `LinkError(stderr)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_link.py`, with a fake `Runner` that records argv and returns a chosen `CompletedProcess`:
  - `test_build_passes_manifest_game_and_out`: argv equals `[binary, "link", "build", manifest, "--game", game, "-o", out]` and `cwd` is passed through.
  - `test_extract_passes_its_flags`: argv holds `"--flm"`, `"--game"`, `"--makeone-sha256"` and `"-o"` with the given values.
  - `test_exit_3_is_not_linkable_and_exit_1_is_an_error`: messages carry the fake's stderr.
  - `test_ensure_binary_skips_cargo_when_the_binary_is_locked` (Review Focus 5): with `binary_locked` patched to `True`, the runner is never called; with it `False`, it is called once with the `cargo build` argv.
  - `test_layout_paths`: `manifest_path("flmonly-balloon") == Path("manifests/all/flmonly-balloon.toml")`; `linked_path("flmonly-balloon", "balloon.flm") == Path("target/linked/flmonly-balloon/BALLOON.ALL")`.

- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_link.py -q`. Expected: FAIL, `link` doesn't exist yet.

- [ ] **Step 3: Implement** `link.py` and the path helpers. Move `binary_path` and `binary_locked` from `parity_pipeline` and re-export them there.

- [ ] **Step 4: Run** `mise run check-py`. Expected: PASS, with the existing `parity_pipeline` tests unchanged.

- [ ] **Step 5: Commit** `feat(link): wrap stuntreel link for Python callers`.

### Task 5: `resolve_all` rebuilds from a manifest

**Files:**
- Modify: `python/stunt_reel/all_archive.py`
- Test: `tests/test_all_archive.py`

**Interfaces:**
- Consumes: `link.build_archive`, `link.ensure_binary`, `link.LinkError` (Task 4); `parity_layout.manifest_path`, `parity_layout.linked_path`.
- Produces: `resolve_all(flm: Path, root: Path, slug: str | None = None, *, link_build: LinkBuild | None = None) -> Path`, where `LinkBuild = Callable[[Path, Path, Path], None]` takes `(manifest, game, out)`. When `None`, the default calls `ensure_binary()` and then `build_archive(..., cwd=root)`.

Order: a sibling `.ALL`; then `root / manifest_path(slug)` if it exists. Read it with `tomllib`. If its `flm_sha256` differs from the film's, skip to the stored archive. Otherwise `game = Path(game_root)`, joined to `root` when relative; if `game` is not a directory, raise `ArchiveError` naming the path and `mise run init`. Then call `link_build` into `root / linked_path(slug, flm.name)` and return that path; any `LinkError` becomes `ArchiveError` naming the manifest. Last, the stored archive, exactly as today.

- [ ] **Step 1: Write the failing tests** (reuse `_film` and `_store`; add `_manifest(root, slug, flm_bytes, game_root="game")`, which writes a minimal TOML, and a fake `link_build` that writes `b"LINKED"` and records its arguments):
  - `test_a_sibling_wins_over_a_manifest`
  - `test_a_matching_manifest_wins_over_a_stored_archive`: returns `root / "target/linked/<slug>/BALLOON.ALL"`, with the fake called with `(manifest, root / "game", that path)`.
  - `test_a_manifest_for_another_film_falls_through_to_the_stored_archive`: the fake is never called.
  - `test_a_failing_manifest_build_is_an_error_not_a_fall_back`: the fake raises `link.LinkError("boom")`; the result is `ArchiveError` whose message names the manifest, even though a stored archive exists.
  - `test_a_missing_game_tree_names_mise_run_init` (Review Focus 2): `ArchiveError` whose message holds the game path and `mise run init`.
  - `test_a_malformed_manifest_is_an_error_naming_it`: invalid TOML gives `ArchiveError`, not a fall back.

- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_all_archive.py -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement** the order above in `resolve_all`, and update its docstring.

- [ ] **Step 4: Run** `mise run check-py`. Expected: PASS. The callers (`capture_playone_reference.py`, `capture_video.py`, `batch_stages.py`) need no change.

- [ ] **Step 5: Commit** `feat(archive): resolve a film's .ALL from its committed manifest`.

### Task 6: `make-all` writes and backfills manifests

**Files:**
- Modify: `python/scripts/make_all.py`
- Test: `tests/test_make_all_script.py`

**Interfaces:**
- Consumes: `link.extract_manifest`, `link.ensure_binary`, `link.NotLinkable`, `link.LinkError`; `parity_layout.manifest_path`; `capture_store.current`; `ArchiveMeta`.
- Produces: `run(args, launch=None, extract: Extract | None = None) -> int`, where `Extract = Callable[[Path, Path, str, str, Path], None]` takes `(archive, flm, game, makeone_sha256, out)`. A new flag, `--manifest-only`.

`game` is `args.game_root` relative to `REPO_ROOT` when it lies inside the checkout, and absolute otherwise; it runs with `cwd=REPO_ROOT`.

- [ ] **Step 1: Write the failing tests** (the existing `_args` gains `manifest_only=False`; a fake `extract` writes the out file or raises):
  - `test_a_run_writes_the_manifest_after_publishing`: exit 0. The fake gets the published `.ALL`, the film, `"corpus/stuntisl"`-style relative game, the meta's `makeone_sha256`, and `REPO_ROOT / manifest_path(slug)`. Output has `[make-all] wrote manifest manifests/all/<slug>.toml`.
  - `test_a_not_linkable_archive_still_exits_0_and_says_why`: the fake raises `NotLinkable("chunk 0x7E01")`. Exit 0; stdout holds `no manifest` and `0x7E01`; no manifest file.
  - `test_a_link_error_after_publish_warns_and_exits_0`: the fake raises `LinkError`. Exit 0; stderr holds `warning`.
  - `test_manifest_only_extracts_from_the_stored_archive_without_makeone`: `launch` is never called, and the fake gets the stored archive path and the meta's `makeone_sha256`.
  - `test_manifest_only_without_a_stored_archive_exits_2`: the message names `mise run make-all -- --film`.
  - `test_manifest_only_for_another_flm_exits_2`: the stored meta's `flm_sha256` differs.
  - `test_manifest_only_not_linkable_exits_1`.

- [ ] **Step 2: Run** `mise exec -- uv run pytest tests/test_make_all_script.py -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement.** The hook runs after the existing `wrote …` line. The default `extract` calls `ensure_binary()` and then `extract_manifest(..., cwd=REPO_ROOT)`. `--manifest-only` keeps the film, slug and `ensure_links_or_report` checks, skips `check_replaceable` and MAKEONE, and reads the stored archive through `capture_store.current(REPO_ROOT / archive_path(slug))` and its `meta.json`.

- [ ] **Step 4: Run** `mise run check-py`. Expected: PASS.

- [ ] **Step 5: Commit** `feat(make-all): write the film's manifest and backfill with --manifest-only`.

### Task 7: Decision record, docs and the full gate

**Files:**
- Create: `docs/adr/0032-a-films-archive-is-committed-as-a-manifest.md` (context, decision D1–D9 from the spec, considered options: our own selection rejected for now, stored archive only, manifest replacing the store; it amends ADR 0023's resolve order)
- Modify: `NOTICE.md` (an "Archive manifests" section: item numbers and hashes of game files, no game bytes, rebuilt from the user's own copy)
- Modify: `docs/ARCHITECTURE.md` (route `crates/stunt-core/src/link.rs`, `crates/stunt-cli/src/link.rs` and `python/stunt_reel/link.py` to the ADR and `linking.md`)
- Modify: `docs/development.md` (project structure: `manifests/all/`)
- Modify: `research/formats/all.md` § 3.7 (link the writer)
- Modify: `docs/process/plans/all-manifests-2026-11-03.md` (status: implemented on `feat/all-manifests`; correct section 5 to this plan's names: `vfs::res_regions`, `vfs::all_chunks`, `--makeone-sha256`, `link.py` and the path helpers in `parity_layout`)

- [ ] **Step 1: Write** the files above.
- [ ] **Step 2: Run** `mise run check`. Expected: `[gate] PASS`, with every step `ok` and the doc invariants included.
- [ ] **Step 3: Commit** `docs(adr): record that a film's archive is committed as a manifest`.

### Task 8: Corpus verification and backfill (outside the gate)

**Files:**
- Modify: `research/makeone-exe/linking.md` (§ 3: the result of the CLI run; answer open question 3)
- Create: `manifests/all/<slug>.toml` for each stored archive that extracts
- Modify: `research/parity/log.md` (one row)

- [ ] **Step 1: Run** `cargo build --release -p stunt-cli`. For every `.ALL` under `corpus/siarchive` and `corpus/stisldem` that has a `.FLM` beside it, run `target/release/stuntreel link extract <ALL> --flm <FLM> --game corpus/stuntisl --makeone-sha256 0000… -o <scratch>/<n>.toml` and tally the exit codes. Expected: 83 exit 0, 205 exit 3, and `BRIEFING.ALL` exit 1 (it is truncated). Any other count is a finding: stop, and record it before going on.
- [ ] **Step 2: Backfill.** For every film with a stored archive under `captures/*/archives/`, run `mise run make-all -- --manifest-only --film <FLM>`. If none are stored on this machine, first run `mise run make-all -- --film corpus/stuntisl/VAULT/BALLOON.FLM` (about 40 s on the `archive` profile) and then backfill it. Expected: the `BALLOON` manifest's `all_sha256` equals the `all_sha256` in the stored archive's `meta.json`. After `mise run capture-ref -- --film corpus/stuntisl/VAULT/BALLOON.FLM` completes, `target/linked/flmonly-balloon/BALLOON.ALL` (or the slug `make-all` printed) exists and hashes to that value.
- [ ] **Step 3: Record** the tallies and the `BALLOON` check in `linking.md` § 3 and add a log row. Commit with the manifests: `docs(research): verify .ALL rebuilds from manifests; add backfilled manifests`.
