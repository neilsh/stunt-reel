# Cloud assets: game data for Claude Code cloud sessions from a private R2 bucket (2026-11-06)

Status: **design, awaiting review**. Source: a brainstorming session that followed the superset
probe ([`research/makeone-exe/linking.md`](../../../research/makeone-exe/linking.md) § 7) and
`mise run superset-all` (#256). Builds on
[ADR 0006](../../adr/0006-ci-renders-on-lavapipe.md) (rendering on lavapipe),
[ADR 0022](../../adr/0022-captures-are-add-only-beside-a-read-only-corpus.md) (a read-only
corpus), [ADR 0032](../../adr/0032-a-films-archive-is-committed-as-a-manifest.md) (archive
manifests), [ADR 0036](../../adr/0036-worktrees-reach-shared-state-by-configuration.md) (the
data root) and [ADR 0037](../../adr/0037-a-reference-pins-its-archive.md) (each reference pins
its archive).

## 1. Goal

A Claude Code cloud session can render films and run parity with no game files in git. It
downloads two archives from the private Cloudflare R2 bucket `stunt-reel-internal-assets`
(location WNAM) into its data root, and every tool then finds its files where it finds them on
the primary machine.

Success:

- A fresh cloud session's setup script fetches both archives and `mise run superset-all`
  succeeds; `stuntreel --headless corpus/stuntisl/VAULT/CTRY.FLM --all
  target/linked/superset/SUPERSET.ALL ...` renders.
- `mise run parity` on CTRY and INTRO resolves the pinned archives and scores within the
  recapture noise of the primary machine's scores (the renderer runs on lavapipe there, see
  open question 2).
- A film whose archive is a committed manifest (`manifests/all/*.toml`) gets it rebuilt in the
  cloud, so a future reference for another `VAULT` film needs nothing beyond a repack of
  `captures`.
- Every downloaded archive is checked against a hash committed in the repo before it is
  unpacked.
- The cloud credential can read this one bucket and nothing else.

## 2. What we measured

On 2026-11-06, zstd level 19 over one tar of each set (throwaway script, not committed):

| Set | Files | Raw | zstd -19 |
|---|---|---|---|
| `corpus/stuntisl` without its 14 sound files | 102 | 7.96 MB | 3.27 MB |
| `corpus/stuntisl` sample files: `RES/COMMNSND.{SMP,ZCR}`, `RES/SNDFX{1,2}.SMP` | 4 | 2.19 MB | 2.02 MB |
| `corpus/stuntisl` music files: `RES/MUSIC{1,2}.{ESS,XMA,XMI,XMM,XMP}` | 10 | 1.79 MB | 1.59 MB |
| `corpus/siarchive/Developer/FreeFlight/SIDATA` | 10 | 1.47 MB | 0.44 MB |
| `corpus/stisldem/VAULT/{CTRY,INTRO}.ALL` | 2 | 0.29 MB | 0.08 MB |
| `captures/` (CTRY and INTRO frames, BALLOON's stored archive; no `*.lock`) | 938 | 33.3 MB | 0.64 MB |

So the `corpus` archive of decision 2 (everything but music) is about 5.8 MB and both archives
about 6.4 MB. These add up per-set measurements; `pack` reports the real figure.

Findings that shaped the design:

- `stuntisl`'s `PFONT.BIN`, `VAULT/CTRY.FLM` and `VAULT/INTRO.FLM` are byte-identical to
  `stisldem`'s.
- `CTRY.ALL` and `INTRO.ALL`, the archives `research/parity/references.toml` pins, exist only
  in `corpus/stisldem/VAULT/`, and cannot be rebuilt without the music files: `CTRY.ALL` holds
  one `0xC0` music chunk and three `0xC3` `COMMNSND` chunks, `INTRO.ALL` one `0xC1` and
  seventeen `0xC3`. `resolve_all` accepts only an archive hashing to the pin
  (`all_archive.py`), so they ship as files. Rendering parity from `SUPERSET.ALL` instead was
  rejected: it scores within noise but not identically, and needs an unpinned parity mode.
- Every `MAKEONE` archive copies a few sound items: `manifests/all/vault-balloon.toml` lists
  `RES/COMMNSND.SMP` and `RES/SNDFX2.SMP`. `resolve_all` tries a film's committed manifest
  before its stored archive, and raises rather than falls back when a matching manifest cannot
  be built. So the sample files ship, and every manifest from our `make-all` profile (which
  writes no music chunk, [`linking.md`](../../../research/makeone-exe/linking.md) § 5)
  rebuilds in the cloud.
- `SUPERSET.ALL` and the 17 shape `.RES` files compress to the same size (1,279,254 against
  1,279,151 bytes), so the archive carries the `.RES` source and the session derives the
  superset.
- The CI ubuntu job renders on Mesa's lavapipe (ADR 0006); a cloud container has no GPU either.

## 3. Decisions

1. **Archives mirror the data root.** Each archive extracts into one folder of
   `$STUNT_DATA_ROOT` with members at their real paths, so `corpus_root()`, `capture_root()`,
   `--game corpus/stuntisl` and `--sidata` resolve unchanged. A cloud data root is a sparse
   copy of the primary machine's.
2. **Two archives.**
   - `corpus`, extracted into `$STUNT_DATA_ROOT/corpus/`:
     - `stuntisl/**`, except the music files `RES/MUSIC1.*` and `RES/MUSIC2.*`;
     - `siarchive/Developer/FreeFlight/SIDATA/**`;
     - `stisldem/VAULT/CTRY.ALL` and `stisldem/VAULT/INTRO.ALL`.
   - `captures`, extracted into `$STUNT_DATA_ROOT/captures/`: each capture's `frames/` and
     `archives/` (ADR 0028), without `*.lock` files. Video captures stay out: nothing scores
     them in the cloud, and they would dominate the size.
3. **Bucket keys: `v<N>/<archive>-<sha256[:16]>.tar.zst`.** `v<N>` changes only when what an
   archive is *meant* to hold changes (a new folder, the music back in). The suffix is the
   first 16 hex digits of the `.tar.zst`'s sha256, so it changes whenever the bytes do (a
   promoted reference, a new file). Objects are never deleted or overwritten, so old commits
   keep fetching theirs; storage is negligible.
   ```
   stunt-reel-internal-assets/
     v1/corpus-<sha16>.tar.zst
     v1/captures-<sha16>.tar.zst
   ```
