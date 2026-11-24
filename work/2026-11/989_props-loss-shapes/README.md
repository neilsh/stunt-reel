---
title: "Which prop shapes cost the props loss on LOCATION and BOMB, and why?"
started: 2026-11-23
issue: 989
outcome: "Ranked the costliest prop shapes on LOCATION and BOMB and gave each a cause in research/parity/prop-shape-loss.md, except about 88% of BOMB street 1756's loss (#1035); filed #1029 to #1034, one per cause."
---

# Which prop shapes cost the props loss on LOCATION and BOMB, and why?

Ranked `location`'s and `bomb`'s prop shapes by `mean_loss_by_shape_scored` on the canonical lavapipe and sorted the worst ones' frames by cause ([`journal.md`](journal.md)); the findings are in [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md).

## Handoff

Each cause has its own issue: the canyon step timing #1029, in-shape paint order #1030, per-shot camera offsets #1031, the far town's stand-ins #1032, one-tick phase #1033, the stadium's lines #1034; BOMB's street 1756, which loses in place for no cause found yet, is #1035, so #989 stays open on it.
The temporary switch `DBG_FAR` is kept in [`switches/DBG_FAR.diff`](switches/DBG_FAR.diff); the per-shape print is #904's [`DBG_SHAPE_DUMP.diff`](../904_near-clip-host-shapes/switches/DBG_SHAPE_DUMP.diff), with its `eprintln!` changed to append to a file.
