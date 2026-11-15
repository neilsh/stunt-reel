---
title: "Is mbx usable for worktree target/ seeding on Cargo 1.100?"
started: 2026-11-14
issue: 511
outcome: "mbx 1.30.0 on Cargo 1.100.0 loses to the seed: a fresh worktree's first check-rust takes a median 20 s (30.8 s wall with its target pre-step) against 15 s; clone and CARGO_TARGET_DIR gates met, speed gate not. Not adopted."
---

# Is mbx usable for worktree target/ seeding on Cargo 1.100?

**Question:** Does `mbx` beat the block-clone seed for a new worktree's first `mise run check-rust` on Cargo 1.100?

Result: no. See [journal.md](journal.md).
