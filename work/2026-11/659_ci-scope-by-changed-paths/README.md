---
title: "CI scopes its jobs by the files a pull request changes"
started: 2026-11-17
issue: 659
outcome: ""
---

# CI scopes its jobs by the files a pull request changes

**Question.** A pull request that changes only Markdown waits on the full CI (lavapipe, Rust, `msrv`, `deny`, `windows-smoke`); can CI run only the docs half for it without leaving a required check pending? Issue [#659](https://github.com/neilsh/stunt-reel/issues/659); [spec](spec.md), [plan](plan.md), decision in [ADR 0047](../../../docs/adr/0047-ci-scopes-a-docs-only-pull-request.md).

## Handoff

- **Done**: plan Tasks 1–3 on branch `ccr-903b2056-eak7i0`: 88fcde1, 1c226ff, dd38699, f5bd51b, 11ab741, 2ba85dd and the commit that adds this handoff. Not pushed; nothing has run on GitHub.
- **Remains**: plan Task 4, verification on GitHub: the PR for this branch to `main`; three throwaway PRs based on the branch (docs-only, a `.py` change, a `gate.py` that does not parse); a run cancelled while `scope` runs; after the merge, the first docs-only PR to `main`, to confirm skipped jobs satisfy the ruleset. Then the finishing PR writes `outcome` and closes #659.
- **Open once Task 4 has run**: [`quality-gate.md`](../../../docs/quality-gate.md) CI paragraph's "has not run in this repository yet" and ADR 0047's not-yet-exercised and cancel-during-`scope` Consequences need rewriting to what was seen; a measured figure for the `scope` wait.
- **Parked minors**: no test that `gate.py scope` ignores `--full` and `--tail`; the text-level tests in `tests/test_ci_scope.py` break on a reformat of `ci.yml`, by design.
