# Harness setup (host-local configuration)

What a new machine needs before an agent session can work in a checkout here, and which settings cannot ship in Git.
Nothing on this page is Stunt Island knowledge; it is a fact about the tools.
Recorded from observed behaviour on 2026-10-25, mise 2026.10.12, Windows, and revised on 2026-11-04 when worktrees stopped holding links ([ADR 0036](adr/0036-worktrees-reach-shared-state-by-configuration.md)).
Policy and per-harness capability notes live in [`harness.md`](harness.md); this page is the machine setup they assume.

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

2. Trust this repository's config without prompts.
   Create `%USERPROFILE%\.config\mise\config.toml` (adjust the path to the primary checkout on this machine, forward slashes):

   ```toml
   [settings]
   trusted_config_paths = ["D:/git/stunt-reel"]
   ```

   Verify it is read:

   ```powershell
   mise settings ls | Select-String trusted
   ```

   This removes the trust *prompt* only.
   `mise run` still records trust for every non-global config it loads, once per checkout, under `%USERPROFILE%\.local\state\mise\trusted-configs`; a sandbox that admits writes only inside its workspace denies that write (see [DSH](#dsh)).

3. Put the game files in the data root, `<parent-of-primary>/<repo-name>.data/corpus/`, as [`corpus/README.md`](../corpus/README.md) lays them out; `STUNT_DATA_ROOT` names another place.
   A clone that already holds them in its own `corpus/` can move them with `mise run init -- --migrate`, or keep them there: when `STUNT_DATA_ROOT` is unset and the data root has no `corpus/`, Python code reads the primary checkout's `corpus/` if it holds a folder of game files.
   The Rust readers, `mise run sod-census` and `mise run test-corpus`, are handed the same corpus by `run_with_corpus.py`.

   The data root also holds `builds/`, which `mise run game-builds` writes: `builds/unpatched` and `builds/patch3` (an old `builds/patched` is no longer read and can be deleted).
   Run `mise run game-builds` before invoking `capture-ref`, `capture-video`, `play`, `make-all`, `debug-x`, or `pair-builds` against those directories.

## A new worktree

Nothing to do.
Create it with any tool, under `.claude/worktrees/` or `.agents/worktrees/` inside the primary checkout, where `mise run reap` can reap it; an Orca workspace's path is Orca's choice, and `reap` covers it too (see [Orca](#orca)):

- Python tasks find the corpus and captures through the data root and build `.venv` on the first `uv run`, hardlinked out of the shared uv cache on the same volume.
- The first task that builds Rust runs the hidden `ensure` task first, which seeds an empty `target/` by block clone from another checkout on a ReFS volume ([ADR 0030](adr/0030-new-worktrees-seed-target-by-block-clone.md)) and sets `core.hooksPath`, `blame.ignoreRevsFile` and the `expected-pins` merge driver (`.githooks/merge-take-main.sh`, [ADR 0053](adr/0053-expected-scores-live-in-a-generated-file-per-class.md)) in the shared repository config.
  Concurrent tasks wait on one lock, so the gate seeds once.
- `mise run init` does both now instead of at the first task, runs `uv sync`, and names any link an older `init` left in the checkout.

## Removing a worktree

- A worktree with no links (every one made since ADR 0036) can be removed by the tool that made it, or by `git worktree remove`.
- An older worktree that `init` linked keeps its junctions until reaped: run `mise run reap -- --yes` from the primary checkout.
  It unlinks the junctions into the data root and proves none remain before `git worktree remove` runs.
  Never call `git worktree remove` directly on a linked worktree: git 2.47.1 deleted the junction targets, and 2.55.0 left the junction directories behind and deregistered the worktree ([ADR 0018](adr/0018-reaping-unlinks-the-data-root-links-first.md)).
  Anything else that deletes recursively needs the links unlinked first, and `robocopy /MIR` needs `/XJ`.
  `mise run init` in such a worktree lists its links (`~ <path> is a link from the old layout`).

  On some Windows machines Python's directory removal fails on every junction with `[WinError 5] Access is denied`, while `cmd /c rmdir <link>` removes the same junction and leaves its target alone.
  The suspected cause is Windows Controlled Folder Access (unconfirmed).
  `remove_link` in [`dataroot.py`](../python/stunt_reel/dataroot.py), which `clean` and `reap` use, therefore retries a refused removal once with the shell's `rmdir`, never with `/s`, so a directory that still holds files is refused, not emptied.
  The path reaches `cmd` in an environment variable expanded after parsing, never on its command line, so `&`, `%` or `(` in a name is plain text.
  If the retry fails too, `reap` reports both errors and leaves the worktree and its branch alone; after a successful retry it still proves no untracked link remains before it removes the worktree.
- `reap` removes nothing while the primary checkout's drive has 20 GB or more free (`--min-free-gb N` moves the bar, `--force` skips it); a dry run still lists the candidates.
- `reap -- --yes` refuses when any file reap's code lives in differs from `origin/main`'s (fetched quietly first): `python/scripts/worktree_init.py`, `python/stunt_reel/dataroot.py` and the `python/stunt_reel/worktree_*.py` modules it imports, since it would reap by rules main has since changed; a dry run only warns.
  Update the primary checkout, or pass `--allow-stale-script`.

## Claude Code

Desktop sessions, `claude --worktree` and subagents with `isolation: worktree` create worktrees under `.claude/worktrees/`, which `.gitignore` and ruff's `exclude` cover.
No `.worktreeinclude` and no worktree hook: everything gitignored here is shared state that must not be copied, and the first task prepares the rest.
Claude Code may remove the worktrees it creates; an older linked one goes through `reap`.

## Cloud sessions

A Claude Code cloud session's setup, its game archives and what it cannot do are in [`cloud-sessions.md`](cloud-sessions.md).

## DSH

DSH's `workspace-write` sandbox admits writes only inside the session workspace, and the shared caches, the data root and mise's trust records are outside a worktree.
Run `mise run` tasks in a DSH session under `danger-full-access`.
The OS temp directory is denied too: a gate run under `workspace-write` panicked in `test-rust` with `create temp dir: Os { code: 5, ... "Access is denied." }`, and `pytest` hit `PermissionError: [WinError 5]` under DSH's own per-session temp path ([`harness/deepseek.md`](harness/deepseek.md#temporary-directories)).
Approval settings should pre-approve `mise run *` and use a short timeout, so a blocked command returns a decision rather than a deadline.

DSH's `run_code` traps, each hit several times by workers on 2026-11-14:

- **Backticks and `${` in a JS template literal** end or interpolate it, so a Python or Markdown edit containing them fails mid-batch with earlier edits already applied.
  Write such text with the `write` or `edit` tool, one edit per call, and after a failed call check what landed.
- **`mise run fix` and the commit hooks rewrite files**, so a later `edit` fails with "file changed since it was read" or "old_string not found": re-read after either.
- **`read` caps a call at about 1300 lines and truncates lines over 2000 characters**, so a `read` then `write` round trip silently cuts long lines (`ARCHITECTURE.md`, research tables).
  Edit in place with `edit`; to copy a file for a move or split, use `git show <ref>:<path>`, which gives its committed content without uncommitted edits.
- **PowerShell 5.1 sets exit 1 when a native command writes to stderr**, even on success: trust `$LASTEXITCODE` or the gate's `] PASS` line.
  Its `>` writes UTF-16; pipe to `Out-File -Encoding utf8` instead.
- **`orca orchestration send` breaks on a quoted or multi-line `--body`:** keep `--body` to one plain line and put the report in a file passed as `--report-path`, with `--task-id` copied from the current brief.
  `orca orchestration check` takes `--terminal <handle>`, not `--from`.

## Orca

Orca workspaces are the one exception to the in-checkout rule in AGENTS.md, Worktrees.
Orca chooses their path, `~/orca/workspaces/stunt-reel/<name>` on this machine; `orca --help` shows the base as a project host setting (`orca project setup-update --setup <id> --worktree-base-path <path>`).
They sit outside the primary checkout, as do the worktrees nested in a workspace's own `.agents/worktrees/`.

`mise run reap` retires a merged Orca workspace as it does its own worktrees: same `--yes`, same 20 GB bar, same merged-and-clean tests ([Removing a worktree](#removing-a-worktree)), and then `orca worktree rm --worktree id:<id>`, never `git worktree remove`.
It reads `orca worktree ps --json` and skips, saying why, a workspace that:

- holds a live terminal, a terminal Orca cannot verify, or an agent whose state is not `done` (a dispatched worker that has not reported, or one blocked on an answer); it asks Orca again just before removing;
- holds nested worktrees, such as `build/tmp/<name>` or `.claude/worktrees/<name>`, which it names; remove those first;
- has modified or untracked files, unless `--stash-dirty` or `--discard-untracked` allows them; unlike a pool worktree, such a workspace does not stop the rest from being reaped.

Before `orca worktree rm` it unlinks every link git does not track, so Orca's removal meets no junction, and leaves a tracked symlink (`.claude/skills`) in place: unlinking that modifies the tree and `orca worktree rm` then fails with `Failed to delete worktree ... D .claude/skills`.
When `orca` is not on PATH, or its output cannot be read, `reap` removes no Orca workspace and prints the `orca worktree rm --worktree "path:<path>"` line for each one it would have removed; it cannot then tell whether a worker is live, so check that first.

A workspace made before ADR 0036 may still hold junctions an older `init` made, and Orca's own removal does not show that it unlinks them.
To unlink one by hand, for a workspace `reap` skipped (read-only listing, from the workspace root, whatever the workspace's own `init`):

1. `cmd /c dir /AL /S /B` lists every reparse point.
   It follows junctions, so a listed path below another listed path lies inside that junction's target: leave it alone.
2. `cmd /c rmdir "<path>"` each remaining one, pasting the path exactly as `dir /B` printed it inside the quotes; it removes the junction and leaves its target alone.
   Never add `/s`.
   `cmd` expands `%NAME%` even inside quotes, so for a path containing `%` run `[System.IO.Directory]::Delete('<path>')` in PowerShell instead, doubling any single quote in the path: single quotes stop expansion, and the call is non-recursive and removes only the junction.
3. `cmd /c dir /AL /S /B` again must print `File Not Found`, leaving a tracked symlink; only then run `orca worktree rm`.

This machine's workspace base is `E:/orca/workspaces`, the Dev Drive that holds the primary checkout and the shared uv cache, so a workspace's `.venv` is hardlinked from that cache and its `target/` is seeded by block clone like any worktree's.
A base on another volume (it was `C:`) copies each `.venv` (about 68 MB, 3 s) and does not seed `target/`; both are slower, not wrong.

## Toolchain drift

Plain `mise run` relies on the toolchain already being installed; `mise install` in step 1 covers it.
The `rust` pin used to name `llvm-tools-preview`, which rustup reports as `llvm-tools-x86_64-...`; mise read that mismatch as a missing component and tried a reinstall on every run.
The pin now names `llvm-tools`, which verifies clean.
If a task still reports a Rust reinstall, the toolchain has drifted from the pin: run `mise install` once outside the sandbox.

## Verify the machine

```powershell
mise settings ls | Select-String trusted
mise trust --show
mise env | Select-String UV_CACHE_DIR   # <primary>/.cache/uv from every checkout
mise run lint-py
mise doctor
git worktree list
```

A `mise WARN tracking config: Access is denied` line is expected in a sandbox that denies writes outside the workspace: the per-config tracking record is host state, and mise continues without it.

## Known gaps

- pytest's per-checkout cache and temporary root used to break `mise run check` under `workspace-write`: pytest deletes a `--basetemp` it finds and resets a cache directory it creates, and the sandbox denies both.
  [tests/conftest.py](../tests/conftest.py) now creates `.pytest_cache` first and gives each run a fresh `basetemp-<stamp>-<id>` (newest three kept), so there is nothing stale to delete.
  A Windows-only shim in the same conftest drops the mode from `os.mkdir`, because a directory created with `0o700` cannot be reopened even by the process that made it; [scratch.py](../python/stunt_reel/scratch.py) does the same for tooling that shells out.
