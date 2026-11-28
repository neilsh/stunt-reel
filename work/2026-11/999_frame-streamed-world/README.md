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
- **Design note and ADR draft, awaiting the owner.** [`design.md`](design.md) lists what each step removes and adds and eight open calls; [`adr-draft.md`](adr-draft.md) is proposed, to move into `docs/adr/` on acceptance.
- **Stage A, #1091.** `crates/stunt-render/src/world_stream.rs` stages a frame's ground, base and decal slices on the CPU; an offline test shows streaming every node reproduces the baked buffers byte for byte.
  Nothing draws from it: stage B (#999's sub-issue order) does.
- **Stage B plan (2026-11-27).** [`plan.md`](plan.md) details stage B (#1092) as two stacked PRs on PR #1101 (#1001), whose per-vertex shape word the stream carries instead of a runs table; stages C and D follow as their own layers, each planned from the layer below's figures.
- **Not started.** Drawing from the stream, the timing gate and the un-baking, each against the issue's gates.
  `#1001` was not timed and the note draws no conclusion from it: the owner holds it on `#1004`'s A/A result.

## Next

The owner accepts or amends `design.md` and `adr-draft.md` and decides its open calls; step 1 then starts from `design.md` § 2 and § 6, in a new session.
