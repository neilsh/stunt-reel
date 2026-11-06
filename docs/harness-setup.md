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
| Worktrees | `.claude/worktrees/` or `.agents/worktrees/` inside the primary checkout, the only place `mise run reap` reaps from | no |

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

Nothing to do. Create it with any tool, under `.claude/worktrees/` or `.agents/worktrees/` inside the primary checkout, where `mise run reap` can reap it:

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

## Claude Code

Desktop sessions, `claude --worktree` and subagents with `isolation: worktree` create
worktrees under `.claude/worktrees/`, which `.gitignore` and ruff's `exclude` cover. No
`.worktreeinclude` and no worktree hook: everything gitignored here is shared state that
must not be copied, and the first task prepares the rest. Claude Code may remove the
worktrees it creates; an older linked one goes through `reap`.

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

Orca workspaces are the one exception to SOP 6's in-checkout rule. Orca chooses their path,
`~/orca/workspaces/stunt-reel/<name>` on this machine; `orca --help` shows the base as a
project host setting (`orca project setup-update --setup <id> --worktree-base-path <path>`).
They sit outside the primary checkout, as do the worktrees nested in a workspace's own
`.agents/worktrees/`, so `mise run reap` skips them all: retire a workspace with
`orca worktree rm --worktree <selector>`.

A workspace made before ADR 0036 may still hold junctions an older `init` made, and nothing shows
that Orca's removal unlinks them first (see [Removing a worktree](#removing-a-worktree)). No task
unlinks one worktree in place; `reap` does it only for the worktrees it removes. Before
`orca worktree rm`, inside the workspace:

1. `mise run init` prints `~ <path> is a link from the old layout` for each junction.
2. `cmd /c rmdir <path>` removes each one and leaves its target alone; never add `/s`.
3. `cmd /c dir /AL /S /B` must then find no file: no reparse point remains.

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
