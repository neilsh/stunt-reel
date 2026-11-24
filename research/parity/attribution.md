---
summary: "Splits the SSIM loss of the seven VAULT reference films by render layer: props lead on four and terrain on two, BALLOON's low mask IoU came from a straight-down camera we drew blank and a zenith sky outside the scorer's band, both since fixed, and a pre-decal CTRY window study puts most loss at edges, not flat colour."
sidebar_label: "Attribution: where our loss sits"
---
# Parity Attribution: Where Our Render's Loss Sits

`[Bounded Observation]`: one capture set per film, 114 scored `CTRY.FLM` frames and 209 scored `INTRO.FLM` frames.
The measuring loop is in [`method.md`](method.md); every figure has a dated record, a journal entry or, for earlier figures, a row of the [parity log](../../work/2026-10/parity-log/log.md).
Framing: [`framing-and-actors.md`](framing-and-actors.md); hero aircraft: [`hero-aircraft-placement.md`](hero-aircraft-placement.md); ground shading: [`../playone-exe/terrain-shade.md`](../playone-exe/terrain-shade.md).

## 1. Method: loss by render layer

`stuntreel parity` splits each SSIM window's loss (`1 - ssim`) among the render layers of its pixels in proportion to pixel count (`mean_loss_by_class_scored` in `report.json`); the classes sum to `1 - mean_ssim_scored`.
Layer ids in the layer plane: 1 ocean, 2 terrain (`MAP.BIN` patches), 3 props (`SCENERY.scn` placements), 16+n actor draw n of the frame (draw order, not film slot).
A shape plane beside it names the prop shape that drew each props pixel, and `mean_loss_by_shape_scored` splits the props class by shape id the same way; its values sum to `mean_loss_by_class_scored.props` ([`report-fields.md`](report-fields.md)).
Each placed prop mesh appends its own run of world vertices, listed with its shape in `World::prop_runs`, and the plane's fragment shader finds a fragment's run from its `vertex_index` by binary search, so every placed shape is attributed.
_Source: [can `primitive_index` or `vertex_index` give a world fragment its prop](../../work/2026-11/809_prop-runs/journal.md#2026-11-19-can-primitive_index-or-vertex_index-give-a-world-fragment-its-prop)._
Extra classes: reference-only (capture non-sky, render sky) and render-only (the reverse).
Windows touching the UI overlay are excluded.

* Attribution is by what **our render** draws, not by what is missing.
  In the worst early props frame (ordinal 41, tick 448, SSIM 0.515) the capture shows the hero biplane and its shadow while our render shows faint struts over flat dark ground, so the loss lands on the ground class.
  The actors class therefore **understates** the aircraft's cost (see [`hero-aircraft-placement.md`](hero-aircraft-placement.md)).
* The index plane is unlit, so the split says where loss is, not that a palette index is wrong.
* Coverage is largely right (CTRY mask IoU 0.978 after the decal and page-timing changes); the loss is how covered ground and props are shaded, textured and bounded.

_Found 2026-10-22; see the [loss attribution row](../../work/2026-10/parity-log/log.md)._

## 2. Current breakdown

The current loss by class is pinned, not copied here: each `[<film>.loss]` table of [`expected/<class>.toml`](expected/) holds a report's `mean_loss_by_class_scored` for one renderer class, written by `mise run parity-repin` and read back by `mise run judge`, which prints a candidate's change in each class from the baseline's and from the pin ([`method.md`](method.md) step 0).
Both the `lavapipe` and `gpu` tables hold the split on the `crates` tree their `crates` line names.
Read a film's classes there; the table below is a dated record and does not follow the pins.

`[Bounded Observation]`, one render per film on the RTX 4070, `main` at `76872e89` (2026-11-16), each film scored against the capture `references.toml` pins.
Loss by class, with its share of `1 - mean_ssim_scored`; classes under 0.001 left out:

| Film | SSIM | IoU | Scored | props | terrain | actors | sky | reference-only | ocean |
|---|---|---|---|---|---|---|---|---|---|
| `ctry` | 0.9185 | 0.9910 | 114 | **0.0402** (49%) | 0.0117 (14%) | 0.0074 (9%) | 0.0153 (19%) | 0.0064 (8%) | — |
| `intro` | 0.8535 | 0.9863 | 209 | **0.0503** (34%) | 0.0303 (21%) | 0.0350 (24%) | 0.0197 (13%) | 0.0065 (4%) | 0.0041 (3%) |
| `land` | 0.8932 | 0.9852 | 97 | 0.0319 (30%) | **0.0337** (32%) | 0.0147 (14%) | 0.0147 (14%) | 0.0093 (9%) | 0.0015 (1%) |
| `balloon` | 0.8174 | 0.6409 | 107 | 0.0015 (1%) | 0.0310 (17%) | 0.0376 (21%) | 0.0095 (5%) | **0.1014** (56%) | 0.0011 (1%) |
| `traintnl` | 0.8599 | 0.9659 | 112 | 0.0343 (24%) | **0.0356** (25%) | 0.0224 (16%) | 0.0223 (16%) | 0.0215 (15%) | 0.0037 (3%) |
| `bomb` | 0.8444 | 0.9118 | 316 | **0.0741** (48%) | 0.0221 (14%) | 0.0141 (9%) | 0.0248 (16%) | 0.0126 (8%) | 0.0075 (5%) |
| `location` | 0.8292 | 0.9784 | 732 | **0.0845** (49%) | 0.0363 (21%) | 0.0098 (6%) | 0.0171 (10%) | 0.0093 (5%) | 0.0129 (8%) |

* **Props are the largest class on four films** (`ctry`, `intro`, `bomb`, `location`), about half the loss on three of them.
  Terrain leads on `land` and `traintnl`, with props 0.0018 and 0.0013 behind it.
* **`balloon` is the exception**: more than half its loss is reference-only, capture geometry where our render draws sky, and 98% of it sits on two runs of frames: 86% on the straight-down run and 12% on the zenith-sky run (section 7).
* **Since the 2026-11-04 run**, props and terrain fell on `ctry` and `intro` and actors on `intro`, over many changes, so the split attributes the fall to none of them.
  _Source: [the fall since the decal run](../../work/2026-11/distill-attribution/journal.md#2026-11-16-the-fall-since-the-decal-run)._

**Worst prop shapes** (`mean_loss_by_shape_scored`).
`[Bounded Observation]`, one render per film on lavapipe, `crates/` tree `b228018` (#821 on `main` at `581d811`), so newer code and another renderer than the table above.
Each row is a shape's mean loss over the scored frames and its share of that film's `props` loss (`location` 0.0839, `bomb` 0.0740, `ctry` 0.0401); the ten worst shapes, then what they hold together.
Every placed shape is attributed (section 1), so no reference film has an `unattributed` share; the `props` loss falls on 1,014 shapes on `location`, 127 on `bomb` and 91 on `ctry`.

| Rank | `location` shape | Loss (share) | `bomb` shape | Loss (share) | `ctry` shape | Loss (share) |
|---|---|---|---|---|---|---|
| 1 | 1610 | 0.0035 (4.2%) | 1756 | 0.0161 (21.7%) | 926 | 0.0129 (32.1%) |
| 2 | 1145 | 0.0017 (2.0%) | 1650 | 0.0078 (10.5%) | 917 | 0.0054 (13.5%) |
| 3 | 1745 | 0.0016 (1.9%) | 1737 | 0.0078 (10.5%) | 880 | 0.0024 (5.9%) |
| 4 | 1150 | 0.0016 (1.9%) | 545 | 0.0044 (5.9%) | 610 | 0.0020 (5.0%) |
| 5 | 613 | 0.0014 (1.7%) | 1648 | 0.0038 (5.1%) | 928 | 0.0017 (4.3%) |
| 6 | 996 | 0.0014 (1.6%) | 1754 | 0.0037 (5.0%) | 927 | 0.0016 (3.9%) |
| 7 | 1164 | 0.0013 (1.6%) | 542 | 0.0023 (3.1%) | 915 | 0.0014 (3.6%) |
| 8 | 1179 | 0.0013 (1.5%) | 1654 | 0.0023 (3.1%) | 914 | 0.0010 (2.5%) |
| 9 | 1984 | 0.0012 (1.4%) | 1637 | 0.0018 (2.4%) | 920 | 0.0010 (2.4%) |
| 10 | 1162 | 0.0012 (1.4%) | 1716 | 0.0016 (2.2%) | 913 | 0.0009 (2.3%) |
| Ten worst | | 0.0161 (19.2%) | | 0.0514 (69.4%) | | 0.0303 (75.6%) |

* **`bomb` and `ctry` concentrated** their props loss on that run, before the 0.1 m near plane: three shapes hold 43% of `bomb`'s (1756, 1650, 1737) and two hold 46% of `ctry`'s (926, 917).
  `location` spreads its `props` loss over 1,014 shapes, the worst (1610) holding 4.2% of it and the ten worst 19.2%, so a fix aimed at one of them moves `location` little.
* The split says which shapes carry the loss, not why; a shape's pixels share SSIM windows with its neighbours, so its figure includes loss its surroundings cause, as the class split does (section 1).
* On a later tree, `location`'s and `bomb`'s worst shapes and why each loses are in [`prop-shape-loss.md`](prop-shape-loss.md).

**Why the two worst shapes lose.**
`[Bounded Observation]`, GPU, `main` at `581453ed` (2026-11-21).

* **Most of `ctry` 926's loss lies around the actors.**
  It is the airfield grass tile `SCENERY2.RES` #157 ([`world-scene.md` § 3](../playone-exe/world-scene.md#3-scenery-shapes-drawn-over-the-ground)); its own pixels match the capture's index on 99%, and correcting only the 4.7% of the frame within 4 px of the actors and shadows removes 72% of its loss.
  So most of it lies in windows it shares with the hero aircraft and shadows ([`hero-aircraft-placement.md`](hero-aircraft-placement.md), [`hero-shadow.md`](hero-shadow.md)).
* **`bomb` 1756 was the street under a missing car.**
  On ticks 1915 to 2048, 47% of its loss, the old 0.5 m near plane cut away the police car's door; the 0.1 m default since [#904](https://github.com/neilsh/stunt-reel/issues/904) draws it, leaving 1756 at 0.0084.
  `PLAYONE`'s polygon clipper has no near plane ([`sod-vm-lines-spans.md` § 8.13](../playone-exe/sod-vm-lines-spans.md#813-the-clip-volume-has-no-near-plane)), but no nearer plane scored clearly better (Ruled out); lowering it against `Depth24Plus`'s precision is [#955](https://github.com/neilsh/stunt-reel/issues/955).
  Another 3% is tick 3302's camera cut (open question 7).

_Source: [why the two worst shapes lose, as first written](../../work/2026-11/distill-attribution/journal.md#2026-11-22-why-the-two-worst-shapes-lose-as-first-written)._

_Source: [every prop shape attributed on the seven references](../../work/2026-11/809_prop-runs/journal.md#2026-11-20-every-prop-shape-attributed-on-the-seven-references)._

_Source: [loss by render layer on the seven VAULT references](../../work/2026-11/477_vault-attribution/journal.md#2026-11-16-loss-by-render-layer-on-the-seven-vault-references)._

### What earlier runs established

Earlier runs, each on its own `main`, established:

* **The ground decals moved loss from terrain to props.**
  Drawing ground-lying props as terrain decals ([ADR 0035](../../docs/adr/0035-ground-lying-props-are-terrain-decals.md), [#69](https://github.com/neilsh/stunt-reel/issues/69)) cut terrain from 0.0772 to 0.0186 on CTRY and from 0.0941 to 0.0439 on INTRO, and raised props from 0.0553 to 0.0793 and from 0.0530 to 0.0808, because the airfield and sand tiles the terrain hid are now drawn and their remaining error is attributed to props (section 1); the total loss fell.
  The tile pixels were most of section 4's off-ramp ground.
  _Source: [loss by class after the ground decals](../../work/2026-11/distill-attribution/journal.md#2026-11-04-loss-by-class-after-the-ground-decals)._
* **Props loss is not the in-shape `IFVIS` branch**: the `IFVIS` facing gate of [#74](https://github.com/neilsh/stunt-reel/issues/74) moved props CTRY 0.0793 -> 0.0793 and INTRO 0.0808 -> 0.0806, its INTRO gain falling on the aircraft (actors 0.0439 -> 0.0431).
  Nor, on the paths the census walks, `BZLT`, `BVIS`, `REJVEC` or `REJ2D` (Ruled out; [`sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) section 8.6, [#235](https://github.com/neilsh/stunt-reel/issues/235)).
  _Source: [the IFVIS facing gate and the props class](../../work/2026-11/distill-attribution/journal.md#2026-11-05-the-ifvis-facing-gate-and-the-props-class)._
* **Props loss is not the `SHADES` light**: shading scenery alone with the world light ([#221](https://github.com/neilsh/stunt-reel/issues/221)) scores the same as the old stand-in to four decimals.
  The world light and per-vertex `GVPOLY` interpolation of #221 moved props CTRY 0.0793 -> 0.0794 and INTRO 0.0806 -> 0.0770, and actors 0.0133 -> 0.0135 and 0.0431 -> 0.0308; the INTRO props drop is most likely SSIM windows shared with the aircraft (`[Supported Inference]`).
  _Source: [the world light and GVPOLY interpolation](../../work/2026-11/distill-attribution/journal.md#2026-11-05-the-world-light-and-gvpoly-interpolation)._
* **Actors are lit by `R · L`**, their rotation times the world light ([`terrain-shade.md`](../playone-exe/terrain-shade.md) section 4.3), not by the unturned world light.
  It raised `INTRO` and moved no other film by more than 0.0002; the object-frame `Rᵀ · L` gains about half as much on `INTRO`.
  _Source: [lighting actors by R · L](../../work/2026-11/474_actor-light/journal.md#2026-11-16-lighting-actors-by-r--l), [the frames R · L lowers](../../work/2026-11/474_actor-light/journal.md#2026-11-16-the-frames-r--l-lowers)._
* **Drawing the aircraft whole moved loss from terrain to actors.**
  With the whole-body aircraft of [#47](https://github.com/neilsh/stunt-reel/pull/47) and the ramp colour of [#48](https://github.com/neilsh/stunt-reel/pull/48), actors rose from 0.0035 to 0.0122 on CTRY and from 0.0081 to 0.0381 on INTRO: a missing body cost the terrain class, and a drawn but miscoloured or misplaced one costs the actors class (section 1).
  The projection of [#132](https://github.com/neilsh/stunt-reel/pull/132) left actors nearly there while props and terrain fell.
  On its error readout only INTRO `aircraft-parts-missing` (11 -> 5) cleared grader noise ([`metric-bench.md`](metric-bench.md) § 2.3).
  _Source: [loss by class after #47, #48 and #132](../../work/2026-11/distill-attribution/journal.md#2026-11-02-loss-by-class-after-47-48-and-132)._
* **The CTRY-derived fixes transfer to INTRO**: on the first INTRO baseline, index agreement was 0.482 against CTRY's 0.472, so the unlit colours and the 185-row viewport are not CTRY artefacts.
  _Source: [the early CTRY and INTRO breakdowns](../../work/2026-11/distill-attribution/journal.md#2026-10-22-the-early-ctry-and-intro-breakdowns-superseded)._

## 3. The loss is structural: edges, not flat colour

Recomputing the comparator's 11x11/stride-8 windows in Python over the 93 CTRY frames above the fade that still use the full palette: 70% of the total window loss sits in windows whose capture luminance standard deviation is above 10, 17% in flat windows (sd < 2) and 12% in between.
Terrain-major windows (80% or more terrain pixels) are 55% of all windows and carry 39% of the loss, 75% of that at edges.
Windows touching an actor carry 13%.
A uniform colour error explains little; the horizon, hills, prop silhouettes, coastline, shadow and aircraft account for nearly all of it.
(Absolute SSIM differs from `report.json` because this run uses the index plane and the static palette; read the shares.)

_Found 2026-10-23 at `d90a047`; see the [parity log](../../work/2026-10/parity-log/log.md)._

## 4. Flat ground owns most of the loss

Oracle, not a realisable gain: repainting the capture pixels where our render is flat terrain (layer 2, index 195) to index 195 and re-scoring gives CTRY 0.7732 -> **0.8225** (+0.0493) and INTRO 0.6799 -> **0.7492** (+0.0693); index agreement 0.505 -> 0.822 and 0.534 -> 0.713.
It forces the capture to agree with the render even where the capture draws something else.

Split by what the capture draws there:

| Repainted capture pixels | CTRY | INTRO |
|---|---|---|
| green ramp 192-199 only (repaintable shade) | 0.7837 (+0.0105) | 0.6828 (+0.0029) |
| off-ramp only | 0.8038 (+0.0306) | 0.7374 (+0.0575) |

Off the ramp, the capture draws the missing beach surface plus the aircraft and its shadow on CTRY, not a colour error, and the montage's sand flats on INTRO.
_Source: [the off-ramp capture indices](../../work/2026-11/distill-attribution/journal.md#2026-10-23-the-off-ramp-capture-indices)._

The levers this split pointed to, the ground shade and the surfaces the capture draws where we draw airfield green, were answered 2026-11-04: the green-ramp shade and much of the off-ramp ground are scenery tiles (`SCENERY2.RES` #144-159 and others) that `PLAYONE` paints over its flat ground leaves and that our depth test hid under the terrain.
_Source: [the reading before the decals](../../work/2026-11/distill-attribution/journal.md#2026-10-23-the-flat-ground-levers-as-first-read)._
`PLAYONE` puts no shade law on the ground ([`world-scene.md`](../playone-exe/world-scene.md) sections 2, 3).
They are now drawn as terrain decals (section 2).

_Found 2026-10-23; see the [parity log](../../work/2026-10/parity-log/log.md)._

## 5. Coastline and sea

* **The sand band was misplaced before the decals.**
  At `d90a047` the 20 highest-loss windows in sampled CTRY frames were beach or shoreline in the horizon band, and most capture sand pixels (88 and 91) fell on our colour-195 airfield at a median ray distance of 29 m: a near-field surface the capture painted sand and we painted green.
  `[Unknown]`: which prop owns the band; the sand tiles have since been drawn as terrain decals (section 4), and the band has not been re-measured.
  _Source: [the coastline sand band](../../work/2026-11/distill-attribution/journal.md#2026-10-23-the-coastline-sand-band)._
* **Ocean colour is right; the sea is wrong by coverage.**
  Under our ocean pixels 544,029 of 655,011 INTRO capture pixels are index 208, the colour we draw; only 4,533 CTRY pixels are ocean at all.
  The ocean-class loss on ticks 2790/2800 (0.209) is structural: 50,615 of those pixels are capture sand (91) where we draw sea.
* **The land/sea boundary is nearly right.**
  The capture draws ocean where we draw land on 3,699 CTRY pixels (0.05%) and 41,233 INTRO pixels (0.33%); we draw airfield green where the capture is ocean on 1,997 and 8,388.
  A distance cull of terrain patches would move very few pixels and was not attempted.

_Found 2026-10-23 at `d90a047`; see the [parity log](../../work/2026-10/parity-log/log.md)._

## 6. Back faces

The player culls back faces: its polygon fillers skip a row whose right end is left of its left, and the span builder takes the left end from the vertex list walked backward and the right end from it walked forward (`[Established]`, static; none of the polygon routines read computes a facing, [`sod-vm-lines-spans.md` § 8.12](../playone-exe/sod-vm-lines-spans.md#812-back-faces-the-span-test)).
So a polygon wound anticlockwise on screen loses its fill and its inclusive ends together, apart from the rows of a lone top or bottom vertex, rows narrower than its edges' runs, and edge-on polygons, which draw as lines (`[Hypothesis]`, read from the instructions, not traced).
Our renderer culls the same side since 2026-10-24: our models wind clockwise for their outward faces, so it draws with `FrontFace::Cw` and `Face::Back`; the `FrontFace::Ccw` default drew a prop's or the hero aircraft's inside when the camera flew through it.
`[Bounded Observation]`: culling raised CTRY and INTRO SSIM by 0.0075 and 0.0049, mostly on the actors class (its loss fell 0.0048 and 0.0059), with IoU unchanged; one frame regressed, CTRY tick 832 (0.710 -> 0.681), where the removed interior exposes an actor surface the capture does not show.
_Source: [the back-face culling sweep](../../work/2026-11/distill-attribution/journal.md#2026-10-24-the-back-face-culling-sweep)._
The two-sided flag (`SodVertex::flags` bit 1) has no known writer, so the culling cannot yet exempt a two-sided polygon; it is an open question in [sod-vm.md](../playone-exe/sod-vm.md), not one here, since the tick-832 regression it was meant to repair is worth about 0.0003 of the film mean.
_Source: [the flag moved out](../../work/2026-11/distill-attribution/journal.md#2026-10-24-the-two-sided-flag-moved-out-of-the-open-questions)._

Per-frame shapes' outlines are culled with their polygon, by the winding of the triangle each outline corner belongs to (in the GPU vertex shader), with two exemptions.
A triangle under 1 px² of screen area keeps its outline: seen edge-on (a rotor blade, a strut) the exemption removes the dashes and the slivers running to the screen centre that the cull drew on `location:1112` (`[Bounded Observation]`, GPU and lavapipe); that its winding is rounding error, differing between the corners of one outline quad and between its three edges, is the inference those artefacts fit (`[Hypothesis]`, not traced).
This area test is not `PLAYONE`'s: its fillers keep a back face's row where its edges' runs cross (section 8.12 of the note above, `[Hypothesis]`), so the area test is an approximation of that rule that is not traced against `PLAYONE`.
A width test instead (under 1 px tall over its longest edge) is not told apart from it: on the 135 pixels the two draw differently in the 13 frames searched, the capture sides with each about as often (`[Bounded Observation]`, GPU).
_Source: [the captures searched for a back-face sliver](../../work/2026-11/858_outline-cull-width/journal.md#2026-11-20-the-captures-searched-for-a-back-face-sliver)._
A shadow's outline is not culled: the shadow pipeline culls no face, so its fill shows both windings and a culled outline thinned the rim (`[Bounded Observation]`: `intro:1090`).
The cull is adopted on the evidence-backed track, citing the fillers' row test at `0x75A1`, `0x7612` and `0x76DC` and the span builder's walk order (`[Established]`, static); that `PLAYONE` culls the outline with the polygon is `[Hypothesis]`, since no routine read computes a facing but the vertex transform and projection were not read ([`sod-vm-lines-spans.md` § 8.12](../playone-exe/sod-vm-lines-spans.md#812-back-faces-the-span-test)). It moves no film's mean SSIM by more than 0.000014 on the GPU, under the 0.002 adoption bound, so the score does not attribute it.
_Source: [the outline cull judged on the evidence track](../../work/2026-11/717_outline-cull/journal.md#2026-11-20-the-outline-cull-judged-on-the-evidence-track) and [the two exemptions the fix round added](../../work/2026-11/717_outline-cull/journal.md#2026-11-20-the-two-exemptions-the-fix-round-added)._

## 7. BALLOON's mask IoU: two runs of frames

`[Bounded Observation]` for the runs and their figures, one render on the RTX 4070 at `76872e89`.
Before 2026-11-18 (the positional sky rule below), `balloon`'s `mean_iou_scored` was 0.6409 while the other six references scored 0.91 to 0.99.
Of its 107 scored frames, 41 score IoU under 0.5 and every other frame scores 0.965 or more (median 0.980).
The 41 fall in two runs:

* **Ticks 12 to 254 (23 frames): the zenith sky is outside the scorer's sky band.**
  The camera looks up at the balloon, and the capture paints the sky 224, then 225 and 226 as the view comes down; our render paints it 228.
  The mask then counted only 227 to 238 as capture sky (`CAPTURE_SKY_INDICES`, section 2.0 of [`method.md`](method.md)), so the capture's whole sky counted as geometry: IoU 0.134 on average while SSIM stays 0.889.
  `PLAYONE` writes entries 224 to 238 as one sky gradient, zenith to horizon ([`palette-fade.md`](../playone-exe/palette-fade.md) section 3.1, a static reading matched against `CTRY` captures at entries 224, 233 and 238).
  The same frames show the sun disc, 1,746 pixels of index 239, which our render does not draw; `0x908E` projects it from the variable-13 vector (same note, section 3.2). ([picture](../../work/2026-11/477_vault-attribution/images/balloon-155-zenith-sky-and-sun.png))
* **Ticks 606 to 793 (18 frames): our render draws nothing.**
  The authored camera looks straight down (eye and target share x and z; `render.json` holds that camera from tick 601 to 796, field of view 8.3 degrees).
  The capture shows the balloon from above over grass; our layer plane is empty and every pixel is sky index 238, so IoU is 0 and SSIM 0.480 on average.
  The view matrix took up `Vec3::Y`, undefined for a view parallel to it; since [#615](https://github.com/neilsh/stunt-reel/issues/615) a view along ±Y takes up `+Z` and the frames draw, turned as the capture's are (`[Bounded Observation]`, `balloon` only); the figures in this section are from before that fix. ([picture](../../work/2026-11/477_vault-attribution/images/balloon-606-straight-down-camera.png))

Of the seven references' cameras only `balloon`'s and `intro`'s point straight down, and `intro`'s only on frames faded to black and unscored.
Widening the capture sky to 224..=238 raises `bomb` 0.9118 -> 0.9540 but lowers `traintnl` 0.9659 -> 0.9608, because shapes paint 224 to 226 too, so the scorer keeps 227..=238 as its index band ([`method.md`](method.md) section 2.0).
_Source: [who paints 224 to 226 in the captures](../../work/2026-11/616_capture-zenith-sky/journal.md#2026-11-18-who-paints-224-to-226-in-the-captures)._
Since 2026-11-18 the zenith sky counts as sky by position, including the sky the balloon cuts off; the figures above are on the scale before that ([`method.md`](method.md) section 2.0).
Since 2026-11-20 the renderer draws the sky as the sky drawer `0x8C45` does, with the sun disc and the variable-13 light ([`palette-and-shading.md`](../formats/concepts/palette-and-shading.md#sky-bands), Sky Bands; [`palette-fade.md` § 3.2](../playone-exe/palette-fade.md#32-other-readers-of-the-live-variables)).
On the RTX 4070, `balloon`'s SSIM rose from 0.8842 to 0.9057 and its IoU stayed 0.8978, because the scorer still counted the capture's disc as geometry and ours as sky ([#844](https://github.com/neilsh/stunt-reel/issues/844)); scoring the disc and the fill as sky raises it by 0.0522 ([section 2.0](method.md#20-sky-mask-and-iou-scale)).
_Source: [draw the read sky, disc and light, scored on the GPU](../../work/2026-11/617_zenith-bands-sun-disc/journal.md#2026-11-20-draw-the-read-sky-disc-and-light-scored-on-the-gpu)._
_Source: [scoring the sun disc and the sky fill as sky](../../work/2026-11/844_score-sky-as-sky/journal.md#2026-11-20-scoring-the-sun-disc-and-the-sky-fill-as-sky)._

_Source: [what drives BALLOON's mask IoU](../../work/2026-11/477_vault-attribution/journal.md#2026-11-16-what-drives-balloons-mask-iou)._

## Ruled out

* **Global framing offset** (2026-10-23): shifting the capture rigidly by rows or columns against unchanged renders, both films are flat horizontally (CTRY within 0.0006 over -4..+6 columns, INTRO's best +0.0007), and CTRY peaks 4 rows up (+0.0044) where INTRO loses 0.0052, so no rigid offset serves both films.
  Nothing adopted; the capture-shift scores are in [the framing offset sweep](../../work/2026-11/distill-attribution/journal.md#2026-10-23-the-global-framing-offset-sweep).
* **`BZLT`, `BVIS`, `REJVEC` or `REJ2D` on the walked paths** (2026-11-12): no census walk reaches them (`BVLT` branches and unreached code are not walked), and the corrected section end moves no score ([which stock shapes reach the gates](../../work/2026-11/235_sod-gates/journal.md#2026-11-12-which-stock-shapes-reach-the-gates)).
* **`balloon`'s low IoU as a placement or framing error** (2026-11-16): outside the zenith-sky and straight-down runs every scored frame scores 0.965 or more, so neither the balloon's placement nor the framing sets the film's 0.6409 ([what drives BALLOON's mask IoU](../../work/2026-11/477_vault-attribution/journal.md#2026-11-16-what-drives-balloons-mask-iou)).
* **Drawing the sun disc at variable 13 read as a zenith angle** (2026-11-18): a probe drew index 239 at `(sin a, cos a, 0)` with radius 0.048 rad; on `balloon` the disc sat about 31 px left of and 8 to 10 px below the capture's at ticks 155 and 200, SSIM fell from 0.8172 to 0.8143 on lavapipe, IoU stayed 0.6409 and no other film moved.
  Not adopted; the trig read since turns the light by a second angle of about 10 degrees out of that plane, 3.75 degrees off the probe's direction, and the disc drawn from it is adopted (section 7, [`palette-fade.md` § 3.2](../playone-exe/palette-fade.md#32-other-readers-of-the-live-variables)).
* **Far props the sub-pixel cull drops, as props loss** (2026-11-18): the half-pixel cull in `build_world` drops no placement on six references and on `location` only 190 placements of shapes with no vertices, and removing it scored the seven films the same to four decimals on lavapipe ([removing the size test from the cull](../../work/2026-11/777_far-prop-cull/journal.md#2026-11-18-removing-the-size-test-from-the-cull); [`world-scene-residuals.md` § 6.4](../playone-exe/world-scene-residuals.md#64-the-ground-decal-pass)).
* **`ctry` shape 926's loss as an error of the grass tile** (2026-11-21): see section 2 ([its loss around the actors](../../work/2026-11/904_near-clip-host-shapes/journal.md#2026-11-21-how-much-of-shape-926s-loss-lies-around-the-actors)).
* **A near plane nearer than 0.1 m** (2026-11-21 and 22): 0.05 m moved no film mean by more than `balloon`'s +0.0002 and 0.01 m lowered all seven films, 39 frames by more than 0.005 ([near planes nearer than 0.1 m](../../work/2026-11/907_playone-near-plane/journal.md#2026-11-22-near-planes-nearer-than-01-m-on-the-evidence-track)).
* **Terrain distance cull** (not attempted): the land/sea boundary is already nearly right (section 5).
* **A primitive-index table for the world props' shape word** (2026-11-19): `@builtin(primitive_index)` works on lavapipe, but it restarts at 0 for every draw call and numbers an outline draw's edges, not its triangles, so each world draw would have to pass its first triangle and outlines would need a second table; the vertex-keyed runs of section 1 need neither ([can `primitive_index` or `vertex_index` give a world fragment its prop](../../work/2026-11/809_prop-runs/journal.md#2026-11-19-can-primitive_index-or-vertex_index-give-a-world-fragment-its-prop)).

## Open questions

The renderer-only levers are exhausted, so each item starts by reading one `PLAYONE.EXE` rule.
An item closes when the rule is in its `playone-exe/` note at an image offset, with the change it licenses and the predicted sign on each film.
Priority is by measured loss, not by which item reads easiest.

1. **The player's ground polygons and light caller** — answered: the ground leaves are `MAP.BIN`'s polygons and colours, the airfield's 193/194/196 and `INTRO`'s sand 91 are scenery tiles, now drawn as terrain decals (section 4; [world-scene-residuals.md](../playone-exe/world-scene-residuals.md) section 6), and the light is one world light per film ([terrain-shade.md](../playone-exe/terrain-shade.md) section 4.2).
   _Source: [open questions 1, 5 and 6 as they stood](../../work/2026-11/distill-attribution/journal.md#2026-11-20-open-questions-1-5-and-6-as-they-stood)._ ([#65](https://github.com/neilsh/stunt-reel/issues/65), [#66](https://github.com/neilsh/stunt-reel/issues/66), [#69](https://github.com/neilsh/stunt-reel/issues/69))
2. **Actor placement, model origin and the body** — since its body draws whole and upright ([#47](https://github.com/neilsh/stunt-reel/pull/47)) the CTRY hero is no longer left of the capture, but after the `ground_y_offset` fix it still sits about 4 rows high while the world, since #132, needs no shift; actors are 0.0074 / 0.0350 of the loss on 2026-11-16 (`ctry` / `intro`, section 2).
   Read the slot and placement arrays (`0x4778` / `0x48B6`) and the model-origin rule; see [`hero-aircraft-placement.md`](hero-aircraft-placement.md#1-the-hero-aircraft-residual-open).
   The hero's ground shadow is a variant of this round, not a separate item: a flattened biplane collapses both wings onto one footprint, so a monoplane-shadow does not discriminate a flattened copy from a sprite, and every flattening sweep so far ran against our defective body. ([#67](https://github.com/neilsh/stunt-reel/issues/67))
3. **The `INTRO.FLM` flat-sand frames** — the sand 91 is a `SCENERY2.RES` tile under our terrain (tick 1517: 91 on all 59.2k terrain pixels once the terrain is removed; [world-scene-residuals.md](../playone-exe/world-scene-residuals.md) section 6).
   Before the decals, 11 frames lost more than 0.30 to terrain, where the capture is mostly sand 91; at tick 1505 the capture also carries indices 216 to 218, which we never emit, and the montage window scored above the film mean on 2026-10-24, before #47, so the montage tick rule is not the cause.
   _Source: [open question 3 as first written](../../work/2026-11/distill-attribution/journal.md#2026-10-24-open-question-3-as-first-written)._ ([#70](https://github.com/neilsh/stunt-reel/issues/70))
4. **Prop shading and detail** — props are the largest class on `ctry`, `intro`, `bomb` and `location` on 2026-11-16 (section 2), 0.040 to 0.085 of each.
   It is the one lever left that needs no decode. ([#74](https://github.com/neilsh/stunt-reel/issues/74))
5. **`balloon`'s straight-down camera** — answered: since [#615](https://github.com/neilsh/stunt-reel/issues/615) a view along ±Y takes up `+Z`, and the 18 frames draw (section 7).
6. **The zenith sky and the sun disc** — answered: the zenith sky counts by position ([#718](https://github.com/neilsh/stunt-reel/issues/718), [#745](https://github.com/neilsh/stunt-reel/issues/745)), and the renderer draws the sky bands and the sun disc ([#617](https://github.com/neilsh/stunt-reel/issues/617), [#844](https://github.com/neilsh/stunt-reel/issues/844)); section 7.
7. **`bomb`'s camera cut at tick 3302** — our camera cuts one captured frame before the capture's; whether `PLAYONE` applies a `view_obj` switch a tick later than our sampler is not read.
