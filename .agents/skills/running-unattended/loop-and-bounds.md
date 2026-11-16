# Clock, disk space, queue, and round bounds

Part of the [`running-unattended`](SKILL.md) skill.

## Clock and disk space

- **Clock:** If the user gave a deadline, stop starting new items 30 minutes before it (`cutoff`). Check the time before starting each item. At the deadline, if the item in flight has unmerged work that is not yet armed for auto-merge: run `mise run fix` (fixing any lint or doc error a pre-commit hook reports, or saving an uncommittable hunk to `build/scratch/wip-<slug>.patch`), commit with a `chore: wip <summary>` subject (never `--no-verify`), push, open or update a **draft** PR with a handoff comment (what is done, what is left, last gate/CI result, and any saved `wip-<slug>.patch` inside a collapsible `<details>` block), and run **Shutdown**. Without a deadline, run until the queue is empty or, on local-windows, free disk space falls under 5 GB.
- **Disk space** (local-windows only: a cloud session has its own disk and skips this and every reap): Check free GB on the checkout's drive (`(Get-PSDrive E).Free / 1GB`, using the checkout's drive letter) at the start, before each item, and after each arming, then tidy from the primary checkout ([`managing-worktrees`](../managing-worktrees/SKILL.md)):
  1. `mise run reap -- --yes` (removes clean worktrees whose branches have merged when free space is under `reap`'s 20 GB bar; above 20 GB it is a no-op without `--force`, which requires asking the user). A linkless worktree created since [ADR 0036](../../../docs/adr/0036-worktrees-reach-shared-state-by-configuration.md) may also be removed by the tool that made it once merged.
  2. Under **10 GB free** after reaping: create no new worktrees, and run `mise run clean -- --yes` in any kept worktree that is pushed and idle.
  3. Under **5 GB free** after tidying: start no new item; bring any in-flight work to a pushed `chore: wip <summary>` commit and draft PR as at the deadline, and run **Shutdown**.
  Never delete a worktree, `target/` or cache directory by hand, and never run `git worktree remove` on a linked worktree ([ADR 0018](../../../docs/adr/0018-reaping-unlinks-the-data-root-links-first.md)).

## Queue order

Build the queue with `mise run queue` at the start and before each item, and keep it on your task list so compaction cannot lose it. It prints one line per item, `ready` or the mechanical reason to skip it, and no bodies: read an item's body when you claim it. The mechanical reasons are open blockers and sub-issues ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions), "Count open blockers"), an open PR on the issue, `in-progress`, `ready-for-human`, a PR stacked on another open PR, an armed PR whose checks are pending, and an issue or PR labelled `local-only` in a cloud session ([`triage-labels.md`](../../../docs/agents/triage-labels.md#environment-roles), [`cloud-sessions.md`](../../../docs/cloud-sessions.md)). Take `ready` items in this order:

1. **Open PRs**, in the stack order it prints, skipping any handed off earlier in this run. An armed PR shows as `ready` only once a check has failed, it conflicts with `main` (often after an earlier armed PR lands), or its checks passed and it still has not merged: fix it before new work. On local-windows, a `local-only` PR a cloud run left for the GPU check is taken here ([`pr-and-filing.md`](pr-and-filing.md) step 5). A stacked PR shows again once its base merges and GitHub retargets it to `main`.
2. **`ready-for-agent` issues.** Skip, with a reason in the Shutdown report, any whose body shows it needs an ADR, a human design choice or a machine this session lacks.
3. **Unblocked issues you filed as `ready-for-agent` during this run**, only once 1 and 2 are empty.

A "stop after N PRs" limit counts armed PRs: start no new item once N are armed.

## Implementing an issue and bounding rounds

Run about two items at once only when they touch different files, each writer in its own worktree; if one depends on the other, start the dependent item after its parent merges, or stack it and arm it after the parent merges ([`pr-and-filing.md`](pr-and-filing.md) step 5). A Claude implementer ends when its PR opens, or earlier if its context passes about 150k tokens; a fresh worker starts from the PR and the review comment to make the fixes. dsh workers may keep their session. Brief every implementer from [`worker-brief.md`](worker-brief.md). Prefer Sonnet to dsh for note splits, an exception to dsh-first routing: on 2026-11-14 each dsh split took three review rounds over stale mentions. In Orca, send a worker its next brief only after its `worker_done`, in full: a send to a busy worker returns only a `messageId` and is usually never acted on, and each follow-up starts a fresh session. Within about 2 minutes of a dispatch, confirm with `worker-read` that the worker has started on it; one dsh worker sat at its splash screen for 30 minutes. Fix a PR yourself only for a one- or two-line text change; send any code change back to a worker, since your commit needs the same re-review.

1. **Claim it** before any branch commit ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions), "Claim an issue"): re-read its labels, swap `ready-for-agent` for `in-progress`, comment `Claimed by branch <branch>.`, and re-read comments to verify your claim is earliest.
2. **Branch** from an up-to-date `origin/main` (`git fetch origin`, then `git switch -c <branch> origin/main`).
3. **3-round cap:** Spend at most **3 hypothesis rounds** (or 3 failures for the same gate/CI/approach reason) on an issue. Do not chain a new heuristic onto a failed sweep ([`improving-render-parity`](../improving-render-parity/SKILL.md)).

   A prototype stops once measured: no PR polish, review or docs until one is chosen; run parallel prototypes only for decisions that are hard to undo.
