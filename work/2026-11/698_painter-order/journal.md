# Journal: painter order on CTRY (#698)

## 2026-11-19: Comparison sheets of the two painters

The variants of [`painter-order.md`](../../../research/parity/painter-order.md) § 1, rebuilt as one switch, [`switches/DBG_PAINTER.diff`](switches/DBG_PAINTER.diff): `DBG_PAINTER=0` is the depth buffer, `1` the sorted painter, `2` the walk-order painter.
Every panel was rendered on cloud lavapipe from commit `bd3c551` (the branch after merging `origin/main`) with that diff applied, by `mise run frame -- --film ctry --ticks 804,837,871,881 --software-only --var DBG_PAINTER=0,1,2` and, for the crop, `--ticks 804 --crop 110,50,210,130 --scale 3`.
Panels run capture, depth buffer, sorted painter, walk-order painter.

The ticks come from the scored frames of the note's § 2 reports (`per_frame` `index_agreement`, painter minus depth buffer):

| Tick | Why | Sorted | Walk-order | Index-plane pixels changed, sorted / walk-order (of 64000) |
|---|---|---|---|---|
| 804 | the painters' best frame | +0.0012 | +0.0010 | 128 / 142 |
| 837 | the walk-order painter's worst frame | −0.0225 | −0.1114 | 1395 / 6861 |
| 871 | the sorted painter's worst frame, and the largest rise in actor loss (+0.053) | −0.0618 | −0.0834 | 4963 / 6308 |
| 881 | an actor beside a building, the second-largest rise in actor loss (+0.028) | −0.0408 | −0.0567 | 3393 / 4258 |

The pixel counts compare each painter's stored index plane with the depth buffer's at that tick, on the `bd3c551` renders. A second run of the same command drew the four whole-frame sheets byte for byte the same.

- [`ctry-837-painters.png`](images/ctry-837-painters.png): a near hillside fills the left of the frame, and a pillar and a red roof stand behind it.
  The capture and the depth buffer hide both.
  The walk-order painter paints the pillar and the roof's faces over the hillside.
  The sorted painter paints their faces before the hillside, which covers them, but their outlines still show through it.
- [`ctry-871-painters.png`](images/ctry-871-painters.png): an explosion sits behind the same hillside.
  In the capture and the depth buffer the hillside cuts off its left part.
  Both painters draw the whole explosion over the hillside, since actors are drawn after the world, and both show the red roof's faces through it.
  The sorted painter also shows the pillar's and the roof's outlines.
- [`ctry-881-painters.png`](images/ctry-881-painters.png): ten ticks later, with the same faults: the explosion is drawn over the hillside, and the hidden roof and pillar show through it in both painters.
- [`ctry-804-painters.png`](images/ctry-804-painters.png) and the crop around the aircraft, [`ctry-804-painters-crop.png`](images/ctry-804-painters-crop.png): the painters change few pixels, spread across the frame from x 0 to 292 and y 20 to 98.
  At either scale the three renders look alike, and none is visibly closer to the capture.

At ticks 837, 871 and 881 the depth buffer is the render closest to the capture; at 804 the three look alike.
