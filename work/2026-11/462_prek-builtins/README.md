---
title: "Adopt prek built-ins in place of custom checks"
started: 2026-11-13
issue: 462
outcome: "Landed as one PR, not the plan's stack of three, rebased after #583 had already removed crlf-check. prek is 0.5.10; trailing-whitespace and end-of-file-fixer (--check) replace diff-check, with LICENSE-CC-BY-4.0 exempt from the latter so the licence stays as published. Added check-symlinks, destroyed-symlinks, check-json, fix-byte-order-marker (--check), check-vcs-permalinks (not in work/, whose plan quotes a branch link) and forbid-new-submodules. The shebang pair was already in from #461. Left out: no-commit-to-branch, deny-filename-pattern, mixed-line-ending, pretty-format-json."
---

# Adopt prek built-ins in place of custom checks
