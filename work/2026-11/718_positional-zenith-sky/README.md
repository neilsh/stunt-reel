---
title: "parity: count the capture zenith sky at 224-226 by position, not index"
started: 2026-11-18
issue: 718
outcome: "Adopted: a 224 to 226 capture run that reaches row 0 and both side columns counts as sky; balloon IoU 0.6409 -> 0.7186 and bomb 0.9129 -> 0.9626 on lavapipe and on the GPU; the gpu tables are repinned, the lavapipe iou repin is left for a cloud run."
---

# parity: count the capture zenith sky at 224-226 by position, not index

Scored three positional rules for the capture's zenith sky at 224 to 226 on the seven `VAULT` references; the figures are in [`journal.md`](journal.md), the decision in `research/parity/method.md` section 2.0.

## Handoff

- `capture_sky_mask` in `crates/stunt-score/src/parity/mask.rs` holds the adopted rule.
- The `gpu` tables in `research/parity/references.toml` are repinned (local-windows, RTX 4070: `balloon` IoU 0.7186, `bomb` 0.9626, the other films and every SSIM unchanged).
- Left for a cloud run: the `lavapipe` tables' `iou`.
  Merging `main` took `main`'s lavapipe tables, measured with the scorer before this rule, and local-windows' llvmpipe (LLVM 21.1.7) is not the pinned LLVM 20.1.2; `mise run parity -- --software-only` then `mise run parity-repin -- --class lavapipe` on the cloud's llvmpipe repins them.
- Follow-up: count the sky the balloon cuts off by its overlap with the previous frame's sky (rule G in the journal), [#745](https://github.com/neilsh/stunt-reel/issues/745).
