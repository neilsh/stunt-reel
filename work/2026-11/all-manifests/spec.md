# `.ALL` manifests: rebuild a film's archive from a committed id list (2026-11-03)

Status: **implemented on branch `feat/all-manifests`
([plan](plan.md)); ADR 0032 accepted 2026-11-03**. Section 5
names the components as built. Source:
a brainstorming session that started from "how difficult would a Rust version of
`MAKEONE.EXE` be", and the probe recorded in
[`research/makeone-exe/linking.md`](../../../research/makeone-exe/linking.md). The durable
decision, once accepted, is ADR 0032 (step 1). Builds on
[ADR 0023](../../../docs/adr/0023-make-all-generates-archives-with-makeone.md) and
[ADR 0028](../../../docs/adr/0028-a-film-has-one-capture-of-each-kind.md).

## 1. Goal

A film's `.ALL` can be rebuilt byte for byte, on any machine that has the game's `RES\`, from
a small committed text record: no emulator run and no stored binary. `MAKEONE.EXE` still
decides what goes in the archive; we record its decision once.

Success:

- `stuntreel link extract` turns a `MAKEONE` archive into a manifest, and `stuntreel link
  build` turns the manifest back into the same bytes.
- `capture-ref`, `capture_video` and the batch survey get a film's `.ALL` from its committed
  manifest when there is one, without running `make-all`.
- Rebuilding the 83 stock-only corpus archives and our stored `make-all` outputs reproduces
  every one byte for byte.

## 2. What the probe established

From [`linking.md`](../../../research/makeone-exe/linking.md), 289 corpus archives:

- Every chunk drawn from the shipped game is a byte-identical copy of one `.RES` or `.SMP`
  item; nothing is transformed (§ 1).
- A chunk's id is `(res_index << 8) | (segment + 1)` (§ 2).
- Ids ascend; the header is `6n + 6` bytes; payloads are packed without padding (§ 3).
- An id list plus the game's `RES\` rebuilt 83 of 83 stock-only archives byte for byte (§ 3).
- Some `res_index` values have several files, one per sound setting: `0xC0`/`0xC1` (`MUSIC1/2`
  `.ESS`, `.XMA`, `.XMM`, `.XMP`) and `0xC3` (`COMMNSND.SMP`, `.ZCR`). The manifest must
  name the file used (§ 5). No archive takes one `res_index` from two files, and no
  `res_index` ever had two files that both matched all of its chunks (checked during the
  review, all 289 archives), so one file per `res_index` is enough.
- All 35 files in `RES\` are `RS` containers, music and `COMMNSND.ZCR` included.
- Which items a film gets most likely depends on what the renderer loaded during playback, so
  the selection is recorded, not computed (§ 4). Computing it is out of scope.

## 3. Decisions

- **D1. One manifest per film, committed.** `manifests/all/<slug>.toml`, where `<slug>` is
  the film's slug from [`parity_layout`](../../../python/stunt_reel/parity_layout.py), the
  same one that names its stored archive (ADR 0028: one archive per film). A manifest changes
  only by a reviewed commit, like
  [`references.toml`](../../../research/parity/references.toml).
- **D2. TOML, grouped by source file.** Python reads it with the standard library's
  `tomllib`. Rust reads and writes it through the `toml` crate, a new dependency of
  `stunt-cli` only, as is `sha2` for the hashes (neither is in `Cargo.lock` today). Items are stored per source file rather than as raw ids, so the numbers
  are small and readable and the sound-variant choice is explicit.
- **D3. Every source file carries its hash.** A rebuild against different game files (another
  release, Patch #3's replaced resources, a different sound file) fails before writing, and
  names the file.
- **D4. The manifest is checked against `MAKEONE`'s own output.** `all_sha256` is the hash of
  the archive `MAKEONE` wrote. `extract` refuses to write a manifest whose rebuild differs,
  and `build` refuses to write a file whose hash differs.
- **D5. Pure core, I/O in the CLI.** The writer and the linker live in `stunt-core` with no
  file access (`[I7]`); `stunt-cli` reads files and calls them.
- **D6. Resolve order: sibling, manifest, stored archive.** A sibling `.ALL` beside the
  `.FLM` still wins (the shipped demo pairs). Next comes a committed manifest whose
  `flm_sha256` matches the film. Last comes the stored archive from `make-all`. A manifest
  that matches the film but fails to rebuild is an error, never a silent fall back.
- **D7. `make-all` writes the manifest it can.** After publishing the archive as today, it
  extracts the manifest into the working tree for review. An archive with add-on chunks gets
  no manifest; its stored archive stays the record, and the run says why.
- **D8. Rebuilt on demand, not cached.** The rebuilt `.ALL` goes to
  `target/linked/<slug>/<FILM>.ALL` and is rebuilt on each resolve. It takes milliseconds, so
  there is no cache to invalidate.
- **D9. `NOTICE.md` names manifests.** A short section says a manifest holds item numbers and
  hashes of game files, no game bytes, and that the archive it describes is rebuilt from the
  user's own copy of the game.

## 4. The manifest

```toml
# Rebuilds BALLOON.ALL from the game's RES tree (ADR 0032).
film = "BALLOON.FLM"
flm_sha256 = "…"
game_root = "corpus/stuntisl"     # the tree make-all ran MAKEONE from, repo-relative
makeone_sha256 = "…"
all_bytes = 46702
all_sha256 = "1db59e1e…"           # sha256 of MAKEONE's archive

