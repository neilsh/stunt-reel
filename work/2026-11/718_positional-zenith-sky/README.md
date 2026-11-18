---
title: "parity: count the capture zenith sky at 224-226 by position, not index"
started: 2026-11-18
issue: 718
outcome: "Adopted: a 224 to 226 capture run that reaches row 0 and both side columns counts as sky; balloon IoU 0.6409 -> 0.7186 and bomb 0.9129 -> 0.9626 on lavapipe, the GPU repin left for local-windows."
---

# parity: count the capture zenith sky at 224-226 by position, not index

Scored three positional rules for the capture's zenith sky at 224 to 226 on the seven `VAULT` references; the figures are in [`journal.md`](journal.md), the decision in `research/parity/method.md` section 2.0.

## Handoff

- `capture_sky_mask` in `crates/stunt-cli/src/parity/mask.rs` holds the adopted rule; the lavapipe `iou` of every film in `research/parity/references.toml` is repinned.
- Left for local-windows: `mise run parity` on the GPU and `mise run parity-repin -- --class gpu`.
- Follow-up: count the sky the balloon cuts off by its overlap with the previous frame's sky (rule G in the journal), [#745](https://github.com/neilsh/stunt-reel/issues/745).
