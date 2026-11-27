---
title: "CTRY: a distant hill vanishes and returns on alternate render ticks around ticks 286–366"
started: 2026-11-27
issue: 1197
outcome: ""
---

# CTRY: a distant hill vanishes and returns on alternate render ticks around ticks 286–366

The hill is `MAP.BIN` records 107 to 109; on the ticks it is missing, the vertex pixel snap of #1064 has slid one of its foot corners kilometres back along a ray that grazes the horizontal plane, so the mountain face behind (record 12) wins the depth test.
The [journal](journal.md) has the diagnosis and four sweeps, none adopted.

## Handoff

* **Cause** (`[Bounded Observation]`): `playone_vertex` in `mode13h.wgsl` slides every world-mesh vertex in the horizontal plane through it; a steep patch's foot corner 5 km off and 6 m below the eye sits less than half a pixel below the horizon, so the snapped pixel's ray meets that plane far beyond it, by an amount that changes with the sub-pixel position from tick to tick.
* **Tried**: bounding the slide (0.3 to 0.03 of the vertex's distance), the bounded vertex keeping the snapped pixel, clamping the slide, and sliding steep terrain in its own plane.
  Each fixes the hill; none passes the adoption rule (`balloon` −0.0052 for the clamp, `land` −0.0033 for the facet slide).
* **Next**: the facet slide is the form the cause points to.
  It shows far mountains `PLAYONE` does not draw (`land` 551), which `main` hides only by the same fault; find the rule by which `PLAYONE` leaves them out, then retry the facet slide.