4. **Ship the clean slice, file the rest:** If a self-contained, evidence-backed subset passes `mise run check` — and, for a rendering change, satisfies the [`loop-rules.md`](../improving-render-parity/loop-rules.md#adoption-rule) adoption rule (`mise run parity` exits `0` even on drift, so read the winner line of `mise run sweep -- --var ... --track <track>` or `mise run judge -- <base> <cand> --track <track>`) — while the rest of the issue is blocked or exposes entangled bugs:
   - Commit the blocked prototype on its own branch from `origin/main` (`proto/<issue>-<slug>`, with no `DBG_*` switch and the hooks passing) and push it, then revert the blocked changes so only the clean subset remains, and complete the required artifacts for the kept subset (including `[film.expected.<class>]` in `references.toml`, the work folder journal entry, [`error-readout.md`](../improving-render-parity/error-readout.md), and [`pr-evidence.md`](../improving-render-parity/pr-evidence.md) for rendering changes).
   - Verify `mise run check`, and ship the clean subset as a PR (`Fixes #N` when all remaining work is split into standalone follow-up issues, else `Part of #N`).
   - File `needs-triage` follow-up issues for the blocked pieces, naming each prototype's branch and commit ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#organizing-issues), "A prototype lives on a branch"; [`pr-and-filing.md`](pr-and-filing.md#filing-issues-and-powershell-safety)). If `#N` stays open (`Part of #N`), comment `Released claim: <why>.` on `#N` and swap `in-progress` for `ready-for-human` (or back to `ready-for-agent` with a `blocked-by` edge to the follow-up issue) so `#N` is not left in `in-progress`.
5. **Needs another environment:** In a cloud session, an item that needs a resource the session lacks is handed on as [`cloud.md` § Handing work to local-windows](../working-in-an-environment/cloud.md#handing-work-to-local-windows) says, with `Released claim: <why>.` on an unmerged issue, and the run moves on.
6. **Stuck or needs a human:** If 3 rounds finish with no shippable slice, or a non-obvious design/visual choice blocks progress, comment on the issue or PR with `Released claim: <why>.` (when releasing an unmerged issue), what you tried, the evidence, and the exact decision or resource needed; replace `in-progress` / `ready-for-agent` with `ready-for-human` (or `needs-info` when what blocks is a fact only a person knows); and move on.

## Measuring

Cost comparison is optional: join `ccusage` blocks and sessions to roles. The quality guard is that no merged PR needs a fix or revert afterwards.

## Never

- Push or force-push to `main`, use `--no-verify`, or weaken/skip a check.
- Commit anything under `corpus/` or `DBG_*` switches.
- Merge, or arm auto-merge, with a red check or an unresolved review thread, or close an issue whose fix has not merged.

## Shutdown

1. Confirm no subagent or background task is still running, and run `mise run queue` once for the PRs you armed. One no longer listed has merged or been closed (`gh pr view <n> --json state` says which: **Merged**, or **Needs you**); `armed, checks pending` goes under **Opened** as "auto-merge armed"; and any other PR you armed that is still listed goes under **Needs you**.
2. On local-windows, run `mise run reap -- --yes` from the primary checkout.
3. End with a summary grouped as: **Merged**, **Draft / WIP**, **Opened**, **Filed** (with labels), **Needs you** (item, reason, decision), and **Skipped**, plus the environment, start/end free disk space on local-windows, and any environment friction.
