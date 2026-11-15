---
name: running-unattended
description: "Use when running unattended or overnight to drain open PRs and ready-for-agent issues, or when a session works through a queue without a human present."
---

# Running unattended

Drains open PRs and `ready-for-agent` issues in queue order without blocking on a human, with about two implementers at once. For single-PR items this loop completes implementation, fresh-context review, and PR thread triage in one session, however long it grows ([`AGENTS.md` § Working economically](../../../AGENTS.md#working-economically) rule 3 does not apply); an item needing a multi-PR spec or a human decision records its handoff, swaps to `ready-for-human`, and moves on.

## Concurrency and models

- **Implementers by fit:** dsh first where the spec is clear and the task needs no judgment over evidence; Sonnet for other well-specified implementation; Opus for research, diagnosis, design, and items expected to need rounds of hypotheses. Prefix-cache hit rate is not the test.
- **About two at once:** run two implementers in parallel, each writer in its own worktree; the Lead integrates in dependency order. Never use `/swarm`.
- **First review:** a PR built by Sonnet or dsh gets its first review from Opus or Antigravity, requested explicitly; on #160 a Sonnet review missed four bugs.
- **Re-reviews:** the Sonnet [`reviewer`](../../../.claude/agents/reviewer.md) agent, or Antigravity when Gemini quota allows; they cover only what changed since the last reviewed commit and run once, after every finding is fixed. A wording-only fix gets no re-review: reply to the finding with the new text.
- **Worker lifetime:** a Claude implementer ends when its PR opens, or earlier past about 150k tokens of context; a fresh worker makes the fixes from the PR and the review comment. dsh workers may keep their session.
- **Prototypes:** stop once measured — no PR polish, review or docs until one is chosen; run parallel prototypes only for decisions hard to undo.
- **Before review:** the implementer scans its own diff for the `AGENTS.md` § 3 rule 5 words and checks every quoted figure against its source.
- **Cost (optional):** compare with `ccusage` blocks and sessions joined to roles; the guard is that no merged PR needs a fix or revert afterwards.

## Workflow

Read [`loop-and-bounds.md`](loop-and-bounds.md) and [`pr-and-filing.md`](pr-and-filing.md) before starting. Copy this checklist to your task list:

```
- [ ] 1. Check clock cutoff and free disk space; tidy with reap/clean (loop-and-bounds.md)
- [ ] 2. Build or refresh the queue with mise run queue (loop-and-bounds.md)
- [ ] 3. Claim up to two items (one per writer worktree), cap at 3 hypothesis rounds each, and ship any clean gate-passing slice while filing blocked pieces as needs-triage (loop-and-bounds.md)
- [ ] 4. Run the first review (Opus or Antigravity) and re-reviews (Sonnet) at HEAD, triage CI and CodeRabbit threads, and arm squash auto-merge under the merge bar (pr-and-filing.md)
- [ ] 5. File out-of-scope or split issues via build/scratch/*.md and --body-file (pr-and-filing.md)
- [ ] 6. At empty queue, deadline, or < 5 GB free, run Shutdown and print the report (loop-and-bounds.md)
```
