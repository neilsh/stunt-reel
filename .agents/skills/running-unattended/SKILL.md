---
name: running-unattended
description: "Use when running unattended or overnight to drain open PRs, status:ready-for-agent and status:needs-plan issues, or when working a queue without a human present."
---

# Running unattended

Drains open PRs, `status:ready-for-agent` and `status:needs-plan` issues in priority queue order without blocking on a human, with about two workers at once.
A **coordinator** dispatches workers, tracks state, checks the merge bar and arms merges; **workers** plan, implement and review.
A single-PR item finishes implementation, review and thread triage during the run ([`AGENTS.md` § Working economically](../../../AGENTS.md#working-economically) rule 3 does not apply; the coordinator restarts at about 100k tokens, [`coordinator.md`](coordinator.md)).
A `status:needs-plan` item posts a tentative plan (`status:plan-review` or `status:ready-for-agent`) without coding; an item needing a multi-PR spec or human decision records its handoff, swaps to `status:ready-for-human` or `status:plan-review`, and moves on.

It runs in either environment of [`working-in-an-environment`](../working-in-an-environment/SKILL.md): read that skill and your environment's file before step 1.
Orca, dsh, Antigravity, PowerShell and the disk checks are `local-windows` resources; a cloud session follows **Cloud** below and `cloud.md` wherever this skill names one.

## Concurrency and models

- **Coordinator:** the current session's model; reads no diffs or issue bodies, keeps `build/scratch/run-state.md`, restarts instead of compacting, checks CodeRabbit once, and dispatches per [`coordinator.md`](coordinator.md) (T3 Code below).
- **Workers by labels, then fit:** an issue's `model-tier:` and `model-context:` labels pick the worker per the [`harness.md`](../../../docs/harness.md#policy-any-agent) table, going up a tier on evidence; with none or two tiers: dsh first where the spec is clear, Sonnet for other well-specified work, Opus for research, diagnosis, design, hypothesis rounds; planning goes to Opus.
  Prefix-cache hit rate is not the test.
- **About two at once:** pair two writers only when their `area:` sets are non-empty and disjoint ([`loop-and-bounds.md`](loop-and-bounds.md#implementing-an-issue-and-bounding-rounds)), each writer in its own worktree; a read-only planner has no file conflict with a writer on another issue, and a dependent item waits for or stacks on its parent.
  Never use `/swarm`.
- **Reviews:** the Sonnet [`reviewer`](../../../.claude/agents/reviewer.md) agent.
  First review of a Sonnet-, dsh- or Haiku-`medium`-built PR goes to Opus or Antigravity: a general-purpose subagent with `model: opus` and `Opus` as `<Reviewer>`, not a `reviewer` override; the `light` review and escalation: [`harness.md`](../../../docs/harness.md#policy-any-agent).
  Re-reviews prefer Antigravity when Gemini quota allows, covering changes since the last review; a wording-only fix gets none, except on a rule 5 PR ([`pr-and-filing.md`](pr-and-filing.md) step 2).
- **Cloud:** subagents for planning, reviews and edits, at most about two Rust builds at once ([`cloud-sessions.md`](../../../docs/cloud-sessions.md#container-limits)); child sessions (`create_session`) for builds and renders, briefed per [`worker-brief.md`](worker-brief.md#child-session-brief).
  Give each writer `isolation: "worktree"`; if that fails, run one at a time.
  Never stack: start a dependent item once its parent merges.
- **T3 Code:** a coordinator in a T3 thread (`T3CODE_THREAD_ID` set) dispatches per [`t3.md`](t3.md) instead of Orca.

## Workflow

Read [`loop-and-bounds.md`](loop-and-bounds.md) and [`pr-and-filing.md`](pr-and-filing.md) before starting.
Copy this checklist to your task list:

```
- [ ] 1. Check clock cutoff; on local-windows, also free disk space with reap/clean (loop-and-bounds.md)
- [ ] 2. Refresh the queue with mise run queue, and append transitions to run-state.md (loop-and-bounds.md, coordinator.md)
- [ ] 3. Claim up to two disjoint-area items (implementers in worktrees, planners read-only), cap at 3 hypothesis rounds, ship any clean slice, file blocked pieces as status:needs-triage (loop-and-bounds.md)
- [ ] 4. Review PRs at HEAD (reviewer by default; first review per harness.md; re-review to Antigravity when quota allows, else reviewer), triage CI and threads, arm squash auto-merge (pr-and-filing.md)
- [ ] 5. File out-of-scope or split issues via build/scratch/*.md and --body-file (pr-and-filing.md)
- [ ] 6. At empty queue, deadline, or (local-windows) < 5 GB free, run Shutdown and print the report (loop-and-bounds.md)
```
