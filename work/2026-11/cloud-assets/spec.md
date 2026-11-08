# Cloud assets: game data for Claude Code cloud sessions from a private R2 bucket (2026-11-06)

Status: **implemented**; accepted as [ADR 0039](../../adr/0039-cloud-sessions-fetch-pinned-game-archives.md). The owner's publish and the first cloud run (plan Task 7) remain. Source: a brainstorming session that followed the superset
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
downloads four archives from the private Cloudflare R2 bucket `stunt-reel-internal-assets`
(location WNAM) into its data root, and every tool then finds its files where it finds them on
the primary machine.

Success:

- A fresh cloud session's setup script fetches all four archives and `mise run superset-all`
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
| `corpus/stisldem` (the whole demo) | 18 | 0.83 MB | 0.32 MB |
| `corpus/siarchive/Developer/FreeFlight` (`SIDATA`, `src`, `Play.exe`) | 32 | 1.90 MB | 0.55 MB |
| `captures/` (CTRY and INTRO frames, BALLOON's stored archive; no `*.lock`) | 938 | 33.3 MB | 0.64 MB |

So the four archives of decision 2 are about 5.3 MB (`corpus-stuntisl`, everything but
music), 0.32 MB, 0.55 MB and 0.64 MB: about 6.8 MB in all. These add up per-set measurements;
`pack` reports the real figures.

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

1. **Archives mirror the data root.** Each archive holds one folder of `$STUNT_DATA_ROOT`
   (its `into`), with members relative to it, so `corpus_root()`, `capture_root()`,
   `--game corpus/stuntisl` and `--sidata` resolve unchanged. A cloud data root is a sparse
   copy of the primary machine's. No two archives share a folder, so each can be fetched,
   skipped or replaced on its own, and a later archive (the community films) takes its own
   folder and name.
2. **Four archives, one per game tree plus the captures.**

   | Archive | `into` | Holds |
   |---|---|---|
   | `corpus-stuntisl` | `corpus/stuntisl` | everything except the music files `RES/MUSIC1.*` and `RES/MUSIC2.*` |
   | `corpus-stisldem` | `corpus/stisldem` | everything: the demo, with the pinned `VAULT/CTRY.ALL` and `INTRO.ALL` beside their films, which `resolve_all` requires (`_corpus_copy` in `all_archive.py`) |
   | `corpus-freeflight` | `corpus/siarchive/Developer/FreeFlight` | everything: `SIDATA` (scenery, map, anchors), `src`, `Play.exe` |
   | `captures` | `captures` | each capture's `frames/` and `archives/` (ADR 0028), without `*.lock`. Video captures stay out: nothing scores them in the cloud, and they would dominate the size |

   A future archive of the rest of `siarchive/` must take a folder that does not contain
   `Developer/FreeFlight` (for example `corpus/siarchive/Films`), or it will be skipped as
   present once `corpus-freeflight` is fetched.
3. **Bucket keys: `v<N>/<archive>-<sha256[:16]>.tar.zst`.** `v<N>` changes only when what an
   archive is *meant* to hold changes (a new folder, the music back in). The suffix is the
   first 16 hex digits of the `.tar.zst`'s sha256, so it changes whenever the bytes do (a
   promoted reference, a new file). Objects are never deleted or overwritten, so old commits
   keep fetching theirs; storage is negligible.
   ```
   stunt-reel-internal-assets/
     v1/corpus-stuntisl-<sha16>.tar.zst
     v1/corpus-stisldem-<sha16>.tar.zst
     v1/corpus-freeflight-<sha16>.tar.zst
     v1/captures-<sha16>.tar.zst
   ```
