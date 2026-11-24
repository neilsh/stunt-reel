# Implementer brief

Part of the [`running-unattended`](SKILL.md) skill.

Every implementer brief, first task or review fix, is self-contained: a follow-up starts a fresh session, and the worker has only the brief.
Give the issue or PR number, the branch and base and, for a fix, the review comment's URL.
The coordinator reads no issue body, so the worker reads the issue or PR and its comments itself (the triage comment's Agent Brief or any `## Tentative plan` comment holds the files in scope and the acceptance criteria) and the brief does not restate them.
State the stop as an absolute UTC time (`stop at 11:45 UTC`), never a duration; the worker runs `mise run now` (the same command in Bash and PowerShell) and quotes its output before deciding it is out of time.
Then copy in this checklist:

1. A dsh worker reads [`docs/harness-setup.md` § DSH](../../../docs/harness-setup.md#dsh) first; in a cloud session (`CLAUDE_CODE_REMOTE=true`), every worker first reads [`cloud.md`](../working-in-an-environment/cloud.md).
2. Iterate with `mise run fix`, `mise run test-py -- <file>`, `mise run check-py` (the gate's Python half: lint, types and tests) and `mise run check-rust` (its Rust half; run Rust checks through it); after editing `research/` or `docs/`, run `mise run check-docs` before the full gate, which catches an evergreen page linking into `work/`; run the full `mise run check` once, at the end.
   Keep the turn open while a build, render or sweep runs: wait inside the turn with a loop that polls its output or exit (in Claude Code, Monitor with an until-loop), since the harness blocks a bare `sleep N`, and a dsh worker whose turn ends mid-run stalls the item until the coordinator notices (a Claude worker is re-invoked when the run ends).
3. After moving, renaming or splitting a file, section or symbol, `rg` every old name (basename, path, symbol, cited section or item number) from the repository root, agent guidance in `.agents/` and `.claude/` included, and fix each mention in prose and comments, not only links.
   Never rewrite files under `work/`: retarget only the links there, with `mise run move-docs` for doc moves.
   A `git mv` commit never edits a moved file, so rename detection carries other branches' edits through a rebase, but it also changes what the hooks need to pass: every link to an old path (retargeted ADR links included, per [`pr-and-filing.md`](pr-and-filing.md) step 5) and every module declaration outside the moved files, such as `main.rs`.
   A module a moved `mod.rs` declares moves with it in that commit.
4. A fix to reviewed code adds a test for the case the previous version already handled, and reruns step 3's sweep, so the fix cannot open a new finding.
   A review finding names one instance of a defect class: for each, `rg` its phrase or pattern across the diff, the PR body, the journal and the work README's `outcome`, fix every sibling, and list the siblings in your report.
   Reread each sentence you reword against its evidence, since a rewording can open a finding of its own.
5. When the diff changes a path [`AGENTS.md` § Committing](../../../AGENTS.md#committing) rule 5 names, run `mise run claim-words -- [<base>]` before the rule 5 commit: it lists each added line under those paths that holds one of the rule's over-broad words, with the line and its nearest evidence-tier tag, and each hit is a line to narrow or justify against its evidence.
   Also scan the diff for tier tags, and recompute every quoted figure from its source.
   A work `spec.md` or `plan.md` gets its fresh review of the uncommitted diff before you commit, in your own worktree, by a subagent you dispatch there, and the commit carries the `Fresh-review:` trailer ([`development.md`](../../../docs/development.md#commit-messages)).
6. The PR body says `Fixes #N` only when the diff meets every acceptance item of the issue or [`loop-and-bounds.md`](loop-and-bounds.md) item 4 applies (the rest filed as follow-up issues); otherwise it says `Part of #N` and lists what remains.
   The PR title ends with the issue it serves, as in `fix(site): ... (#589)`, also when the PR only partly fixes it; the CI title check does not enforce the suffix.
7. Build third-party source only when this brief names the build, under `/tmp`, committing nothing from it; a build the permission prompt refuses is recorded on the issue, which gets `status:ready-for-human` naming the build, and you move on ([`cloud-sessions.md`](../../../docs/cloud-sessions.md#building-mesa-in-a-cloud-session)).
8. Report in about 10 lines, because the coordinator keeps the report in its context: what changed, the gate's result, each acceptance item met or not, `Fixes` or `Part of`, whether the item needs an ADR, a human choice or another machine, and anything left undone.
   An Orca worker sends it with `orca orchestration send` ([`coordinator.md`](coordinator.md#orca-orchestration-flags), § DSH), a subagent or T3 Code child in its final reply.
   On a PR whose diff touches a rule 5 path (step 5), commit but do not push, for a first commit and for every later fix, rebase or merge: the coordinator pushes after the fresh review and opens the PR, so also write the PR body (step 6) to `build/scratch/<name>.md` and report the commit SHA, the PR title (the commit subject for a single commit, ending `(#N)`) and the body file's absolute path, since the coordinator opens the PR from another checkout ([`pr-and-filing.md`](pr-and-filing.md) step 1).
   At a run's deadline or disk stop, the `chore: wip` push is the exception: push it unreviewed and open or update the **draft** PR, whose handoff comment starts `unreviewed: rule 5 review pending` ([`loop-and-bounds.md`](loop-and-bounds.md#clock-and-disk-space)).
   Otherwise push before you report.

## Child-session brief

A cloud child session (`create_session`) gets the brief above and these changes:

1. Read [`cloud.md`](../working-in-an-environment/cloud.md) first, and work on `outcome_branch`.
2. Self-review with a `reviewer` subagent ([`pr-and-filing.md`](pr-and-filing.md) step 2), push, and open the PR, even on a rule 5 path: this replaces step 8's "do not push" paragraph.
   Post the reviewer's verdict comment once the PR is open.
3. Report the PR number, head SHA and that comment's URL with `send_message`; the coordinator alone arms or merges.

## Planner brief

A `status:needs-plan` dispatch runs read-only on Opus or frontier with no branch or PR:

1. Read the issue body and comments (the coordinator has already claimed it with `status:in-progress` and `Claimed by planner <id>.`).
2. Investigate read-only with no branch, code edits or PR, and verify every `file:line` and figure against the checkout ("Cite what you read", [`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions)).
3. Write `build/scratch/plan-<N>.md` starting with `## Tentative plan`: files in scope, concrete approach, acceptance criteria, verification commands, recommended `area:`/`type:` updates, and open decisions with recommendations.
   Add or fix missing `area:`/`type:` labels if needed; never overwrite `priority:`.
4. If a cloud session lacks a `local-windows` resource needed to plan, post nothing and report the missing resource so the coordinator releases the claim with `env:local-only`.
   If any design/ADR/visual decision, ambiguity or multi-PR split remains, post the comment (`--body-file` locally, or REST in cloud per [`issue-tracker.md`](../../../docs/agents/issue-tracker.md#conventions)) and swap `status:in-progress` for `status:plan-review`.
   Otherwise have a fresh-context subagent review the tentative plan comment against the codebase first, revise it, post it (`--body-file` or REST), and swap `status:in-progress` for `status:ready-for-agent`.
5. Report in about 5 lines: the new state (`status:plan-review`, `status:ready-for-agent`, or missing-resource release), the comment URL, any `area:`/`type:` labels applied, and any key open decision.