[[source]]
file = "RES/SCENERY1.RES"         # relative to game_root, DOS case
index = 2                         # res_index, byte 0x0002 of the file
sha256 = "…"
items = [1, 5, 9, 12]             # segment + 1, ascending

[[source]]
file = "RES/MUSIC1.XMA"
index = 192
sha256 = "…"
items = [3]
```

Rules, checked by both `extract` and `build`:

- `source` entries are ordered by `index`; no two share an `index`; `items` ascend and lie in
  `1..=255` within the file's item count.
- The ids are `(index << 8) | item` over all sources. They must be unique, and the archive is
  written in ascending id order.
- `game_root` is a hint for where the files are looked up; the hashes are what make a tree
  acceptable. It is written relative to the checkout when the tree is inside it (`corpus/…`
  is, through the data-root link), and as an absolute path otherwise, which only works on the
  machine that wrote it. `build` takes `--game` to override it, for example with a Patch #3
  tree under the data root's `builds/`.
- An item number `n` names region `n - 1` of the source file in the
  [`res.ksy`](../../../research/formats/res.ksy) sense: region 0 is item 1, whether it holds
  a prop archive's name table or a scenery archive's first payload.

## 5. Components

### 5.1 `stunt-core`

- `vfs::write_all(chunks: &[(u16, &[u8])]) -> Result<Vec<u8>, VfsError>`. It sorts by
  id, rejects duplicates (`VfsError::DuplicateId`) and a count above `u16::MAX` or an offset past
  `u32` (`InvalidOffsetTable`), writes the `6n + 6` header, then the payloads. Its inverse is
  `vfs::all_chunks`, the raw `(id, payload)` split `parse_all` now names entries from; a
  property test checks that `all_chunks(write_all(x))` gives back `x` sorted.
- `vfs::res_regions(data) -> Result<ResRegions<'_>, VfsError>`, where `ResRegions { index:
  u8, regions: Vec<&[u8]> }` is the raw split: byte `0x0002` and every region, region 0
  included. `parse_res` drops region 0 as a name table, so the linker cannot use it as it
  stands. `parse_res` is refactored onto `res_regions` so the header checks live in one place,
  and its behaviour is unchanged.
- A new module, `link`, with the manifest types behind the existing `serde` feature:
  - `Manifest`, `Source` (the TOML of section 4). Digests are opaque strings to the core.
  - `build(sources, files: &BTreeMap<u8, ResRegions>) -> Result<Vec<u8>, LinkError>`, over
    the manifest's sources. The caller has already loaded and hash-checked the files they name.
  - `extract(all: &[u8], candidates: &[(&str, ResRegions)]) -> Result<Vec<Source>,
    LinkError>`. For each `res_index` in the archive, it keeps the candidate files with that
    index in which item `(id & 0xFF)` equals the payload for every chunk with that index. If
    several qualify, the first by file name wins; the archive's bytes are the same either way,
    and the corpus has no such case. Hashes are left empty for the CLI to fill.
  - `LinkError` (structural only): `NoSource { id }` when a chunk matches no candidate
    (add-on content); `Mixed { index }` when every chunk of an index has a source but no
    single file covers them all; `ItemOutOfRange`; `DuplicateIndex` and `Unsorted` (a manifest
    breaking section 4's rules); `Vfs` (the writer's `DuplicateId` and offset errors).
- Hashing stays out of `stunt-core`, which gains no dependency. The CLI computes digests and
  owns the hash errors.

### 5.2 `stunt-cli`: `stuntreel link`

- `stuntreel link extract <X.ALL> --flm <X.FLM> --game <tree> --makeone-sha256 <hex> -o
  <manifest>`. It takes the hash rather than the executable because a backfill has only the
  hash, from `meta.json`; `--game` is recorded verbatim as `game_root`. Every file in `<tree>/RES/` that starts with `RS` is a candidate, not just
  `*.RES` and `*.SMP`: the music files and `COMMNSND.ZCR` carry `0xC0`, `0xC1` and `0xC3`. It
  runs `extract`, fills the hashes, rebuilds in memory, and writes the TOML only if the
  rebuild equals the input.
- `stuntreel link build <manifest> [--game <tree>] -o <X.ALL>`. It checks every source hash
  (an error naming the file, the expected and actual hash, and the tree), builds, checks
  `all_bytes` and `all_sha256`, and writes the file atomically (`<out>.<pid>.tmp`, then a
  rename). Game files are found in any case (`[I8]`).
- Exit codes, so callers need not parse messages: 0 written; 1 an error (I/O, a hash, a
  malformed manifest, a rebuild that differs); 3 not linkable, meaning `NoSource` or `Mixed`
  (the archive holds content the game's `RES\` lacks).
- New dependencies in `stunt-cli`: `toml` and `sha2`.

### 5.3 Python

- [`link.py`](../../../python/stunt_reel/link.py) runs the binary: `build_archive`,
  `extract_manifest`, `NotLinkable` (exit 3) and `LinkError`, and `ensure_binary`, which runs
  `cargo build --release -p stunt-cli` (a no-op when current; an older binary has no `link`)
  unless the binary is running. `binary_path`, `binary_locked` and the cargo command
  (`BUILD_ARGV`, which `parity_pipeline.build_release` also runs) moved here from
  `parity_pipeline`; a separate module avoids an import cycle with `all_archive`.
- [`parity_layout.py`](../../../python/stunt_reel/parity_layout.py): `manifest_path(slug)`
  (`manifests/all/<slug>.toml`) and `linked_path(slug, film)` (`target/linked/<slug>/<FILM>.ALL`).
- [`all_archive.py`](../../../python/stunt_reel/all_archive.py):
  - `resolve_all(flm, root, slug=None, *, link_build=None)` follows D6. It reads the manifest
    with `tomllib` and compares `flm_sha256` itself, so a manifest for another `.FLM` costs no
    process launch. `link_build` is an injected `(manifest, game, out)` callable; its default,
    `link_build_in(root)`, calls `ensure_binary()` and then `build_archive`. The parity
    pipeline builds the binary itself (or was told `--no-build`), so it renders with
    `link_build_in(root, build=False)`, and its preflight passes `no_link`, which checks the
    manifest without building anything. An earlier build in `target/linked/` whose hash is
    still `all_sha256` is reused, so the file is rewritten only when it changes. A missing
    game tree is an error naming `mise run init`. Tests inject a fake.
- [`make_all.py`](../../../python/scripts/make_all.py): after `publish_archive`, it runs
  `stuntreel link extract` on the published `.ALL` with the same `--game-root`. On exit 0 it
  prints the manifest path; on exit 3 it says the archive holds add-on content and stays the
  record. When no manifest is written, for either reason, an earlier one is removed: it
  describes the archive just replaced and would still win over it. `make-all`'s exit code
  does not depend on the manifest, because the archive is already stored.
- Backfill: `make-all --manifest-only --film X.FLM [--game-root <tree>]` extracts the
  manifest from the film's stored archive without running `MAKEONE`. `meta.json` does not
  record the game root, so it takes the same default as a normal run. The byte-identical
  rebuild is what proves the tree is the right one.

## 6. Error handling

| Situation | Behaviour |
|---|---|
| Archive holds an add-on chunk | `extract` exits 3 naming the id; `make-all` keeps the archive, writes no manifest, says why |
| Source file missing or hash differs | `build` refuses, naming the file, the expected hash and the tree it looked in |
| Rebuilt bytes differ from `all_sha256` | `build` refuses; nothing is written |
| Manifest's `flm_sha256` differs from the film | The manifest does not apply; the resolver goes on to the stored archive (as for a stored archive made from another `.FLM`) |
| Manifest unreadable or malformed | Error naming the file; no fall back |

## 7. Testing

- **Fixtures** ([`tests/fixtures/`](../../../tests/fixtures/README.md)): two synthetic
  `.RES` files with distinct `res_index`, and a pair of files sharing one `res_index` to model
  the sound variants. A synthetic `.ALL` and its `.toml` manifest are built from them. All are
  documented in the fixtures README.
- **`stunt-core` tests:** the `write_all` round trip and property test; `regions` keeps
  region 0 as item 1, and `parse_res`'s existing tests still pass after the refactor;
  `extract` then `build` is the identity; a duplicate id, an out-of-range item, a mixed
  `res_index` and an add-on chunk each give their error.
- **`stunt-cli` tests:** `link extract` and `link build` on the fixtures; a changed source
  byte or a missing source file gives an error naming the file, its expected hash and the
  tree, with exit 1; an add-on chunk gives exit 3; and none leaves an output file.
- **Python tests:** the resolve order (sibling, manifest, stored archive) with a fake `link`;
  a matching manifest that fails to build is an error, not a fall back; `make-all` writes a
  manifest on success and none on a `NoSource` refusal (fake binary).
- **Outside the gate, once, recorded in `linking.md`:** rebuild the 83 stock corpus archives,
  and extract and rebuild every stored `make-all` archive in the data root, including
  `BALLOON` and `747LAND`.

## 8. Steps

1. ADR 0032 (manifests are the committed record of a film's archive; amends ADR 0023's resolve
   order) and the `NOTICE.md` section.
2. `write_all`, `vfs::res::regions` with `parse_res` moved onto it, and their tests.
3. The `link` module, fixtures and tests.
4. `stuntreel link extract|build` and their tests.
5. `resolve_all` order and the `make-all` hook and `--manifest-only`, with Python tests.
6. Backfill manifests for the films we use (`vault-*` films without a sibling, the batch
   survey's films) and commit them; run the outside-the-gate check of section 7. Done
   2026-11-03 for the one film with a stored archive on the machine that ran it, `BALLOON`;
   `747LAND` and the rest wait for their archives to be made.
7. Update [`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md),
   [`docs/development.md`](../../../docs/development.md) (the `manifests/` directory), and
   [`linking.md`](../../../research/makeone-exe/linking.md)'s open question 3.

