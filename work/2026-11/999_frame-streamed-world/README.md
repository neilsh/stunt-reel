---
title: "Stream the world's visible slices each frame and un-bake its static props onto shared shapes"
started: 2026-11-23
issue: 999
outcome: ""
---

# Stream the world's visible slices each frame and un-bake its static props onto shared shapes

The owner ruled on 2026-11-22 that architecture alone justifies replacing the baked world mesh if it costs no performance and moves toward a more maintainable design; this folder holds the probe, the design note and the ADR draft the issue asks for before any code.

## State (2026-11-23)

- **Probe, done.** A CPU-only count over the seven reference films ([`journal.md`](journal.md#2026-11-23-world-stream-sizes-a-frame-on-the-seven-reference-films)): the largest frame emits `75,576` vertices, `76,008` indices and `149,956` outline indices (`INTRO` 3635), `2.88` MiB, against `LOCATION`'s `333.75` MiB of baked buffers.
  Raw rows in [`probe/`](probe/); the probe is [`world-stream-probe.patch`](world-stream-probe.patch) against `eabff61a`, driven by [`probe_world_stream.py`](probe_world_stream.py).
- **Design note and ADR draft, accepted.** [`design.md`](design.md) lists what each step removes and adds and eight open calls; the owner accepted it and settled the calls on 2026-11-26 ([#999](https://github.com/neilsh/stunt-reel/issues/999#issuecomment-7184561095)), and [`adr-draft.md`](adr-draft.md) moved into `docs/adr/` once stage C passed.
- **Stage A, #1091.** `crates/stunt-render/src/world_stream.rs` stages a frame's ground, base and decal slices on the CPU; an offline test shows streaming every node reproduces the baked buffers byte for byte.
  Nothing draws from it: stage B (#999's sub-issue order) does.
- **Stage B plan (2026-11-27).** [`plan.md`](plan.md) details stage B (#1092) as two stacked PRs on PR #1101 (#1001), whose per-vertex shape word the stream carries instead of a runs table; stages C and D follow as their own layers, each planned from the layer below's figures.
- **Stage B, #1092 (2026-11-28).** Layers 1 and 2 of the stack are PRs [#1214](https://github.com/neilsh/stunt-reel/pull/1214) and [#1215](https://github.com/neilsh/stunt-reel/pull/1215); `STUNT_WORLD_STREAM=1` draws the world from the stream.
  Cloud lavapipe: seven-film stores identical, peak memory `277` to `281` MiB lower ([`journal.md`](journal.md#2026-11-28-stage-b-the-world-drawn-from-the-stream-stores-and-memory-on-cloud-lavapipe)); Windows lavapipe and the RTX 4070: stores identical on all seven films, peak memory lower on lavapipe, `11` MiB lower on the RTX 4070 ([`journal.md`](journal.md#2026-11-28-stage-b-windows-lavapipe-and-rtx-4070-stores-and-memory)).
- **Stage C, #1093 (2026-11-28).** The stream is the only world path: the baked upload, its switch and buffer splitting are deleted, and the ADR is [`docs/adr/0060`](../../../docs/adr/0060-the-static-world-is-streamed-each-frame-not-uploaded.md).
  Whole `LOCATION` lavapipe loop `-0.4%` (faster in 3 of 4), RTX 4070 `+14.5%` (reported, not gating; #1227), peak memory lower on both, stores identical on all seven films on both ([`journal.md`](journal.md#2026-11-28-stage-c-the-stream-as-the-only-world-path-loop-memory-and-stores)).
  `marks`, `cut` and `cut_out` stay, since the cut points' outline offsets only the plan computes (#1228).
- **Not started.** The un-baking (stage D, #1094), against the issue's gates.
  `#1001` was not timed and the note draws no conclusion from it: the owner holds it on `#1004`'s A/A result.

## Next

Stage D (#1094) un-bakes the static props onto shared shapes, planned from stage C's figures in a new session.
