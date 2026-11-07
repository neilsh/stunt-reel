# Harness setup (host-local configuration)

What a new machine needs before an agent session can work in a checkout here, and
which settings cannot ship in Git. Nothing on this page is Stunt Island knowledge; it is
a fact about the tools. Recorded from observed behaviour on 2026-10-25, mise 2026.10.12,
Windows, and revised on 2026-11-04 when worktrees stopped holding links
([ADR 0036](adr/0036-worktrees-reach-shared-state-by-configuration.md)). Policy and
per-harness capability notes live in [`harness.md`](harness.md); this page is the machine
setup they assume.

## What lives where

| Item | Location | In Git? |
| --- | --- | --- |
| Tool versions and task definitions | [`mise.toml`](../mise.toml), `uv.lock`, `Cargo.toml` | yes |
| Installed tools (Rust, Python, uv, Java, dosbox-automation, cargo tools) | `%LOCALAPPDATA%\mise\installs` | no |
| mise trust and tracked-config records | `%USERPROFILE%\.local\state\mise` | no |
| mise global settings | `%USERPROFILE%\.config\mise\config.toml` | no |
| Shared data root (corpus, captures, stage) | `<parent-of-primary>/<repo-name>.data`, or `STUNT_DATA_ROOT`, read by code directly, see [ADR 0008](adr/0008-worktrees-share-one-read-only-data-root.md) | no |
| Shared uv and Cargo caches | `<primary>/.cache/uv` and `<primary>/.cache/cargo`, named by absolute path in `mise.toml`, see [ADR 0013](adr/0013-worktrees-share-one-writable-tool-cache.md) | no |
| A worktree's Python environment | its own `.venv`, made by uv on the first `uv run` | no |
| Harness permission modes and approvals | each harness's host settings | no |
| Worktrees | `.claude/worktrees/` or `.agents/worktrees/` inside the primary checkout, where `mise run reap` looks | no |

Every location in that table except the first row is host-local, and no checkout can carry it.

## One-time setup

Run these in a normal terminal, outside an agent sandbox.

1. Install the pinned toolchain and check it:

   ```powershell
   mise install
   mise doctor
   ```

