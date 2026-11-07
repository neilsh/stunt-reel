# Cloud sessions fetch pinned game archives

## Status

accepted 2026-11-06 ([spec](../process/plans/cloud-assets-2026-11-06.md) decisions 3, 4, 6 and 7,
[plan](../process/plans/cloud-assets-implementation-2026-11-06.md)). Amends
[ADR 0022](0022-captures-are-add-only-beside-a-read-only-corpus.md) for provisioning only.

## Context

A Claude Code cloud session starts from a clone of the repo, which holds no game files (`[I7]`),
and has no data root ([ADR 0036](0036-worktrees-reach-shared-state-by-configuration.md)). To
render films and run parity it needs part of the primary machine's data root: the full game
without its music, the demo with the archives `references.toml` pins, FreeFlight's scenery, and
the reference captures. Game data must not become public, so the store is a private Cloudflare
R2 bucket, `stunt-reel-internal-assets`, and a session can hold only a credential that anything
in it, the agent included, can read.

## Decision

- **Keys name their content.** Each archive is stored at `v<N>/<archive>-<sha256[:16]>.tar.zst`,
  the suffix taken from the compressed bytes. `v<N>` changes only when what an archive is meant
  to hold changes. Objects are never overwritten or deleted, so every commit keeps fetching the
  archives it pins.
- **The repo pins the archives.** `manifests/cloud-assets.toml` holds each archive's folder,
  include and exclude globs, key, sha256 and size, and, for `captures`, the capture digest of
  every `references.toml` row it holds. An offline test fails when those digests disagree with
  `references.toml`, so promoting a reference repacks `captures` in the same PR.
- **A scoped read token, fetched with curl.** Cloud sessions hold an R2 token with Object Read
  only, scoped to the bucket, as environment variables of the cloud environment. `mise run
  cloud-assets -- fetch` downloads with `curl --aws-sigv4` against R2's S3 API, passing the key
  pair on standard input, and checks size and sha256 before unpacking. The owner uploads from
  the primary machine with a pinned `wrangler` and their `wrangler login`; no long-lived write
  key exists.
- **Fetch writes only an absent folder.** Each archive fills one folder of the data root. Fetch
  extracts into `<folder>.new/` and renames it into place when the folder is absent, and skips
  the archive when it exists. This is the one write into `corpus/` this project makes, and it is
  provisioning, not a run: it never updates or merges, so the primary machine's data root is
  never touched.

## Considered Options

- **`wrangler r2 object get` for fetch.** It uses Cloudflare's REST API, which bucket-scoped
  object tokens cannot use, so the cloud token would read every bucket in the account.
- **A public bucket, an `r2.dev` URL or presigned URLs.** The first two distribute game data;
  presigned URLs last at most seven days.
- **A Worker behind Cloudflare Access.** More infrastructure for the same exposure.
- **A mutable `latest` object.** A branch would fetch whatever is newest, not what it pins.
- **Updating an existing folder in place.** It would let a fetch rewrite the read-only corpus
  and needs markers to know what a folder holds.

## Consequences

- A leaked cloud token reads about 7 MB of game data and nothing else; rotate it on any sighting
  in a log or transcript.
- A live session that wants a newer pin deletes the folder and fetches again. A stale `captures/`
  is caught anyway: parity refuses a capture whose digest differs from its row.
- Unverified until the first cloud run: the exact network allowlist entry, whether lavapipe
  ([ADR 0006](0006-ci-renders-on-lavapipe.md)) scores CTRY and INTRO as the primary machine's GPU
  does, and how long the setup script takes.
