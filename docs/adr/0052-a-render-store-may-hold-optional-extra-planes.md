# A render store may hold optional extra planes

## Status

accepted 2026-11-20 for [#774](https://github.com/neilsh/stunt-reel/issues/774) (proposed 2026-11-19, revised 2026-11-20 after the owner's review).
Amends [ADR 0027](0027-renders-store-planes-in-per-second-zstd-chunks.md) and does not supersede it: the files ADR 0027 lists stay as it says, and a render directory may also hold the planes this record admits.

## Context

ADR 0027 fixes what a render directory holds: `frames.zst`, `layers.zst`, `palettes.zst`, `render.json` and `preview/`.
[PR #805](https://github.com/neilsh/stunt-reel/pull/805) splits the parity report's `props` loss class by prop shape, and to do so needs to know which prop drew each pixel of a render.
It adds `shapes.zst` beside `layers.zst`, which ADR 0027 does not list.
`render.json` does not list it either, so nothing ties the file to the render whose other planes sit beside it.

## Decision

- **Extra planes.**
  A render directory's store may hold per-pixel planes beside `layers.zst`, in addition to the files ADR 0027 lists.
- **What qualifies.**
  An extra plane holds one value per pixel per tick, in the same per-second chunks as `layers.zst`.
  `render.json` schema version 4 ([#813](https://github.com/neilsh/stunt-reel/issues/813)) lists each such plane with its SHA-256 and one span per chunk-table entry.
  It is never needed to score a render: a render's scores are the same with or without it, and only the report fields that describe the plane itself depend on it.
- **Optional.**
  Each plane is written only when its producer runs, and read only by the tools that need it.
- **Missing or unlisted means absent.**
  A plane that `render.json` does not list is absent, whatever file lies beside it.
  A listed plane that is missing or does not match its listing is an error.
- **The Python store.**
  The Python store reads and validates the version 4 `render.json`, its plane listing included, but never decodes a plane's contents.
- **`shapes.zst` is the first.**
  It holds one little-endian u16 per pixel, the shape word (`shape id + 1` of the prop drawing the pixel, 0 for none), chunked like `layers.zst`.
  The Rust store writes it and only the Rust store reads it, so only the Rust store yields the per-shape loss split.
  A render the Python store writes has no shape plane, and its `mean_loss_by_shape_scored` is `None`.
  The store's module docs in `crates/stunt-score/src/render_store/` hold the file's framing and the writer's and reader's details.

## Considered Options

- **Supersede ADR 0027** with a record of the whole layout: the owner chose to amend it instead.
- **Leave the plane unrecorded:** the owner chose to record it.
- **List the plane in `render.json`:** chosen, as [#813](https://github.com/neilsh/stunt-reel/issues/813).
  #813 moved `render.json` to schema version 4, which lists every optional plane with its SHA-256 and per-chunk spans, validated like the chunk table.
  Under ADR 0027's version rule, readers refuse any other version, so every existing render store, judge baselines included, is re-rendered once.
  The owner accepted that cost on 2026-11-20 ([#813 comment](https://github.com/neilsh/stunt-reel/issues/813#issuecomment-7026508652)).
  #813 started once #805 and this record merged, so #805 landed with the plane unlisted.

## Consequences

- Version 4's listing ties `shapes.zst` to its render by SHA-256, so a stale `shapes.zst` is never read as the render's own.
  Before #813 nothing did.
- The version 4 re-render of #813 rewrote every render store once, judge baselines included.
- A plane that a score would need does not qualify under this record.
- [#809](https://github.com/neilsh/stunt-reel/issues/809), moving the prop-shape attribution slot out of `SodVertex`, may become a user of this record; this record decides nothing about it.
