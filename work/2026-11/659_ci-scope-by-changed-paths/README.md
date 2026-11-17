---
title: "CI scopes its jobs by the files a pull request changes"
started: 2026-11-17
issue: 659
outcome: ""
---

# CI scopes its jobs by the files a pull request changes

**Question.** A pull request whose changed paths are all docs by `gate.py`'s classifier (ADR 0038's docs category; for example a Markdown file under `crates/` is Rust, a `.ksy` is docs) waits on the full CI (lavapipe, Rust, `msrv`, `deny`, `windows-smoke`); can CI run only the docs half for it without leaving a required check pending? Issue [#659](https://github.com/neilsh/stunt-reel/issues/659); [spec](spec.md), [plan](plan.md), decision in [ADR 0047](../../../docs/adr/0047-ci-scopes-a-docs-only-pull-request.md).

## Handoff

- **Done**: plan Tasks 1–3 on branch `ccr-903b2056-eak7i0`: 88fcde1, 1c226ff, dd38699, f5bd51b, 11ab741. The final whole-branch review's fixes: 2ba85dd (evergreen docs and ADR 0047 Consequences), the commit that adds this handoff, and a wording follow-up. Not pushed; nothing has run on GitHub.
- **Remains**: plan Task 4, verification on GitHub: the PR for this branch to `main`; three throwaway PRs based on the branch (docs-only, a `.py` change, a `gate.py` that does not parse); after the merge, the first docs-only PR to `main`, to confirm skipped jobs satisfy the ruleset. Then the finishing PR writes `outcome` and closes #659.
- **Not in `plan.md`; add when Task 4's PRs are open**: cancel a throwaway PR's run while `scope` runs and read the four gated checks' conclusions (skipped would pass, cancelled would fail); record it in #659 and ADR 0047.
- **Open once Task 4 has run**: [`quality-gate.md`](../../../docs/quality-gate.md)'s "Neither the skip nor the failed-`scope` path has run in this repository yet (ADR 0047)" and ADR 0047's not-yet-exercised and cancel-during-`scope` Consequences need rewriting to what was seen; a measured figure for the `scope` wait.
- **Parked minors**: no test that `gate.py scope` ignores `--full` and `--tail`; the text-level tests in `tests/test_ci_scope.py` break on a reformat of `ci.yml`, by design.
