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
| Installed tools (Rust, Python, uv, Java, DOSBox-X, cargo tools) | `%LOCALAPPDATA%\mise\installs` | no |
| mise trust and tracked-config records | `%USERPROFILE%\.local\state\mise` | no |
| mise global settings | `%USERPROFILE%\.config\mise\config.toml` | no |
| Shared data root | `<parent-of-primary>/<repo-name>.data`, see [ADR 0008](adr/0008-worktrees-share-one-read-only-data-root.md) | no |
| Shared tool cache | `<primary>/.cache`, linked per worktree, see [ADR 0013](adr/0013-worktrees-share-one-writable-tool-cache.md) | no |
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
   the checkout puts `.venv`, `.cache` and every junction target outside the sandbox.

## Provisioning a worktree

The scripted setup is `mise run init`; under DSH its link step needs the wider preset.

1. Create the worktree: DSH's `create_worktree`, or `git worktree add` under
   `.agents/worktrees/`.
2. Switch the session to `danger-full-access`.
3. Run `mise run init`; it runs `uv sync` and creates the junctions and the `.cache`
   link.
4. Verify the links and that the corpus reads (see below).
5. Switch back to `workspace-write`; later `mise run` tasks in that worktree do not need
   the state write, because an existing trust record is not rewritten.

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
- Worktrees outside the session workspace are unsupported under `workspace-write`.
