# Capture and render frame storage: per-second zstd chunks

Status: capture half replaced by [`video-parity-2026-10-31.md`](video-parity-2026-10-31.md), which
records each film as one AVI instead of frame dumps. The render half (per-second zstd chunks for index
and layer planes, per-second preview PNGs, no PNG per tick) stands as a separate project, to follow that
spec's rollout; its section 2 (code) was presented but not approved, and section 3 not presented.

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

### Section 3: rollout (not yet presented)

New ADR for the format; updates to ADR 0011/0024 references, `docs/ARCHITECTURE.md`, the fixtures
README and the capture research note; recapture, repoint
[`references.toml`](../../../research/parity/references.toml) in a reviewed commit, reap the v1 runs.

## Open questions

- Settled: an AVI-based capture replaces the capture half
  ([`video-parity-2026-10-31.md`](video-parity-2026-10-31.md)); only the render store remains here.
- Full-rate frame-dump capture is out of scope there; the video capture records every emulated frame.