4. **The repo pins the archives.** `manifests/cloud-assets.toml` holds the version, each archive's
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
   - Fetch: `curl --aws-sigv4 "aws:amz:auto:s3"` against the S3 API
     (`https://<account_id>.r2.cloudflarestorage.com/<bucket>/<key>`), so we write no signer
     and the token can be bucket-scoped. The key pair goes to curl through `--config -` on
     standard input, never on its command line, where any process could read it.
   - Cloud sessions: an R2 API token with **Object Read only**, scoped to this bucket. Its S3
     key pair and the account id are environment variables of the Claude Code cloud
     environment (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`), never in the
     repo. Anything in the session, the agent included, can read them; the scope limits a leak
     to reading about 6.8 MB of game data. Rotate on any sighting in a log or transcript.
   - Uploads: from the primary machine through `wrangler` with the owner's `wrangler login`, at
     a pinned version (`npx wrangler@<version> r2 object put ... --remote`); no long-lived
     write key exists.
   - Rejected: `wrangler r2 object get` for fetch (it uses Cloudflare's REST API, which
     bucket-scoped Object tokens cannot use, so the cloud token would read every bucket in the
     account), our own SigV4 signer (curl has one), a public bucket or `r2.dev` URL
     (distributes game data), presigned URLs (7-day maximum life), a Worker behind Cloudflare
     Access (more infrastructure for the same exposure), and a mutable `latest` pointer in the
     bucket (a branch would get whatever is newest).
7. **Fetch skips a destination that exists.** ADR 0022 keeps `corpus/` read-only and captures
   add-only. Fetching is provisioning, not a run: it writes `<into>/` only when it is absent,
   extracting into `<into>.new/` and renaming that into place, so an interrupted fetch leaves
   nothing half-written. When `<into>/` exists, fetch skips that archive and says so; it never
   updates or merges. So the primary machine's data root is never touched, and no marker files
   are needed. A cloud session is normally fresh; to take a newer pin in a live session,
   delete the folder and fetch again. A stale `captures/` is caught anyway: the parity
   pipeline refuses a capture whose content does not hash to its `references.toml` row. A new
   ADR records this exception.
8. **`DEFAULT_FILM` stays `corpus/stisldem/VAULT/CTRY.FLM`.** Its only users are the DOSBox
   tools (`capture-ref`, `capture-video`, `play`, `probe-light`), which do not run in the
   cloud, and the cloud corpus holds that file anyway. Changing it could change which game tree
   a local capture runs.
9. **The session builds `SUPERSET.ALL`** with `mise run superset-all` after fetching, until
   #252's `--game` makes it unnecessary.

## 4. Components

### 4.1 `manifests/cloud-assets.toml`

```toml
# Game data for cloud sessions, in the private R2 bucket (docs/process/plans/cloud-assets-2026-11-06.md).
bucket = "stunt-reel-internal-assets"
version = "v1"

[corpus-stuntisl]
into = "corpus/stuntisl"
include = ["**"]
exclude = ["RES/MUSIC1.*", "RES/MUSIC2.*"]
key = "v1/corpus-stuntisl-<sha16>.tar.zst"
sha256 = "<64 hex>"
bytes = 0

[corpus-stisldem]
into = "corpus/stisldem"
include = ["**"]
exclude = []
key = "v1/corpus-stisldem-<sha16>.tar.zst"
sha256 = "<64 hex>"
bytes = 0

[corpus-freeflight]
into = "corpus/siarchive/Developer/FreeFlight"
include = ["**"]
exclude = []
key = "v1/corpus-freeflight-<sha16>.tar.zst"
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

### 4.2 `python/stunt_reel/cloud_assets.py` and `mise run cloud-assets`

- `pack [ARCHIVE...]`: builds each archive from its `into` folder of the local data root into `target/cloud-assets/`
  (decision 5, zstd level 19), and rewrites its `key`, `sha256`, `bytes` (and for `captures`,
  `references`) in `cloud-assets.toml`. Prints the size and how it changed.
- `upload [ARCHIVE...]`: runs the pinned `wrangler r2 object put <bucket>/<key> --file <path>
  --remote` for each archive whose packed file matches its pin. A key names its content, so
  uploading one twice writes the same bytes.
- `fetch [ARCHIVE...]` (default: all): downloads each pinned key with the pinned
  `curl --aws-sigv4 "aws:amz:auto:s3" --fail` (decision 6; curl 7.75 or later). It checks size and sha256,
  decompresses with `compression.zstd`, extracts with `tarfile`'s `data` filter (no absolute
  paths, no `..`, no links out), and renames the folder into place (decision 7). Skips, without
  downloading, an archive whose destination exists. Never prints the key pair. It needs Python
  3.14 or later for `compression.zstd`, so it runs under the pinned 3.15 through `mise run`.
- `status`: for each archive, the pinned key, whether its destination exists, and whether the
  local packed file matches.

The task needs no `ensure` dependency: it builds no binary.

### 4.3 Cloud environment (configured once by the owner in claude.ai)

- Environment variables: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and
  `STUNT_DATA_ROOT` pointing outside the checkout.
