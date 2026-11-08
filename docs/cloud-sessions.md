# Cloud sessions

A Claude Code cloud session has no data root. Its SessionStart hook fetches four archives from the
private R2 bucket `stunt-reel-internal-assets`, each pinned by key and sha256 in
[`manifests/cloud-assets.toml`](../manifests/cloud-assets.toml)
([ADR 0039](adr/0039-cloud-sessions-fetch-pinned-game-archives.md)).

## The read token

In the Cloudflare dashboard, R2, Manage API tokens, create an API token with **Object Read
only** permission on `stunt-reel-internal-assets` alone, and keep its Access Key ID, Secret
Access Key and the account id. `fetch` signs S3 requests to
`<account_id>.r2.cloudflarestorage.com` with that pair (`curl --aws-sigv4`, the pair on
standard input, never on argv).

## The cloud environment

In claude.ai, the cloud environment for this repo is `stunt-reel-cloud`:

- **Environment variables:** `R2_ACCOUNT_ID`, not a secret; `R2_ACCESS_KEY_ID` and
  `R2_SECRET_ACCESS_KEY`, the token's key pair; and `STUNT_DATA_ROOT`, an absolute path
  outside the checkout, such as `/root/stunt-reel.data`. Anyone who uses the environment, and
  anything in a session, can read the key pair; it reads only the one bucket. Also
  `MISE_AUTO_INSTALL=false` and `MISE_USE_VERSIONS_HOST=false`, as CI sets them: otherwise the
  first `mise run` in a session installs every tool `mise.toml` declares, compiling the cargo
  ones from source.
- **Network access:** the default trusted list, plus `<account_id>.r2.cloudflarestorage.com`,
  and `gitlab.freedesktop.org` for reading Mesa's source and issues when a render differs on
  lavapipe ([#265](https://github.com/neilsh/stunt-reel/issues/265)).
  The cloud setup downloads from GitHub releases, `static.rust-lang.org`, PyPI and the Ubuntu
  mirror, all on the list.
- **Network secrets:** none on the R2 host. The proxy's AWS SigV4 secret signs for hosts under
  `amazonaws.com` alone, and while one is set it answers every request to the R2 host with a
  502 (`injection failed (...): the hostname is not under amazonaws.com`, 2026-11-07).
- **Setup script:** the bootstrap below, which runs the repo's cloud setup.

## The cloud setup

The setup script is the claude.ai field; the *cloud setup* is
[`.claude/cloud-setup.sh`](../.claude/cloud-setup.sh), the checkout's script that does the
work. The field holds only a bootstrap, so a change to the setup is reviewed and versioned
with the repo, and no copy here can drift from it. The cloud setup installs mise at a pinned,
checksum-checked release, then from the checkout's `mise.lock` the tools the gate needs (not
the DOSBox tool) and the Python environment, then lavapipe as CI does
([ADR 0006](adr/0006-ci-renders-on-lavapipe.md)). It fetches no game archives: the setup
script runs before the environment variables are set, so the hook fetches them. Each step skips
work already done, and it needs root only to replace mise or install the apt packages. It
refuses to run without `--cloud`, which only the bootstrap and the hook pass, or on anything
but Linux x86_64 with `dpkg`; it does not detect a container, so `--cloud` on a developer
machine would replace that machine's mise. CI's `install_args` is a separate list: CI also
installs Java.

The lockfile is what makes the install work: it holds each tool's download URL and checksum,
so mise reads no GitHub API. Without it mise asks the API three or four times per tool, and
cloud sessions share an address whose 60 anonymous requests an hour are gone. Java is the
image's OpenJDK 21: mise's Java reads `mise-java.jdx.dev`, which the default list lacks.

The setup script does not start in the checkout, so it looks for it:

```bash
set -euo pipefail
lock=$(find / -maxdepth 4 -path /proc -prune -o -path '*/stunt-reel/mise.lock' -print -quit)
[ -n "$lock" ] || { echo "setup: no stunt-reel checkout found" >&2; exit 1; }
setup=${lock%/mise.lock}/.claude/cloud-setup.sh
[ -f "$setup" ] || { echo "setup: this branch predates .claude/cloud-setup.sh; rebase on main" >&2; exit 1; }
bash "$setup" --cloud
```

A branch older than the cloud setup fails the setup script rather than starting without mise:
the hook below runs through `mise`, so a session without it would fail every hook and tell
Claude nothing. A failed setup script should also keep that environment out of the cache
(unverified).

## The SessionStart hook

The repo's SessionStart hook (`.claude/settings.json`) runs `mise run cloud-session-start` on
every session start and resume. Outside a cloud session (`CLAUDE_CODE_REMOTE` unset) it does
nothing; in one it runs the cloud setup again, then
`mise run cloud-assets -- fetch --replace-unmarked` and
`mise run superset-all`, with the environment variables set. The setup script's cache outlives
a pin change, so the rerun is what brings a new pin; work already done costs nothing. A new
session can find an earlier session's archive folders already in its data root (seen
2026-11-08, mechanism unknown), so fetch replaces each one that holds another pin
([ADR 0042](adr/0042-fetch-replaces-a-folder-it-wrote-when-the-pin-changes.md)). The hook
prints one line to the session, `ready` or `FAILED`, and appends the rest to
`/tmp/cloud-session-start.log` under a `== <UTC time> <commit> ==` line per run, so a rerun keeps
the startup run's output.

