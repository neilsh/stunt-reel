# A reference pins the archive its film plays

## Status

accepted 2026-11-06 ([spec](../process/plans/vault-parity-films-2026-11-06.md) D9,
[plan](../process/plans/vault-parity-films-implementation-2026-11-06.md) Task 6–8). Amends
[ADR 0029](0029-references-name-each-films-builds-and-reference.md). Closes
[#245](https://github.com/neilsh/stunt-reel/issues/245).

## Context

A `references.toml` row pinned the capture by its digest and named the builds, but not the `.ALL`
archive the film plays. The render found its archive by path: the first copy of the film's slug in
sorted corpus order, then the `.ALL` beside it. For both references that copy is under
`siarchive/Films/NewPLAY/Vault/`, whose archives differ from the demo archives the captures
recorded in `meta.json` `all_sha256` (`research/parity/method.md` § 3, the 2026-11-06 archive
finding). The two render the same to four decimals, so no recorded score moved, but nothing
checked the render's archive against the capture's.

The same lookup blocks new references. `references.archive_makeone_build` calls an archive shipped
under `siarchive/` an `unknown` build, and the capture's build check refuses that for a row naming a
`makeone`. A film whose only copy is there, such as `SPLANES.FLM`, could not be captured against a
row at all.

## Decision

A row may name `all_sha256`, the SHA-256 of the archive the film plays. `mise run parity` and
`mise run capture-ref` resolve the archive by that hash (`all_archive.resolve_all(..., pinned=)`):
the sibling `.ALL` if it matches, else a committed manifest (ADR 0032) that builds it, else the
stored archive, else any corpus copy whose `.FLM` matches. None matching is an error naming the
pin. `parity` also refuses a capture whose `meta.json` records another archive than the row pins.
`capture-digest` prints the capture's archive hash as the row's `all_sha256` line.

`[ctry]` and `[intro]` pin the demo archives their captures recorded.

## Considered Options

- **Pin the `.FLM` path.** Corpus copies move and are renamed between packages; a path names a
  place, not the bytes the capture saw.
- **Pin nothing and compare after the fact.** A check after rendering finds the mismatch, but the
  lookup still takes the `siarchive` copy, whose `unknown` build the capture's build check refuses.

## Consequences

- A row without `all_sha256` resolves as before, so existing rows keep working until pinned.
- New references build their archive from a committed manifest (ADR 0032), and the row pins the
  manifest's `all_sha256`.
- Changing a row's pin is a reviewed edit of `references.toml`, like changing its capture.
