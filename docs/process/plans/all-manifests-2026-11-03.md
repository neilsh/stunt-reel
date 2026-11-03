# `.ALL` manifests: rebuild a film's archive from a committed id list (2026-11-03)

Status: **design approved in chat 2026-11-03; spec awaiting review, not implemented**. Source:
a brainstorming session that started from "how difficult would a Rust version of
`MAKEONE.EXE` be", and the probe recorded in
[`research/makeone-exe/linking.md`](../../../research/makeone-exe/linking.md). The durable
decision, once accepted, is ADR 0030 (step 1). Builds on
[ADR 0023](../../adr/0023-make-all-generates-archives-with-makeone.md) and
[ADR 0028](../../adr/0028-a-film-has-one-capture-of-each-kind.md).

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
  name the file used (§ 5).
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
  `stunt-cli` only. Items are stored per source file rather than as raw ids, so the numbers
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
# Rebuilds BALLOON.ALL from the game's RES tree (docs/adr/0030-…).
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
- `game_root` names where the files are looked up. `build` takes `--game` to override it, for
  example a Patch #3 tree under the data root's `builds/`. The hashes decide whether the
  override is acceptable.

## 5. Components

### 5.1 `stunt-core`

- `vfs::all::write_all(chunks: &[(u16, &[u8])]) -> Result<Vec<u8>, VfsError>`. It sorts by
  id, rejects duplicates and a count above `u16::MAX`, writes the `6n + 6` header, then the
  payloads. It is the inverse of `parse_all` for an intact archive: a property test checks
  that `parse_all(write_all(x))` gives back `x`.
- A new module, `link`, behind the existing `serde` feature for the manifest type:
  - `Manifest`, `Source` (the TOML of section 4).
  - `SourceArchive { index: u8, items: Vec<&[u8]> }`, one parsed `.RES` or `.SMP` file. It
    reuses the segment split of `vfs::res`, refactored to expose raw segments if needed.
  - `build(manifest, lookup: impl Fn(&Source) -> Result<SourceArchive>) -> Result<Vec<u8>>`.
  - `extract(all: &[u8], candidates: &[(name, SourceArchive)]) -> Result<Vec<Source>>`. For
    each chunk it finds the candidates whose `index` is the id's high byte and keeps those
    whose item `(id & 0xFF) - 1` equals the payload. It fails with `LinkError::NoSource { id }`
    when none matches (add-on content), and with `LinkError::Mixed { index }` when one
    `res_index` would need two files.
  - `LinkError` variants: `NoSource`, `Mixed`, `ItemOutOfRange`, `DuplicateId`,
    `SourceMismatch` (hash), `ArchiveMismatch` (`all_sha256`).
- Hashing: `stunt-core` gains no SHA-256 dependency. The CLI hashes and passes the digests in,
  so the core compares strings it is given.

### 5.2 `stunt-cli`: `stuntreel link`

- `stuntreel link extract <X.ALL> --flm <X.FLM> --game <tree> [--makeone <exe>] -o
  <manifest>`. It scans `<tree>/RES/*.RES` and `*.SMP` as candidates, runs `extract`, fills
  the hashes, rebuilds in memory, and refuses (exit 1, no file written) unless the rebuild
  equals the input. It writes the TOML.
- `stuntreel link build <manifest> [--game <tree>] -o <X.ALL>`. It checks every source hash,
  builds, checks `all_sha256`, and writes the file atomically (a temporary name, then a
  rename).
- New dependency in `stunt-cli`: `toml`, plus `sha2` if no SHA-256 implementation is already
  in its dependency tree.

### 5.3 Python

- [`all_archive.py`](../../../python/stunt_reel/all_archive.py):
  - `manifest_path(slug) -> Path` (`manifests/all/<slug>.toml`).
  - `resolve_all(flm, root, slug=None, *, link=...)` follows D6. `link` is an injected callable
    that runs `stuntreel link build`. Its default calls the release binary from
    `parity_pipeline.binary_path()` and builds it first when missing, as the batch survey does.
    Tests inject a fake.
- [`make_all.py`](../../../python/scripts/make_all.py): after `publish_archive`, it runs
  `stuntreel link extract` on the published `.ALL`. It prints the manifest path on success, or
  the `NoSource` id on refusal. `make-all`'s exit code does not depend on the manifest: the
  archive is already stored.
- Backfill: `make-all --manifest-only --film X.FLM` extracts the manifest from the film's
  stored archive without running `MAKEONE`. It covers archives made before this change.

## 6. Error handling

| Situation | Behaviour |
|---|---|
| Archive holds an add-on chunk | `extract` refuses with the id; `make-all` keeps the archive, writes no manifest, says why |
| Source file missing or hash differs | `build` refuses, naming the file, the expected hash and the tree it looked in |
| Rebuilt bytes differ from `all_sha256` | `build` refuses; nothing is written |
| Manifest's `flm_sha256` differs from the film | The manifest does not apply; the resolver goes on to the stored archive (as for a stored archive made from another `.FLM`) |
| Manifest unreadable or malformed | Error naming the file; no fall back |

## 7. Testing

- **Fixtures** ([`tests/fixtures/`](../../../tests/fixtures/README.md)): two synthetic
  `.RES` files with distinct `res_index`, and a pair of files sharing one `res_index` to model
  the sound variants. A synthetic `.ALL` and its `.toml` manifest are built from them. All are
  documented in the fixtures README.
- **`stunt-core` tests:** the `write_all` round trip and property test; `extract` then `build`
  is the identity; a duplicate id, an out-of-range item, a mixed `res_index` and an add-on
  chunk each give their error.
- **`stunt-cli` tests:** `link extract` and `link build` on the fixtures; a changed source
  byte gives `SourceMismatch`, and no output file is left.
- **Python tests:** the resolve order (sibling, manifest, stored archive) with a fake `link`;
  a matching manifest that fails to build is an error, not a fall back; `make-all` writes a
  manifest on success and none on a `NoSource` refusal (fake binary).
- **Outside the gate, once, recorded in `linking.md`:** rebuild the 83 stock corpus archives,
  and extract and rebuild every stored `make-all` archive in the data root, including
  `BALLOON` and `747LAND`.

## 8. Steps

1. ADR 0030 (manifests are the committed record of a film's archive; amends ADR 0023's resolve
   order) and the `NOTICE.md` section.
2. `write_all` and its tests.
3. The `link` module, fixtures and tests.
4. `stuntreel link extract|build` and their tests.
5. `resolve_all` order and the `make-all` hook and `--manifest-only`, with Python tests.
6. Backfill manifests for the films we use (`vault-*` films without a sibling, the batch
   survey's films) and commit them; run the outside-the-gate check of section 7.
7. Update [`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md),
   [`docs/development.md`](../../development.md) (the `manifests/` directory), and
   [`linking.md`](../../../research/makeone-exe/linking.md)'s open question 3.

## 9. Out of scope

- Computing the item selection from the `.FLM` without running `MAKEONE`
  ([`linking.md`](../../../research/makeone-exe/linking.md) open questions 1 and 2).
- Archives with community add-on chunks.
- The renderer reading a manifest directly instead of a `.ALL` file.
- Rebuilding an archive for a different sound setting than `MAKEONE` used. The format allows
  it (swap a source file), but nothing offers it yet.

## 10. Open questions

1. Does `toml` serialise a long `items` array readably, or does `stunt-cli` need its own line
   wrapping? Answered in step 4. The file stays valid TOML either way.
2. When ADR 0029's per-film builds land, should `game_root` become a build name
   (`"patch3"`, `"unpatched"`)? The hashes already pin the files, so this only changes where
   `build` looks by default.
