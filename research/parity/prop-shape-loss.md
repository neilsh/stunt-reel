---
summary: "Ranks the prop shapes costing LOCATION's and BOMB's props loss and why each loses: a camera held through far-moving slices (fixed), pages drawn a tick off while the camera moves, sphere cover order on the trees, far-town stand-ins that drew no `BLOCK` (fixed), tick phase, and the stadium's edges and chalk lines and the BOMB street's lane dashes a pixel off, mostly toward the projection centre."
sidebar_label: "Costliest prop shapes"
---
# Parity: The Prop Shapes That Cost LOCATION and BOMB

* **Scope**: which prop shapes carry the `props` class of [`attribution.md`](attribution.md) on `location` and `bomb`, the two films it costs most, and why each loses; the 2026-11-22 baseline's `scenery-missing` ticks on `bomb` (1585, 1904; [historical readout](https://github.com/neilsh/stunt-reel/blob/ef237840/research/parity/readouts/bomb.json)) are sorted the same way.
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
| Pages a tick or two off ours while the camera moves; a row on the static opening shot | `bomb` 1648, 1650, 1737, 1654, 1754, 1756 on the opening shot (7% of its loss) | 2.2 | [#1064](https://github.com/neilsh/stunt-reel/issues/1064) (drawn, not remeasured), [#1033](https://github.com/neilsh/stunt-reel/issues/1033) |
| Overlapping spheres of one shape cover each other in list order | `bomb` 542, 545 | 2.3 | [#1066](https://github.com/neilsh/stunt-reel/issues/1066) |
| Far houses missing: the stand-ins' `BLOCK` houses went undrawn (fixed) | 2026-11-22 baseline: `bomb` `scenery-missing` 1585, 1904 | 2.4 | [#1032](https://github.com/neilsh/stunt-reel/issues/1032) |
| A run of frames prefers a one-tick offset | `location` 1745, 996 | 2.5 | [#1033](https://github.com/neilsh/stunt-reel/issues/1033) |
| Edges and chalk lines a pixel off, toward the projection centre, on a shape drawn in place | `location` 613 | 2.5 | [#1064](https://github.com/neilsh/stunt-reel/issues/1064) (drawn, not remeasured) |
| Lane dashes, outline lines, a pixel off, mostly toward the projection centre, on a shape drawn in place | `bomb` 1756 on ticks 2036 to 2740 and 3312 to 3477 (about 88% of its loss) | 2.6 | [#1064](https://github.com/neilsh/stunt-reel/issues/1064) (drawn, not remeasured) |

In the issue's terms, 2.1, 2.2 and 2.5 are misplacement by the camera or the projection, not by the prop; 2.3 is draw order for the trees; 2.4 was missing geometry; 2.6 is misplacement by the projection too.
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
On the static opening shots (ticks 12 to 420, where the fire station 1650 and church 1648 lose 0.040 to 0.043 a frame) the props sit a row low below the projection centre and level or a row high above it, as truncating toward the centre would place them (the rule is drawn since [#1064](https://github.com/neilsh/stunt-reel/issues/1064) and was not remeasured here), and the sky's band edges sit a row low.
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
The stadium 613 is drawn in place (best shift 0, 0.89 of its pixels match at 2729, no offset better than 0).

_Source: [the LOCATION canyon run steps late](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-location-canyon-run-steps-late), [what the canyon and BOMB frames show](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-what-the-canyon-and-bomb-frames-show)._

`[Bounded Observation]`, one film's 27 frames on the GPU: its loss sits at its edges, not on its chalk lines alone.
Giving the capture our index on a set of 613's pixels (a capture-side oracle, [`probes.md` § 7](probes.md#7-no-rebuild-experiments-on-the-capture)) removes, of 613's loss at 2729 and of its mean over the 27 frames it loses on (ticks 2586 to 2872; the GPU's 613 loss at 2729 is the canonical lavapipe's to 0.00001):

| 613's pixels given our index | At 2729 | Mean |
|---|---|---|
| every pixel of 613 | 68% | 81% |
| lines drawn by `ZLINETO` (the chalk) and by the outline ([`sod-vm-lines-spans.md` § 8.11](../playone-exe/sod-vm-lines-spans.md#811-polygon-spans-include-both-ends)) | 17% | 20% |
| those lines and the one-pixel band beside them | 54% | 60% |
| the chalk lines and their band | 16% | 18% |
| the interior, more than a pixel from any line | 13% | 17% |

The 32% (19%) that no pixel of 613 removes is the loss of windows over 613 whose other pixels, of the shapes, ground or sky beside it, still differ.
The chalk lines are drawn a pixel off rather than missing: 958 of the 1,003 chalk pixels whose index differs have the capture's line a pixel away.
On the lines and outlines the capture's matching pixel lies mostly a pixel toward the projection centre, the direction `PLAYONE`'s projectors truncate a vertex ([`sod-vm-lines-spans.md` § 8.14](../playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)).
#1027's prototype of that rule (its facet-plane form) cuts 613's loss by 39% at 2729 and 29% over the 27 frames, and its index disagreement from 8.9% to 5.9%, though it raises the outline pixels' own from 17.1% to 23.2%; the rule is drawn since #1064, in a form that differs from the prototype's (the world mesh and near-horizontal shape facets slide horizontally), and the per-shape losses here were not remeasured on it ([#1064](https://github.com/neilsh/stunt-reel/issues/1064)).

_Source: [the stadium's loss split by line, outline and fill](../../work/2026-11/1034_stadium-outlines/journal.md#2026-11-24-the-stadiums-loss-split-by-line-outline-and-fill), [the projector truncation prototype on the stadium](../../work/2026-11/1034_stadium-outlines/journal.md#2026-11-24-the-projector-truncation-prototype-on-the-stadium)._

### 2.6 The street's dashes are drawn a pixel off

`bomb` 1756, the street and the film's costliest prop shape, loses 7% of its loss on the opening shot (2.2) and 4% at 3302, the camera cut of [`attribution.md`](attribution.md) open question 7.
The other part, about 88%, falls on ticks 2036 to 2740 and 3312 to 3477, where the street is drawn in place (best whole-frame shift 0 or one column at nine ticks from 2190 to 3345) with 0.95 to 0.98 of its pixels in the capture's colour, yet it loses 0.020 to 0.066 a frame.

_Source: [the BOMB street 1756 loses in place](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-street-1756-loses-in-place)._

`[Bounded Observation]`, one film's 81 scored frames on those ranges, on the GPU at `4d5c01b0` (1756's film mean there, 0.0083005, rounds to #989's 0.00830 on the canonical lavapipe at `3e53f767`): the loss is the street's own lane dashes, not the shapes on it.
Windows wholly inside the street carry 68% of its loss on 2036 to 2740 and 51% on 3312 to 3477, and of those, windows where every pixel has the capture's index carry 0.0% and 0.1%, respectively.
Giving the capture our index on a set of pixels (the capture-side oracle of 2.5) removes, of 1756's summed loss on each range:

| Pixels given our index | 2036 to 2740 | 3312 to 3477 |
|---|---|---|
| every pixel of 1756 | 88% | 74% |
| its dash pixels where the capture and we swap the dash grey (index 52) and the street grey (14), 1.6% of its pixels | 74% | 48% |
| its other disagreeing pixels | 13% | 25% |
| every pixel not 1756's: the lots, trees, buildings, actors and ground beside it | 11% | 26% |

So windows straddling the street's edges charge it part of its neighbours' loss, 11% and 26% of its own: [#1035](https://github.com/neilsh/stunt-reel/issues/1035)'s hypothesis holds for that part and not for the bulk.
The dashes are outline lines: every line pixel of 1756 comes from the world's outline line list ([`sod-vm-lines-spans.md` § 8.11](../playone-exe/sod-vm-lines-spans.md#811-polygon-spans-include-both-ends)), and among its disagreeing outline pixels, the capture's dash lies mostly a row higher, toward the projection centre (7,374 against 496 below the centre), and a column to the right on both sides of the centre ([sheet](../../work/2026-11/1035_bomb-street-loss/images/bomb-2520-street-dashes.png)).
#1027's prototype of the truncation rule of 2.5 cuts 1756's loss by 37% on 2036 to 2740 and 22% on 3312 to 3477, about half of what the dashes own, and raises 71 of the 81 frames; the rule is drawn since #1064, in a form that differs from the prototype's (the world mesh and near-horizontal shape facets slide horizontally), and the per-shape losses here were not remeasured on it ([#1064](https://github.com/neilsh/stunt-reel/issues/1064)).
The horizontal offset, which is not toward the centre, and the rest of the dash mismatch are open with the outline pixels of [`sod-vm-lines-spans.md` § 10](../playone-exe/sod-vm-lines-spans.md#10-open-questions).

_Source: [the street's loss is in windows it fills alone](../../work/2026-11/1035_bomb-street-loss/journal.md#2026-11-24-the-streets-loss-is-in-windows-it-fills-alone), [the street's own pixels own its loss, its dashes most of it](../../work/2026-11/1035_bomb-street-loss/journal.md#2026-11-24-the-streets-own-pixels-own-its-loss-its-dashes-most-of-it), [the dashes are outline lines a pixel off](../../work/2026-11/1035_bomb-street-loss/journal.md#2026-11-24-the-dashes-are-outline-lines-a-pixel-off), [the projector truncation prototype on the street](../../work/2026-11/1035_bomb-street-loss/journal.md#2026-11-24-the-projector-truncation-prototype-on-the-street)._

## Ruled out

* **Windows straddling the edges of the shapes on `bomb`'s street 1756 as most of its loss in place** (2026-11-24): giving the capture our index on every pixel but the street's removes 11% of its loss on ticks 2036 to 2740 and 26% on 3312 to 3477 ([the street's own pixels own its loss, its dashes most of it](../../work/2026-11/1035_bomb-street-loss/journal.md#2026-11-24-the-streets-own-pixels-own-its-loss-its-dashes-most-of-it)).
* **The stadium 613's chalk lines as most of its loss** (2026-11-24): with the pixel band beside them they own 16% of its loss at `location` 2729 and 18% of its mean ([the stadium's loss split by line, outline and fill](../../work/2026-11/1034_stadium-outlines/journal.md#2026-11-24-the-stadiums-loss-split-by-line-outline-and-fill)).
* **The `scale_index` distance cut as the cause of `bomb`'s missing far houses** (2026-11-23): keeping every object it drops draws the same picture at 1585 and 1904 ([the BOMB far town is the level-of-detail gate](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-far-town-is-the-level-of-detail-gate)).
* **The near branch of every `SP_1NODE`** (2026-11-23): it draws the far houses but lowers `bomb` by 0.0118 and `location` by 0.0178, and the 2026-11-22 baseline's two `scenery-missing` ticks too ([same entry](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-far-town-is-the-level-of-detail-gate)).
* **The `SP_1NODE` gate's choice as the cause of `bomb`'s missing far houses** (2026-11-24): the gate's stand-ins hold the houses as `OP_BLOCK`s, which `vm.rs` did not draw ([the far town's stand-ins draw no `OP_BLOCK`](../../work/2026-11/1032_block-stand-ins/journal.md#2026-11-24-the-far-towns-stand-ins-draw-no-op_block)).
* **In-shape paint order for the canyon rock 1145 at `location` 7019** (2026-11-24): list order with `SORTON` swaps changes 20 of its 49,095 pixels ([list order explains the BOMB trees, not the canyon rock](../../work/2026-11/1030_close-shape-order/journal.md#2026-11-24-list-order-explains-the-bomb-trees-not-the-canyon-rock)).
* **Timing as the whole of the canyon run's loss** (2026-11-23): frames such as 7019 and 7317 rise by no more than 0.05 at any offset from -10 to +12 ([the LOCATION canyon run steps late](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-location-canyon-run-steps-late)); the held camera of 2.1 was the rest (7317 from 0.6509 to 0.9152).
* **A per-shot camera offset on `bomb`** (2026-11-24): no shot's offset follows the view slot, the eye or the lens; the opening shot's row flips sign about the projection centre, and the larger offsets are pages a tick or two off ours ([the offset per shot, against the camera](../../work/2026-11/1031_bomb-world-offset/journal.md#2026-11-24-the-offset-per-shot-against-the-camera)).

## Open questions

In order of the loss each would explain:

1. **What truncation toward the projection centre leaves** (drawn since [#1064](https://github.com/neilsh/stunt-reel/issues/1064), in a form that differs from the prototype's; the per-shape losses below were measured before it), on `bomb`'s opening shot: five of its eight worst shapes and 1756; on `location`, the stadium 613's edges and chalk lines (2.5); on `bomb`, the street 1756's lane dashes (2.6).
2. **Pages a tick or two off ours while the camera moves** ([#1033](https://github.com/neilsh/stunt-reel/issues/1033)).
3. **Spheres in list order** ([#1066](https://github.com/neilsh/stunt-reel/issues/1066)).
4. **One-tick phase** ([#1033](https://github.com/neilsh/stunt-reel/issues/1033)).
