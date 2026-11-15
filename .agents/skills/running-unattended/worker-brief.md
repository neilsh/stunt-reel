# Implementer brief

Part of the [`running-unattended`](SKILL.md) skill.

Every implementer brief, first task or review fix, is self-contained: a follow-up starts a fresh session, and the worker has only the brief. Give the issue or PR number, the branch and base, the files in scope, the acceptance criteria and, for a fix, the review comment's URL. Then copy in this checklist:

1. A dsh worker reads [`docs/harness-setup.md` § DSH](../../../docs/harness-setup.md#dsh) first.
2. Iterate with `mise run fix`, `mise run test-py -- <file>` and `mise run check-py` (the gate's Python half: lint, types and tests); run the full `mise run check` once, at the end.
3. After moving, renaming or splitting a file, section or symbol, `rg` every old name (basename, path, symbol, cited section or item number) from the repository root, agent guidance in `.agents/` and `.claude/` included, and fix each mention in prose and comments, not only links. Never rewrite files under `work/`: retarget only the links there, with `mise run move-docs` for doc moves.
4. A fix to reviewed code adds a test for the case the previous version already handled, and reruns step 3's sweep, so the fix cannot open a new finding.
5. Push, then report with `orca orchestration send` as § DSH describes: what changed, the gate's result, and anything left undone.
