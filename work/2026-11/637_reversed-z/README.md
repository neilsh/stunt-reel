---
title: "Standard-Z 24-bit depth leaves far near-coplanar ties to rounding"
started: 2026-11-16
issue: 637
outcome: ""
---

# Standard-Z 24-bit depth leaves far near-coplanar ties to rounding

**Question.** Whether reversed, infinite depth (in `Depth32Float`, as proposed) makes lavapipe and the GPU agree on the near-coplanar depth ties left after eye-relative transforms ([`lavapipe.md`](../../../research/parity/lavapipe.md) section 5; [#637](https://github.com/neilsh/stunt-reel/issues/637), Lane A step 2 of #639), and what it does to GPU parity.

## Status

- 2026-11-16: implemented in `Depth32Float`; single-tick checks in [journal.md](journal.md).
- 2026-11-21: measured over every tick against `main` `5fbfe844`: `Depth32Float` raised the GPU-lavapipe residue on five films; the same projection in `Depth24Plus` lowered it on all seven, with GPU parity inside every guard ([ADR 0054](../../../docs/adr/0054-depth-is-reversed-and-infinite.md); [journal.md](journal.md)).
