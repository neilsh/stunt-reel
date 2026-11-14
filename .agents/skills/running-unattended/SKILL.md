---
name: running-unattended
description: "Use when running unattended or overnight to drain open PRs and ready-for-agent issues, or when a session works through a queue without a human present."
---

# Running unattended

Drains open PRs and `ready-for-agent` issues one item at a time without blocking on a human. For single-PR items this loop completes implementation, fresh-context review, and PR thread triage in one session, however long it grows ([`AGENTS.md` § Working economically](../../../AGENTS.md#working-economically) rule 3 does not apply); an item needing a multi-PR spec or a human decision records its handoff, swaps to `ready-for-human`, and moves on.

## Concurrency and models

- **One active item at a time:** Take each PR or issue through review, thread triage and CodeRabbit (or its timeout) until its squash auto-merge is armed ([`pr-and-filing.md`](pr-and-filing.md) step 5), then start the next item; GitHub merges the armed PR when CI passes. Never use `/swarm`.
- **Subagent models:** Keep subagents in the session's provider family and never escalate above the session model ([`docs/harness.md`](../../../docs/harness.md#policy-any-agent)):
  - Leave `Model` unset (`inherit` — `Orchestrator (Argon)` on Antigravity, `Opus` on Claude Code) for diagnosis, design, implementation, and fresh-context code/spec review.
  - Use the `fast` tier in the same provider family (`Gemini 4 Hydrogen` / `flash` on Antigravity, `Haiku` on Claude Code) only for bounded mechanical work where the brief fully specifies the task and the result is easy to check.

## Workflow

Read [`loop-and-bounds.md`](loop-and-bounds.md) and [`pr-and-filing.md`](pr-and-filing.md) before starting. Copy this checklist to your task list:

```
- [ ] 1. Check clock cutoff and free disk space; tidy with reap/clean (loop-and-bounds.md)
- [ ] 2. Build or refresh the queue with mise run queue (loop-and-bounds.md)
- [ ] 3. Claim one item, cap at 3 hypothesis rounds, and ship any clean gate-passing slice while filing blocked pieces as needs-triage (loop-and-bounds.md)
- [ ] 4. Run fresh-context inherit review, triage CI and CodeRabbit threads, and arm squash auto-merge under the merge bar (pr-and-filing.md)
- [ ] 5. File out-of-scope or split issues via build/scratch/*.md and --body-file (pr-and-filing.md)
- [ ] 6. At empty queue, deadline, or < 5 GB free, run Shutdown and print the report (loop-and-bounds.md)
```
