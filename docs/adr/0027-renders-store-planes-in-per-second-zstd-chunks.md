# Renders store their planes in per-second zstd chunks

## Status

accepted. Moves `render.json` to schema version 2 on its own: a capture's `meta.json` stays at
version 1 under [ADR 0011](0011-parity-artifacts-are-a-versioned-port.md). Ends the legacy
`palette_controls.json` fallback that ADR 0011 kept scorable, since a render that carries only that
sidecar has no store. Design and measurements: the render half of
[`capture-frame-storage-2026-10-31.md`](../process/plans/capture-frame-storage-2026-10-31.md).

## Context

`stuntreel --headless --out-dir` wrote three files per tick: `tick_NNNNN.png`, a 64,000-byte
`.idx` palette-index plane and a 128,000-byte `.layer` plane (u16 little-endian). A `CTRY.FLM`
render was about 4,000 files and 260 MB, almost all of it planes, and each file open costs
milliseconds on Windows. The batch survey deleted every render after scoring it to stay inside the
disk, and the error readout, which grades sheets drawn from a render's planes, needs them kept.

The planes compress well: consecutive ticks barely differ, and zlib per frame already shrank
`CTRY.FLM`'s `.idx` from 85 MB to 1.9 MB and `.layer` from 171 MB to 1.2 MB. The PNG adds nothing:
the renderer draws every pixel at its palette index with no lighting (`mode13h.wgsl`, light level
31), so the picture is `palette[index]` for that tick's film palette.

## Decision

A render directory holds:

- `frames.zst`: index planes, one byte per pixel; `layers.zst`: layer planes, one u16 per pixel.
  Each file is a run of independent zstd frames (level 3), one per film second
  (`tick / 50`, [I4]), holding that second's ticks back to back. A second with no tick has none.
- `palettes.zst`: each distinct effective palette once (768 bytes), as one zstd frame. A render
  changes palette far more often than a capture (350 distinct controls in a `CTRY.FLM` render), so
  JSON palettes would rival the planes in size.
- `render.json`, written last: version 2, with `palette_count`, per tick `palette_index`, and
  `chunks`, one `{second, ticks, index: {offset, length}, layer: {offset, length}}` per second.
  Validation checks that the chunks ascend, tile both files from offset 0, and hold every tick in
  its own second; readers refuse any other version with the re-render action.
- `preview/sec_NNNN.png`: each second's first tick as an indexed PNG, for people.

No PNG is written per tick, and nothing is lost: the writer compares every pixel of the page it
was handed with `palette[index]` and refuses the tick on a mismatch, so the store cannot silently
drop a picture that is not derivable. `--sample-count` and `--video` runs, keyed by sample index
rather than tick, keep their PNGs and write no planes.

One module per language knows the layout: `stunt-cli/src/render_store.rs` (the `zstd` and `png`
crates; `stunt-cli` is not bound by [I7]'s pure-Rust clause, which covers `stunt-core`) and
`RenderStore`/`RenderStoreWriter` in `python/stunt_reel/parity_artifacts.py`, on the standard
library's `compression.zstd` (Python 3.14+; the project requires 3.15). `stunt_reel` keeps
`dependencies = []`, so [ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md)
is not engaged.

## Considered Options

- **Palettes as a JSON list in `render.json`**, as first drafted: about 1.4 MB for `CTRY.FLM`,
  parsed on every open.
- **Porting `PaletteControls::film_palette` to Python** instead of storing palettes: a second copy
  of the palette code to keep in step.
- **Smaller chunks** (a tick, or ten): renders are read in tick order, and a second matches the
  previews and the per-second video scorer.
- **`ruzstd`** (pure Rust): its encoder offers fewer levels and is younger than libzstd.
- **Converting existing renders**: renders are cheap to redo; a version-1 directory is refused
  with the re-render action instead.

## Consequences

- A `CTRY.FLM` render drops from about 260 MB in 4,000 files to a few megabytes in a handful; the
  batch survey keeps its renders.
- `planes_digest`, which pins the render an error readout graded, hashes decoded content (tick,
  palette, index plane, layer plane) rather than files, so it survives a re-encode; digests from
  before this change do not match, and those readouts are graded again.
- `retime` and `plant_tree` stream ticks from one store into another, re-cut by the target seconds.
  A planted fault is stored as its index plane under a palette that reproduces its picture
  (`flicker` shifts that tick's palette); a fault no palette can carry is refused.
- After the first render on this format, the rotated `previous` render is version 1 for one run:
  `--compare` still writes `compare.json` but skips the verdict and the before/after sheets.
