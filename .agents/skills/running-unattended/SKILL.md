---
name: running-unattended
description: "Use when running unattended or overnight to drain open PRs and ready-for-agent issues, or when a session works through a queue without a human present."
---

# Running unattended

Drains open PRs and `ready-for-agent` issues in queue order without blocking on a human, with about two implementers at once. For single-PR items this loop completes implementation, fresh-context review, and PR thread triage in one session, however long it grows ([`AGENTS.md` § Working economically](../../../AGENTS.md#working-economically) rule 3 does not apply); an item needing a multi-PR spec or a human decision records its handoff, swaps to `ready-for-human`, and moves on.

It runs in either environment of [`working-in-an-environment`](../working-in-an-environment/SKILL.md): read that skill and your environment's file before step 1. Orca, dsh, Antigravity, PowerShell and the disk checks are `local-windows` resources; a cloud session follows the **Cloud** bullet below and `cloud.md` wherever this skill names one.

## Concurrency and models

- **Implementers by fit:** dsh first where the spec is clear and the task needs no judgment over evidence; Sonnet for other well-specified implementation; Opus for research, diagnosis, design, and items expected to need rounds of hypotheses. Prefix-cache hit rate is not the test.
- **About two at once:** run two items in parallel only when they touch different files, each writer in its own worktree; if one depends on the other, start it after its parent merges, or stack it and arm it after the parent merges. Never use `/swarm`.
- **Reviews:** the Sonnet [`reviewer`](../../../.claude/agents/reviewer.md) agent by default, for first reviews and re-reviews. The first review of a Sonnet- or dsh-built PR goes to Opus or Antigravity instead, because on #160 a Sonnet review missed four bugs: request it as a general-purpose subagent with `model: opus` and `Opus` as `<Reviewer>` in the brief, or as an Antigravity worker, not as a `reviewer` model override, which names `Sonnet`. A re-review prefers Antigravity when Gemini quota allows, otherwise the `reviewer` agent. A re-review covers only what changed since the last reviewed commit, runs once after every finding is fixed, and a wording-only fix gets none, except on a rule 5 path.
- **Cloud:** implementers and reviewers are Claude subagents: Sonnet implementers by default, Opus for research, diagnosis and design and for the first review of a Sonnet-built PR, and the `reviewer` agent for re-reviews. Give each writer `isolation: "worktree"`, and run one at a time if that isolation fails there. Every brief starts by telling the subagent to read `cloud.md`. Never stack: start a dependent item once its parent merges.
- **Elsewhere:** worker lifetime, prototype bounds, the pre-review diff scan and optional `ccusage` measuring are in [`loop-and-bounds.md`](loop-and-bounds.md) and [`pr-and-filing.md`](pr-and-filing.md).

## Workflow

Read [`loop-and-bounds.md`](loop-and-bounds.md) and [`pr-and-filing.md`](pr-and-filing.md) before starting. Copy this checklist to your task list:

```
- [ ] 1. Check clock cutoff; on local-windows, also free disk space, tidying with reap/clean (loop-and-bounds.md)
- [ ] 2. Build or refresh the queue with mise run queue (loop-and-bounds.md)
- [ ] 3. Claim up to two items (one per writer worktree), cap at 3 hypothesis rounds each, and ship any clean gate-passing slice while filing blocked pieces as needs-triage (loop-and-bounds.md)
- [ ] 4. Run the reviews at HEAD (the `reviewer` by default; a Sonnet/dsh-built first review goes to Opus or Antigravity; a re-review to Antigravity when Gemini quota allows, otherwise the `reviewer`), triage CI and any review threads, and arm squash auto-merge under the merge bar (pr-and-filing.md)
- [ ] 5. File out-of-scope or split issues via build/scratch/*.md and --body-file (pr-and-filing.md)
- [ ] 6. At empty queue, deadline, or (local-windows) < 5 GB free, run Shutdown and print the report (loop-and-bounds.md)
```
