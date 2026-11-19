# A render store may hold optional extra planes

## Status

Proposed 2026-11-19 for [#774](https://github.com/neilsh/stunt-reel/issues/774); awaits the owner's acceptance.
Amends [ADR 0027](0027-renders-store-planes-in-per-second-zstd-chunks.md) and does not supersede it: the files ADR 0027 lists stay as it says, and a render directory may also hold the planes this record admits.

## Context

ADR 0027 fixes what a render directory holds: `frames.zst`, `layers.zst`, `palettes.zst`, `render.json` and `preview/`.
[PR #805](https://github.com/neilsh/stunt-reel/pull/805) splits the parity report's `props` loss class by prop shape, and to do so needs to know which prop drew each pixel of a render.
It adds `shapes.zst` beside `layers.zst`: one little-endian u16 per pixel, the shape word (`shape id + 1` of the prop drawing the pixel, 0 for none).
Only the Rust render store, `crates/stunt-score/src/render_store/`, reads it.
ADR 0027 does not list such a file.

## Decision

- **Extra planes.**
  A render directory's store may hold per-pixel planes beside `layers.zst`, in addition to the files ADR 0027 lists.
- **Optional.**
  Each plane is written only when its producer runs, and read only by the tools that need it.
- **Missing means absent.**
  A reader treats a missing plane as absent, not as an error.
- **`shapes.zst` is the first.**
  Its producer is the Rust store writer, and its reader is the Rust store, whose frames carry the plane to the scorer's per-shape loss split.

### How #805 keeps `shapes.zst` beside the other planes

This is the behaviour of #805's store code at `3f481b7`.

- **Layout.**
  The file is a run of records, each a u64 little-endian packed length followed by one zstd frame, one record per chunk in the chunk table's order.
  Each frame holds that second's ticks back to back.
  `render.json` does not list the file, and its schema version stays at 3.
- **The Rust writer.**
  `StoreWriter` creates `frames.zst`, `layers.zst` and `shapes.zst` together on a render's first tick, truncating any earlier copy of each.
  It writes a chunk's shape record when it closes that chunk, beside the chunk's index and layer frames.
  Each tick must carry a shape word for every pixel, and a word that does not fit a u16 is refused.
- **The Python writer.**
  `RenderStoreWriter` never writes `shapes.zst`.
  When it starts a store, on its first tick, it removes any `shapes.zst` in the directory.
  #805's review found that the writer left a `shapes.zst` from an earlier Rust render in a directory it rewrote, where the Rust store would pair that old plane with the new layers, or refuse the render on a chunk-count mismatch; this removal is the fix (`3f481b7`).
- **The Rust reader.**
  `RenderStore` opens `shapes.zst` with the rest of the store.
  When the file is not there, each frame's `shapes` is `None`; the Python report field `mean_loss_by_shape_scored` documents `None` for a render with no shape plane.
  When the file is there, it must hold exactly as many records as `render.json` has chunks, each record inside the file, or opening the store fails; the count error names the re-render.
  Each record must also decompress to two bytes per pixel of its chunk's ticks, or reading that chunk fails.
- **The Python reader.**
  `RenderStore` in `python/stunt_reel/parity_artifacts/` does not read the file.

## Considered Options

- **Supersede ADR 0027** with a record of the whole layout: the owner chose to amend it instead.
- **Leave the plane unrecorded:** the owner chose to record it.
- **List the plane in `render.json`:** a change to `render.json`'s schema, which under ADR 0027 its readers refuse at any other version, for a plane the Python store does not read.
  #805 does not do this.

## Consequences

- Only a missing plane counts as absent.
  A `shapes.zst` that is there but does not match the chunk table, does not decompress or cannot be opened is an error, as a damaged `layers.zst` is.
- Nothing ties `shapes.zst` to the render that wrote the other planes beyond its record count and decompressed sizes: `render.json` neither lists nor digests it.
  In #805 the two store writers keep it in step, the Rust one by rewriting it with the other planes and the Python one by removing it; a stale file with the same chunk count and tick counts would be read as the render's own.
- A writer handed no tick creates none of its files, as under ADR 0027, so it leaves an earlier `shapes.zst` in place along with the earlier `frames.zst` and `layers.zst`.
- The Python store keeps ADR 0027's layout: it neither reads nor writes extra planes.
- [#809](https://github.com/neilsh/stunt-reel/issues/809), moving the prop-shape attribution slot out of `SodVertex`, may become a user of this record; this record decides nothing about it.
