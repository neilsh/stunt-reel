---
title: "parity: count the zenith sky the balloon cuts off by overlap with the previous frame (from #718)"
started: 2026-11-20
issue: 745
outcome: ""
---

# parity: count the zenith sky the balloon cuts off by overlap with the previous frame (from #718)

Scored rule G, a 224 to 226 run that is full width or overlaps a pixel the previous captured frame counted by the same rule, on the seven `VAULT` references.
The figures are in [`journal.md`](journal.md), the decision in [`method.md`](../../../research/parity/method.md#20-sky-mask-and-iou-scale) section 2.0.

## Handoff

- `capture_sky_mask` in `crates/stunt-score/src/parity/mask.rs` returns the full sky mask and the 224 to 226 pixels it counted; `score_matched` carries the counted pixels to the next matched frame.
- The `gpu` table in `research/parity/expected/gpu.toml` is repinned from the RTX 4070 run (`balloon` IoU 0.8868 -> 0.8978, the other six films and every SSIM unchanged; `crates` `4a3688f`).
- Left for a cloud run: the `lavapipe` table's `iou` and `crates`, which need the pinned `llvmpipe (LLVM 20.1.2, 256 bits)` while this machine's is LLVM 21.1.7; the figures in `journal.md` and `method.md` are measured on that local lavapipe, and [#830](https://github.com/neilsh/stunt-reel/issues/830) tracks the catch-up.
- The residual 6,580 `balloon` 224 to 226 pixels that neither rule reaches stay geometry; they are recorded in `method.md` section 2.0.