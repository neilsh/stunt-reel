---
name: managing-worktrees
description: "Use when creating, removing or reaping a stunt-reel worktree, running `mise run reap` or `clean`, or when a task in a worktree needs the corpus, a capture or the data root (`STUNT_DATA_ROOT`)."
---

# Managing worktrees

Game files and captures live outside every checkout, in one shared data root; a worktree only reads them. Machine setup, junction and robocopy details are in [`docs/harness-setup.md`](../../../docs/harness-setup.md); writer modes are in [`docs/harness.md`](../../../docs/harness.md).

## Steps

1. **Find the data root.** It is `STUNT_DATA_ROOT` when set, otherwise the primary checkout's sibling `<repo-name>.data` (`stunt-reel.data` beside the `stunt-reel` primary checkout), never `corpus/` in a worktree. Done when you have its absolute path.
2. **Find a capture.** A film's captures are `<data root>/captures/<film slug>/<kind>`, one each of `frames`, `video` and `archives` ([ADR 0024](../../../docs/adr/0024-captures-are-filed-by-film-then-kind.md), [ADR 0028](../../../docs/adr/0028-a-film-has-one-capture-of-each-kind.md)). The film slug for a parity reference is pinned with its content hash in [`research/parity/references.toml`](../../../research/parity/references.toml) (`CTRY.FLM` is `vault-ctry`). Done when you name the directory.
3. **Judge completeness.** A capture is complete only once its `meta.json` exists: a new capture is written beside the old one and becomes visible when `meta.json` lands ([ADR 0022](../../../docs/adr/0022-captures-are-add-only-beside-a-read-only-corpus.md)). A reference also has to match its pin, so a replaced one fails parity until a reviewed commit repins it. Done when you have checked `meta.json` and the pin.
4. **New worktree.** Make it under `.claude/worktrees/` or `.agents/worktrees/` inside the primary checkout. It needs no setup ([ADR 0036](../../../docs/adr/0036-worktrees-reach-shared-state-by-configuration.md)); `mise run init` only does the same eagerly and names links an older `init` left. Done when the first `mise run` task works.
5. **Remove one.** A worktree made since ADR 0036 goes with the tool that made it. One an older `init` linked goes through `mise run reap` from the primary checkout: dry run first, then `--yes`. A branch with patches `main` lacks and no merged PR is never a candidate, `--force` included. `--yes` recomputes the candidates and removes all of them, not only the one you meant: get approval for the dry run's whole list, run `--yes` straight after, and stop if its list differs. Done when the dry run lists it and the real run removes it.

## Quick reference

| Need | Command or path |
|---|---|
| Capture of a film | `<data root>/captures/<slug>/frames`, complete when `meta.json` exists |
| Reference pin | `research/parity/references.toml` |
| `--film corpus/...` argument | resolves against the data root |
| Reap dry run, then real | `mise run reap`, `mise run reap -- --yes` |
| Reap with room on the drive | add `--force` (it waits for under 20 GB free; `--min-free-gb N`) |
| Squash-merged, cherry-picked, leftovers | `gh` recognises merged PRs; `--cherry`; `--prune` |
| Work at risk | `--stash-dirty`, `--discard-untracked` |
| Clear build outputs of a kept checkout | `mise run clean -- --yes` |

## Common mistakes

- **Looking for captures under `corpus/` or in the worktree.** Captures are in the data root.
- **Calling a capture complete from its frame count.** Completeness is `meta.json`, then the pin.
