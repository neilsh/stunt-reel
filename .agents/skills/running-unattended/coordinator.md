# Coordinator and workers

Part of the [`running-unattended`](SKILL.md) skill. The run is one **coordinator** and its **workers**; the coordinator runs longest of any session in the run (416 turns on 2026-11-14, #509), so it holds as little as it can.

## Roles

| | Coordinator | Worker (implementer or reviewer) |
|---|---|---|
| Model | Sonnet from the start; never Opus | By fit ([`SKILL.md`](SKILL.md#concurrency-and-models)) |
| Does | Builds the queue, claims, dispatches, checks the merge bar, arms, files an issue for a reviewer's out-of-scope finding, rewrites `run-state.md` | Reads the issue or PR and its comments, implements or reviews in its own worktree, files the follow-up issues its item produces and reports their numbers |
| Reads | `mise run queue` lines, worker reports, the first line of a review comment, CI state, the lines `mise run pr-threads` prints, a PR's changed file names | The bodies, diffs and code the coordinator does not |
| Never | Opens a diff, an issue body or a thread's text; writes no code and no PR or doc content; `sleep`s or polls; loads `--help` or the orchestration guide | Arms or merges |

The text the coordinator does write is `run-state.md`, claim and release comments, status notes on a PR, an issue for a reviewer's out-of-scope finding, and a reviewer's returned text posted verbatim. When it needs a fact that sits in a body or diff, a worker reads it and reports one line. Its claim check reads claim comments by first line, not whole comments ([`loop-and-bounds.md`](loop-and-bounds.md#implementing-an-issue-and-bounding-rounds) step 1).

## `run-state.md`

`build/scratch/run-state.md`, ignored through `build/` (`git check-ignore -v build/scratch/run-state.md` shows the rule); no tracked file is written there. Rewrite it whole, with the file-write tool, at every transition: claimed, dispatched, worker reported, review verdict, armed, merged, handed off. Record only what a fresh container can re-derive from GitHub (branch, PR number, head SHA, label state), plus what the coordinator holds locally: a worker's unpushed rule 5 commit with its reviewed local SHA and PR-body path, and a due time. Fields:

| Group | Fields |
|---|---|
| Run | start time, environment, deadline and cutoff, "stop after N" limit, PRs armed so far, coordinator number |
| Queue | the `mise run queue` lines verbatim, when refreshed, items skipped and why |
| Each item | issue or PR number, state (`claimed`, `implementing`, `in review`, `fixing`, `armed`, `merged`, `handed off`), worker (agent or terminal handle, model, task id), branch, worktree path, time of last event |
| Each PR's merge bar ([`pr-and-filing.md`](pr-and-filing.md#bringing-a-pr-to-mergeable-and-merge-bar) step 5) | head SHA (7 characters), CI at that SHA, local gate at that SHA, review comment URL and its verdict at that SHA, review-body findings answered, CodeRabbit (`not requested`, `check due <time>`, `checked`), acceptance items and `Fixes` or `Part of` as the worker reported them, changed paths that need a human cleared, `local-only`, armed |
| Shutdown report | Merged, Draft / WIP, Opened, Filed (labels), Needs you (item, reason, decision), Skipped |
| Next action | the one step a fresh coordinator takes first |

## Restart instead of compacting

Check the context size at each rewrite: the harness's context indicator or `/context` where there is one, else an estimate from the turn count. Once it passes about 150k tokens, stop dispatching, rewrite the file and hand off; never compact. In a cloud session a successor's new container cannot see the predecessor's worktrees, subagents or unpushed commits, so wait until no worker is in flight, or until every in-flight item has a pushed branch (a rule 5 item only after its review and push), before handing off. Release any other item (`Released claim: <why>.`, swap `in-progress` back to `ready-for-agent`) and list it under **Needs you**; an item left `in-progress` with no remote branch is a dropped claim ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions)). The outgoing coordinator starts its successor:

- **Cloud:** a new session has a new container, so it cannot read the predecessor's gitignored file. With `create_session` (when the session has that tool), put the full content of `run-state.md` in the `prompt`, which the file's small size allows, with the brief "read the `running-unattended` skill, rewrite this state into `build/scratch/run-state.md` in your own checkout, resume at Next action, and re-check each in-flight item's head SHA and state with one call before acting". A session with no way to start one runs Shutdown instead of handing off, under the same wait and release rule ([`loop-and-bounds.md`](loop-and-bounds.md#shutdown)).
- **local-windows:** the repo records no command for starting a Sonnet coordinator. The coordinator runs Shutdown at the context limit unless a person has said how to hand off.

## CodeRabbit: one scheduled check

CodeRabbit reviews when a person asks ([`pr-and-filing.md`](pr-and-filing.md#bringing-a-pr-to-mergeable-and-merge-bar) step 4). When a request follows the latest push, write `check due <request time + 20 min>` in the PR's row and set one timer for that time (`send_later` in a cloud session, when the session has that tool; on local-windows the repo records a timer for Antigravity (`schedule`, [`harness.md`](../../../docs/harness.md#antigravity)) and none for Claude Code, so there the coordinator looks once at the timeout in a later turn, and when no other event is expected it runs that look and notes the outcome before ending the run, or runs Shutdown with the PR under **Needs you**), then work on other items or end the turn. At the timer, look once: a completed review goes to step 3, anything else gets a PR comment and the run proceeds. A successor re-sets a timer from the file's due time. The 20-minute wait stays in the merge bar.

## `orca orchestration` flags

Use these lines and nothing from `--help` or `orca skills get orchestration`: either puts thousands of characters in context for every later turn to re-read (#509). This is for Orca workers; a cloud session's workers are subagents that report in their final reply.

| Need | Line | Source |
|---|---|---|
| Worker reports | `orca orchestration send --body "<one plain line>" --report-path <file> --task-id <id from the brief>`; keep the report file to about 10 lines, because the coordinator keeps it in context | [`harness-setup.md` § DSH](../../../docs/harness-setup.md#dsh) |
| Check | `orca orchestration check --terminal <handle>`; there is no `--from` | same |
| Worker done | the `worker_done` event; a send to a busy worker returns a `messageId` and is usually not acted on, so send the next brief after `worker_done`, in full | [`loop-and-bounds.md`](loop-and-bounds.md#implementing-an-issue-and-bounding-rounds) |
| Confirm a worker started | `worker-read`, once, within about 2 minutes of the dispatch | same |
| Retire a workspace | `orca worktree rm --worktree <selector>` | [`harness-setup.md` § Orca](../../../docs/harness-setup.md#orca) |

**Flags not verified.** The repo records no flags for starting or dispatching a worker (`worker-start`), for `worker-read`, for the recipient of `send`, or for listing worker handles, and the cloud session this was written in has no `orca`. The worker that first uses one successfully adds the exact line to this table in its PR; a lookup runs in a throwaway subagent that returns the command line and nothing else, never in the coordinator's context.
