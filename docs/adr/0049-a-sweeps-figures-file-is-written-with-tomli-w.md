# A sweep's figures file is written with tomli-w

## Status

accepted 2026-11-18. The admitting record that
[ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md) asks for, for the
`tomli-w` dev dependency of [`parity_sweep.py`](../../python/scripts/parity_sweep.py)
(`mise run sweep -- --record`, [#696](https://github.com/neilsh/stunt-reel/issues/696)).

## Context

[#696](https://github.com/neilsh/stunt-reel/issues/696) makes a tracked sweep write the figures
behind its verdict into its work folder as TOML, `<work folder>/sweeps/<topic>.toml`, which
`mise run judge -- --recheck` reads back and judges again
([`score-a-render-change.md`](../howto/score-a-render-change.md) § 8). The recheck must compute on
the very floats the sweep did, so the file must read back unchanged. The standard library reads
TOML (`tomllib`) and has no writer. The first draft of #696 wrote the TOML by hand: string escapes,
key quoting, the nesting of `[[variant]]` and its film tables, float formatting, and `nan` standing
for a missing index agreement. Its review asked for a writer library instead.

## Decision

`python/scripts/parity_sweep.py` writes the figures file with `tomli-w` (dev group, `>=1.2.0`): its
`figures_toml` puts the comment lines of `HEADER` before `tomli_w.dumps` of the tables that
[`parity_figures.py`](../../python/stunt_reel/parity_figures.py) builds. `stunt_reel.parity_figures`
builds those tables and reads a file back with `tomllib`, so the shipped wheel keeps no runtime
dependencies.

The job `tomli-w` does is write a mapping as TOML that `tomllib` reads back as the same mapping. It
writes a float with `str`, the shortest text that reads back as the same float, `nan` and `inf`
included. It writes no comments, so `HEADER` is prepended as text.

Its layout sets the file's: every array is written one element per line, except an array of tables
that each fit a 100-column line with its indent, which is written one inline table per line. A
frame is therefore a table, one line each,
`{ tick = 871, ssim = 0.7732145, index = 0.5123456, scored = true }`, with `index` or `scored` left
out where the report gave none, which also removes the hand-written draft's `nan` sentinel. A film
with a longer row, which takes a six-digit tick and scores written in exponent form, would get
`[[variant.film.<film>.frames]]` tables instead; they read back the same.

ADR 0010's checks:

- **Wheels:** one `py3-none-any` wheel, so `uv sync --locked` never builds from source.
- **Typed:** ships `py.typed`.
- **Licence:** MIT.
- **Maintained:** 1.2.0 was released on 2025-01-15.
- **Dependency tree:** none; `uv tree --package tomli-w` lists only the package.

## Considered Options

- **The hand-written writer** of #696's first draft, with a frame as `[tick, ssim, index, scored]`.
  Rejected: escaping, key quoting and table nesting are a writer library's job, and the rows needed
  `nan` for a missing value. It wrote about half the bytes (below).
- **tomlkit**, a style-preserving TOML editor that also writes comments. Rejected: the job is one
  write of a document built in memory, which is `tomli-w`'s whole API, `dumps`; nothing here edits
  a file in place or keeps its style.
- **A zstd-compressed file**, as nothing edits a figures file once written (`compression.zstd`
  is in the standard library). Rejected: it was 70 KiB at four variants against Git's own 96 KiB,
  while a binary file cannot be read in a review or searched, and leaves `check-toml` nothing to
  parse, so nothing would show that it holds only scores
  ([`NOTICE.md`](../../NOTICE.md#scores-and-metrics)).
- **One row per film tick**, a CSV table with two columns per variant inside the TOML: 177 KiB
  at four variants, under the hook's limit up to about 12 variants. Rejected: history would
  shrink by about 25 KiB per sweep, for a second format parsed by hand inside the first.

## Consequences

- `tomli-w` stays in the dev group and only `python/scripts/` imports it, so only a development
  checkout installs it.
- A figures file takes a line per frame per variant. On synthetic scores written as `report.json`
  writes an `f32` (its shortest decimal form), with as many frames per film as each reference
  film's capture holds (1,875 over the seven), a four-variant sweep's file was 540 KiB, 96 KiB
  compressed by zlib: about 135 KiB per variant in a checkout. Git stores it compressed, 96 KiB
  once packed, so history grows by about 24 KiB per variant. The hand-written rows took 282 KiB
  for the same frames.
- `check-added-large-files` refuses a file over 500 KiB, which a sweep of four variants or more
  passes, and a tracked sweep's file must be committed, so [`prek.toml`](../../prek.toml) excludes
  `work/*/*/sweeps/*.toml` from that hook. That hook guards asset isolation
  ([ADR 0026](0026-commit-hooks-run-the-gates-own-tasks.md)); `check-toml` still parses every
  file the exclusion lets through, so no binary passes as one, though a valid TOML file can hold
  any data. A recheck cannot do with fewer frames: the verdict's lost-tick and film-mean tests,
  the listed frames, side effects and worst frame read every frame the join counts.
- Parallel arrays per film (`ticks`, `ssim`, `index`, `scored`) measured 31% smaller on the same
  basis (373 KiB at four variants), which fits sweeps of up to five variants under the limit. They
  were not taken: a frame's values would sit on four lines, a missing index would need a stand-in
  again, and a larger sweep would still need the exclusion.
- A change to the file's layout raises `SCHEMA` in `parity_figures.py`, which reads only its own.
