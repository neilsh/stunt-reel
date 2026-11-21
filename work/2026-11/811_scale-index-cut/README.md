---
title: "Apply PLAYONE's scale_index distance cut (0x1B28) to scenery props"
started: 2026-11-20
issue: 811
outcome: "adopted: the renderer drops scenery props per frame by PLAYONE's scale_index distance cut (0x1B28); 14 drawn placements lay past it in the frame on location, none on the other six references; location rises by 0.0000049, no frame falls"
---

# Apply PLAYONE's scale_index distance cut (0x1B28) to scenery props

## Handoff

The count and the sweep are in [the journal](journal.md); the finding is in [`world-scene-residuals.md` § 6.4](../../../research/playone-exe/world-scene-residuals.md#64-the-ground-decal-pass).
The cut is adopted as `VisibilityCondition::ScaleReach`, set by `build_world` on each placement some camera eye puts past it and tested per frame.
The #777 reading took `[0x229E]` as 1 at the default lens; it is 0, and § 6.4 and its Ruled out section now say so.
Not done: the error readout after adopting (the change moves three `location` frames by at most 0.0014 SSIM), and the stand-ins at `location` 3642 to 3697, which the cut drops without changing a pixel, were not traced.
