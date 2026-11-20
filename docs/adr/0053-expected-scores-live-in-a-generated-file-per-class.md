# Expected scores live in a generated file per renderer class

## Status

accepted 2026-11-19 for [#829](https://github.com/neilsh/stunt-reel/issues/829).
Revises the layout #436 chose in `work/2026-11/436_expected-scores-layout/spec.md`, which is not an ADR; [ADR 0041](0041-dated-records-live-in-work-folders.md)'s "The current baseline" row points here.

## Context

Every `mise run parity-repin` rewrote all seven films' expected tables for its class in `research/parity/references.toml`, the `crates` line included, even when no score moved.
So any two open render PRs that repinned conflicted in every expected table.
#436 chose layout (d), keeping the tables in `references.toml` and making the resolution mechanical: take `main`'s tables, re-measure, repin.
The resolution was mechanical, but git still stopped on it every time: in the GPU queue of 2026-11-19, #773, #778 and #808 each conflicted only in expected tables.
#436 rejected one file per renderer class (its option (b)) because render PRs would still conflict in one file, and it did not consider a merge driver.

## Decision

- **A generated file per class.**
  `research/parity/expected/gpu.toml` and `research/parity/expected/lavapipe.toml` hold the expected tables, `[<film>]` (`ssim`, `iou`, `crates`, `sha256`, `all_sha256`, `adapter`) and `[<film>.loss]`, in `references.toml` row order.
  `mise run parity-repin` regenerates one class's file whole, under a fixed header that documents the fields, and nobody edits one by hand.
  The class defaults to the one the reports were drawn on, and the repin refuses reports of more than one.
- **Hand-edited facts stay in `references.toml`.**
  Rows, `sha256`, `all_sha256`, `background`, builds and slugs conflict loudly in a real edit, as before.
  A row that still holds `[<film>.expected.<class>]` tables, as a branch made before this record does after merging `main`, is refused with a message naming the new files.
- **A take-`main` merge driver.**
  `.githooks/merge-take-main.sh`, a POSIX `sh` script registered as the `expected-pins` driver and attached to `research/parity/expected/*.toml` by `.gitattributes`, keeps `main`'s side on a merge (`%B`) and on a rebase (`%A`, the upstream).
  The branch then re-measures and repins its own class.
  `mise run init` and the hidden `ensure` task register the driver in the shared repository config beside `core.hooksPath`; a clone without it gets a plain conflict, as before.
- **The driver's contract is a merge or rebase of `main`.**
  A merge of any other branch also takes the other side.
  A cherry-pick takes the picked side too: while a driver runs, git has written neither `MERGE_HEAD` nor `CHERRY_PICK_HEAD` and sets no reflog action for a pick, so the script cannot tell it from a merge (`tests/test_merge_driver.py`).
- **Each PR repins only the class it measured.**
  A cloud PR repins `lavapipe`, a local-windows PR `gpu`, and the other class's `crates` lags until a catch-up repin (`chore(parity): repin expected scores`, its own commit).
  The drift line says so, `crates/ tree <found>, measured on <pinned>: awaiting a repin or catch-up repin of this class`, and stays informational.
  Lavapipe catch-ups are tracked on the standing issue [#830](https://github.com/neilsh/stunt-reel/issues/830), done by a cloud session whose llvmpipe matches the pinned `adapter`; local-windows cannot redo one, since its llvmpipe is LLVM 21.1.7 and the pins name LLVM 20.1.2.
- **GitHub's server-side merges never run a custom driver.**
  The workflow already merges `main` into a branch locally ([`pr-and-filing.md`](../../.agents/skills/running-unattended/pr-and-filing.md) step 1), so nothing changes there.

## Considered Options

- **Layout (d), as #436 chose:** keep the tables in `references.toml`.
  Rejected: git stops on every pair of repinning PRs, and the driver cannot be attached to part of a file.
- **One generated file for both classes:** a PR that repinned `gpu` merging a `main` that only got a lavapipe catch-up would conflict in it, and the driver would take `main`'s `gpu` tables with it.
  Two files let git merge them at file level, keeping both.
- **Detect a cherry-pick and conflict:** the plan's first design.
  Not possible, as above.

## Consequences

- Two PRs that repinned different or the same class merge without a conflict, taking `main`'s file; the one that merges second re-measures and repins.
- `references.toml` keeps only hand-edited facts, so a stale expected table can no longer hide in a conflict marker.
- The driver keeps `main`'s numbers over the branch's own repin, so a branch re-measures after an update that conflicted.
  A lavapipe repin cannot be redone locally, which makes the catch-up on #830 the only way a cloud-only class gets current after a local-windows PR.
- A reader of a generated file for a film no row names ignores it, and a film missing from it has no expected entry; the next repin rewrites the file to the rows.

Source: `work/2026-11/436_expected-scores-layout/spec.md`, `work/2026-11/829_expected-pins-merge-driver/plan.md`.
