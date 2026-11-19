# Implementer brief

Part of the [`running-unattended`](SKILL.md) skill.

Every implementer brief, first task or review fix, is self-contained: a follow-up starts a fresh session, and the worker has only the brief.
Give the issue or PR number, the branch and base and, for a fix, the review comment's URL.
The coordinator reads no issue body, so the worker reads the issue or PR and its comments itself (the triage comment's Agent Brief holds the files in scope and the acceptance criteria) and the brief does not restate them.
State the stop as an absolute UTC time (`stop at 11:45 UTC`), never a duration; the worker runs `date -u` and quotes its output before deciding it is out of time.
Then copy in this checklist:

1. A dsh worker reads [`docs/harness-setup.md` § DSH](../../../docs/harness-setup.md#dsh) first; in a cloud session (`CLAUDE_CODE_REMOTE=true`), every worker first reads [`cloud.md`](../working-in-an-environment/cloud.md).
2. Iterate with `mise run fix`, `mise run test-py -- <file>`, `mise run check-py` (the gate's Python half: lint, types and tests) and `mise run check-rust` (its Rust half; run Rust checks through it); after editing `research/` or `docs/`, run `mise run check-docs` before the full gate, which catches an evergreen page linking into `work/`; run the full `mise run check` once, at the end.
3. After moving, renaming or splitting a file, section or symbol, `rg` every old name (basename, path, symbol, cited section or item number) from the repository root, agent guidance in `.agents/` and `.claude/` included, and fix each mention in prose and comments, not only links.
   Never rewrite files under `work/`: retarget only the links there, with `mise run move-docs` for doc moves.
4. A fix to reviewed code adds a test for the case the previous version already handled, and reruns step 3's sweep, so the fix cannot open a new finding.
5. When the diff changes a path [`AGENTS.md` § Committing](../../../AGENTS.md#committing) rule 5 names, scan it before committing for that rule's over-broad words and for tier tags, and recompute every quoted figure from its source.
   A work `spec.md` or `plan.md` gets its fresh review of the uncommitted diff before you commit, in your own worktree, by a subagent you dispatch there, and the commit carries the `Fresh-review:` trailer ([`development.md`](../../../docs/development.md#commit-messages)).
6. The PR body says `Fixes #N` only when the diff meets every acceptance item of the issue or [`loop-and-bounds.md`](loop-and-bounds.md) item 4 applies (the rest filed as follow-up issues); otherwise it says `Part of #N` and lists what remains.
   The PR title ends with the issue it serves, as in `fix(site): ... (#589)`, also when the PR only partly fixes it; the CI title check does not enforce the suffix.
7. Report in about 10 lines, because the coordinator keeps the report in its context: what changed, the gate's result, each acceptance item met or not, `Fixes` or `Part of`, whether the item needs an ADR, a human choice or another machine, and anything left undone.
   An Orca worker sends it with `orca orchestration send` ([`coordinator.md`](coordinator.md#orca-orchestration-flags), § DSH), a subagent in its final reply.
   On a PR whose diff touches a rule 5 path (step 5), commit but do not push, for a first commit and for every later fix, rebase or merge: the coordinator pushes after the fresh review and opens the PR, so also write the PR body (step 6) to `build/scratch/<name>.md` and report the commit SHA, the PR title (the commit subject for a single commit, ending `(#N)`) and the body file's absolute path, since the coordinator opens the PR from another checkout ([`pr-and-filing.md`](pr-and-filing.md) step 1).
   Otherwise push before you report.

## Child-session brief

A cloud child session (`create_session`) gets the brief above and these changes:

1. Read [`cloud.md`](../working-in-an-environment/cloud.md) first, and work on `outcome_branch`.
2. Self-review with a `reviewer` subagent ([`pr-and-filing.md`](pr-and-filing.md) step 2), push, and open the PR, even on a rule 5 path: this replaces step 7's "do not push" paragraph.
   Post the reviewer's verdict comment once the PR is open.
3. Report the PR number, head SHA and that comment's URL with `send_message`; the coordinator alone arms or merges.
