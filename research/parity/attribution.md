# Parity Attribution: Where Our Render's Loss Sits

`[Bounded Observation]`: one capture set per film, 114 scored `CTRY.FLM` frames and 209 scored `INTRO.FLM` frames. This note says which parts of the frame carry the SSIM loss. The measuring loop is in [`method.md`](method.md); every figure has a row in [`log.md`](log.md). The framing and hero-aircraft residual is in [`framing-and-actors.md`](framing-and-actors.md); how the player shades the ground is in [`../playone-exe/terrain-shade.md`](../playone-exe/terrain-shade.md).

## 1. Method: loss by render layer

`stuntreel parity` splits each SSIM window's loss (`1 - ssim`) among the render layers of its pixels in proportion to pixel count (`mean_loss_by_class_scored` in `report.json`); the classes sum to `1 - mean_ssim_scored`. Layer ids in the `.layer` plane: 1 ocean, 2 terrain (`MAP.BIN` patches), 3 props (`SCENERY.scn` placements), 16+n actor draw n of the frame (draw order, not film slot). Extra classes are reference-only (capture non-sky, render sky) and render-only (the reverse). Windows touching the UI overlay are excluded.

* Attribution is by what **our render** draws, not by what is missing. In the worst early props frame (ordinal 41, tick 448, SSIM 0.515) the capture shows the hero biplane and its shadow while our render shows faint struts over flat dark ground, so the loss lands on the ground class. The actors class therefore **understates** the aircraft's cost (see [`framing-and-actors.md`](framing-and-actors.md)).
* The index plane is unlit, so the split says where loss is, not that a palette index is wrong.
* Coverage is largely right (CTRY mask IoU 0.978 after the decal and page-timing changes); the loss is how covered ground and props are shaded, textured and bounded.

_Found 2026-10-22; see the [loss attribution row](log.md)._

## 2. Current breakdown

Loss by class, most recent run per film (`main` at `d90a047`, 2026-10-23, no DBG switches): CTRY 0.7708 over 114 scored frames (index agreement 0.475, IoU 0.978): terrain 0.113, props 0.074, sky 0.018, reference-only 0.014, actors 0.008. INTRO 0.6762 over 209 (0.481, 0.919): terrain 0.170, props 0.068, reference-only 0.029, sky 0.024, ocean 0.012.

Earlier breakdowns, superseded: CTRY after the lighting change (2026-10-22) terrain 0.116, props 0.072, reference-only 0.035, actors 0.008, sky and ocean 0.003 (total 0.234). The INTRO baseline of 2026-10-22 (0.676, IoU 0.802, index agreement 0.482) had terrain 0.175, props 0.071, reference-only 0.051, actors 0.013, ocean 0.012, sky 0.002.

* **The CTRY-derived fixes transfer to INTRO**: index agreement was 0.482 on INTRO against 0.472 on CTRY, so the unlit colours and the 185-row viewport are not CTRY artefacts.
* INTRO is worse than CTRY, with terrain the largest class. Its capture covers ticks 769 to 3,640 and ends before tick 3,822, so it is not a full-film score.
* `INTRO.FLM` uses the partial SOD `0x7F09` (opcode `0x02FD`, `[Unknown]`) and CTRY the partial `0x0107` (`OP_ANIMATE`, `0x01F8`); their cost is not isolated by this split.
* Worst terrain frames in the early CTRY run: ordinals 52, 55 and 35 (ticks 568, 601, 382), 0.22 to 0.25 each; not inspected.

_Found 2026-10-22 and 2026-10-23 at `d90a047`; see the [parity log](log.md)._

## 3. The loss is structural: edges, not flat colour

Recomputing the comparator's 11x11/stride-8 windows in Python over the 93 CTRY frames above the fade that still use the full palette: 70% of the total window loss sits in windows whose capture luminance standard deviation is above 10, 17% in flat windows (sd < 2) and 12% in between. Terrain-major windows (80% or more terrain pixels) are 55% of all windows and carry 39% of the loss, 75% of that at edges. Windows touching an actor carry 13%. A uniform colour error explains little; the horizon, hills, prop silhouettes, coastline, shadow and aircraft account for nearly all of it. (Absolute SSIM differs from `report.json` because this run uses the index plane and the static palette; read the shares.)

_Found 2026-10-23 at `d90a047`; see the [parity log](log.md)._

## 4. Flat ground owns most of the loss

Oracle, not a realisable gain: repainting the capture pixels where our render is flat terrain (layer 2, index 195) to index 195 and re-scoring gives CTRY 0.7732 -> **0.8225** (+0.0493) and INTRO 0.6799 -> **0.7492** (+0.0693); index agreement 0.505 -> 0.822 and 0.534 -> 0.713. It forces the capture to agree with the render even where the capture draws something else.