4. **The repo pins the archives.** `manifests/assets.toml` holds the version, each archive's
   file list (include and exclude globs relative to its folder), and the current key, sha256
   and size. It holds paths and hashes, no game bytes. Changing an archive is one reviewed
   commit of that file. `pack` also records, under `[captures]`, the capture hash of every
   `references.toml` row it packed, and an offline test fails when the two files disagree, so
   a PR that promotes a reference must repack `captures` in the same PR.
5. **Deterministic tar.** Members sorted, mtime 0, uid/gid 0, mode 0644 (0755 for folders), no
   user names, so the same files give the same tar on any machine. The compressed bytes depend
   on the libzstd version as well; a repack under another version gives a new key, which is
   harmless.
6. **Auth.**
   - Cloud sessions: an R2 API token with **Object Read only**, scoped to this bucket. Its S3
     key pair and the account id are environment variables of the Claude Code cloud
     environment (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`), never in the
     repo. Anything in the session, the agent included, can read them; the scope limits a leak
     to reading about 6.4 MB of game data. Rotate on any sighting in a log or transcript.
   - Uploads: from the primary machine through `wrangler` with the owner's Cloudflare login,
     at a pinned version (`npx wrangler@<version> r2 object put ... --remote`); no long-lived
     write key exists.
   - Rejected: a public bucket or `r2.dev` URL (distributes game data), presigned URLs (7-day
     maximum life), a Worker behind Cloudflare Access (more infrastructure for the same
     exposure), and a mutable `latest` pointer in the bucket (a branch would get whatever is
     newest).
7. **Fetch replaces only what it created.** ADR 0022 keeps `corpus/` read-only and captures
   add-only. Fetching is provisioning, not a run. It extracts into `<into>.new/`, then swaps
   that for `<into>/`, and only when `<into>/` is absent or carries the marker a previous fetch
   left (`$STUNT_DATA_ROOT/.assets/<archive>.sha256`). The swap removes files a newer archive
   dropped (a reference with fewer frames). It refuses a `corpus/` or `captures/` it did not
   create, so the primary machine's data root is never touched. A new ADR records this
   exception.
8. **`DEFAULT_FILM` becomes `corpus/stuntisl/VAULT/CTRY.FLM`** (same bytes as the demo's), so
   tasks run with no film argument work on a cloud data root.
9. **The session builds `SUPERSET.ALL`** with `mise run superset-all` after fetching, until
   #252's `--game` makes it unnecessary.

## 4. Components

### 4.1 `manifests/assets.toml`

```toml
# Game data for cloud sessions, in the private R2 bucket (docs/process/plans/cloud-assets-2026-11-06.md).
bucket = "stunt-reel-internal-assets"
version = "v1"

[corpus]
into = "corpus"
include = ["stuntisl/**", "siarchive/Developer/FreeFlight/SIDATA/**",
           "stisldem/VAULT/CTRY.ALL", "stisldem/VAULT/INTRO.ALL"]
exclude = ["stuntisl/RES/MUSIC1.*", "stuntisl/RES/MUSIC2.*"]
key = "v1/corpus-<sha16>.tar.zst"
sha256 = "<64 hex>"
bytes = 0

[captures]
into = "captures"
include = ["*/frames/**", "*/archives/**"]
exclude = ["**/*.lock"]
key = "v1/captures-<sha16>.tar.zst"
sha256 = "<64 hex>"
bytes = 0
# Written by pack: the capture hash of each references.toml row this archive holds.
references = { ctry = "<64 hex>", intro = "<64 hex>" }
```

Globs match case-insensitively (`[I8]`).

### 4.2 `python/stunt_reel/assets.py` and `mise run assets`

- `pack [ARCHIVE...]`: builds each archive from the local data root into `target/assets/`
  (decision 5, zstd level 19), and rewrites its `key`, `sha256`, `bytes` (and for `captures`,
  `references`) in `assets.toml`. Prints the size and how it changed.
- `upload [ARCHIVE...]`: runs the pinned `wrangler r2 object put <bucket>/<key> --file <path>
  --remote` for each archive whose packed file matches its pin. A key names its content, so
  uploading one twice writes the same bytes.
- `fetch [ARCHIVE...]` (default: all): downloads each pinned key with an S3 SigV4 GET (region
  `auto`, `x-amz-content-sha256: UNSIGNED-PAYLOAD`, signed with `hmac` and `hashlib`, endpoint
  `https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com`). It checks size and sha256, decompresses
  with `compression.zstd`, extracts with `tarfile`'s `data` filter (no absolute paths, no `..`,
  no links out), and swaps the folder in (decision 7). Skips an archive whose marker already
  names its sha256. Never prints the credentials. Standard library only, so it runs before
  anything else is installed beyond Python.
- `status`: for each archive, the pinned key, whether the marker matches, and whether the
  local packed file matches.

The task needs no `ensure` dependency: it builds no binary.

### 4.3 Cloud environment (configured once by the owner in claude.ai)

- Environment variables: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and
  `STUNT_DATA_ROOT` pointing outside the checkout.
- Network access: the default trusted list plus `<account_id>.r2.cloudflarestorage.com`.
- Setup script: install `mesa-vulkan-drivers` (lavapipe, as CI does), then
  `mise run assets -- fetch && mise run superset-all`.

[`docs/harness-setup.md`](../../harness-setup.md) gets the steps.

## 5. Error handling

| Case | Result |
|---|---|
| Credentials missing | `fetch` exits 2 naming the missing variables and the setup doc |
| HTTP 403 / 404 | Exit 1 naming the key and the status; 403 says to check the token's bucket scope |
| Size or sha256 differs from the pin | Exit 1; nothing is extracted; the download is deleted |
| Target folder exists without a fetch marker | Exit 1: refuses to replace a folder it did not create (decision 7) |
| A member escapes its folder | Exit 1 from the `data` filter; `<into>.new/` is removed and `<into>/` is untouched |
| `pack` finds no file for an include glob | Exit 1 naming the glob |
| `upload` with an unpacked or stale archive | Exit 1 telling the owner to run `pack` |
| `references.toml` and `assets.toml` disagree | The offline test fails, naming the row (decision 4) |

## 6. Testing

Offline, synthetic data only (`[I7]`):

- SigV4: the signer reproduces the AWS documented GET-object example signature.
- Packing: the same files packed twice, in different orders and with different mtimes, give
  an identical tar; include and exclude globs pick the expected members, case-insensitively.
- Fetch, with a fake HTTP opener: a matching archive extracts and leaves its marker; a hash
  mismatch extracts nothing; a second fetch is a no-op; a newer archive replaces the folder
  and drops a file the old one had; a populated folder without a marker is refused; a `../`
  member is refused and leaves the old folder intact.
- `upload`: the wrangler argv for a pinned archive, with a fake runner.
- The committed `assets.toml` names, for every `references.toml` row, the same capture hash.

Manual, once: pack and upload `v1`, then a cloud session runs the setup script, renders CTRY
and runs parity on CTRY and INTRO.

## 7. Steps

1. ADR: cloud sessions fetch pinned game archives from a private R2 bucket (decisions 3, 4, 6
   and 7).
2. `assets.py`, `manifests/assets.toml` with empty pins, the `assets` task and tests.
3. `DEFAULT_FILM` to `corpus/stuntisl/VAULT/CTRY.FLM`, with the docs that spell it.
4. `docs/harness-setup.md`: the R2 tokens, the cloud environment's variables, network
   allowlist and setup script.
5. Owner: create the read-only token, `wrangler login`, `mise run assets -- pack`, commit the
   pins, `mise run assets -- upload`, configure the cloud environment.
6. Verify in a cloud session (section 6, manual), and record the lavapipe parity scores in
   [`research/parity/log.md`](../../../research/parity/log.md).

## 8. Out of scope

- Music files, and so rebuilding an archive with a music chunk in the cloud (the demo's
  `CTRY.ALL` and `INTRO.ALL` ship as files instead).
- Video captures.
- The 205 corpus archives with add-on shapes, and the rest of `siarchive/`.
- `capture-ref` and `make-all` in the cloud (they need DOSBox-X).
- Uploading from CI.

## 9. Open questions

1. The exact form of the cloud environment's custom network allowlist (one host or a
   wildcard), to be confirmed in the claude.ai settings at step 5.
2. Whether lavapipe renders CTRY and INTRO to the same indices as the primary machine's GPU.
   ADR 0006 leaves it unverified; step 6 measures it. If it differs beyond noise, cloud parity
   rows are labelled with their adapter.
3. Whether the cloud image already has mise, the Rust toolchain and Python 3.15, or the setup
   script installs them; to be settled at step 4.
