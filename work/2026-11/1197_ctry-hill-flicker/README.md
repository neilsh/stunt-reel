---
title: "CTRY: a distant hill vanishes and returns on alternate render ticks around ticks 286–366"
started: 2026-11-27
issue: 1197
outcome: ""
---

# CTRY: a distant hill vanishes and returns on alternate render ticks around ticks 286–366

The hill is `MAP.BIN` records 107 to 109; on the ticks it is missing, the vertex pixel snap of #1064 has slid one of its foot corners kilometres back along a ray that grazes the horizontal plane, so the mountain face behind (record 12) wins the depth test.
The [journal](journal.md) has the diagnosis and five sweeps, none adopted.

## Handoff

* **Cause** (`[Bounded Observation]`): `playone_vertex` in `mode13h.wgsl` slides every world-mesh vertex in the horizontal plane through it; a steep patch's foot corner 5 km off and 6 m below the eye sits less than half a pixel below the horizon, so the snapped pixel's ray meets that plane far beyond it, by an amount that changes with the sub-pixel position from tick to tick.
* **Tried**: bounding the slide (0.3 to 0.03 of the vertex's distance), the bounded vertex keeping the snapped pixel, clamping the slide, and sliding steep terrain in its own plane.
  Each keeps the hill on the ticks checked (not every tick at a 30% bound); none passes the adoption rule (`balloon` −0.0052 for the clamp, `land` −0.0033 for the facet slide).
* **`land` 551** (#1206): the mountain the steep facet slide drew there is records 46 and 50, 7 to 10 km off, which a nearer face (record 2) covers in the capture; no distance cut reaches them.
  They are just under the 26-degree threshold, so their feet slid nearer in the horizontal plane and beat record 2 once it slid in its own.
* **Fifth sweep**: every raised patch in its own plane keeps the hill and `land` 551, but draws ocean at the foot of far raised terrain (`balloon` −0.0018, `land` −0.0012); not adopted.
* **Next**: a raised patch's corner needs its own plane where it stands clear of the flat ground and the ground's where it meets it; a form that does both was not tried.
