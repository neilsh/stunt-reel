---
title: "CI scopes its jobs by the files a pull request changes"
started: 2026-11-17
issue: 659
outcome: "CI runs the docs half for a pull request whose changed paths are all docs (ADR 0047); seen on GitHub: docs-only, full, failing-scope and cancelled runs, and a docs-only pull request to main with a clean merge state."
---

# CI scopes its jobs by the files a pull request changes

**Question.** A pull request whose changed paths are all docs by `gate.py`'s classifier (ADR 0038's docs category; for example a Markdown file under `crates/` is Rust, a `.ksy` is docs) waits on the full CI (lavapipe, Rust, `msrv`, `deny`, `windows-smoke`); can CI run only the docs half for it without leaving a required check pending? Issue [#659](https://github.com/neilsh/stunt-reel/issues/659); [spec](spec.md), [plan](plan.md), decision in [ADR 0047](../../../docs/adr/0047-ci-scopes-a-docs-only-pull-request.md).

## Handoff

- **Done**: the scoping landed in #667 (`gate.py scope`, the `scope` job and the skips in `ci.yml`, ADR 0047, `docs/quality-gate.md`); the verification on GitHub is recorded on [#659](https://github.com/neilsh/stunt-reel/issues/659) and in ADR 0047's Consequences; the finishing pull request is #675, itself the first docs-only pull request to `main`.
- **Not seen**: a failed `scope` beside a docs-only diff (the failing-`scope` throwaway edited `ci.yml`, so its diff was not docs-only); the cancel result is from one API cancel.
- **Parked minors**: no test that `gate.py scope` ignores `--full` and `--tail`; the text-level tests in `tests/test_ci_scope.py` break on a reformat of `ci.yml`, by design.
