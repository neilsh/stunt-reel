# Reaping unlinks the data-root links first

## Status

amended 2026-11-04 by [ADR 0036](0036-worktrees-reach-shared-state-by-configuration.md): new worktrees hold no links; this applies to old ones until
reaped.

amended 2026-11-14 (issue #541): links git tracks as symlinks are left for git to remove.

amended 2026-11-16 (issue #557): reap unlinks a changed tracked link before git stash push.

amended 2026-11-22 (issue #912): a detached worktree named `review-*` is a candidate once no
review is live in it; it has no branch to delete, its untracked test output never keeps it, and
its in-tree test links are unlinked by the same walker.

accepted; `mise run reap` is the only supported way to remove a linked worktree.

## Context

[ADR 0008](0008-worktrees-share-one-read-only-data-root.md) links the shared data root
into every worktree with junctions, so `corpus/` and
`build/parity/captures/` work unchanged (the links were `corpus/`, `target_bin/` and
`build/parity/reference/` until [ADR 0022](0022-captures-are-add-only-beside-a-read-only-corpus.md); reaping unlinks any reparse point git does not track, so it serves either set). A linked worktree therefore holds several reparse
points whose targets live outside it, and `mise run init` recreates them on demand.

Removing that worktree is not one operation. `git worktree remove` is the documented
tool, and its recursive delete has treated a junction two different ways across builds:

| git | result | how it was measured |
| --- | --- | --- |
| 2.47.1 | deleted the junction target's contents | [anthropics/claude-code#84162](https://github.com/anthropics/claude-code/issues/84162), by controlled comparison: PowerShell 7, Windows PowerShell 5.1, `rm -rf` and `shutil.rmtree` all preserved the target, only git destroyed it |
| 2.55.0.windows.3 | removed the contents, left the junction directories, deregistered the worktree | four variants here — clean, dirty, untracked link, `--force` — target intact, a `corpus/` skeleton left behind |

Both outcomes are wrong for us. The first destroys the shared data root; the second
leaves an unregistered skeleton that a second `git worktree remove` refuses ("not a
working tree"), which is how `.agents/worktrees/wt-202610261030-seed-b` and
`wt-202610261400-defender-probe` came to exist before the cleanup that prompted this
record.

General-purpose deleters are not a rule either: Windows treats a junction as a directory
to some tools and as a leaf to others. PowerShell 7, Windows PowerShell 5.1,
`git clean -fdx`, `cmd /c rmdir /s` and Python's `shutil.rmtree` all unlinked rather than
followed in the measurements here, but one git build already recurses
([the Nomi lesson](https://github.com/aqm857886159/Nomi/blob/main/docs/lessons/windows-worktree-remove-follows-junctions.md)
reports the same for `git worktree remove --force`), and `robocopy /MIR` follows a
junction unless `/XJ` is given. The practice cannot depend on which build is installed.

## Decision

`mise run reap` (`python/scripts/worktree_init.py reap`) removes worktrees, ordered so
that no recursive delete ever sees a link git does not track:

1. **classify** — the branch must be an ancestor of `main` (`--cherry` also accepts a
   branch whose patches `main` already holds), or the worktree must be a detached
   `review-*` scratch checkout no review is live in; the worktree must live inside this
   checkout (`.agents/worktrees/`, `.claude/worktrees/`), and the candidate must be
   clean;
2. **refuse** — modified tracked files need `--stash-dirty`, untracked files need
   `--discard-untracked` (a review worktree's test output excepted), and any refusal stops
   the run before the first delete;
3. **unlink** — every reparse point under the worktree that git does not track is removed
   with `remove_link` (`rmdir`/`unlink` on the link, never its target), by a walker that
   never descends into one; a path git records as a symlink (mode 120000) is left for git to
   delete as a leaf, because unlinking it first leaves the checkout modified and the
   clean-tree check then refuses (issue #541);
4. **prove** — the walker runs again and the run aborts if any reparse point git does not
   track remains;
5. **remove** — only now does `git worktree remove` run (`--force` only when untracked
   files were explicitly allowed); no link git does not track is left to follow, and git
   removes the tracked symlinks as leaves;
6. **delete the branch** — `-d` for an ancestor of `main`, `-D` for a patch-equivalent
   branch, and none for a detached review worktree;
7. **`--prune`** — remove pool directories git no longer registers (only when they hold
   nothing but links) and branches no worktree holds.

`clean` is not part of reaping: deleting the checkout reclaims `target/`, `build/` and
the caches in the same pass, and `clean` would recreate the reference link that step 3 is
about to remove. `reap` runs from the primary checkout; running it from a worktree is
refused because branch deletion is defined against the primary's `main`.

## Considered Options

- **Switch to `mklink /D` directory symlinks.** Rejected. It does fix removal, because git
  treats a symlink as a leaf, but creating one needs `SeCreateSymbolicLinkPrivilege` — an
  elevated shell or the machine-wide Developer Mode flag — which is exactly why
  [ADR 0008](0008-worktrees-share-one-read-only-data-root.md) chose junctions. Measured
  cost: `git status` stops matching the trailing-slash ignore rules (`target_bin/`,
  `/.cache/`), so two ignore lines would have to change, and old worktrees keep junctions
  forever, leaving a mixed pool.
- **Trust the deleter.** Rejected: the same command follows on 2.47.1 and does not on
  2.55.0, and a leftover skeleton is silent while the destroyed root is not.
- **Make the data root ACL-read-only outside capture runs.** Not adopted here. It is a
  real second line of defence, but it breaks ad-hoc captures and render-tree rotation, so
  it needs its own decision and its own gate.
- **Keep the old sequence: `mise run clean -- --yes`, then `git worktree remove`.** Rejected:
  `clean` removes `target/` and `build/` but leaves the corpus, `target_bin` and `.cache`
  links in place, which is exactly the state that produced the skeletons.

## What enforces this

[`tests/test_worktree_reap.py`](../../tests/test_worktree_reap.py) pins the order: a junction
into a temporary target is unlinked without changing the target, the walker finds a link
without descending into it, `_reap_one` removes the checkout while the target survives,
and the refusal rules are unit-tested against a real temporary git repository.
[`mise.toml`](../../mise.toml) exposes only `mise run reap`; the raw git commands stay
inside the task.

## Consequences

- Reaping is one command, and the destructive path is never reached through a data-root
  link: no link git does not track exists when the delete starts. The only links left sit at
  paths git tracks as symlinks; the clean-tree check refuses a worktree where anything but
  that symlink sits there, and `git worktree remove` deletes the symlink as a leaf (measured
  on git 2.55.0.windows.3, issue #541).
- A dirty worktree is preserved by default. A stash made with `--stash-dirty` survives the
  removal in the shared repository (`git stash list`), and its message names the branch.
- Pool leftovers and branches orphaned by a removal are reclaimed only with `--prune`,
  which deletes a leftover directory only when it holds nothing but links.
- A junction skeleton is no longer routine residue: if one appears, `reap` has a bug, and
  the tool aborts rather than deleting anything when an untracked link survives the unlink step.
  `robocopy /MIR` over a checkout still needs `/XJ`, and `cmd /c rmdir` on a link remains
  the safe way to remove one by hand.
