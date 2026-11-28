# Clock, disk space, queue, and round bounds

Part of the [`running-unattended`](SKILL.md) skill.

## Clock and disk space

- **Clock:** If the user gave a deadline, stop starting new items 30 minutes before it (`cutoff`).
  Check the time before starting each item.
  At the deadline, if the item in flight has unmerged work that is not yet armed for auto-merge, send its worker to run `mise run fix` (fixing any lint or doc error a pre-commit hook reports, or saving an uncommittable hunk to `build/scratch/wip-<slug>.patch`), commit with a `chore: wip <summary>` subject (never `--no-verify`), push, and open or update a **draft** PR with a handoff comment (what is done, what is left, last gate/CI result, and any saved `wip-<slug>.patch` inside a collapsible `<details>` block); then run **Shutdown**.
  A **rule 5 item** (a diff touching a path [`AGENTS.md` § Committing](../../../AGENTS.md#committing) rule 5 names) gets its fresh review first when the time allows, then pushes as usual.
  Otherwise it still gets this `chore: wip` commit, push and **draft** PR, unreviewed, and its handoff comment starts `unreviewed: rule 5 review pending`; the merge bar's `clean` review at `HEAD` still keeps it from merging.
  Without a deadline, run until the queue is empty or, on local-windows, free disk space falls under 5 GB.
- **Disk space** (local-windows only: a cloud session has its own disk and skips this and every reap): `mise run queue` ends with `free disk: <N> GB on <drive>` for the drive holding the primary checkout; under 10 GB free it adds `create no new worktrees; run mise run clean`, and under 5 GB free it adds `run Shutdown`.
  Read that line at the start, before each item, and after each arming, then tidy from the primary checkout ([`managing-worktrees`](../managing-worktrees/SKILL.md)):
  1. For each item whose PR has merged and whose worker has reported done, close the worker's terminals: `orca terminal close --worktree id:<id> --all` ([`coordinator.md`](coordinator.md#orca-orchestration-flags)); Orca keeps a finished worker's terminal live, and `reap` skips a workspace with one.
     Then `mise run reap -- --yes --reviews` (removes clean worktrees and Orca workspaces whose branches have merged when free space is under `reap`'s 20 GB bar, and a detached `review-*` checkout nothing under it or in its git dir changed for six hours; above 20 GB it is a no-op without `--force`, which requires asking the user).
     It skips, and names, a workspace with a live terminal or an unfinished worker or one that holds nested worktrees ([`harness-setup.md` § Orca](../../../docs/harness-setup.md#orca)).
     Any other linkless worktree made since [ADR 0036](../../../docs/adr/0036-worktrees-reach-shared-state-by-configuration.md) goes with the tool that made it.
  2. Under **10 GB free** after reaping: create no new worktrees, and run `mise run clean -- --yes` in any kept worktree that is pushed and idle.
  3. Under **5 GB free** after tidying: start no new item; bring any in-flight work to a pushed `chore: wip <summary>` commit and draft PR as at the deadline (a rule 5 item reviewed first when the time allows, otherwise pushed unreviewed with its handoff comment starting `unreviewed: rule 5 review pending`), and run **Shutdown**.
     Never delete a worktree, `target/` or cache directory by hand, and never run `git worktree remove` on a linked worktree ([ADR 0018](../../../docs/adr/0018-reaping-unlinks-the-data-root-links-first.md)).

## Queue order

Build the queue with `mise run queue` at the start and before each item, and keep it in `build/scratch/run-state.md`, which a restart reads ([`coordinator.md`](coordinator.md)).
It prints one line per item, `ready` or the mechanical reason to skip it, and no bodies: the coordinator reads none, and the worker you dispatch reads the item's body.
The mechanical reasons are open blockers and sub-issues ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions), "Count open blockers"), an open PR on the issue, `status:in-progress`, `status:ready-for-human`, a PR stacked on another open PR, an armed PR whose checks are pending, and an issue or PR labelled `env:local-only` in a cloud session ([`triage-labels.md`](../../../docs/agents/triage-labels.md#environment-roles), [`cloud-sessions.md`](../../../docs/cloud-sessions.md)).
Issue lines come ordered by `priority:` (`priority:p0` down to `priority:p3`, then unprioritized items carrying an `unprioritized` note), breaking ties with `issue` (`status:ready-for-agent`) before `plan` (`status:needs-plan`), then issue number.
Take `ready` items in this order:

1. **Open PRs**, in the stack order it prints, skipping any handed off earlier in this run.
   An armed PR shows as `ready` only once a check has failed, it conflicts with `main` (often after an earlier armed PR lands), or its checks passed and it still has not merged: fix it before new work.
   A stacked PR shows again once its base merges and GitHub retargets it to `main`.
2. **`status:ready-for-agent` (`issue`) and `status:needs-plan` (`plan`) issues**, in the queue's priority order.
   Skip, with a reason in the Shutdown report, any whose worker reports, after reading the body, that it needs an ADR, a human design choice or a machine this session lacks (release its claim as step 5 or 6 says).
   Skip the standing `Error readout due: merged render PRs since the last baseline` issue as well, with the reason "the coordinator runs it at Shutdown when an agreement batch is due": a run records its merged render PRs on that issue and never dispatches it to a worker ([Shutdown](#shutdown) step 2).
3. **Unblocked issues you filed as `status:ready-for-agent` during this run**, only once 1 and 2 are empty.

A "stop after N PRs" limit counts armed PRs: start no new item once N are armed.

## Implementing an issue and bounding rounds

Run about two writers at once only when their `area:` label sets are non-empty and disjoint ([`triage-labels.md`](../../../docs/agents/triage-labels.md#area-roles)), each writer in its own worktree (an unlabeled issue does not pair with another writer, while a read-only planner has no file conflict with a writer on another issue); never pair a `type:perf` item running `mise run ab` with another concurrent Rust-building worker on local-windows, and never run or merge two repinning `type:fidelity` PRs at once; if one depends on the other, start the dependent item after its parent merges, or stack it and arm it after the parent merges ([`pr-and-filing.md`](pr-and-filing.md) step 5).
A Claude implementer ends when its PR opens, or earlier if its context passes about 150k tokens; a fresh worker starts from the PR and the review comment to make the fixes. dsh workers may keep their session.
Brief every implementer from [`worker-brief.md`](worker-brief.md), and read its report, not its diff.
For an issue with no `model-tier:` label, prefer Sonnet to dsh for note splits, an exception to dsh-first routing (a planned note split is `model-tier:medium`): on 2026-11-14 each dsh split took three review rounds over stale mentions.
In Orca, send a worker its next brief only after its `worker_done`, in full: a send to a busy worker returns only a `messageId` and is usually never acted on, and each follow-up starts a fresh session.
Within about 2 minutes of a dispatch, confirm once with `worker-read` that the worker has started on it ([`coordinator.md`](coordinator.md#orca-orchestration-flags)); a dsh dispatch also copies the brief into its workspace and sends its start message at once, since one dsh worker sat at its splash screen for 30 minutes ([`coordinator.md`](coordinator.md#dispatching-a-dsh-worker)).
On Orca's "worker stopped without reporting" escalation, when its "Last output" names a running build, render or Monitor of a Claude worker, log it in `run-state.md` and leave the worker, without `worker-read`: the command's exit re-invokes it.
Otherwise (a dsh worker included) read the worker with `worker-read`: a command still running means wait; an open PR with the worker idle means treat it as done and start the review; otherwise re-dispatch.
The coordinator edits no PR, and sends every fix, text or code, back to a worker, since a fix needs the same re-review.

The worker does steps 2 to 4, filing its follow-up issues; the coordinator does steps 1, 5 and 6 and step 4's claim release and label swap, from the worker's report.

1. **Claim it** before any branch commit ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions), "Claim an issue"): re-read its labels, swap `status:ready-for-agent` for `status:in-progress`, comment `Claimed by branch <branch>.`, and re-read the claim comments to verify yours is earliest, by first line, not whole comments (cloud: `gh api 'repos/{owner}/{repo}/issues/<n>/comments?per_page=100' --jq '.[] | select(.body | test("^(Claimed by (branch|planner)|Released claim:|Lost claim to)")) | [.created_at, (.body | split("\n")[0])] | @tsv'`).
2. **Branch** from an up-to-date `origin/main` (`git fetch origin`, then `git switch -c <branch> origin/main`).
3. **3-round cap:** Spend at most **3 hypothesis rounds** (or 3 failures for the same gate/CI/approach reason) on an issue.
   Do not chain a new heuristic onto a failed sweep ([`improving-render-parity`](../improving-render-parity/SKILL.md)).

   A prototype stops once measured: no PR polish, review or docs until one is chosen; run parallel prototypes only for decisions that are hard to undo.
4. **Ship the clean slice, file the rest:** If a self-contained, evidence-backed subset passes `mise run check` — and, for a rendering change, satisfies the [`loop-rules.md`](../improving-render-parity/loop-rules.md#adoption-rule) adoption rule (`mise run parity` exits `0` even on drift, so read the winner line of `mise run sweep -- --var ... --track <track>` or `mise run judge -- <base> <cand> --track <track>`) — while the rest of the issue is blocked or exposes entangled bugs:
   - Commit the blocked prototype on its own branch from `origin/main` (`proto/<issue>-<slug>`, with no `DBG_*` switch and the hooks passing) and push it, then revert the blocked changes so only the clean subset remains, and complete the required artifacts for the kept subset (including `research/parity/expected/<class>.toml`, the work folder journal entry, and [`pr-evidence.md`](../improving-render-parity/pr-evidence.md) for rendering changes).
   - Verify `mise run check`, and ship the clean subset as a PR (`Fixes #N` when all remaining work is split into standalone follow-up issues, else `Part of #N`).
   - The worker files `status:needs-triage` follow-up issues for the blocked pieces and reports their numbers, naming each prototype's branch and commit ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#organizing-issues), "A prototype lives on a branch"; [`pr-and-filing.md`](pr-and-filing.md#filing-issues-and-powershell-safety)).
     If `#N` stays open (`Part of #N`), comment `Released claim: <why>.` on `#N` and swap `status:in-progress` for `status:ready-for-human` (or back to `status:ready-for-agent` with a `blocked-by` edge to the follow-up issue) so `#N` is not left in `status:in-progress`.
5. **Needs another environment:** In a cloud session, an item that needs a resource the session lacks is handed on as [`cloud.md` § Handing work to local-windows](../working-in-an-environment/cloud.md#handing-work-to-local-windows) says: `Released claim: <why>.` on an unmerged issue, `status:in-progress` swapped for `status:ready-for-agent` or `status:needs-triage` beside `env:local-only`, and the run moves on.
6. **Stuck or needs a human:** If 3 rounds finish with no shippable slice, or a non-obvious design/visual choice blocks progress, comment on the issue or PR with `Released claim: <why>.` (when releasing an unmerged issue), what you tried, the evidence, and the exact decision or resource needed; replace `status:in-progress` / `status:ready-for-agent` with `status:ready-for-human` (or `status:needs-info` when what blocks is a fact only a person knows); and move on.
   When the worker's report or a reviewer's finding shows a lack of capability or context, the coordinator also moves `model-tier:` up one (`light` to `medium`, `medium` to `heavy`; a swap that removes the old label) or adds `model-context:wide` in the same pass, with `gh issue edit` (REST in cloud), and says so in its `Released claim:` comment; it takes effect when the issue next becomes `status:ready-for-agent`.

## Planning an issue (`status:needs-plan`)

A `plan` line in `mise run queue` goes to a planner (an available `heavy` model from [`models.md`](../../../docs/harness/models.md), briefed from [`worker-brief.md`](worker-brief.md#planner-brief)).
The coordinator does step 1 and any claim release (`Released claim: <why>.`, swapping `status:in-progress` back to `status:needs-plan`, plus `env:local-only` when a cloud planner hits a `local-windows` resource) if the planner stops without posting a plan; the planner does steps 2 to 4:

1. **Claim it** before investigating: swap `status:needs-plan` for `status:in-progress`, comment `Claimed by planner <id>.`, and verify yours is earliest using step 1's claim check above.
2. **Investigate read-only:** make no branch, code edits or PR; check every `file:line` and figure you cite against the repository ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions), "Cite what you read").
3. **Write `## Tentative plan` comment:** write the comment to `build/scratch/plan-<N>.md` stating files in scope, concrete approach, testable acceptance criteria, verification commands, any missing `area:` or `type:` updates, the `model-tier:` (exactly one) and any `model-context:` labels it recommends, and open decisions with a recommended option.
   Add or fix missing `area:`/`type:` labels when needed, and never overwrite an existing `priority:` label.
   Apply the `model-tier:` and `model-context:` labels it names when posting, swapping an existing tier rather than adding a second ([`triage-labels.md`](../../../docs/agents/triage-labels.md#model-roles)).
4. **Route by clarity and post:**
   - **Decisions, ambiguity, ADR question, visual call or multi-PR split:** single-pass planner posts the comment with `--body-file` (or REST in cloud per [`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions)) and swaps `status:in-progress` for `status:plan-review`.
   - **Purely mechanical and unambiguous within existing specs and single-PR scope:** have a fresh-context subagent review the tentative plan comment against the codebase first, apply any fix, post the comment with `--body-file` (or REST in cloud per [`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions)), and swap `status:in-progress` for `status:ready-for-agent`.

## Measuring

Cost comparison is optional: join `ccusage` blocks and sessions to roles.
The quality guard is that no merged PR needs a fix or revert afterwards.

## Never

- Push or force-push to `main`, use `--no-verify`, or weaken/skip a check.
- Commit anything under `corpus/` or `DBG_*` switches.
- Merge, or arm auto-merge, with a red check or an unresolved review thread, or close an issue whose fix has not merged.

## Shutdown

1. In a cloud session, a Shutdown at the context limit first waits until no worker is in flight, or until every in-flight item has a pushed branch (a rule 5 item only after its review and push), and releases any other item (`Released claim: <why>.`, `status:in-progress` back to its prior state (`status:ready-for-agent` or `status:needs-plan`)), listing it under **Needs you**, since its unpushed commit and body file are lost with the container.
   Then confirm no subagent or background task is still running (in a cloud session, except a worker whose item has a pushed branch; on local-windows, wait until none is, because step 2 reaps worktrees), and run `mise run queue` once for the PRs you armed.
   One no longer listed has merged or been closed (`gh pr view <n> --json state` says which: **Merged**, or **Needs you**); `armed, checks pending` goes under **Opened** as "auto-merge armed"; and any other PR you armed that is still listed goes under **Needs you**.
   Take each item's last state from its newest line in `build/scratch/run-state.md`.
2. When the run merged render PRs that left `lavapipe` behind, catch it up on the canonical lavapipe: `mise run parity -- --software-only`, then `mise run parity-repin -- --class lavapipe`, in a cloud session or on local-windows through the WSL lavapipe ([`render-on-lavapipe.md` § 5](../../../docs/howto/render-on-lavapipe.md#5-render-the-canonical-lavapipe-under-wsl)), as its own `chore(parity): repin expected scores` PR.
   Never repin `gpu`: the class agreement batch writes it ([ADR 0055](../../../docs/adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md)).
   The [error readout](../improving-render-parity/error-readout.md) is the coordinator's as well, since it needs subagents a worker does not dispatch, against the committed baseline in `research/parity/readouts/` ([#901](https://github.com/neilsh/stunt-reel/issues/901)).
   Run it at a Shutdown where `mise run queue` prints `agreement batch due` and the run merged render PRs or the standing `Error readout due` issue is open; once it is graded, open a PR that refreshes the baseline by step 7 of that procedure.
   A Shutdown that merged render PRs while no batch is due records them on the standing issue `Error readout due: merged render PRs since the last baseline` (`status:ready-for-agent`, `env:local-only`) instead: search for it first, file it when it is missing, comment on it when it exists, and the baseline-refresh PR closes it.
   A render PR body says its readout waits for the agreement batch.
3. On local-windows, close the terminals of each merged item's workspace as in [Disk space](#clock-and-disk-space) step 1, then run `mise run reap -- --yes --reviews` from the primary checkout; it retires the run's merged Orca workspaces too, and its review worktrees idle six hours.
4. End with a summary built from each item's newest line in `build/scratch/run-state.md`, the file's **Filed** list and its **Queue** section's skipped reasons, grouped as: **Merged**, **Planned** (moved to `status:ready-for-agent`; items moved to `status:plan-review` go under **Needs you**), **Draft / WIP**, **Opened**, **Filed** (with labels), **Needs you** (item, reason, decision, and `PR #n: N alternatives` for each item whose newest line records an alternatives count), and **Skipped**, plus the environment, start/end free disk space on local-windows, and any environment friction.
