---
summary: "Ranks the prop shapes costing LOCATION's and BOMB's props loss and why each loses: a camera held through far-moving slices (fixed), pages drawn a tick off while the camera moves, sphere cover order on the trees, far-town stand-ins that drew no `BLOCK` (fixed), tick phase, lines; most of BOMB's street loss is unexplained."
sidebar_label: "Costliest prop shapes"
---
# Parity: The Prop Shapes That Cost LOCATION and BOMB

* **Scope**: which prop shapes carry the `props` class of [`attribution.md`](attribution.md) on `location` and `bomb`, the two films it costs most, and why each loses; the error readout's `scenery-missing` ticks on `bomb` (1585, 1904; [`readouts/`](readouts/)) are sorted the same way.
* **Sources**: one render of each film on the canonical lavapipe under WSL (`llvmpipe (LLVM 20.1.2, 256 bits)`) at `main` `3e53f767`, which reproduced both films' `expected/lavapipe.toml` scores; `mean_loss_by_shape_scored` ([`report-fields.md`](report-fields.md)), a per-frame print of it, `--retime` rescoring, `mise run frame` pictures and temporary switches.
* **Evidence tier**: `[Bounded Observation]` throughout, one render of each film, unless a finding says otherwise.

## 1. The ranking

Each value is the shape's `mean_loss_by_shape_scored` and its share of the film's `props` loss; neither film has an `unattributed` share.

| Rank | `location` shape | Loss (share) | `bomb` shape | Loss (share) |
|---|---|---|---|---|
| 1 | 1145 canyon rock | 0.00169 (2.2%) | 1756 street | 0.00830 (13.9%) |
| 2 | 1745 railway track | 0.00158 (2.0%) | 1737 red lot | 0.00704 (11.8%) |
| 3 | 1150 crater | 0.00156 (2.0%) | 545 autumn tree | 0.00423 (7.1%) |
| 4 | 613 stadium | 0.00142 (1.8%) | 1650 fire station | 0.00403 (6.8%) |
| 5 | 996 town lots | 0.00137 (1.7%) | 1648 church | 0.00375 (6.3%) |
| 6 | 1164 canyon rock | 0.00132 (1.7%) | 1754 red road | 0.00364 (6.1%) |
| 7 | 1179 canyon rock | 0.00128 (1.6%) | 542 autumn tree | 0.00230 (3.9%) |
| 8 | 1162 canyon rock | 0.00121 (1.5%) | 1654 building | 0.00222 (3.7%) |
| Ten worst | | 0.0136 (17.4%) | | 0.0386 (64.7%) |

The names say what each shape draws in the frames inspected.
`location`'s `props` loss (0.0784) is spread over 1,014 shapes, and each of its eight worst loses on one to three short runs (1150 on three) of 14 to 27 of its 732 scored frames; `bomb`'s (0.0597) falls on 127 shapes, each of its eight worst losing on 48 to 150 of 316 frames.

_Source: [the costliest prop shapes on LOCATION and BOMB](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-costliest-prop-shapes-on-location-and-bomb)._

## 2. Why each loses

