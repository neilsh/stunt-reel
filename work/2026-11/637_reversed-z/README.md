---
title: "Standard-Z 24-bit depth leaves far near-coplanar ties to rounding"
started: 2026-11-16
issue: 637
outcome: "Reversed, infinite depth in Depth24Plus adopted (ADR 0054, signed off 2026-11-22); Depth32Float rejected twice on GPU-lavapipe agreement, re-checked by #966 after the moat fix."
---

# Standard-Z 24-bit depth leaves far near-coplanar ties to rounding

**Question.** Whether reversed, infinite depth (in `Depth32Float`, as proposed) makes lavapipe and the GPU agree on the near-coplanar depth ties left after eye-relative transforms ([`lavapipe.md`](../../../research/parity/lavapipe.md) section 5; [#637](https://github.com/neilsh/stunt-reel/issues/637), Lane A step 2 of #639), and what it does to GPU parity.

**Measured.** In `Depth32Float` the GPU-lavapipe difference rose on five of seven films, and on all seven when re-measured after #904 and #922; in `Depth24Plus` it fell on all seven (LOCATION 62.0 to 29.8 pixels per tick), with GPU parity inside every guard, and the largest tie, LOCATION 3815, halved (3,131 to 1,490 pixels) while the next largest (LOCATION 3830, LAND 415 and 416) moved by under 6%, so the title's claim about rounding is not shown ([journal.md](journal.md)).

## Status

- 2026-11-16: implemented in `Depth32Float`; single-tick checks in [journal.md](journal.md).
- 2026-11-20: measured over every tick against `main` `5fbfe844`: `Depth32Float` raised the GPU-lavapipe residue on five films; the same projection in `Depth24Plus` lowered it on all seven, with GPU parity inside every guard ([ADR 0054](../../../docs/adr/0054-depth-is-reversed-and-infinite.md); [journal.md](journal.md)).
- 2026-11-20: rebased onto `main` `b028f7d3` (#690) and re-measured: the same residue and GPU scores to the figures quoted; `expected/gpu.toml` repinned on `crates` `97c0f90`, then on `90bdee2` after a comment-only change to `mesh.rs` with every expected score the same ([journal.md](journal.md)).
- 2026-11-22: `Depth32Float` re-measured on `main` `44a3bf31`, after #904 and #922, on the canonical lavapipe: the disagreement rose on all seven films and neither judge adopts it ([journal.md](journal.md)).
- 2026-11-22: the owner signed off on ADR 0054's `Depth24Plus`; #637 closed, with #966 to re-measure `Depth32Float` after the castle moat's tie is fixed.
