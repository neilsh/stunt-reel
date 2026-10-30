# Captures are filed by film, then by kind

## Status

accepted 2026-10-29. The design and the ruled-out alternatives are in
[the captures layout note](../process/plans/captures-layout-2026-10-29.md). Supersedes the
layout parts of [ADR 0022](0022-captures-are-add-only-beside-a-read-only-corpus.md)
(`captures/<film>/<capture id>/`) and [ADR 0023](0023-make-all-generates-archives-with-makeone.md)
(`captures/all/<film>/<id>/`); add-only captures and the read-only corpus stay.

## Context

`captures/all/` shared a namespace with the film directories, so a film called `ALL` had to be
refused. A film directory was the `.FLM` stem, and different films share stems while one film
sits in up to four corpus copies. A capture id packed a date, a checkout label and a film hash,
of which only the hash described the capture.

## Decision

- **Film first.** `captures/<film>/frames/<run>/` holds a DOSBox-X frame capture and
  `captures/<film>/archives/<run>/` a generated `.ALL`. Every top-level entry is a film; no name is reserved.
- **The film is named by its source.** The slug is the parent folder and stem of the corpus
  path, lower case, runs outside `[a-z0-9_]` collapsed to `-`: `VAULT/CTRY.FLM` is `vault-ctry`
  whichever corpus copy was read. `--name` overrides it.
- **Runs are counters.** `001`, `002`, ... per film and kind, claimed by an atomic `mkdir`
  (an archive claims `NNN.lock`). Date, checkout and the film's hash live in `meta.json`;
  `references.toml` pins a capture by film, run and content digest.
- **Frame files sit under `frames/`** inside a capture so `meta.json` is visible. The capture
  readers accept a file name that is a basename or `frames/<basename>`; older captures read unchanged.

## Consequences

- A repeat capture of the same bytes is allowed and becomes the next run; make-all no longer refuses an existing id.
- The digest of a capture covers relative paths and `meta.json`, so moving the two existing captures
  changes it. The migration (`mise run migrate-captures`) checks every file's own hash, then re-pins
  `references.toml` in a reviewed commit.
- Branches that name `legacy-2026-10-24` break until they rebase; no compatibility link is left.
