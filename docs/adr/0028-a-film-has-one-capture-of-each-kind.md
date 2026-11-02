# A film has one capture of each kind

## Status

accepted 2026-11-01, not yet implemented: the order of work is in
[the capture store plan](../process/plans/capture-store-deepening-2026-11-01.md). Supersedes the
add-only rule of [ADR 0022](0022-captures-are-add-only-beside-a-read-only-corpus.md) and the numbered
runs of [ADR 0023](0023-make-all-generates-archives-with-makeone.md) and
[ADR 0024](0024-captures-are-filed-by-film-then-kind.md). The read-only corpus, filing by film and
then kind, and pinning a reference capture by digest all stay. Answers the decision half of
[#79](https://github.com/neilsh/stunt-reel/issues/79).

## Context

Numbered runs (`captures/<film>/<kind>/NNN/`) were made add-only so that a recapture could not
silently move another worktree's parity baseline. Since then the capture has settled, and the runs
have piled up without adding anything. Every repeated archive is the same file: `flmonly-747land`
holds three byte-identical `.ALL`s, `act1` and `act5` two each. `vault-ctry` holds eight frame
captures (113 to 124 frames), left over from changes to the capture tool, not real variants of the film.

The numbering also cost code. Six modules each work out which runs exist, which are complete and
which is newest, and they disagree: the batch survey and the parity bench take the highest number
without checking for `meta.json`, so they can score a run that is still being written, while
`resolve_all` skips it.

The game build is the only reason left to keep a second capture of a film, and we decided to name
each film's build in [`references.toml`](../../research/parity/references.toml)
([ADR 0029](0029-references-name-each-films-builds-and-reference.md)) rather than keep a capture for
each build.

## Decision

- **One of each kind.** A film has at most one frame capture, one video capture and one archive:
  `captures/<film>/frames/`, `captures/<film>/video/` and `captures/<film>/archives/`, with no run
  directory below them. A reader sees one only once it is complete (its `meta.json` is written
  last), and otherwise sees none. An archive is not a capture; it is filed beside them under the
  same rule.
- **The build lives in `meta.json`**, never in the path: the `PLAYONE` build that played a capture,
  and the `MAKEONE` build that wrote an archive.
- **A new capture replaces the old one.** It is written beside the old one and swapped in once its
  `meta.json` exists. The `sha256` that `references.toml` pins turns a replaced reference capture
  into a loud hash mismatch in every worktree until a reviewed commit repins it. That is the
  protection ADR 0022 got from never replacing anything.
- **Only default parameters fill the store.** A capture with a non-default `--stride` or
  `--max-frames`, or a second capture for measuring recapture noise, goes to an explicit `--out`
  outside `captures/`. `parity-bench --recapture` takes a path.

## Considered Options

- **File captures by build** (`captures/<film>/frames/<build>/`). Rejected: patch3 is the default
  and unpatched is only a fallback, so a build directory would be empty for almost every film.
  The build in `meta.json`, plus each film's row in `references.toml`, answers "which build?"
  without a second capture.
- **Keep numbered runs with one owner for the run protocol.** Rejected: it would fix how the
  readers disagree, but keep a store of duplicates nobody reads.

## Consequences

- Migration deletes every run except the two pinned references (`vault-ctry` and `vault-intro`
  004), which move into the new layout unchanged, so no baseline moves during the refactor. A
  batch survey under the new rules then recaptures and re-archives the other films.
- `references.toml` drops `capture = "NNN"`; a row pins its reference by `sha256` alone.
- `runs.py`, run claiming and both "latest capture" helpers are deleted.
