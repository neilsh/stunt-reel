---
summary: "Ranks the prop shapes costing LOCATION's and BOMB's props loss and why each loses: a late canyon camera step, per-shot camera offsets, in-shape cover order, far-town stand-ins, tick phase, lines; most of BOMB's street loss is unexplained."
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
| Canyon camera steps reach the capture 1 to 3 ticks early | `location` 1145, 1164, 1179, 1162, 1150 (in part) | 2.1 | [#1029](https://github.com/neilsh/stunt-reel/issues/1029) |
| The whole frame is off by 1 to at least 4 px, per shot | `bomb` 1648, 1650, 1737, 1654, 1754, 1756 on the opening shot (7% of its loss); `[Hypothesis]` `location` 1150 at 2212 | 2.2 | [#1031](https://github.com/neilsh/stunt-reel/issues/1031) |
| Overlapping polygons of one close shape cover each other in another order | `location` canyon rocks; `bomb` 542, 545 | 2.3 | [#1030](https://github.com/neilsh/stunt-reel/issues/1030) |
| Far houses missing: the level-of-detail stand-ins | `bomb` `scenery-missing` 1585, 1904 | 2.4 | [#1032](https://github.com/neilsh/stunt-reel/issues/1032) |
| A run of frames prefers a one-tick offset | `location` 1745, 996 | 2.5 | [#1033](https://github.com/neilsh/stunt-reel/issues/1033) |
| Lines and outlines on a shape drawn in place | `location` 613 | 2.5 | [#1034](https://github.com/neilsh/stunt-reel/issues/1034) |
| Unexplained: drawn in place, in the capture's colours | `bomb` 1756 on ticks 2036 to 2740 and 3312 to 3477 (89% of its loss) | 2.6 | [#1035](https://github.com/neilsh/stunt-reel/issues/1035) |

In the issue's terms, 2.1, 2.2 and 2.5 are misplacement by the camera, not by the prop; 2.3 is draw order; 2.4 is missing; 2.6 has no cause yet.
No shape inspected shows a wrong shade or a wrong shape of its own.

### 2.1 The canyon run steps late

Between ticks 6713 and 7150 of `location` our render changes only every 10 ticks (6731, 6741, …, 7141, and a few ticks beside 6771, 6891 and 7011; every tick hashed), and on the frames that straddle a step the capture already shows the next one, 1 to 3 ticks before we do.
Relabelling our render later by that much raises the frames that straddle a step: 7184 from 0.723 to 0.923, 7030 from 0.741 to 0.880, 6920 from 0.778 to 0.881; the mean of the 64 scored frames from 6700 to 7400 rises from 0.8312 to 0.8542 at +3, and earlier offsets lower it.
Before the run, offset 0 is best on 8 of 10 frames, so this is a rule of the stepped run, not a film-wide lag; which record `PLAYONE` shows on such a run is [#1029](https://github.com/neilsh/stunt-reel/issues/1029).

_Source: [the LOCATION canyon run steps late](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-location-canyon-run-steps-late)._

### 2.2 The camera is off by a few pixels per shot

The `bomb` buildings and lots 1648, 1650, 1737 and 1654 are drawn in the capture's colours (0.89 to 0.95 of their pixels match in place at the ticks examined), so their loss sits at their edges; the road 1754 matches 0.81 at 2961, where the frame is furthest off.
The whole frame is displaced: ours a row low on the opening shot (ticks 155 and 233, where the fire station 1650 and church 1648 lose 0.040 to 0.043 a frame), two rows low at 3191, three rows high and a column left at 3268, and at least four columns left at 2961 (four is the search's limit).
The offset changes between shots, unlike the rigid offset ruled out for whole films in [`attribution.md`](attribution.md#ruled-out).
`[Hypothesis]`: on `location` tick 2212 the crater 1150's near rim differs in outline and no whole-frame shift fixes it (0.730, 0.741 at the best shift), which the camera moving differently during the shot would explain; a shape or cover-order difference would too, and these frames do not tell them apart.
Which camera input the offsets follow is [#1031](https://github.com/neilsh/stunt-reel/issues/1031).

_Source: [what the canyon and BOMB frames show](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-what-the-canyon-and-bomb-frames-show)._

### 2.3 Close shapes cover their own polygons differently

`[Hypothesis]`: on canyon frames no tick offset raises (7019, 7317), our depth buffer shows a near face of the rock where the capture shows farther facets of the same shape ([sheet](../../work/2026-11/989_props-loss-shapes/images/location-7019.png)), and the `bomb` autumn trees sit in place but their leaf clusters cover each other differently (0.67 to 0.68 of their pixels match).
`PLAYONE` paints a shape's polygons in display-list order ([`render-model.md`](render-model.md) § 2), which would explain both; no render in that order was made for these frames, and the whole-scene painters of [`painter-order.md`](painter-order.md) ordered by node, not by polygon.
Testing it is [#1030](https://github.com/neilsh/stunt-reel/issues/1030).

_Source: [what the canyon and BOMB frames show](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-what-the-canyon-and-bomb-frames-show)._

### 2.4 The far town draws no houses

At `bomb` ticks 1585 and 1904 the capture draws the distant town's houses; ours draws lots, roads and trees there ([sheet](../../work/2026-11/989_props-loss-shapes/images/bomb-1904-lod.png)).
Keeping the near branch of every `SP_1NODE` ([`lod.md`](../playone-exe/lod.md)) draws houses there, so our gate shows stand-ins where the capture shows houses; lifting the `scale_index` distance cut draws the same picture at both ticks.
The near branch everywhere lowers both films (`bomb` 0.8949 to 0.8831, `location` 0.8728 to 0.8549) and those two ticks too, so whether the gate's choice or our stand-ins are wrong is [#1032](https://github.com/neilsh/stunt-reel/issues/1032).

_Source: [the BOMB far town is the level-of-detail gate](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-far-town-is-the-level-of-detail-gate)._

### 2.5 One-tick phase and lines

The railway track 1745, which the camera rides along, rises over ticks 4330 to 4470 from 0.8939 to 0.9076 one tick later; the town lots 996 over 2040 to 2140 from 0.7887 to 0.8044 one tick earlier.
Over the whole film a one-tick offset helps frames in both directions (+1 raises 49 frames by more than 0.02, -1 raises 101) while offset 0 keeps the best mean, so which pages show another tick is [#1033](https://github.com/neilsh/stunt-reel/issues/1033).
The stadium 613 is drawn in place (best shift 0, 0.89 of its pixels match at 2729, no offset better than 0); `[Hypothesis]`: its loss is the field's chalk lines and the stands' outlines ([`sod-vm-lines-spans.md` § 10](../playone-exe/sod-vm-lines-spans.md#10-open-questions)), measured by [#1034](https://github.com/neilsh/stunt-reel/issues/1034).

_Source: [the LOCATION canyon run steps late](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-location-canyon-run-steps-late), [what the canyon and BOMB frames show](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-what-the-canyon-and-bomb-frames-show)._

### 2.6 The street loses in place, unexplained

`bomb` 1756, the street and the film's costliest prop shape, loses 7% of its loss on the opening shot (2.2) and 4% at 3302, the camera cut of [`attribution.md`](attribution.md) open question 7.
The other 89%, on ticks 2036 to 2740 and 3312 to 3477, has no cause found: at nine ticks from 2190 to 3345 the street is drawn in place (best whole-frame shift 0 or one column, raising agreement by at most 0.014) with 0.95 to 0.98 of its pixels in the capture's colour, yet it loses 0.020 to 0.066 a frame.
`[Hypothesis]`: each pixel takes a share of every SSIM window's loss over it ([`report-fields.md`](report-fields.md)), so windows straddling the edges of the lots, trees and buildings on the street charge part of their loss to it; testing it is [#1035](https://github.com/neilsh/stunt-reel/issues/1035).

_Source: [the BOMB street 1756 loses in place](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-street-1756-loses-in-place)._

## Ruled out

* **The `scale_index` distance cut as the cause of `bomb`'s missing far houses** (2026-11-23): keeping every object it drops draws the same picture at 1585 and 1904 ([the BOMB far town is the level-of-detail gate](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-far-town-is-the-level-of-detail-gate)).
* **The near branch of every `SP_1NODE`** (2026-11-23): it draws the far houses but lowers `bomb` by 0.0118 and `location` by 0.0178, and the two `scenery-missing` ticks too ([same entry](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-bomb-far-town-is-the-level-of-detail-gate)).
* **Timing as the whole of the canyon run's loss** (2026-11-23): frames such as 7019 and 7317 rise by no more than 0.05 at any offset from -10 to +12 ([the LOCATION canyon run steps late](../../work/2026-11/989_props-loss-shapes/journal.md#2026-11-23-the-location-canyon-run-steps-late)).

## Open questions

In order of the loss each would explain:

1. **The canyon step rule** ([#1029](https://github.com/neilsh/stunt-reel/issues/1029)).
2. **The per-shot camera offset** ([#1031](https://github.com/neilsh/stunt-reel/issues/1031)), which touches five of `bomb`'s eight worst shapes and 1756's opening shot.
3. **The street's loss in place** ([#1035](https://github.com/neilsh/stunt-reel/issues/1035)), 89% of `bomb`'s costliest shape.
4. **In-shape paint order** ([#1030](https://github.com/neilsh/stunt-reel/issues/1030)).
5. **The far town's stand-ins** ([#1032](https://github.com/neilsh/stunt-reel/issues/1032)).
6. **One-tick phase** ([#1033](https://github.com/neilsh/stunt-reel/issues/1033)) and **the stadium's lines** ([#1034](https://github.com/neilsh/stunt-reel/issues/1034)).
