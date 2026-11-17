# Coordinator and workers

Part of the [`running-unattended`](SKILL.md) skill. The run is one **coordinator** and its **workers**; the coordinator's context is what the run spends longest, so it holds as little as it can (#509).

## Roles

| | Coordinator | Worker (implementer or reviewer) |
|---|---|---|
| Model | Sonnet from the start; never Opus | By fit ([`SKILL.md`](SKILL.md#concurrency-and-models)) |
| Does | Builds the queue, claims, dispatches, checks the merge bar, arms, files follow-ups from reports, rewrites `run-state.md` | Reads the issue or PR and its comments, implements or reviews in its own worktree, reports |
| Reads | `mise run queue` lines, worker reports, the first line of a review comment, CI state, the lines `mise run pr-threads` prints, a PR's changed file names | The bodies, diffs and code the coordinator does not |
| Never | Opens a diff, an issue body or a thread's text; writes code or text; `sleep`s or polls; loads `--help` or the orchestration guide | Arms or merges |

When the coordinator needs a fact that sits in a body or diff, a worker reads it and reports one line.

## `run-state.md`

`build/scratch/run-state.md`, ignored through `build/` (`git check-ignore -v build/scratch/run-state.md` shows the rule); no tracked file is written there. Rewrite it whole, with the file-write tool, at every transition: claimed, dispatched, worker reported, review verdict, armed, merged, handed off. Fields:

| Group | Fields |
|---|---|
| Run | start time, environment, deadline and cutoff, "stop after N" limit, PRs armed so far, coordinator number |
| Queue | the `mise run queue` lines verbatim, when refreshed, items skipped and why |
| Each item | issue or PR number, state (`claimed`, `implementing`, `in review`, `fixing`, `armed`, `merged`, `handed off`), worker (agent or terminal handle, model, task id), branch, worktree path, time of last event |
| Each PR's merge bar ([`pr-and-filing.md`](pr-and-filing.md#bringing-a-pr-to-mergeable-and-merge-bar) step 5) | head SHA (7 characters), CI at that SHA, local gate at that SHA, review comment URL and its verdict at that SHA, review-body findings answered, CodeRabbit (`not requested`, `check due <time>`, `checked`), acceptance items and `Fixes` or `Part of` as the worker reported them, changed paths that need a human cleared, `local-only`, armed |
| Shutdown report | Merged, Draft / WIP, Opened, Filed (labels), Needs you (item, reason, decision), Skipped |
| Next action | the one step a fresh coordinator takes first |

## Restart instead of compacting

Check the context at each rewrite. Once it passes about 150k tokens, rewrite the file, end the session with the line `handoff: build/scratch/run-state.md`, and let the run's starter start a fresh Sonnet coordinator in the same checkout with the brief "read the `running-unattended` skill and `build/scratch/run-state.md`, resume at Next action, and re-check each in-flight item's head SHA and state with one call before acting". Never compact: the queue, workers and merge-bar state are in the file.

## CodeRabbit: one scheduled check

CodeRabbit reviews when a person asks ([`pr-and-filing.md`](pr-and-filing.md#bringing-a-pr-to-mergeable-and-merge-bar) step 4). When a request follows the latest push, write `check due <request time + 20 min>` in the PR's row and set one timer for that time (`send_later` in Claude Code; `schedule` in Antigravity, [`harness.md`](../../../docs/harness.md#antigravity)), then work on other items or end the turn. At the timer, look once: a completed review goes to step 3, anything else gets a PR comment and the run proceeds. A successor re-sets a timer from the file's due time. The 20-minute wait stays in the merge bar.

## `orca orchestration` flags

Use these lines and nothing from `--help` or `orca skills get orchestration`: either puts thousands of characters in context for every later turn to re-read (#509). This is for Orca workers; a cloud session's workers are subagents that report in their final reply.

| Need | Line | Source |
|---|---|---|
| Worker reports | `orca orchestration send --body "<one plain line>" --report-path <file> --task-id <id from the brief>`; keep the report file to about 10 lines, because the coordinator keeps it in context | [`harness-setup.md` § DSH](../../../docs/harness-setup.md#dsh) |
| Check | `orca orchestration check --terminal <handle>`; there is no `--from` | same |
| Worker done | the `worker_done` event; a send to a busy worker returns a `messageId` and is usually not acted on, so send the next brief after `worker_done`, in full | [`loop-and-bounds.md`](loop-and-bounds.md#implementing-an-issue-and-bounding-rounds) |
| Confirm a worker started | `worker-read`, once, about 2 minutes of the dispatch | same |
| Retire a workspace | `orca worktree rm --worktree <selector>` | [`harness-setup.md` § Orca](../../../docs/harness-setup.md#orca) |

**Flags not verified.** The repo records no flags for starting or dispatching a worker (`worker-start`), for `worker-read`, for the recipient of `send`, or for listing worker handles, and the cloud session this was written in has no `orca`. The worker that first uses one successfully adds the exact line to this table in its PR; a lookup runs in a throwaway subagent that returns the command line and nothing else, never in the coordinator's context.
