# Capture and render frame storage: per-second zstd chunks

Status: capture half replaced by [`video-parity-2026-10-31.md`](video-parity-2026-10-31.md), which
records each film as one AVI instead of frame dumps. The render half (per-second zstd chunks for index
and layer planes, per-second preview PNGs, no PNG per tick) stands as a separate project, to follow that
spec's rollout; its revised section 2 (render half) and section 3 were approved on 2026-11-01.

## Intent

A capture run (`captures/<film>/frames/<run>/`) and a render run (`build/parity/ours/<name>/`, batch
`…/render/`) each store one file per frame and per plane. That costs disk and, above all, read time on
Windows. The goal is a store that is quick to read, easy to write from the capture harness and the
renderer, and compact enough that the whole capture set stays small. Compression ratio matters less than
read time and writing simplicity.

Success: a run is a handful of files; reading every frame of a capture takes tens of milliseconds, not
seconds; any one frame reads without decoding the run; a person can still glance at the film.

## What exists today

| Run | Files | Contents |
|---|---|---|
| Capture | `meta.json`, `frames/tick_NNNN.idx` (64,000 bytes each), `frames/palettes_NNNN.json` (one per frame) | about 1,500 files for a 751-frame capture |
| Render | `render.json`, `tick_NNNNN.png`, `.idx`, `.layer` (u16 LE) per tick | about 4,000 files for `CTRY.FLM` |

Measured 2026-10-31 on the shared data root and the primary checkout:

- The capture store holds about 85 runs, 4.0 GB and about 124,000 files; walking it with `find`/`du`
  took over two minutes.
- One capture (`amcrisis-ac/frames/001`, 751 frames, 48.1 MB of planes) holds 751 palette files of
  3,963 bytes (2.97 MB) but only 27 distinct palettes; the palette JSON outweighs the compressed frames.
- One render (`ctry_current`, 1,333 ticks): `.idx` 85 MB compresses to 1.9 MB with zlib and `.layer`
  171 MB to 1.2 MB. Each PNG is derivable from its `.idx` and the palette, and `build/parity/previous/`
  holds a second full copy (794 MB).

## Options considered

Compression on the 751-frame capture (`zlib`/`lzma` stdlib, `ffmpeg` for video):

| Encoding | Size | Ratio | Applies to |
|---|---|---|---|
| zlib per frame | 1.98 MB | 24x | zip, `.npz`, HDF5 gzip, TIFF deflate, SQLite with zlib blobs |
| XOR with previous frame, then zlib | 1.10 MB | 44x | any container; frame *k* needs *k*-1 |
| H.264 lossless, gray8 | 0.81 MB | 59x | MP4/MKV; exact round trip |
| FFV1 | 3.5 MB | 14x | palette indices are not smooth, so FFV1 loses to zlib |
| xz over the whole stack | 0.50 MB | 96x | one stream, no per-frame access |

Read and write time, same capture, Python, warm cache:

| Layout | Size | Write | Read 1 frame | Read all |
|---|---|---|---|---|
| directory of `.idx` (today) | 48 MB | 240 ms | 5.7 ms | 4,223 ms |
| zip, deflate per frame | 2.10 MB | 399 ms | 1.1 ms | 68 ms |
| xz whole stack | 0.50 MB | 2,885 ms | ~22 ms | 43 ms |
| zstd -3 whole stack | 0.81 MB | 17 ms | ~17 ms | 34 ms |
| zstd -19 whole stack | 0.51 MB | 2,918 ms | ~18 ms | 35 ms |
| zstd -3 per frame | 2.24 MB | 32 ms | 0.04 ms | 31 ms |
| zstd -3, chunks of 10 frames | 0.97 MB | 23 ms | 0.15 ms | 24 ms |
| zstd -3, chunks of 50 frames | 0.87 MB | 34 ms | 1.7 ms | 25 ms |

The whole-stack "read 1 frame" figures are half a full decode. Rust and cold-cache reads were not timed.

What decided it:

- **Today's layout is the slow one.** Opening a 64 KB file costs about 5.7 ms even when cached (Defender
  scans each open, most likely), so a capture takes 4.2 s to read; every single-file layout takes 25 to
  70 ms.
- **The container matters less than the encoding.** Every container that compresses frames one at a time
  lands near 24x; only encodings that see the previous frame do better, because consecutive frames are
  very similar.
- **zstd beats xz on every axis** except being in Python 3.12's standard library: level 19 matches xz's
  ratio at the same cost, and level 3 writes about 170 times faster at a 60% larger file.
- **Small zstd chunks keep per-frame access** (0.15 ms) while catching most of the inter-frame
  redundancy (49x at 10 frames).
- **Rejected containers.** HDF5 needs `h5py` and numpy in Python and the C HDF5 library in Rust, and a
  crash mid-write can corrupt the file. `.npz` is zip plus a numpy dependency. Lossy video destroys
  palette indices; lossless H.264 needs `ffmpeg` on every reader and decodes from a keyframe. Multi-page
  TIFF fits the data well (a per-page `ColorMap`, per-page `ImageDescription` JSON, viewable in image
  viewers) but stays at 24x, stores each page's colormap uncompressed (about 1.1 MB per capture), and
  needs a dependency or a hand-written writer. SQLite adds no compression of its own; its gains are
  transactions and SQL over the metadata, at the price of moving every `meta.json` reader to SQL and a
  bundled C build. One database for the whole data root conflicts with add-only runs (ADR 0022),
  concurrent captures (ADR 0021) and reaping.
- **Not a filesystem setting.** NTFS compression would shrink the bytes but not the file count, and is
  per machine.

## Frame rate