## 9. Out of scope

- Computing the item selection from the `.FLM` without running `MAKEONE`
  ([`linking.md`](../../../research/makeone-exe/linking.md) open questions 1 and 2).
- Archives with community add-on chunks.
- The renderer reading a manifest directly instead of a `.ALL` file.
- Rebuilding an archive for a different sound setting than `MAKEONE` used. The format allows
  it (swap a source file), but nothing offers it yet.

## 10. Open questions

1. When ADR 0029's per-film builds land, should `game_root` become a build name
   (`"patch3"`, `"unpatched"`)? The hashes already pin the files, so this only changes where
   `build` looks by default.

## 11. Review log

Self-review on 2026-11-03, against the code on `main` (`69facb3`) and a corpus check:

- The candidate scan was limited to `*.RES` and `*.SMP`, which misses the music files and
  `COMMNSND.ZCR`. It now takes every `RS` file in `RES\`.
- `parse_res` treats region 0 as a name table and drops it, but item 1 of a scenery archive
  is region 0. Added `vfs::res::regions` and the item-to-region rule.
- "One file per `res_index`" was assumed. It is now checked over all 289 archives (section 2),
  with a deterministic tie-break for a case the corpus does not have.
- The hash errors sat in a core that cannot hash. They moved to the CLI, and `sha2` is named
  as a new dependency because none is in `Cargo.lock`.
- `make-all` could not tell add-on content from a failure without parsing messages. Added
  exit code 3.
- `resolve_all` could call a release binary built before `link` existed. It now runs
  `build_release` first, and reads `flm_sha256` itself.
- Backfill needed a game root that `meta.json` does not record. It now takes `--game-root`
  with the normal default.
- `game_root` is now a hint, not an authority, so an absolute path does not break the
  manifest elsewhere.

Branch review on 2026-11-03 (Opus, standards and spec):

- `toml` writes each `items` array on one line; `vault-balloon.toml`'s longest is about
  125 characters. That is readable enough, so `stunt-cli` does no wrapping (was open
  question 1).
- The parity preflight ran `cargo build` and `link build` through `resolve_all`'s default,
  ignoring `--no-build`. Preflight now passes `no_link` and the render
  `link_build_in(root, build=False)`.
- A manifest whose `flm_sha256` was not a string fell through to the stored archive. A
  manifest field of the wrong type is now an error.
