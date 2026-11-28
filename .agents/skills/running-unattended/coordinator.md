# Coordinator and workers

Part of the [`running-unattended`](SKILL.md) skill.
The run is one **coordinator** and its **workers**; the coordinator runs longest of any session in the run (416 turns on 2026-11-14, #509), so it holds as little as it can.

## Roles

| | Coordinator | Worker (planner, implementer or reviewer) |
|---|---|---|
| Model | Current session's model | By labels, then fit, using [`models.md`](../../../docs/harness/models.md) for available providers ([`SKILL.md`](SKILL.md#concurrency-and-models)) |
| Does | Builds the queue, claims, dispatches, checks the merge bar, arms, files an issue for a reviewer's out-of-scope finding, appends to `run-state.md`; at a claim release, on a worker's report or a reviewer's finding, moves `model-tier:` up one (a swap) when the worker lacked capability, or adds `model-context:wide` when it ran out of context, and says so in its `Released claim:` comment | Reads the issue or PR and its comments; a planner investigates read-only and posts a `## Tentative plan` comment (updating missing `area:`/`type:` labels and naming and applying the `model-tier:` and any `model-context:` labels, without touching `priority:`), while an implementer or reviewer works in its own worktree and files follow-up issues |
| Reads | `mise run queue` lines, worker reports, the first line of a review comment, the reviewer's reply (its `alternatives: N` and `apply: M` included), CI state, the lines `mise run pr-threads` prints, a PR's changed file names | The bodies, diffs and code the coordinator does not |
| Never | Opens a diff, an issue body, a thread's text or a session transcript; writes no code and no PR or doc content; `sleep`s or polls; loads `--help` or the orchestration guide | Arms or merges |

The text the coordinator does write is `run-state.md`, claim and release comments, status notes on a PR, an issue for a reviewer's out-of-scope finding, and a reviewer's comment file posted verbatim with `--body-file`.
When it needs a fact that sits in a body, diff, thread or transcript, a worker or subagent reads it and reports one line.
Its claim check reads claim comments by first line, not whole comments ([`loop-and-bounds.md`](loop-and-bounds.md#implementing-an-issue-and-bounding-rounds) step 1).

## `run-state.md`

`build/scratch/run-state.md`, ignored through `build/` (`git check-ignore -v build/scratch/run-state.md` shows the rule); no tracked file is written there.
Its per-item and per-PR state is an append-only log: each transition appends one line, and no earlier line is rewritten.
Append in the same shell call as the command the line records (`gh`, `git`, `mise`), not in a turn of its own.
The Run header, the Queue lines, the Filed list and the Next action are edited in place, outside the log.
Record only what a fresh container can re-derive from GitHub (branch, PR number, head SHA, label state), plus what the coordinator holds locally: a worker's worktree path, an unpushed rule 5 commit with its reviewed local SHA and PR-body path, an `env:local-only` clearance, and a due time.
Fields:

| Group | Fields |
|---|---|
| Run | start time, environment, deadline and cutoff, "stop after N" limit, PRs armed so far, coordinator number |
| Queue | the `mise run queue` lines verbatim, when refreshed, items skipped and why |
| Log | one line per transition, oldest first, in the format below |
| Filed | issues the run filed, one line each with its labels |
| Next action | the one step a fresh coordinator takes first |

A filed issue has no transition of its own, so the Filed list records each one with its labels for Shutdown.

Each log line is:

```text
- <HH:MMZ> #<item> <state> | <agent/model> <task id> | <branch> | <head sha7 or -> | <note>
```

`<item>` is one key per tracked work item and `<state>` is one of `claimed`, `planning`, `planned`, `implementing`, `in review`, `fixing`, `armed`, `merged` and `handed off`.
Key an issue's work by its issue number, with `PR #<n>` in the note once one opens, and a PR taken from the queue by its PR number; never switch an item's key mid-item.
`<agent/model>` names the worker's agent and model, or its terminal handle, and `<task id>` is the task id of its current dispatch.
An issue carrying two `model-tier:` labels is routed as if it had none, and its note says `two tiers`.
The remaining fields are the branch, the head SHA at 7 characters or `-` when there is none, and the note.
The note carries what the merge bar needs: the worktree path (for `worker-start --worktree "path:<workspace path>"`), the review comment URL and its verdict at the head, the reviewer's `alternatives: N` and `apply: M` counts with the refactor step's state (`pending`, `small`, `review due`, `reviewed`), CodeRabbit (`not requested`, `check due <time>`, `checked`), the rule 5 reviewed SHA and PR-body path, a due time, the local gate at the head, the acceptance items as the worker reported them, review-body findings answered, changed paths that need a human cleared, and `env:local-only` (cleared or pending).
The newest line for an item is self-contained: each new line repeats every still-active local fact from that item's earlier lines (worktree path, local gate at the head, acceptance report, review-body findings answered, human-path and `env:local-only` clearance, an unpushed rule 5 SHA and PR-body path, a pending CodeRabbit due time, the alternatives and apply counts and the refactor step's state), since `mise run merge-bar` cannot re-derive them.
Record that count in the item's newest line and carry it forward like its other still-active facts.
Alternatives marked `owner`, or unmarked, are the owner's to read on the PR: never send them to a worker as fix requests and never file them as issues.
When the reviewer replies `apply: M`, dispatch, after the fix round, a fresh worker on the reviewer's model to apply those items as one `refactor:` commit, then get the second review a non-small commit needs, both by [`harness.md`](../../../docs/harness.md#policy-any-agent) (A higher-tier first review also improves the code), before the merge bar; on a rule 5 PR the refactor commit stays unpushed until that review at its SHA is clean.
Run `mise run merge-bar -- <n> --issue <N>` and put its `PASS` or `FAIL` in the note rather than repeating the CI, base, thread or body-line fields that report already reads.
For example:

```text
- 14:32Z #852 armed | dsh/deepseek-flash task_03e76ef44c0c | neilsh/852-git-longpaths-tests | 4a1c2d3 | worktree E:/orca/workspaces/stunt-reel/852-git-longpaths-tests; PR #859; merge-bar PASS; Antigravity review at 4a1c2d3 clean, https://github.com/neilsh/stunt-reel/pull/859#issuecomment-2520000000
```

An item's current state is its newest line, read alongside `mise run queue`.

## Restart instead of compacting

Check the context size after each append: the harness's context indicator or `/context` where there is one, else an estimate from the turn count.
Once it passes about 100k tokens, stop dispatching, update the Run header and Next action, and hand off; never compact.
A harness compaction means that point passed unnoticed: hand off at the next append.
In a cloud session a successor's new container cannot see the predecessor's worktrees, subagents or unpushed commits, so wait until no worker is in flight, or until every in-flight item has a pushed branch (a rule 5 item only after its review and push), before handing off.
Release any other item (`Released claim: <why>.`, swap `status:in-progress` back to its prior state (`status:ready-for-agent` or `status:needs-plan`)) and list it under **Needs you**; an item left `status:in-progress` with no remote branch is a dropped claim ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions)).
A successor rebuilds current state from the log: for each item, read its newest line, then check it against `mise run queue` and, for a PR, one `mise run merge-bar -- <n> --issue <N>` run before acting.
An item whose newest line predates GitHub's state gets a new line recording the checked state; an older line is never edited.
The outgoing coordinator starts its successor:

- **Cloud:** a new session has a new container, so it cannot read the predecessor's gitignored file.
  With `create_session` (when the session has that tool), put the full content of `run-state.md` in the `prompt`, which the file's small size allows, with the brief "read the `running-unattended` skill, write this state into `build/scratch/run-state.md` in your own checkout, resume at Next action, and re-check each in-flight item's head SHA and state with one call before acting".
  A session with no way to start one runs Shutdown instead of handing off, under the same wait and release rule ([`loop-and-bounds.md`](loop-and-bounds.md#shutdown)).
- **local-windows:** the repo records no command for starting a successor coordinator.
  The coordinator runs Shutdown at the context limit unless a person has said how to hand off.
- **T3 Code:** the coordinator restarts its own thread with a fresh context ([`t3.md`](t3.md)).

## CodeRabbit: one scheduled check

CodeRabbit reviews when a person asks ([`pr-and-filing.md`](pr-and-filing.md#bringing-a-pr-to-mergeable-and-merge-bar) step 4).
When a request follows the latest push, append a line for the PR with its current state and a note that carries its still-active facts and `check due <request time + 20 min>`, and set one timer for that time (`send_later` in a cloud session, when the session has that tool; `schedule_task` under T3 Code, [`t3.md`](t3.md); otherwise on local-windows the repo records a timer for Antigravity (`schedule`, [`harness.md`](../../../docs/harness.md#antigravity)) and none for Claude Code, so there the coordinator looks once at the timeout in a later turn, and when no other event is expected it runs that look and notes the outcome before ending the run, or runs Shutdown with the PR under **Needs you**), then work on other items or end the turn.
At the timer, look once: a completed review goes to step 3, anything else gets a PR comment and the run proceeds.
A successor re-sets a timer from the newest line's due time.
The 20-minute wait stays in the merge bar.

## Dispatching a dsh worker

A dsh worker can sit on its start screen with an empty prompt and run no brief until it receives a message: six dsh dispatches did on 2026-11-22 ([#959](https://github.com/neilsh/stunt-reel/issues/959)).
So a dsh dispatch puts the brief in the worker's workspace and sends the start message at once, rather than waiting to see whether it stalled:

1. Start it from the `worker-start` line in the flags table below, with `--agent dsh` and `--json`, and keep its `dispatch` id and workspace path.
2. Put the brief in that workspace: `New-Item -ItemType Directory -Force <workspace>/build/scratch`, then `Copy-Item <brief>.md <workspace>/build/scratch/` (a fresh workspace has no `build/`).
3. Send `orca orchestration send --to dispatch:<dispatch id> --subject "Start" --body "Read and follow build/scratch/<brief>.md in this workspace now"` immediately, before the usual `worker-read` confirmation.

Step 3 is part of the dispatch, not a recovery from a stall: the worker has started nothing until the message arrives.

## `orca orchestration` flags

Use these lines and nothing from `--help` or `orca skills get orchestration`: either puts thousands of characters in context for every later turn to re-read (#509).
This is for Orca workers; a cloud session's workers are subagents that report in their final reply, and a T3 Code run's are in [`t3.md`](t3.md).

| Need | Line | Source |
|---|---|---|
| Worker reports | `orca orchestration send --body "<one plain line>" --report-path <file> --task-id <task id from your prompt>` (a follow-up dispatch has a new one); keep the report file to about 10 lines, because the coordinator keeps it in context | [`harness-setup.md` § DSH](../../../docs/harness-setup.md#dsh) |
| Check | `orca orchestration check --terminal <handle>`; there is no `--from` | same |
| Worker done | the `worker_done` event; a send to a busy worker returns a `messageId` and is usually not acted on, so send the next brief after `worker_done`, in full | [`loop-and-bounds.md`](loop-and-bounds.md#implementing-an-issue-and-bounding-rounds) |
| Confirm a worker started | `worker-read`, once, within about 2 minutes of the dispatch | same |
| Send a dsh worker's start | after `worker-start --agent dsh --json`, `New-Item -ItemType Directory -Force <workspace>/build/scratch`, `Copy-Item <brief>.md <workspace>/build/scratch/`, then `orca orchestration send --to dispatch:<dispatch id> --subject "Start" --body "Read and follow build/scratch/<brief>.md in this workspace now"` at once, not as a stall fallback ([dispatch steps](#dispatching-a-dsh-worker)) | run 2026-11-22, [#959](https://github.com/neilsh/stunt-reel/issues/959) |
| Start a worker in a new workspace | `orca orchestration worker-start --spec-file <brief> --worktree new-top-level --repo id:<repo id> --name <issue>-<slug> --base-branch origin/main --agent <claude\|dsh\|antigravity> --model <id> --task-title "<title>" --json`; dsh ran without `--model` | run `run_b217992041c6`, 2026-11-20 |
| Name the workspace | `--name` takes a bare slug such as `852-git-longpaths-tests`, and Orca makes the branch `neilsh/<slug>`; a name starting `neilsh-` or `neilsh/` became `neilsh/neilsh-…` or `neilsh/neilsh/…` | same |
| Pick an Antigravity model | `--agent antigravity --model gemini-4-neon`, two flags; `--agent "antigravity --model …"` fails with `agent_unconfigured` | same |
| Start a worker in an existing workspace | `worker-start --spec-file <brief> --worktree "path:<workspace path>" --agent <agent> --model <id> --task-title "<title>" --json`, without `--repo`, `--name` or `--base-branch` | same |
| Link a workspace to its issue and PR in the Orca UI | `orca worktree set --worktree "path:<workspace path>" --issue <N>` after `worker-start` (it has no issue flag), and again with `--pr <M>` once the PR opens | run 2026-11-21 |
| Send to an idle worker | `orca orchestration send --to dispatch:<dispatch id> --subject "<subject>" --body "<body>" --json` | same |
| Send to every worker in a run | `orca orchestration send --to run:<run id> --run <run id> --subject … --body …`; `send --chat <id>` fails with `run_required` when no run resolves | same |
| Answer a worker's question | `orca orchestration reply --id <message id> --body "<answer>"` | same |
| Read a worker | `orca orchestration worker-read --dispatch <dispatch id> --limit 15` | same |
| List workers | `orca orchestration worker-list --json` | same |
| Close a finished worker's terminals | `orca terminal close --worktree id:<id> --all` (stops every terminal process of the workspace; only after its PR merged and the worker reported done) | [`harness-setup.md` § Orca](../../../docs/harness-setup.md#orca) |
| Retire merged workspaces | `mise run reap -- --yes --reviews` from the primary checkout, after closing their terminals; it also retires a `review-*` checkout idle six hours; by hand, one workspace: `orca worktree rm --worktree <selector>` | same |

For any other flag, a throwaway subagent looks it up and returns the command line and nothing else, never in the coordinator's context; whoever first uses a new line successfully adds it to this table in their PR.