`film_tick` is the authored 50 Hz clock ([I4]), so every frame belongs to film second
`film_tick // 50`. Today's captures hold 4 to 5 frames per second, unevenly (gaps of 10 to 11 ticks;
some seconds 1 to 3 after torn pages and palette steps are skipped). That is the capture's own stride
(`FILM_STRIDE_TICKS`, `plan.pick_every`), not the old 7,000-cycle setting: at 45,000 cycles `PLAYONE`
draws a page on about 99% of emulated frames, about 1.4 pages per film tick or about 70 per film second
([`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4).
The stride exists because each dump pass replays the film and holds at most `MAX_DUMPS` (40) pages.
Full-rate capture is estimated at about 6 minutes for `CTRY.FLM` and 30 for `INTRO.FLM` with eight
passes side by side, past the batch's 900 s timeout. Renders write one plane per tick, 50 per second.
The format therefore treats frames per second as variable.

## Design

### Section 1: format (approved)

A run holds:

- `frames.zst`: palette-index planes. A render also holds `layers.zst`: u16 little-endian layer planes.
- `meta.json` (capture) or `render.json` (render): schema version 2, written last, so a run without it
  is incomplete.
- `preview/sec_NNNN.png`: one indexed PNG per film second, the first frame of that second in its own
  palette, for people.

Chunk *s* is one independent zstd frame (level 3) holding every plane with `film_tick // 50 == s`, in
ordinal order, back to back. A second with no frames has no chunk.

The description file keeps today's fields except the per-frame file names, and adds:

- `palettes`: the distinct palettes, each in today's JSON shape (256 `[r, g, b]` triples);
- per frame, `palette`: its index into `palettes`;
- `chunks`: a list of `{second, offset, length, frames}`; a frame is found by its second and its
  position within the chunk.

Readers accept version 2 only. Existing captures are recaptured rather than converted (they are cheap to
redo), and stay in place until repointed and reaped, so ADR 0022 stands. Renders stop writing a PNG per
tick.

### Section 2: code (presented, not yet approved)

- **One codec per language, the only code that knows the layout.** Rust: `stunt-cli/src/plane_codec.rs`
  becomes the store codec (`PlaneWriter` closes a chunk when the film second changes and returns the
  chunk table; `PlaneReader` returns plane *n* and keeps the last chunk decoded), using the `zstd` crate
  (`cc` is already in `Cargo.lock`) and `image` for previews. Python: a new
  `python/stunt_reel/plane_store.py` with the same writer and reader and a stdlib `zlib` indexed-PNG
  writer. Python gains `zstandard`, the project's first runtime dependency (`dependencies = []` today),
  which must meet ADR 0010's bar.
- **Description types** stay in `stunt-parity`; `validate()` checks ascending contiguous chunks,
  per-chunk frame counts summing to the frame count, palette indices in range, and schema version 2.
- **Writers.** The capture harness (`tac/framebuffer.py`) gathers pages from passes that finish out of
  order and writes the store once all passes are done (about 48 MB of memory for 751 frames; about
  350 MB for a full-rate `INTRO.FLM`, which would justify per-pass chunks). The renderer (`headless.rs`)
  streams ticks in order into both stores and writes a preview at each new second.
- **Readers moved to the codec.** Rust parity (`compare.rs`, `frames.rs`, `mod.rs`, `score.rs`,
  `sheets.rs`); Python `parity_artifacts.py`, `parity_pipeline.py`, `parity_probe`, `parity_sweep`
  (crops from planes and palette, not PNGs), `batch_parity` (contact sheets), `capture_digest`,
  `capture_playone_reference`. `migrate_captures` is removed.
- **Errors.** An invalid document is refused naming the field; a chunk that decompresses to the wrong
  length names its second and file.
- **Tests.** A small synthetic v2 fixture in `tests/fixtures/` (three seconds holding 3, 0 and 2 frames,
  two palettes, one repeated `film_tick`), read by both languages and compared as decoded planes, since
  zstd versions may compress differently; per-language round trips, second boundaries, empty seconds,
  the last chunk, out-of-range ordinals, corrupt offsets and bad palette indices; `mise run check`.

### Section 2, render half (revised 2026-11-01, approved 2026-11-01)

Re-checked against `main` at `f7ca3d8` (PR #42 merged). Captures are out of scope; a capture's
`meta.json` stays at version 1.

**Format refinements to section 1.**

- A render has two plane files, so a chunk records both: `chunks` is a list of
  `{second, ticks, index: {offset, length}, layer: {offset, length}}`. Offsets run contiguously from 0
  in each file; a tick's place in its chunk is its order in `ticks`.
- The effective palettes go in a third file, `palettes.zst`: one zstd frame of 768-byte palettes
  (256 RGB triples), each distinct palette once, in first-use order. `render.json` gains
  `palette_count`, and per tick `palette_index` (`palette` is already the tick's controls `sky`,
  `brightness`, `saturation`). This departs from section 1's JSON list: renders change palette far
  more often than captures (`ctry_current` 1,333 ticks with 350 distinct controls, `intro_current`
  2,876 with 171), and 350 palettes in today's JSON shape are about 1.4 MB, as large as the compressed
  planes and parsed on every open. Python and the scorer then need neither the PNG nor a port of
  `PaletteControls::film_palette`.
- `render.json` moves to version 2 on its own: `SCHEMA_VERSION` splits into a render and a capture
  constant, in both languages.
- `--sample-count` and `--video` runs (keys `sample_NNNN`, not ticks) keep their PNGs and drop their
  planes; nothing reads sample planes.

**Rust.**

- `stunt-cli/src/plane_codec.rs` becomes `render_store.rs`, the only Rust code that knows the layout:
  `RenderStoreWriter` takes `(tick, palette, indices, layers)` in tick order, closes a chunk when the
  film second changes, writes `preview/sec_NNNN.png` (indexed, through the `png` crate already in the
  lock) for each second's first tick, and returns the chunk table and palettes. `RenderStore::open(dir)`
  reads and validates `render.json`, checks the chunk table against the two file sizes, and returns a
  tick's index plane, layer plane and palette, keeping the last decoded chunk. Decoding a chunk costs
  one film second (50 ticks, 9.6 MB decoded), so a reader walking ticks in order decodes each chunk
  once.
- The writer replaces its own files (`frames.zst`, `layers.zst`, `palettes.zst`, `preview/`) and
  leaves anything else in the directory; `parity_run` already starts each render in a fresh tree.
- New crate dependency `zstd` (C libzstd built through `cc`), level 3; `cargo deny` must pass.
- **The PNG is dropped only because it is derivable.** The writer checks every pixel's RGBA against
  `palette[index]` and refuses the tick, naming tick and pixel, on any mismatch. Checked on
  `ctry_current` (every tenth of 1,333 ticks): each index maps to exactly one colour in each tick.
- `RenderJournal` (`parity_artifacts.rs`) owns the writer, so `render.json` is still written last.
- Description types in `stunt-parity/src/render.rs`: `palettes`, `palette_index`, `RenderChunk`.
  `validate()` checks version 2; chunks ascending by second, contiguous in each file; chunk tick counts
  summing to the tick count; every tick's `tick // 50` equal to its chunk's second; `palette_index` in
  range; 256 entries per palette.
- Readers: `parity/frames.rs` (`load_render_frame` takes luminance from `palette[index]`, not a PNG),
  `parity/mod.rs` (a tick is present when the record holds it, not when a PNG exists),
  `parity/compare.rs` (both the previous and the current render through the store).

**Python** (`python/stunt_reel`, no new dependency).

- `parity_artifacts.py` gains the same reader and writer on the standard library: `compression.zstd`
  (Python 3.14+; the project requires 3.15, whose build ships libzstd 1.5.7) and a `zlib` indexed-PNG
  writer for previews. ADR 0010 is not engaged: `stunt_reel` keeps `dependencies = []`.
- `render_plane_paths`, `RENDER_SUFFIXES` and the per-tick file checks go. `read_page` reads through the
  store, so `parity_probe` and `parity_sweep` need no change of their own.
- `parity_pipeline.py`: `check_render` asks the record for the captured ticks; `retime` streams the
  source ticks through the reader into a new store, re-cut by the target seconds (memory stays at one
  chunk, not the 256 MB of a whole `CTRY.FLM` render).
- `bench/planes.py` `RenderTree` reads the store; `rgb` is `palette[idx]`. Its 64-tick cache (about
  500 MB for a whole tree's worth of hits) gives way to the reader's decoded chunks: the last two, so
  a sheet that reaches back one second does not decode twice. `bench/run.py` `plant_tree` streams the
  source into a new store, substituting the planted ticks, instead of overwriting files in a copy.
- **`planes_digest`** (`bench/errors.py`) becomes SHA-256 over, for each tick in order: the tick as
  u32 LE, its 768 palette bytes, its index plane and its layer plane (u16 LE). That is everything a
  sheet shows (the picture is `palette[index]`), and it does not change with zstd version or level.
  Digests recorded before the change will not match, so existing readouts are re-graded once; the
  render must be redone for version 2 anyway.

**Errors.** A version-1 `render.json` is refused with "re-render with the current
`stuntreel --headless`". A chunk that decompresses to the wrong length names its second and file. A
missing tick names the tick and the render. An invalid document names the field.

**Tests.**

- `tests/fixtures/parity/v2/render/`: a 4x3 render with ticks in three seconds holding 3, 0 and 2
  ticks and two palettes, written by Rust, read by both languages and compared as decoded planes (zstd
  versions may compress differently). The v1 `pages/` planes and `render.json` move to it.
- `tests/fixtures/parity/bench/render{,_before}` regenerated as stores by `make_fixture.py`; the SSIM
  and differential goldens must stay unchanged.
- Per-language round trips; second boundaries; an empty second; the last chunk; a missing tick; a
  corrupt offset; a truncated chunk; a bad `palette_index`; a `palettes.zst` of the wrong length; a
  version-1 document; the RGBA mismatch refusal; `planes_digest` stable across a re-encode.
- The Rust test helpers that write renders (`parity/test_support.rs`, `compare.rs` tests) write
  through `RenderStoreWriter`, so no test builds the layout by hand.

**Rejected.**

- Palettes as a JSON list in `render.json` (section 1): 1.4 MB for `CTRY.FLM`, see above.
- Deriving palettes from the controls in Python: a second copy of `film_palette` to keep in step.
- A chunk per tick or per 10 ticks: renders are read in order, and per-second chunks match the
  previews and the per-second video scorer.
- `ruzstd` (pure Rust): its encoder offers fewer levels and is younger than libzstd. [I7]'s pure-Rust
  clause ([ADR 0002](../../adr/0002-stunt-core-may-take-small-dependencies.md)) covers `stunt-core`
  only, so `stunt-cli` takes the C library without amending it.

### Section 3: rollout (approved 2026-11-01)

One branch and one PR against `main`. Captures and
[`references.toml`](../../../research/parity/references.toml) are untouched, so no reviewed repoint is
needed.

1. **Code and tests** as section 2, test-first, with the v2 fixture and the regenerated bench fixture.
2. **Records.** A new ADR, "Renders store planes in per-second zstd chunks": the format, the
   derivable-PNG check, palettes in `palettes.zst`, and stdlib zstd in Python, so ADR 0010 is not
   engaged. Updated to match: `tests/fixtures/README.md` (§ 13's v1 `pages/`, the bench fixture, the new
   v2 render), `docs/development.md`, `docs/ARCHITECTURE.md` if it routes `plane_codec.rs`, and the
   living notes that describe a render directory (`research/parity/method.md`, `attribution.md`,
   `probes.md`). Dated plans and `log.md` rows stay as written.
3. **The batch survey keeps renders.** `batch_parity.py` stops deleting each film's `render/` after
   scoring: at about 3 MB a film, every film's render together is smaller than one of today's, and the
   error readout reads them.
4. **Old renders are not converted.** A version-1 render is refused with the re-render message. The
   next `mise run parity` writes `ours` as version 2, and the rotated `previous` becomes comparable from
   the run after that; until then `--compare` against a version-1 `previous` still writes
   `compare.json` (reports only) but skips the verdict and the before/after sheets, naming the
   re-render action. The v1 trees under `build/parity/` (about 1.6 GB in the primary checkout) are
   left for the user to delete; nothing deletes them automatically.
5. **Measurement**, recorded in this plan before the PR, on `CTRY.FLM` (the `ctry_current` render),
   before and after: size and file count, render wall time, Python time to read every tick through
   `RenderTree`, and `stuntreel parity` wall time against its reference.

### Measurement (2026-11-01)

`CTRY.FLM`, 1,337 ticks, `build/parity/ours/ctry_current` in this worktree, release build, the same
machine for both. Before is `main` at `f7ca3d8`; after is this branch. Times are `mise run parity --
--films ctry --no-build` (render and score) and `--no-render` (score only), two runs each.

| | Before (per-tick files) | After (render store) |
|---|---|---|
| Size | 263 MB | 3.9 MB (`frames.zst` 1.98 MB, `layers.zst` 1.20 MB, `render.json` 0.58 MB, `palettes.zst` 18 KB, 27 previews) |
| Files | 4,012 | 31 |
| Render and score | 5.7 to 6.9 s | 4.3 to 4.6 s |
| Score only | 1.1 s | 1.2 to 1.3 s |
| `RenderTree`, every tick | 0.69 s | 0.81 s |
| `RenderTree`, one tick from cold | 0.4 ms | 16 ms (parsing `render.json` and decoding one second) |
| Score | SSIM 0.7808, IoU 0.9774, idx 0.515, 114/121 | identical |

The writer's derivable-picture check passed on every tick, so the film palette over the index plane
reproduces the renderer's RGBA exactly. Reading is a little slower per tick from cold because
`render.json` is now a 585 KB document carrying the chunk table and palette indices; every reader in
the repo opens a store once and walks its ticks, so this does not show in the scorer's time.

## Open questions

- Settled: an AVI-based capture replaces the capture half
  ([`video-parity-2026-10-31.md`](video-parity-2026-10-31.md)); only the render store remains here.
- Full-rate frame-dump capture is out of scope there; the video capture records every emulated frame.
