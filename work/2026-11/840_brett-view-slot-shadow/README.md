---
title: "View slot's shadow draws about 5% of BRETT.FLM's black band on one frame and none on 19 (#499 follow-up)"
started: 2026-11-22
issue: 840
outcome: "The shadow draw tests its facing gates on the flattened face, as PLAYONE's REJ does, so the view slot's shadow draws 4,809 of BRETT.FLM's 4,856 index-0 pixels on all 20 view-slot frames; the judge adopts it on the GPU and lavapipe (ctry 0.9377 to 0.9385); the lavapipe expected table awaits its WSL catch-up repin."
---

# View slot's shadow draws about 5% of BRETT.FLM's black band on one frame and none on 19 (#499 follow-up)

The view slot's shadow now draws the car's flattened footprint on all 20 `BRETT.FLM` view-slot frames.
The cause was the shadow draw's facing gates, not the near plane or the cull: [journal](journal.md).