| Cause | Shapes | Section | Issue |
|---|---|---|---|
| Our player held the camera through slices it moves more than 50 m in (fixed) | `location` 1145, 1164, 1179, 1162 on the canyon run, 1150 at 2212 | 2.1 | [#1029](https://github.com/neilsh/stunt-reel/issues/1029), [#1031](https://github.com/neilsh/stunt-reel/issues/1031) |
| Pages a tick or two off ours while the camera moves; a row on the static opening shot | `bomb` 1648, 1650, 1737, 1654, 1754, 1756 on the opening shot (7% of its loss) | 2.2 | [#1064](https://github.com/neilsh/stunt-reel/issues/1064), [#1033](https://github.com/neilsh/stunt-reel/issues/1033) |
| Overlapping spheres of one shape cover each other in list order | `bomb` 542, 545 | 2.3 | [#1066](https://github.com/neilsh/stunt-reel/issues/1066) |
| Far houses missing: the stand-ins' `BLOCK` houses went undrawn (fixed) | `bomb` `scenery-missing` 1585, 1904 | 2.4 | [#1032](https://github.com/neilsh/stunt-reel/issues/1032) |
| A run of frames prefers a one-tick offset | `location` 1745, 996 | 2.5 | [#1033](https://github.com/neilsh/stunt-reel/issues/1033) |
| Lines and outlines on a shape drawn in place | `location` 613 | 2.5 | [#1034](https://github.com/neilsh/stunt-reel/issues/1034) |
| Unexplained: drawn in place, in the capture's colours | `bomb` 1756 on ticks 2036 to 2740 and 3312 to 3477 (about 88% of its loss) | 2.6 | [#1035](https://github.com/neilsh/stunt-reel/issues/1035) |

In the issue's terms, 2.1, 2.2 and 2.5 are misplacement by the camera, not by the prop; 2.3 is draw order for the trees; 2.4 was missing geometry; 2.6 has no cause yet.
No shape inspected shows a wrong shade or a wrong shape of its own.

### 2.1 The camera held through far-moving slices (fixed)

Between ticks 6713 and 7150 of `location` our render changed only every 10 ticks (6731, 6741, …, 7141), and on the frames that straddle a step the capture already showed the next one, 1 to 3 ticks before we did.
The canyon run's view slot moves about 59 m in each 10-tick slice, and our player flagged a cut whenever the eye moved more than 50 m between slices and held the old pose for the whole slice; `PLAYONE` interpolates a slot across a slice whatever the distance ([`timeline-and-ticks.md` § 3.2](../formats/concepts/timeline-and-ticks.md#32-director-cut-suppression)).
The same hold froze the camera on `location` 2201 to 2212, where the crater 1150's near rim differed in outline: our eye stood still while the capture's moved, a camera-position difference, not a shape or cover order.
Interpolating those slices raised the 64 scored frames from 6700 to 7400 from 0.8312 to 0.9421 (GPU, `bc166452`) and 2212 from 0.6201 to 0.8698, and removed the near face of the canyon rock 1145 that our render drew across the lower left at 7019 (index agreement 0.424 to 0.870).
`[Bounded Observation]`: one render of each variant.

_Source: [the LOCATION canyon run steps late](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-location-canyon-run-steps-late), [PLAYONE interpolates a slot across any distance](../../work/2026-11/1031_bomb-world-offset/journal.md#2026-11-24-playone-interpolates-a-slot-across-any-distance)._

### 2.2 The frame is off on the opening shot and while the camera moves

The `bomb` buildings and lots 1648, 1650, 1737 and 1654 are drawn in the capture's colours (0.89 to 0.95 of their pixels match in place at the ticks examined), so their loss sits at their edges; the road 1754 matches 0.81 at 2961, where the frame is furthest off.
Searched on every scored `bomb` frame, the offset follows no camera input as a per-shot rule ([`framing-and-actors.md` § 4](framing-and-actors.md#4-background-misregistration-is-neither-one-time-offset-nor-one-page-shift)).
On the static opening shots (ticks 12 to 420, where the fire station 1650 and church 1648 lose 0.040 to 0.043 a frame) the props sit a row low below the projection centre and level or a row high above it, as truncating toward the centre would place them ([#1064](https://github.com/neilsh/stunt-reel/issues/1064)), and the sky's band edges sit a row low.
The frames 2 to 4 px off (2961, 3191, 3268) are frames where the camera turns or moves fast, and a render tick or two either way matches them about as well as a page shift does ([#1033](https://github.com/neilsh/stunt-reel/issues/1033)).

_Source: [what the canyon and BOMB frames show](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-what-the-canyon-and-bomb-frames-show), [the offset per shot, against the camera](../../work/2026-11/1031_bomb-world-offset/journal.md#2026-11-24-the-offset-per-shot-against-the-camera)._

### 2.3 Close shapes cover their own polygons differently

`PLAYONE` paints a shape's polygons in display-list order ([`render-model.md`](render-model.md) § 2), its `SORTON` branches in the order their facing flag picks ([`sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) § 8.6).
A CPU painter in that order, checked against a CPU z-buffer that reproduces our render, splits the two cases:

* **The `bomb` autumn trees 542 and 545** lose to list order: each later `SPHERE` covers the earlier ones and the trunk whatever its depth.
  Inside the trees' pixels at ticks 2080 and 2300, the painter carries the capture's index on 0.85 to 0.91 of them against 0.59 to 0.69 for our render, while the z-buffer of the same discs stays within 0.022 of ours ([sheet](../../work/2026-11/1030_close-shape-order/images/bomb-2300-545-inshape.png)).
  `[Bounded Observation]`: two trees at two ticks of one film.
  Drawing spheres so in the renderer is [#1066](https://github.com/neilsh/stunt-reel/issues/1066).
* **The canyon rock 1145** does not: at `location` 7019 the painter, `SORTON` swaps included, shows another polygon than the z-buffer on 20 of the rock's 49,095 pixels, and draws the same near face across the lower left that the capture does not show ([sheet](../../work/2026-11/1030_close-shape-order/images/location-7019-inshape.png)).
  It was the camera: with the far-moving slices interpolated (2.1) the face is gone.

_Source: [list order explains the BOMB trees, not the canyon rock](../../work/2026-11/1030_close-shape-order/journal.md#2026-11-24-list-order-explains-the-bomb-trees-not-the-canyon-rock)._

### 2.4 The far town drew no houses (fixed)

At `bomb` ticks 1585 and 1904 the capture draws the distant town's houses; ours drew lots, roads and trees there ([sheet](../../work/2026-11/989_props-loss-shapes/images/bomb-1904-lod.png)).
At 1904 the gate ([`lod.md`](../playone-exe/lod.md)) draws the stand-ins of the town's city blocks, `SP_1NODE`s of `splitdist` 100 between 222 and 468 m of view depth.
Those stand-ins (`0x0669`, `0x066B`, `0x066E` among them) hold the block's houses as `OP_BLOCK`s beside its trees, and `vm.rs` read each `BLOCK` and drew nothing, so the stand-ins drew trees alone.
`vm.rs` now draws a `BLOCK` as a cube standing in for `PLAYONE`'s screen square ([`sod-vm-generators.md` § 8.8](../playone-exe/sod-vm-generators.md#88-model-frame-the-other-generators)); the town then shows red and white houses where the capture does ([sheet](../../work/2026-11/1032_block-stand-ins/images/bomb-1904-block-cube.png)), and the gate is not shown wrong.

_Source: [the far town's stand-ins draw no `OP_BLOCK`](../../work/2026-11/1032_block-stand-ins/journal.md#2026-11-24-the-far-towns-stand-ins-draw-no-op_block), [`OP_BLOCK` drawn as a cube](../../work/2026-11/1032_block-stand-ins/journal.md#2026-11-24-op_block-drawn-as-a-cube)._

### 2.5 One-tick phase and lines

The railway track 1745, which the camera rides along, rises over ticks 4330 to 4470 from 0.8939 to 0.9076 one tick later; the town lots 996 over 2040 to 2140 from 0.7887 to 0.8044 one tick earlier.
Over the whole film a one-tick offset helps frames in both directions (+1 raises 49 frames by more than 0.02, -1 raises 101) while offset 0 keeps the best mean, so which pages show another tick is [#1033](https://github.com/neilsh/stunt-reel/issues/1033).
The stadium 613 is drawn in place (best shift 0, 0.89 of its pixels match at 2729, no offset better than 0); `[Hypothesis]`: its loss is the field's chalk lines and the stands' outlines ([`sod-vm-lines-spans.md` § 10](../playone-exe/sod-vm-lines-spans.md#10-open-questions)), measured by [#1034](https://github.com/neilsh/stunt-reel/issues/1034).

_Source: [the LOCATION canyon run steps late](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-location-canyon-run-steps-late), [what the canyon and BOMB frames show](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-what-the-canyon-and-bomb-frames-show)._

### 2.6 The street loses in place, unexplained

`bomb` 1756, the street and the film's costliest prop shape, loses 7% of its loss on the opening shot (2.2) and 4% at 3302, the camera cut of [`attribution.md`](attribution.md) open question 7.
The other part, about 88%, on ticks 2036 to 2740 and 3312 to 3477, has no cause found: at nine ticks from 2190 to 3345 the street is drawn in place (best whole-frame shift 0 or one column, raising agreement by at most 0.014) with 0.95 to 0.98 of its pixels in the capture's colour, yet it loses 0.020 to 0.066 a frame.
`[Hypothesis]`: each pixel takes a share of every SSIM window's loss over it ([`report-fields.md`](report-fields.md)), so windows straddling the edges of the lots, trees and buildings on the street charge part of their loss to it; testing it is [#1035](https://github.com/neilsh/stunt-reel/issues/1035).

_Source: [the BOMB street 1756 loses in place](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-street-1756-loses-in-place)._

## Ruled out

* **The `scale_index` distance cut as the cause of `bomb`'s missing far houses** (2026-11-23): keeping every object it drops draws the same picture at 1585 and 1904 ([the BOMB far town is the level-of-detail gate](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-far-town-is-the-level-of-detail-gate)).
* **The near branch of every `SP_1NODE`** (2026-11-23): it draws the far houses but lowers `bomb` by 0.0118 and `location` by 0.0178, and the two `scenery-missing` ticks too ([same entry](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-far-town-is-the-level-of-detail-gate)).
* **The `SP_1NODE` gate's choice as the cause of `bomb`'s missing far houses** (2026-11-24): the gate's stand-ins hold the houses as `OP_BLOCK`s, which `vm.rs` did not draw ([the far town's stand-ins draw no `OP_BLOCK`](../../work/2026-11/1032_block-stand-ins/journal.md#2026-11-24-the-far-towns-stand-ins-draw-no-op_block)).
* **In-shape paint order for the canyon rock 1145 at `location` 7019** (2026-11-24): list order with `SORTON` swaps changes 20 of its 49,095 pixels ([list order explains the BOMB trees, not the canyon rock](../../work/2026-11/1030_close-shape-order/journal.md#2026-11-24-list-order-explains-the-bomb-trees-not-the-canyon-rock)).
* **Timing as the whole of the canyon run's loss** (2026-11-23): frames such as 7019 and 7317 rise by no more than 0.05 at any offset from -10 to +12 ([the LOCATION canyon run steps late](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-location-canyon-run-steps-late)); the held camera of 2.1 was the rest (7317 from 0.6509 to 0.9152).
* **A per-shot camera offset on `bomb`** (2026-11-24): no shot's offset follows the view slot, the eye or the lens; the opening shot's row flips sign about the projection centre, and the larger offsets are pages a tick or two off ours ([the offset per shot, against the camera](../../work/2026-11/1031_bomb-world-offset/journal.md#2026-11-24-the-offset-per-shot-against-the-camera)).

## Open questions

In order of the loss each would explain:

1. **Truncation toward the projection centre** ([#1064](https://github.com/neilsh/stunt-reel/issues/1064)), on `bomb`'s opening shot: five of its eight worst shapes and 1756.
2. **Pages a tick or two off ours while the camera moves** ([#1033](https://github.com/neilsh/stunt-reel/issues/1033)).
3. **The street's loss in place** ([#1035](https://github.com/neilsh/stunt-reel/issues/1035)), about 88% of `bomb`'s costliest shape.
4. **Spheres in list order** ([#1066](https://github.com/neilsh/stunt-reel/issues/1066)).
5. **One-tick phase** ([#1033](https://github.com/neilsh/stunt-reel/issues/1033)) and **the stadium's lines** ([#1034](https://github.com/neilsh/stunt-reel/issues/1034)).
