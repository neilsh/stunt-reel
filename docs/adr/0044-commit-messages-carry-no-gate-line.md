# Commit messages carry no gate line

## Status

accepted 2026-11-09. Supersedes in part [ADR 0026](0026-commit-hooks-run-the-gates-own-tasks.md)
(the commit-msg hook's gate-line check) and [ADR 0038](0038-the-local-gate-runs-what-a-change-touches.md)
(the scoped gate line). Keeps the commit-msg hook's Conventional Commit subject check and CI's
range check of a pull request's commits. Amended 2026-11-12: the hook also requires a
`Fresh-review:` trailer on a commit that changes a work spec or plan (below). Amended 2026-11-15: the
range check is replaced by a pull-request title check (below).

## Context

Since #223, the commit-msg hook required a commit body to close with a gate line naming the
gate's outcome, such as `mise run check passes.`; #259 then had the hook hold each `passes`
claim to the tree a passing run recorded under `target/gate/`. A rebase gives every commit a new tree, so each
rebased commit failed the hook until `mise run regate` (#327) re-ran the gate on every commit and
rewrote its message. That tool drew two Major review findings, and a 2026-11-09 retro of agent
sessions counted the hook's refusals and the re-gating among the costliest process steps.

The line proves nothing CI does not. The `main` ruleset requires `quality` (the full gate on
Ubuntu), `windows-smoke`, `msrv` and `deny` on every pull request, and CI ran the hook's check
on a range of commits by wording alone, since it never saw a local run.

## Decision

- **A commit message needs a Conventional Commit subject and, when a reviewer would ask why, a
  body that says why.** It carries no gate line.
- **The commit-msg hook checks the subject**
  ([`check_commit_msg.py`](../../python/scripts/check_commit_msg.py)); CI's range check stays.
  Since 2026-11-12 the hook also requires a `Fresh-review: <what it read>` trailer on a commit
  that changes a work `spec.md` or `plan.md` (`work/<month>/<folder>/`), the record of the
  fresh review AGENTS.md § Committing rule 5 asks for there; the range check does not look for it.
- **`gate.py` neither records the tree it tested nor prints a gate line.** `gate_record.py`,
  `regate.py`, the `regate` task and its how-to are deleted.

## Considered Options

- **Keep the line, drop only the tree check.** Rejected: the line then states an unchecked claim,
  and still costs a rewrite after each rebase to stay true.
- **Keep both and make re-gating cheaper.** Rejected: a rebase still re-runs the gate per commit,
  for a proof the required checks already give.

## Consequences

- Run `mise run check` before committing, as AGENTS.md's Committing rules still ask; nothing in
  the message records that you did. A missed local failure surfaces as a red required check.
- A rebase needs no follow-up beyond the gate on the new tip.
- Commits made before this change keep their gate lines; nothing reads them.

## Amendment 2026-11-15: the range check is replaced by a PR-title check

The Decision's "CI's range check stays" no longer holds. CI's `PR title` workflow checks the pull
request's title with the hook's subject rule, since the title is the squash commit's subject on
`main`; the range of commits is not checked in CI, and the local hook remains the only check of a
commit's subject and of the `Fresh-review:` trailer. See the matching
[amendment to ADR 0026](0026-commit-hooks-run-the-gates-own-tasks.md#amendment-2026-11-15-ci-checks-the-pull-request-title)
(#577's spec, section 2).
