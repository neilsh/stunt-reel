# Harness setup (host-local configuration)

What a new machine needs before an agent session can provision a checkout here, and
which settings cannot ship in Git. Nothing on this page is Stunt Island knowledge; it is
a fact about the tools. Recorded from observed behaviour on 2026-10-25, mise 2026.10.12,
Windows. Policy and per-harness capability notes live in [`harness.md`](harness.md); this
page is the machine setup they assume.

## What lives where

| Item | Location | In Git? |
| --- | --- | --- |
| Tool versions and task definitions | [`mise.toml`](../mise.toml), `uv.lock`, `Cargo.toml` | yes |
| Installed tools (Rust, Python, uv, Java, dosbox-automation, cargo tools) | `%LOCALAPPDATA%\mise\installs` | no |
| mise trust and tracked-config records | `%USERPROFILE%\.local\state\mise` | no |
| mise global settings | `%USERPROFILE%\.config\mise\config.toml` | no |
| Shared data root | `<parent-of-primary>/<repo-name>.data`, see [ADR 0008](adr/0008-worktrees-share-one-read-only-data-root.md) | no |
| Shared tool cache, with each worktree's virtualenv under `venvs/` | `<primary>/.cache`, linked per worktree, see [ADR 0013](adr/0013-worktrees-share-one-writable-tool-cache.md) and [ADR 0019](adr/0019-a-worktrees-virtualenv-lives-in-the-shared-cache.md) | no |
| DSH permission mode and approvals | `~/.dsh` (host settings) | no |
| Worktrees | `.agents/worktrees/` inside the primary checkout | no |

[`mise run init`](../mise.toml) links the data root into a worktree with junctions; every
target in that table is host-local, and no checkout can carry any of it.

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
   `%USERPROFILE%\.local\state\mise\trusted-configs`; that write is outside a
   `workspace-write` workspace. A sandboxed invocation that cannot write it may set
   `CI=true`, which makes mise treat every config as trusted and record nothing; keep
   that for automation over your own repository, not as a default.

3. Set the session permission preset (DSH host setting, cannot ship). `workspace-write`
   is the default and the right mode for reading and editing the checkout. Provisioning a
   worktree and the first mise trust record need writes outside the workspace, so switch
   the session to `danger-full-access` for that step, then switch back (`/permission` in
   the GUI). Host approval settings should pre-approve `mise run *` and use a short
   timeout, so a blocked command returns a decision rather than a deadline.

4. Keep the worktree pool inside the checkout. For a `workspace-write` session, a
   worktree must live under the session workspace (`.agents/worktrees/`). A pool beside
   the checkout puts the checkout, its `.cache` and `.venv` junctions and every junction
   target outside the sandbox.

## Provisioning a worktree

The scripted setup is `mise run init`; under DSH its link step needs the wider preset.

1. Create the worktree: DSH's `create_worktree`, or `git worktree add` under
   `.agents/worktrees/`.
2. Switch the session to `danger-full-access`.
3. Run `mise run init`; it creates the `.cache` and `.venv` junctions and the data-root
   links, then runs `uv sync` into the cached environment.
4. Verify the links and that the corpus reads (see below).
5. Switch back to `workspace-write`; later `mise run` tasks in that worktree do not need
   the state write, because an existing trust record is not rewritten.
6. To retire the worktree later, run `mise run reap -- --yes` from the primary checkout;
   it unlinks the junctions into the data root before `git worktree remove` runs. Never
   call `git worktree remove` directly on a linked worktree: git 2.47.1 deleted the
   junction targets, and 2.55.0 left the junction directories behind and deregistered the
   worktree ([ADR 0018](adr/0018-reaping-unlinks-the-data-root-links-first.md)). Anything
   else that deletes recursively needs the links unlinked first, and `robocopy /MIR` needs
   `/XJ`.

Why the split: [`worktree_init.py`](../python/scripts/worktree_init.py) creates junctions
whose targets are in the shared data root, outside the workspace. DSH creates a junction
whose target is inside the workspace and denies one whose target is outside it, and it
has no settings for extra writable roots or a worktree setup hook.

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
Get-Item corpus\stisldem -Force | Select-Object Target   # junction into the data root
mise run lint-py
mise doctor
git worktree list
```

A `mise WARN tracking config: Access is denied` line is expected under
`workspace-write`: the per-config tracking record is host state, and mise continues
without it.

## Known gaps

- A junction to a target outside the workspace cannot be created under
  `workspace-write`; DSH has no setting for additional writable roots and no worktree
  setup hook, so provisioning keeps the `danger-full-access` step. The same run also writes
  mise's per-checkout trust record. The data root stays outside the checkout by design
  ([ADR 0008](adr/0008-worktrees-share-one-read-only-data-root.md)).
- pytest's per-checkout cache and temporary root used to break `mise run check` under
  `workspace-write`: pytest deletes a `--basetemp` it finds and resets a cache directory it
  creates, and the sandbox denies both. [tests/conftest.py](../tests/conftest.py) now creates
  `.pytest_cache` first and gives each run a fresh `basetemp-<stamp>-<id>` (newest three
  kept), so there is nothing stale to delete. A Windows-only shim in the same conftest drops
  the mode from `os.mkdir`, because a directory created with `0o700` cannot be reopened even by
  the process that made it; [scratch.py](../python/stunt_reel/scratch.py) does the same for
  tooling that shells out.
- Worktrees outside the session workspace are unsupported under `workspace-write`.
