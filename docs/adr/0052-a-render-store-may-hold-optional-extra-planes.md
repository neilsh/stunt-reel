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
  It is listed in `render.json` once [#813](https://github.com/neilsh/stunt-reel/issues/813)'s schema version 4 lands.
  It is never needed to score a render: a render's scores are the same with or without it, and only the report fields that describe the plane itself depend on it.
- **Optional.**
  Each plane is written only when its producer runs, and read only by the tools that need it.
- **Missing or unlisted means absent.**
  Until #813 lands, a reader treats a missing plane file as absent, not as an error.
  After #813, a plane that `render.json` does not list is absent, and a listed plane that is missing or does not match its listing is an error.
- **The Python store.**
  Once #813 lands, the Python store reads and validates the version 4 `render.json`, its plane listing included, but never decodes a plane's contents.
- **`shapes.zst` is the first.**
  It holds one little-endian u16 per pixel, the shape word (`shape id + 1` of the prop drawing the pixel, 0 for none), chunked like `layers.zst`.
  The Rust store writes it and only the Rust store reads it, so only the Rust store yields the per-shape loss split.
  A render the Python store writes has no shape plane, and its `mean_loss_by_shape_scored` is `None`.
  The store's module docs in `crates/stunt-score/src/render_store/` hold the file's framing and the writer's and reader's details.

## Considered Options

- **Supersede ADR 0027** with a record of the whole layout: the owner chose to amend it instead.
- **Leave the plane unrecorded:** the owner chose to record it.
- **List the plane in `render.json`:** chosen, as [#813](https://github.com/neilsh/stunt-reel/issues/813).
  #813 will move `render.json` to schema version 4, which lists every optional plane with its offsets or digest, validated like the chunk table.
  Under ADR 0027's version rule, readers refuse any other version, so every existing render store, judge baselines included, is re-rendered once.
  The owner accepted that cost on 2026-11-20 ([#813 comment](https://github.com/neilsh/stunt-reel/issues/813#issuecomment-7026508652)).
  #813 starts once #805 and this record merge, so #805 lands with the plane unlisted.

## Consequences

- Until #813 lands, nothing in `render.json` ties `shapes.zst` to its render, so a stale `shapes.zst` that matches the chunk table could be read as the render's own.
  #813's version 4 listing is the fix.
- The version 4 re-render of #813 rewrites every render store once, judge baselines included.
- A plane that a score would need does not qualify under this record.
- [#809](https://github.com/neilsh/stunt-reel/issues/809), moving the prop-shape attribution slot out of `SodVertex`, may become a user of this record; this record decides nothing about it.