2. Trust this repository's config without prompts. Create
   `%USERPROFILE%\.config\mise\config.toml` (adjust the path to the primary checkout on
   this machine, forward slashes):

   ```toml
   [settings]
   trusted_config_paths = ["D:/git/stunt-reel"]
   ```

   Verify it is read:

   ```powershell
   mise settings ls | Select-String trusted
   ```

   This removes the trust *prompt* only. `mise run` still records trust for every
   non-global config it loads, once per checkout, under
   `%USERPROFILE%\.local\state\mise\trusted-configs`; a sandbox that admits writes only inside
   its workspace denies that write (see [DSH](#dsh)).

3. Put the game files in the data root, `<parent-of-primary>/<repo-name>.data/corpus/`, as
   [`corpus/README.md`](../corpus/README.md) lays them out; `STUNT_DATA_ROOT` names another
   place. A clone that already holds them in its own `corpus/` can move them with
   `mise run init -- --migrate`, or keep them there: when `STUNT_DATA_ROOT` is unset and the
   data root has no `corpus/`, Python code reads the primary checkout's `corpus/` if it holds a
   folder of game files. The Rust readers, `mise run sod-census` and `mise run test-corpus`,
   are handed the same corpus by `run_with_corpus.py`.

   The data root also holds `builds/`, which `mise run game-builds` writes: `builds/unpatched`
   and `builds/patch3`. The Patch #3 tree was once `builds/patched`. A data root that has only
   that old directory keeps working in `debug-x` and `pair-builds`, the callers of
   `game_builds.build_tree`: they use it and print a message to run `mise run game-builds`
   again, which creates `builds/patch3`. An explicit `--game-root <data root>/builds/patch3`
   for `capture-ref`, `capture-video`, `play` or `make-all` is a plain path and fails until
   `mise run game-builds` has run (or pass the old `builds/patched` path). Nothing renames the old
   directory, and keep it until the worktrees that use it and the `make-all` manifests that
   record it as their game root are migrated: `all_archive` rejects a manifest whose recorded
   directory is missing. The fallback is transitional,
   `game_builds.build_tree` in [`game_builds.py`](../python/stunt_reel/game_builds.py).

## A new worktree

Nothing to do. Create it with any tool, under `.claude/worktrees/` or `.agents/worktrees/` inside the primary checkout, where `mise run reap` can reap it, except an Orca workspace, whose path Orca chooses (see [Orca](#orca)):

- Python tasks find the corpus and captures through the data root and build `.venv` on the
  first `uv run`, hardlinked out of the shared uv cache on the same volume.
- The first task that builds Rust runs the hidden `ensure` task first, which seeds an empty
  `target/` by block clone from another checkout on a ReFS volume
  ([ADR 0030](adr/0030-new-worktrees-seed-target-by-block-clone.md)) and sets
  `core.hooksPath`. Concurrent tasks wait on one lock, so the gate seeds once.
- `mise run init` does both now instead of at the first task, runs `uv sync`, and names any
  link an older `init` left in the checkout.

## Removing a worktree

- A worktree with no links (every one made since ADR 0036) can be removed by the tool that
  made it, or by `git worktree remove`.
- An older worktree that `init` linked keeps its junctions until reaped: run
  `mise run reap -- --yes` from the primary checkout. It unlinks the junctions into the data
  root and proves none remain before `git worktree remove` runs. Never call
  `git worktree remove` directly on a linked worktree: git 2.47.1 deleted the junction
  targets, and 2.55.0 left the junction directories behind and deregistered the worktree
  ([ADR 0018](adr/0018-reaping-unlinks-the-data-root-links-first.md)). Anything else that
  deletes recursively needs the links unlinked first, and `robocopy /MIR` needs `/XJ`.
  `mise run init` in such a worktree lists its links (`~ <path> is a link from the old layout`).

  On some Windows machines Python's directory removal fails on every junction with
  `[WinError 5] Access is denied`, while `cmd /c rmdir <link>` removes the same junction
  and leaves its target alone. The suspected cause is Windows Controlled Folder Access
  (unconfirmed). `remove_link` in [`dataroot.py`](../python/stunt_reel/dataroot.py), which
  `clean` and `reap` use, therefore retries a refused removal once with the shell's `rmdir`,
  never with `/s`, so a directory that still holds files is refused, not emptied. The path
  reaches `cmd` in an environment variable expanded after parsing, never on its command line,
  so `&`, `%` or `(` in a name is plain text. If the retry fails too, `reap` reports both
  errors and leaves the worktree and its branch alone; after a successful retry it still
  proves no link remains before it removes the worktree.
- `reap` removes nothing while the primary checkout's drive has 20 GB or more free
  (`--min-free-gb N` moves the bar, `--force` skips it); a dry run still lists the candidates.
- `reap -- --yes` refuses when the primary checkout's committed `worktree_init.py` differs
  from `origin/main`'s (fetched quietly first), since it would reap by rules main has since
  changed; a dry run only warns. Update the primary checkout, or pass `--allow-stale-script`.

## Claude Code

Desktop sessions, `claude --worktree` and subagents with `isolation: worktree` create
worktrees under `.claude/worktrees/`, which `.gitignore` and ruff's `exclude` cover. No
`.worktreeinclude` and no worktree hook: everything gitignored here is shared state that
must not be copied, and the first task prepares the rest. Claude Code may remove the
worktrees it creates; an older linked one goes through `reap`.

## Cloud sessions

A Claude Code cloud session has no data root. Its SessionStart hook fetches four archives from the
private R2 bucket `stunt-reel-internal-assets`, each pinned by key and sha256 in
[`manifests/cloud-assets.toml`](../manifests/cloud-assets.toml)
([ADR 0039](adr/0039-cloud-sessions-fetch-pinned-game-archives.md)).

### The read token

In the Cloudflare dashboard, R2, Manage API tokens, create an API token with **Object Read
only** permission on `stunt-reel-internal-assets` alone, and keep its Access Key ID, Secret
Access Key and the account id. `fetch` signs S3 requests to
`<account_id>.r2.cloudflarestorage.com` with that pair (`curl --aws-sigv4`, the pair on
standard input, never on argv).

### The cloud environment

In claude.ai, the cloud environment for this repo:

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

### The cloud setup

The setup script is the claude.ai field; the *cloud setup* is
[`.claude/cloud-setup.sh`](../.claude/cloud-setup.sh), the checkout's script that does the
work. The field holds only a bootstrap, so a change to the setup is reviewed and versioned
with the repo, and no copy here can drift from it. The cloud setup installs mise at a pinned,
checksum-checked release, then from the checkout's `mise.lock` the tools the gate needs (not
the DOSBox tool) and the Python environment, then lavapipe as CI does
([ADR 0006](adr/0006-ci-renders-on-lavapipe.md)). It fetches no game archives: the setup
script runs before the environment variables are set, so the hook fetches them. Each step skips
work already done, and it needs root only to replace mise or install the apt packages. It
refuses to run without `--cloud`, which only the bootstrap and the hook pass, or outside a
Linux x86_64 container with `dpkg`, since on a developer machine it would replace that
machine's mise. CI's `install_args` is a separate list: CI also installs
Java.

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

### The SessionStart hook

The repo's SessionStart hook (`.claude/settings.json`) runs `mise run cloud-session-start` on
every session start and resume. Outside a cloud session (`CLAUDE_CODE_REMOTE` unset) it does
nothing; in one it runs the cloud setup again, then `mise run cloud-assets -- fetch` and
`mise run superset-all`, with the environment variables set. The setup script's cache outlives
a pin change, so the rerun is what brings a new pin; work already done costs nothing. The cache
holds no archives, so each new session fetches the pins of the commit it starts from. The hook
prints one line to the session, `ready` or `FAILED`, and logs the rest to
`/tmp/cloud-session-start.log`.

The hook does not run where Claude Code loads no repo settings: a cloud session with several
repositories, or a cloud thread of a project. Nothing is fetched there and no line is printed;
run `CLAUDE_CODE_REMOTE=true mise run cloud-session-start` from the checkout instead.

### Without the key pair: a Bearer network secret (unverified)

To keep the token out of the session, leave `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` unset
and add a network secret instead: type **Bearer**, allowed website `api.cloudflare.com`, header
`Authorization`, prefix `Bearer`, the token value as value. `fetch` then reads R2's REST API on
that host, and the proxy adds the token as each request leaves the session; anything in a
session can still use it through the proxy. R2's REST API refuses bucket-scoped tokens, so this
token needs **Admin Read only**, which reads every bucket in the account; recheck that the
account holds only `stunt-reel-internal-assets` before adding a bucket. A REST read with such a
token returned the pinned bytes from the primary machine, but no cloud session has fetched this
way yet.

### Fetching

`fetch` skips an archive whose folder already exists, so a resumed session downloads nothing
and keeps the pins it fetched first. To take a newer pin there, delete that folder under
`$STUNT_DATA_ROOT` and fetch again.
`mise run cloud-assets -- status` shows each pin and folder, reading nothing remote. From
`fetch`, exit 2 means `R2_ACCOUNT_ID`, or one half of the key pair, is unset, and a 403 means
the key pair or the network secret cannot read the bucket.

### Publishing new archives (owner, primary machine)

1. `npx wrangler login` once; uploads use that login, so no write key exists.
2. `mise run cloud-assets -- pack [ARCHIVE...]` builds into `target/cloud-assets/` and rewrites
   the pins in `manifests/cloud-assets.toml`. A PR that promotes a reference in
   `research/parity/references.toml` repacks `captures`; a test fails until it does.
3. Commit `manifests/cloud-assets.toml`, then `mise run cloud-assets -- upload [ARCHIVE...]`.
   A key names its content, so old commits keep fetching theirs; never delete an object.

### What a cloud session cannot do

- **Attach a picture to a pull request.** The image's `gh` is older than the 2.103 that `--attach`
  needs, and a cloud session has no `gh` login: GitHub goes through the session's own tools,
  which upload no files. PR pictures are attached, not committed ([`NOTICE.md`](../NOTICE.md)),
  and the PNG stays on the session's own machine, which no one else can reach. Describe each one
  in the PR body with the revision it renders and the `mise run frame` command (film, ticks, crop,
  never `--no-build`, so the recipient's binary is rebuilt for that revision); a before-and-after
  made with a `DBG_*` switch gives the base and head revisions and a command for each, since the
  switch is not committed. Someone with GitHub access and the data root regenerates it and
  attaches it. Only a picture that a
  research note cites as evidence for a finding is committed, under
  [`research/images/`](../research/images/README.md); the PR body may then link it at its commit
  (`https://github.com/<owner>/<repo>/blob/<commit>/<path>?raw=true`), as #264 did.
- **Measure the GPU.** The renderer runs on lavapipe, whose scores are not yet shown to equal a
  GPU's ([`research/parity/lavapipe.md`](../research/parity/lavapipe.md)). An adoption decision
  still needs a GPU run.

### Rotating the token

Rotate on any sighting of the secret in a log, transcript or commit: create a new token as
above, replace the two key variables (or the network secret: delete it and add it again) in
the cloud environment, then delete the old token in the dashboard.

## DSH

DSH's `workspace-write` sandbox admits writes only inside the session workspace, and the
shared caches, the data root and mise's trust records are outside a worktree. Run `mise run`
tasks in a DSH session under `danger-full-access`. The OS temp directory is denied too: a
gate run under `workspace-write` panicked in `test-rust` with
`create temp dir: Os { code: 5, ... "Access is denied." }`, and `pytest` hit
`PermissionError: [WinError 5]` under DSH's own per-session temp path
([harness.md](harness.md#temporary-directories)). Approval settings should pre-approve
`mise run *` and use a short timeout, so a blocked command returns a decision rather than a
deadline.

## Orca

Orca workspaces are the one exception to the in-checkout rule in AGENTS.md, Worktrees. Orca chooses their path,
`~/orca/workspaces/stunt-reel/<name>` on this machine; `orca --help` shows the base as a
project host setting (`orca project setup-update --setup <id> --worktree-base-path <path>`).
They sit outside the primary checkout, as do the worktrees nested in a workspace's own
`.agents/worktrees/`, so `mise run reap` skips them all: retire a workspace with
`orca worktree rm --worktree <selector>`.

A workspace made before ADR 0036 may still hold junctions an older `init` made, and nothing shows
that Orca's removal unlinks them first (see [Removing a worktree](#removing-a-worktree)). No task
unlinks one worktree in place; `reap` does it only for the worktrees it removes. Before
`orca worktree rm`, from the workspace root (read-only listing, whatever the workspace's
own `init`):

1. `cmd /c dir /AL /S /B` lists every reparse point. It follows junctions, so a listed path
   below another listed path lies inside that junction's target: leave it alone.
2. `cmd /c rmdir "<path>"` each remaining one, pasting the path exactly as `dir /B` printed
   it inside the quotes; it removes the junction and leaves its target alone. Never add `/s`.
   `cmd` expands `%NAME%` even inside quotes, so for a path containing `%` run
   `[System.IO.Directory]::Delete('<path>')` in PowerShell instead, doubling any single quote
   in the path: single quotes stop expansion, and the call is non-recursive and removes only the junction.
3. `cmd /c dir /AL /S /B` again must print `File Not Found`; only then run `orca worktree rm`.

Orca workspaces live on `C:`, another volume from the shared uv cache, so uv copies each
`.venv` (about 68 MB, 3 s) instead of hardlinking it, and `target/` is not seeded, because
`C:` does not clone blocks. Both are slower, not wrong.

## Toolchain drift

Plain `mise run` relies on the toolchain already being installed; `mise install` in
step 1 covers it. The `rust` pin used to name `llvm-tools-preview`, which rustup reports
as `llvm-tools-x86_64-...`; mise read that mismatch as a missing component and tried a
reinstall on every run. The pin now names `llvm-tools`, which verifies clean. If a task
still reports a Rust reinstall, the toolchain has drifted from the pin: run `mise install`
once outside the sandbox.

## Verify the machine

```powershell
mise settings ls | Select-String trusted
mise trust --show
mise env | Select-String UV_CACHE_DIR   # <primary>/.cache/uv from every checkout
mise run lint-py
mise doctor
git worktree list
```

A `mise WARN tracking config: Access is denied` line is expected in a sandbox that denies
writes outside the workspace: the per-config tracking record is host state, and mise
continues without it.

## Known gaps

- pytest's per-checkout cache and temporary root used to break `mise run check` under
  `workspace-write`: pytest deletes a `--basetemp` it finds and resets a cache directory it
  creates, and the sandbox denies both. [tests/conftest.py](../tests/conftest.py) now creates
  `.pytest_cache` first and gives each run a fresh `basetemp-<stamp>-<id>` (newest three
  kept), so there is nothing stale to delete. A Windows-only shim in the same conftest drops
  the mode from `os.mkdir`, because a directory created with `0o700` cannot be reopened even by
  the process that made it; [scratch.py](../python/stunt_reel/scratch.py) does the same for
  tooling that shells out.
