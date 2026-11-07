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
- **A read token the session never holds, fetched with curl.** The cloud environment keeps an
  R2 Admin Read only token as a Bearer network secret for `api.cloudflare.com`, which
  Anthropic's proxy attaches outside the session. `mise run cloud-assets -- fetch` downloads
  with curl from R2's REST API there, and checks size and sha256 before unpacking. With an
  Object Read only key pair in the environment variables instead, it signs S3 requests with
  `--aws-sigv4`, the pair on standard input. The owner uploads from
  the primary machine with a pinned `wrangler` and their `wrangler login`; no long-lived write
  key exists.
- **Fetch writes only an absent folder.** Each archive fills one folder of the data root. Fetch
  extracts into `<folder>.new/` and renames it into place when the folder is absent, and skips
  the archive when it exists. This is the one write into `corpus/` this project makes, and it is
  provisioning, not a run: it never updates or merges, so the primary machine's data root is
  never touched.

## Considered Options

- **`wrangler r2 object get` for fetch.** The REST API it calls is the one fetch uses, at the
  cost of Node.js in every session.
- **An AWS SigV4 network secret on R2's S3 host.** The bucket-scoped token works only there,
  but the proxy signs SigV4 for hosts under `amazonaws.com` alone and answered every request to
  the R2 host with a 502: `injection failed (...): the hostname is not under amazonaws.com`
  (2026-11-07). R2's REST API refuses bucket-scoped tokens, so the network secret is an Admin
  Read only token.
- **The key pair in environment variables.** It works, and stays as the fallback, but anyone
  who uses the environment can read the variables, and so can any session through them.
- **A public bucket, an `r2.dev` URL or presigned URLs.** The first two distribute game data;
  presigned URLs last at most seven days.
- **A Worker behind Cloudflare Access.** More infrastructure for the same exposure.
- **Fetching in the setup script.** It runs before the cloud environment's variables are set,
  so it cannot read the token; the SessionStart hook runs after Claude Code starts and can.
- **A mutable `latest` object.** A branch would fetch whatever is newest, not what it pins.
- **Updating an existing folder in place.** It would let a fetch rewrite the read-only corpus
  and needs markers to know what a folder holds.

## Consequences

- The token reads every bucket in the account, today only `stunt-reel-internal-assets`, with
  every archive version ever uploaded, since none is deleted. A session never sees it, but can
  use it through the proxy for any request to `api.cloudflare.com`. A new bucket widens what it
  reads; rotate the token on any sighting in a log or transcript.
- A failed fetch still lets the session start: the hook exits 0 and tells Claude, in one
  `FAILED` line, that archives may be missing, and `SUPERSET.ALL` is not built. The next start
  or resume fetches the archives still absent.
- A live session that wants a newer pin deletes the folder and fetches again. A stale `captures/`
  is caught anyway: parity refuses a capture whose digest differs from its row.
- Unverified until the first cloud run: that the proxy attaches the Bearer secret to the
  SessionStart hook's requests (a REST read with a Bearer token returned the pinned bytes from
  the primary machine), whether lavapipe
  ([ADR 0006](0006-ci-renders-on-lavapipe.md)) scores CTRY and INTRO as the primary machine's GPU
  does, and how long the setup script takes.
