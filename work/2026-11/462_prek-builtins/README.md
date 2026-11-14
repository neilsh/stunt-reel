---
title: "Adopt prek built-ins in place of custom checks"
started: 2026-11-13
issue: 462
outcome: "Landed as a stack of three PRs. prek is 0.5.10; trailing-whitespace and end-of-file-fixer (--check) replace diff-check; crlf-check stays, since no built-in repairs a CRLF-only working copy. Added check-symlinks, destroyed-symlinks, check-json, fix-byte-order-marker (--check), check-vcs-permalinks (not in work/, whose plan quotes a branch link) and forbid-new-submodules. The shebang pair was already in from #461. Left out: no-commit-to-branch, deny-filename-pattern, mixed-line-ending, pretty-format-json."
---

# Adopt prek built-ins in place of custom checks
