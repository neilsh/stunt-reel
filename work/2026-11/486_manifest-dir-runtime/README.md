---
title: "Read CARGO_MANIFEST_DIR at runtime in Rust tests (~18 s worktree seed speedup) and re-test mbx on Cargo 1.100"
started: 2026-11-14
issue: 486
outcome: ""
---

# Read CARGO_MANIFEST_DIR at runtime in Rust tests (~18 s worktree seed speedup) and re-test mbx on Cargo 1.100

**Question:** Can a worktree seeded from a donor keep the donor's builds of the workspace crates whose sources are unchanged, so its first `mise run check-rust` drops from about 40 s toward the 22 s warm time? Rust tests must first read `CARGO_MANIFEST_DIR` at run time. The `mbx` re-test, once part of this issue, moved to #511.

Plan: [plan.md](plan.md).
