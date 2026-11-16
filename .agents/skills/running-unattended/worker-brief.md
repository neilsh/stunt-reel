# Implementer brief

Part of the [`running-unattended`](SKILL.md) skill.

Every implementer brief, first task or review fix, is self-contained: a follow-up starts a fresh session, and the worker has only the brief. Give the issue or PR number, the branch and base, the files in scope, the acceptance criteria and, for a fix, the review comment's URL. Then copy in this checklist:

1. A dsh worker reads [`docs/harness-setup.md` § DSH](../../../docs/harness-setup.md#dsh) first; in a cloud session (`CLAUDE_CODE_REMOTE=true`), every worker first reads [`cloud.md`](../working-in-an-environment/cloud.md).
2. Iterate with `mise run fix`, `mise run test-py -- <file>`, `mise run check-py` (the gate's Python half: lint, types and tests) and `mise run check-rust` (its Rust half; run Rust checks through it); after editing `research/` or `docs/`, run `mise run check-docs` before the full gate, which catches an evergreen page linking into `work/`; run the full `mise run check` once, at the end.
3. After moving, renaming or splitting a file, section or symbol, `rg` every old name (basename, path, symbol, cited section or item number) from the repository root, agent guidance in `.agents/` and `.claude/` included, and fix each mention in prose and comments, not only links. Never rewrite files under `work/`: retarget only the links there, with `mise run move-docs` for doc moves.
4. A fix to reviewed code adds a test for the case the previous version already handled, and reruns step 3's sweep, so the fix cannot open a new finding.
5. When the diff changes a path [`AGENTS.md` § Committing](../../../AGENTS.md#committing) rule 5 names, scan it before pushing for that rule's over-broad words and for tier tags, and recompute every quoted figure from its source.
6. The PR body says `Fixes #N` only when the diff meets every acceptance item of the issue or [`loop-and-bounds.md`](loop-and-bounds.md) item 4 applies (the rest filed as follow-up issues); otherwise it says `Part of #N` and lists what remains.
7. Push, then report what changed, the gate's result, and anything left undone: an Orca worker with `orca orchestration send` as § DSH describes, a subagent in its final reply.