Split by what the capture draws there:

| Repainted capture pixels | CTRY | INTRO |
|---|---|---|
| green ramp 192-199 only (repaintable shade) | 0.7837 (+0.0105) | 0.6828 (+0.0029) |
| off-ramp only | 0.8038 (+0.0306) | 0.7374 (+0.0575) |

The off-ramp capture indices on our CTRY flat ground are sand 88 (66,288 px), black 0 (28,328), the aircraft's dark blue 136 (24,058), sand 91 (11,653), then 63, the beach colours 161/163, 174 and 47, over 96 of the 114 scored frames: the missing beach surface plus the aircraft and its shadow, not colour. On INTRO it is dominated by the montage's sand flats (1.39 million pixels).

Reading: the two large levers are the per-shot, depth-cued ground shade (+0.0105 CTRY / +0.0029 INTRO if a law reproduced it exactly; see [`terrain-shade.md`](../playone-exe/terrain-shade.md)) and the surfaces the capture draws where we draw airfield green (sand, aircraft, shadow on CTRY; the montage view on INTRO).

_Found 2026-10-23; see the [parity log](log.md)._

## 5. Coastline and sea

* **The worst windows are the coastline and the sand band is misplaced.** The 20 highest-loss windows in sampled CTRY frames all sit at rows 40 to 64 (horizon band) and are beach or shoreline: the capture shows sand index 88 (210,178,113) against our props or terrain, capture sd 40 to 60. Over the 114 scored frames the capture has 106,774 sand pixels; we draw 40,480 (24,324 at 88, 16,156 at 91), every one from a prop (layer 3); the terrain layer holds one sand pixel. 74,333 capture sand pixels fall on our terrain layer (73,823 on the colour-195 airfield) at a median ray distance of 29 m: a near-field surface the capture paints sand and we paint green. At tick 590 the bands are adjacent rather than absent: 1,711 capture sand pixels against our 1,720, overlap 875, our band a few rows low. `[Unknown]`: which prop owns the band and whether its placement or scale is wrong; `SCENERY.scn` places 6,345 instances, of which `build_world` keeps 286 on CTRY after de-duplication and the sub-pixel cull.
* **Ocean colour is right; the sea is wrong by coverage.** Under our ocean pixels 544,029 of 655,011 INTRO capture pixels are index 208, the colour we draw; only 4,533 CTRY pixels are ocean at all. The ocean-class loss on ticks 2790/2800 (0.209) is structural: 50,615 of those pixels are capture sand (91) where we draw sea.
* **The land/sea boundary is nearly right.** The capture draws ocean where we draw land on 3,699 CTRY pixels (0.05%) and 41,233 INTRO pixels (0.33%); we draw airfield green where the capture is ocean on 1,997 and 8,388. A distance cull of terrain patches would move very few pixels and was not attempted.

_Found 2026-10-23 at `d90a047`; see the [parity log](log.md)._

## Ruled out

* **Global framing offset** (2026-10-23): capture rows 0-184 shifted by `dy`, columns by `dx`, scored against unchanged renders (`mean_ssim_scored`). Rows -6..+6: CTRY 0.7694, **0.7776** (-4), 0.7761, 0.7732 (0), 0.7631, 0.7477, 0.7400; INTRO 0.6665, 0.6723, 0.6747, **0.6799** (0), 0.6737, 0.6655, 0.6596. Columns -8..+8: CTRY flat within 0.0006 over -4..+6 (best 0.7738 at +6), INTRO best 0.6806 at -2. CTRY peaks 4 rows up (+0.0044) where INTRO loses 0.0052, so no rigid offset serves both films. Nothing adopted. See [`framing-and-actors.md`](framing-and-actors.md).
* **Terrain distance cull** (not attempted): the land/sea boundary is already nearly right (section 5).

## Next probes

1. Find the prop (or terrain surface) that draws the CTRY sand band at rows 40 to 64 and why its placement is low; check `SCENERY.scn` instances dropped by de-duplication and the sub-pixel cull.
2. Reproduce the per-shot depth-cued ground shade ([`terrain-shade.md`](../playone-exe/terrain-shade.md)); the ceiling is +0.0105 CTRY / +0.0029 INTRO.
3. Prop shading and detail (props are the second-largest class on both films).
4. INTRO's sand flats under the ocean and terrain classes (montage view; see [`framing-and-actors.md`](framing-and-actors.md) next probes).
