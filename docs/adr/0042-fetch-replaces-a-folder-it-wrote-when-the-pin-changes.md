# Fetch replaces a folder it wrote when the pin changes

## Status

accepted 2026-11-08. Amends [ADR 0039](0039-cloud-sessions-fetch-pinned-game-archives.md)'s
"Fetch writes only an absent folder".

## Context

Under ADR 0039, `fetch` skipped any archive whose folder existed, on the assumption that each
new cloud session starts with an empty data root. On 2026-11-08 a new `stunt-reel-cloud`
session on a commit pinning `v2/corpus-stuntisl-…` found `corpus/stuntisl` already holding
the `v1` contents. `fetch` skipped it, and `status` printed the `v2` key with the `v1` tree on
disk. How the folder outlived its session is not known (`[Unknown]`). Parity then refused the
three films whose manifests read the files `v2` added. Every repin would do the same.

## Decision

- **Fetch marks what it unpacks.** It writes `.cloud-assets-pin`, holding the archive's key,
  into `<folder>.new/` before unpacking, so a folder and its pin file arrive together. A
  leftover `<folder>.new/` is deleted only when it holds a pin file.
- **A pin file that names another key means replace.** Fetch unpacks the pinned archive into
  `<folder>.new/`, deletes the folder, its pin file last, and renames `<folder>.new/` into
  place. A delete that stops partway leaves a folder still naming the old key, and a failed
  rename leaves none; either way the next fetch downloads the archive again, which R2 keeps
  since objects are never deleted. An empty pin file counts as none.
- **A folder without a pin file is never touched**, since fetch did not write it: the primary
  machine's `corpus/` stays read-only ([ADR 0022](0022-captures-are-add-only-beside-a-read-only-corpus.md)).
  The cloud SessionStart hook alone passes `--replace-unmarked`: a cloud data root's archive
  folders hold what fetch wrote, from before pin files too, and whatever a session added.
- **`status` reports the folder, not just the pin**: absent, without a pin file, holding the pin,
  or holding another key.

## Considered Options

- **Folders named after the pin, behind a link at the usual path.** Nothing would be deleted,
  and switching between pins would need no download. But with Python 3.15, `rglob` does not
  follow a linked folder below its start, so `_corpus_copy` and `batch_films.discover()`, which
  search from `corpus/`, would find nothing there, and only cloud sessions would see it.
- **Keeping the old folder as `<folder>.old/` until the new one is in place.** It guards a
  copy R2 already holds, and its cleanup could delete a folder of that name fetch never wrote.
- **Reporting a stale folder without replacing it.** Each session would have to delete the
  folder itself before parity could run.
- **DVC, rclone or a sync tool.** They track or sync paths inside a repository or loose
  objects, while the data root lies outside the checkout
  ([ADR 0036](0036-worktrees-reach-shared-state-by-configuration.md)) and each archive is one
  pinned tarball.

## Consequences

- A repin reaches a cloud session at its next start or resume, at the cost of one download.
- The first cloud start after this replaces every archive folder without a pin file,
  `captures/` included, whatever its pin; after that, each pin change replaces its folder.
  Whatever a session wrote inside a replaced folder is deleted. Cloud sessions have no DOSBox
  (`.claude/cloud-setup.sh`), so they make no captures or `make-all` archives there.
- On the primary machine, `fetch` replaces only a folder it wrote there itself.