- Network access: the default trusted list plus `<account_id>.r2.cloudflarestorage.com`.
- Setup script. The default image has `uv`, `rustc`/`cargo`, Java 21 and an unpinned Python
  3.x, but not mise, and `compression.zstd` needs Python 3.14 or later. So, as CI's
  `install_args` does:
  1. install mise at a pinned version from its GitHub release, checksum-verified;
  2. `mise install rust python uv prek java github:kaitai-io/kaitai_struct_compiler`
     (the pinned 1.99.1 toolchain and Python 3.15.2; the DOSBox tool is left out);
  3. `uv sync --locked --all-groups`;
  4. install `mesa-vulkan-drivers` (lavapipe, as CI does);
  5. `mise run cloud-assets -- fetch && mise run superset-all`.

  The script lives in [`docs/harness-setup.md`](../../harness-setup.md), from which the owner
  pastes it into the environment; no shell script is committed, as the repo has none.

## 5. Error handling

| Case | Result |
|---|---|
| Token or account id missing | `fetch` exits 2 naming the missing variables and the setup doc |
| `curl` fails (403 no access, 404 no such key) | Exit 1 naming the key and the HTTP status; 403 says to check the token's bucket scope |
| Size or sha256 differs from the pin | Exit 1; nothing is extracted; the download is deleted |
| Destination folder exists | Skipped with a note naming it, exit 0 (decision 7) |
| A member escapes its folder | Exit 1 from the `data` filter; `<into>.new/` is removed and `<into>/` is not created |
| `pack` finds no file for an include glob | Exit 1 naming the glob |
| `upload` with an unpacked or stale archive | Exit 1 telling the owner to run `pack` |
| `references.toml` and `cloud-assets.toml` disagree | The offline test fails, naming the row (decision 4) |

## 6. Testing

Offline, synthetic data only (`[I7]`):

- Packing: the same files packed twice, in different orders and with different mtimes, give
  an identical tar; include and exclude globs pick the expected members, case-insensitively.
- Fetch, with a fake runner standing in for `curl`: a matching archive extracts into place; a hash mismatch
  extracts nothing; an existing destination is skipped with no request made; a `../` member
  is refused and leaves no destination folder.
- `upload`: the `wrangler` argv for a pinned archive. `fetch`: the `curl` argv and the config it
  is fed, with the key pair only on standard input. Both with a fake runner.
- The committed `cloud-assets.toml` names, for every `references.toml` row, the same capture hash.

Manual, once: pack and upload `v1`, then a cloud session runs the setup script, renders CTRY
and runs parity on CTRY and INTRO.

## 7. Steps

1. ADR: cloud sessions fetch pinned game archives from a private R2 bucket (decisions 3, 4, 6
   and 7).
2. `cloud_assets.py`, `manifests/cloud-assets.toml` with empty pins, the `cloud-assets` task and tests.
3. `docs/harness-setup.md`: the R2 tokens, the cloud environment's variables, network
   allowlist and setup script.
4. Owner: create the read-only token, `wrangler login`, `mise run cloud-assets -- pack`, commit the
   pins, `mise run cloud-assets -- upload`, configure the cloud environment.
5. Verify in a cloud session (section 6, manual), and record the lavapipe parity scores in
   [`research/parity/log.md`](../../../research/parity/log.md).

## 8. Out of scope

- Music files, and so rebuilding an archive with a music chunk in the cloud (the demo's
  `CTRY.ALL` and `INTRO.ALL` ship as files instead).
- Video captures.
- The 205 corpus archives with add-on shapes, and the rest of `siarchive/`.
- `capture-ref` and `make-all` in the cloud (they need DOSBox-X).
- Uploading from CI.

## 9. Open questions

1. The cloud environment's network allowlist: whether the default trusted list already covers what the setup script
   downloads (GitHub releases for mise and Python, `static.rust-lang.org`, PyPI, the Ubuntu
   mirror), and the exact form of the R2 entry. To be confirmed in the claude.ai settings at step 5.
2. Whether lavapipe renders CTRY and INTRO to the same indices as the primary machine's GPU.
   ADR 0006 leaves it unverified; step 6 measures it. If it differs beyond noise, cloud parity
   rows are labelled with their adapter.
3. How long the setup script takes (the Rust toolchain, Python and `uv sync`), and whether the
   cloud environment caches its result between sessions.
