# Clock, disk space, queue, and round bounds

Part of the [`running-unattended`](SKILL.md) skill.

## Clock and disk space

- **Clock:** If the user gave a deadline, stop starting new items 30 minutes before it (`cutoff`). Check the time before starting each item. At the deadline, if a branch has unmerged work: run `mise run fix` (fixing any lint or doc error a pre-commit hook reports, or saving an uncommittable hunk to `build/scratch/wip-<slug>.patch`), commit with a `chore: wip <summary>` subject (never `--no-verify`), push, open or update a **draft** PR with a handoff comment (what is done, what is left, last gate/CI result, and any saved `wip-<slug>.patch` inside a collapsible `<details>` block), and run **Shutdown**. Without a deadline, run until the queue is empty or free disk space falls under 5 GB.
- **Disk space:** Check free GB on the checkout's drive (`(Get-PSDrive E).Free / 1GB`, using the checkout's drive letter) at the start, before each item, and after each merge, then tidy from the primary checkout ([`managing-worktrees`](../managing-worktrees/SKILL.md)):
  1. `mise run reap -- --yes` (removes clean worktrees whose branches have merged when free space is under `reap`'s 20 GB bar; above 20 GB it is a no-op without `--force`, which requires asking the user). A linkless worktree created since [ADR 0036](../../../docs/adr/0036-worktrees-reach-shared-state-by-configuration.md) may also be removed by the tool that made it once merged.
  2. Under **10 GB free** after reaping: create no new worktrees, and run `mise run clean -- --yes` in any kept worktree that is pushed and idle.
  3. Under **5 GB free** after tidying: start no new item; bring any in-flight work to a pushed `chore: wip <summary>` commit and draft PR as at the deadline, and run **Shutdown**.
  Never delete a worktree, `target/` or cache directory by hand, and never run `git worktree remove` on a linked worktree ([ADR 0018](../../../docs/adr/0018-reaping-unlinks-the-data-root-links-first.md)).

## Queue order

Build the queue at the start and refresh it after each merge. Keep the queue on your task list so compaction cannot lose it:

1. **Open PRs** (`gh pr list --state open --limit 100 --json number,title,headRefName,baseRefName,isDraft,labels,mergeable,statusCheckRollup`), skipping any PR labeled `ready-for-human` or handed off earlier in this run, in dependency or stack order (bottom layer first when `baseRefName` is not `main`).
2. **Unblocked `ready-for-agent` issues** with no open PR (`gh issue list --label ready-for-agent --state open --limit 100 --json number,title,body,labels`), skipping any issue with open blockers or open sub-issues ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions), "Count open blockers") or carrying `in-progress`. In a cloud session (`CLAUDE_CODE_REMOTE=true`, [`cloud-sessions.md`](../../../docs/cloud-sessions.md)), also skip `local-only` ([`triage-labels.md`](../../../docs/agents/triage-labels.md#environment-roles)).
3. **Unblocked issues you filed as `ready-for-agent` during this run**, only once 1 and 2 are empty, skipping `local-only` in a cloud session.

## Implementing an issue and bounding rounds

1. **Claim it** before any branch commit ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions), "Claim an issue"): re-read its labels, swap `ready-for-agent` for `in-progress`, comment `Claimed by branch <branch>.`, and re-read comments to verify your claim is earliest.
2. **Branch** from an up-to-date `origin/main` (`git fetch origin`, then `git switch -c <branch> origin/main`).
3. **3-round cap:** Spend at most **3 hypothesis rounds** (or 3 failures for the same gate/CI/approach reason) on an issue. Do not chain a new heuristic onto a failed sweep ([`improving-render-parity`](../improving-render-parity/SKILL.md)).
4. **Ship the clean slice, file the rest:** If a self-contained, evidence-backed subset passes `mise run check` — and, for a rendering change, satisfies the [`loop-rules.md`](../improving-render-parity/loop-rules.md#adoption-rule) adoption rule (`mise run parity` exits `0` even on drift, so read the winner line of `mise run sweep -- --var ... --track <track>` or `mise run judge -- <base> <cand> --track <track>`) — while the rest of the issue is blocked or exposes entangled bugs:
   - Save the blocked prototype diff to `build/scratch/<slug>.patch`, revert the blocked changes so only the clean subset remains, and complete the required artifacts for the kept subset (including `[film.expected.<class>]` in `references.toml`, the work folder journal entry, [`error-readout.md`](../improving-render-parity/error-readout.md), and [`pr-evidence.md`](../improving-render-parity/pr-evidence.md) for rendering changes).
   - Verify `mise run check`, and ship the clean subset as a PR (`Fixes #N` when all remaining work is split into standalone follow-up issues, else `Part of #N`).
   - File `needs-triage` follow-up issues for the blocked pieces, embedding each saved prototype diff inside a collapsible `<details>` block ([`pr-and-filing.md`](pr-and-filing.md#filing-issues-and-powershell-safety)). If `#N` stays open (`Part of #N`), comment `Released claim: <why>.` on `#N` and swap `in-progress` for `ready-for-human` (or back to `ready-for-agent` with a `blocked-by` edge to the follow-up issue) so `#N` is not left in `in-progress`.
5. **Stuck or needs a human:** If 3 rounds finish with no shippable slice, or a non-obvious design/visual choice blocks progress, comment on the issue or PR with `Released claim: <why>.` (when releasing an unmerged issue), what you tried, the evidence, and the exact decision or resource needed; replace `in-progress` / `ready-for-agent` with `ready-for-human` (or `needs-info`); and move on.

## Never

- Push or force-push to `main`, use `--no-verify`, or weaken/skip a check.
- Commit anything under `corpus/` or `DBG_*` switches.
- Merge with a red check or an unresolved review thread, or close an issue whose fix has not merged.

## Shutdown

1. Confirm no subagent or background task is still running.
2. From the primary checkout, run `mise run reap -- --yes`.
3. End with a summary grouped as: **Merged**, **Draft / WIP**, **Opened**, **Filed** (with labels), **Needs you** (item, reason, decision), and **Skipped**, plus start/end free disk space and any environment friction.