The hook does not run where Claude Code loads no repo settings: a cloud session with several
repositories, or a cloud thread of a project. Nothing is fetched there and no line is printed;
run `CLAUDE_CODE_REMOTE=true mise run cloud-session-start` from the checkout instead.

## Without the key pair: a Bearer network secret (unverified)

To keep the token out of the session, leave `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` unset
and add a network secret instead: type **Bearer**, allowed website `api.cloudflare.com`, header
`Authorization`, prefix `Bearer`, the token value as value. `fetch` then reads R2's REST API on
that host, and the proxy adds the token as each request leaves the session; anything in a
session can still use it through the proxy. R2's REST API refuses bucket-scoped tokens, so this
token needs **Admin Read only**, which reads every bucket in the account; recheck that the
account holds only `stunt-reel-internal-assets` before adding a bucket. A REST read with such a
token returned the pinned bytes from the primary machine, but no cloud session has fetched this
way yet.

## Fetching

Fetch writes `.cloud-assets-pin`, the archive's key, into each folder it unpacks. It skips a
folder whose pin file names the pinned key and replaces one naming another, so a session takes a
newer pin at its next start or resume. It never touches a folder without a pin file, such as the
primary machine's corpus, unless given `--replace-unmarked`, which the SessionStart hook alone
passes ([ADR 0042](adr/0042-fetch-replaces-a-folder-it-wrote-when-the-pin-changes.md)).
`mise run cloud-assets -- status` shows each pin and what its folder holds, reading nothing
remote. From
`fetch`, exit 2 means `R2_ACCOUNT_ID`, or one half of the key pair, is unset, and a 403 means
the key pair or the network secret cannot read the bucket.

## Publishing new archives (owner, primary machine)

1. `npx wrangler login` once; uploads use that login, so no write key exists.
2. `mise run cloud-assets -- pack [ARCHIVE...]` builds into `target/cloud-assets/` and rewrites
   the pins in `manifests/cloud-assets.toml`. A PR that promotes a reference in
   `research/parity/references.toml` repacks `captures`; a test fails until it does.
3. Commit `manifests/cloud-assets.toml`, then `mise run cloud-assets -- upload [ARCHIVE...]`.
   A key names its content, so old commits keep fetching theirs; never delete an object.

## What a cloud session cannot do

- **Attach a picture to a pull request.** The image's `gh` is older than the 2.103 that `--attach`
  needs, and its `gh` reaches GitHub only through REST: `gh api` lists, opens and reads pull
  requests (the 2026-11-08 gardening run opened #319 that way), but the proxy refuses the
  GraphQL that `gh pr` and `gh issue` use. The session's own GitHub tools upload no files. PR pictures are attached, not committed ([`NOTICE.md`](../NOTICE.md)),
  and the PNG stays on the session's own machine, which no one else can reach. Describe each one
  in the PR body with the revision it renders and the `mise run frame` command (film, ticks, crop,
  never `--no-build`, so the recipient's binary is rebuilt for that revision); a before-and-after
  made with a `DBG_*` switch gives the base and head revisions and a command for each, since the
  switch is not committed. Someone with GitHub access and the data root regenerates it and
  attaches it. Only a picture that a
  research note or a journal entry cites as evidence for a finding is committed, under
  `work/<YYYY-MM>/<folder>/images/` ([`work/README.md`](../work/README.md#images)); the PR body
  may then link it at its commit
  (`https://github.com/<owner>/<repo>/blob/<commit>/<path>?raw=true`), as #264 did.
- **Measure the GPU.** The renderer runs on lavapipe, whose scores are not yet shown to equal a
  GPU's ([`research/parity/lavapipe.md`](../research/parity/lavapipe.md)). An adoption decision
  still needs a GPU run. It is also slower: `mise run parity` on the seven reference films took
  177 s on 2026-11-08, its release build included.
- **Use GitHub's GraphQL API.** The proxy answers every GraphQL request with 403, whatever the
  client (`gh api graphql` included), and names the REST routes it offers in its place, among them
  `/repos/{owner}/{repo}/pulls/{n}/ccr/review_threads` and `.../ccr/auto_merge` (2026-11-08).
- **Merge a stacked pull request.** GitHub's REST merge endpoint answers a stacked PR with 403
  (`Merging stacked PRs via this endpoint is not supported`), it refuses auto-merge on one, and
  `gh stack` needs GraphQL. The owner runs `gh stack merge` (2026-11-08, #302 and #303).
- **Install a newer `gh`.** The image's `gh` is 2.89.0; Ubuntu's apt package is 2.45.0, older,
  and the proxy refuses `cli.github.com` and GitHub's release downloads (2026-11-08). A newer
  `gh` would still meet the GraphQL refusal above.
- **Silence uv's `UV_NATIVE_TLS` warning.** The harness's `/etc/profile.d` script sets the
  deprecated variable, so every `uv` call warns ([#320](https://github.com/neilsh/stunt-reel/issues/320)).

## Rotating the token

Rotate on any sighting of the secret in a log, transcript or commit: create a new token as
above, replace the two key variables (or the network secret: delete it and add it again) in
the cloud environment, then delete the old token in the dashboard.
