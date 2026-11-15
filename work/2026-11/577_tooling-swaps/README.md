---
title: "Retire the CRLF hook, CI's commit-range check and the GPU watchdog script"
started: 2026-11-15
issue: 577
outcome: ""
---

# Retire the CRLF hook, CI's commit-range check and the GPU watchdog script

Fewer lines to maintain and more trustworthy checks: three independent changes. Design: [spec.md](spec.md).

## Handoff (2026-11-15)

Three PRs, all reviewed:

- #582 (A): per-test GPU hang deadline, 60 s default from a 4.7 s lavapipe run; retires `watch_render_test.py`. Carries this folder.
- #583 (B): drops `crlf-check`.
- #584 (C, draft): checks the PR title in CI and drops the commit-range check. It stays a draft until the owner turns off rebase merging, sets the squash title to "Pull request title" and adds `PR title` to the `main` ruleset.

Merge order: B before C. Rebase C onto `main` and keep both 2026-11-15 amendments in ADR 0026 (B's first, one merged status line). The last PR to merge writes `outcome` here and closes #577.
