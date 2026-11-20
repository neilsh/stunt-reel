---
title: "Background bands for traintnl and bomb drift from the strict rule on the current render"
started: 2026-11-20
issue: 614
outcome: "On crates tree 5ad0346 (after #617's sky drawer) the strict band rule gives intro, land, traintnl, bomb and location their committed rows; balloon drops 228 (IoU 0.7237 -> 0.7143) and ctry drops 236 (0.5417 -> 0.5391), each newly painted by our actors."
---

# Background bands for traintnl and bomb drift from the strict rule on the current render

The question: do the reference films' `background` bands in `research/parity/references.toml` still follow the strict rule of [`probes.md` § 3](../../../research/parity/probes.md#3-actor-window-iou-iou) on current `main`'s render?

## What changed

- The `balloon` and `ctry` rows of `research/parity/references.toml` drop 228 and 236; no capture pin changed.
- [`probes.md` § 3](../../../research/parity/probes.md#3-actor-window-iou-iou) gives the bands' IoU on tree `5ad0346` and the counts that moved.
- [`journal.md`](journal.md): the per-film recheck, with IoU before and after.

## Handoff

- The rule's output moves with the render: each change to our actors' indices can admit or drop an index.
  Rechecking the bands after a render change is manual (the § 3 snippet).
- Index 208: since #617 our render draws it as sky, and 46 % of `bomb`'s capture 208 falls on our sky layer; past half the rule's sky test would drop it from `bomb`, `balloon` and `location`.
