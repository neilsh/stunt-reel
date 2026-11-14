---
summary: "Splits the CTRY.FLM and INTRO.FLM SSIM loss by render layer: props are the largest class once ground tiles are decals, and a pre-decal CTRY window study puts most loss at edges, not flat colour."
---
# Parity Attribution: Where Our Render's Loss Sits

`[Bounded Observation]`: one capture set per film, 114 scored `CTRY.FLM` frames and 209 scored `INTRO.FLM` frames. The measuring loop is in [`method.md`](method.md); every figure has a dated record, a journal entry or, for earlier figures, a row of the [parity log](../../work/2026-10/parity-log/log.md). Framing: [`framing-and-actors.md`](framing-and-actors.md); hero aircraft: [`hero-aircraft-placement.md`](hero-aircraft-placement.md); ground shading: [`../playone-exe/terrain-shade.md`](../playone-exe/terrain-shade.md).

## 1. Method: loss by render layer

`stuntreel parity` splits each SSIM window's loss (`1 - ssim`) among the render layers of its pixels in proportion to pixel count (`mean_loss_by_class_scored` in `report.json`); the classes sum to `1 - mean_ssim_scored`. Layer ids in the layer plane: 1 ocean, 2 terrain (`MAP.BIN` patches), 3 props (`SCENERY.scn` placements), 16+n actor draw n of the frame (draw order, not film slot). Extra classes are reference-only (capture non-sky, render sky) and render-only (the reverse). Windows touching the UI overlay are excluded.

* Attribution is by what **our render** draws, not by what is missing. In the worst early props frame (ordinal 41, tick 448, SSIM 0.515) the capture shows the hero biplane and its shadow while our render shows faint struts over flat dark ground, so the loss lands on the ground class. The actors class therefore **understates** the aircraft's cost (see [`hero-aircraft-placement.md`](hero-aircraft-placement.md)).
* The index plane is unlit, so the split says where loss is, not that a palette index is wrong.
* Coverage is largely right (CTRY mask IoU 0.978 after the decal and page-timing changes); the loss is how covered ground and props are shaded, textured and bounded.

_Found 2026-10-22; see the [loss attribution row](../../work/2026-10/parity-log/log.md)._

## 2. Current breakdown

Loss by class, most recent run per film (2026-11-04, the ground decals of [ADR 0035](../../docs/adr/0035-ground-lying-props-are-terrain-decals.md) for [#69](https://github.com/neilsh/stunt-reel/issues/69), against `8b36b79` just before them): CTRY 0.8298 -> **0.8645** over 114 scored frames (index agreement 0.587 -> 0.884, IoU 0.9897): terrain 0.0772 -> **0.0186**, props 0.0553 -> **0.0793**, sky 0.0158, actors 0.0133, reference-only 0.0078 -> 0.0076, ocean 0.0008 -> 0.0007. INTRO 0.7745 -> **0.7973** over 209 (0.663 -> 0.812, IoU 0.9856): terrain 0.0941 -> **0.0439**, props 0.0530 -> **0.0808**, actors 0.0441 -> 0.0439, sky 0.0199, reference-only 0.0072, ocean 0.0068, props_and_actors_render_only 0.0004. Terrain falls from 45% of the loss to 14% on CTRY and from 42% to 22% on INTRO, and props are now the largest class on both. The props class rises because the airfield and sand tiles that the terrain hid are now drawn, so their remaining error is attributed to props (section 1); the total loss still falls. The tile pixels were most of section 4's off-ramp ground.

The `IFVIS` facing gate of [#74](https://github.com/neilsh/stunt-reel/issues/74) (2026-11-05, [log row](../../work/2026-10/parity-log/log.md)) leaves the props class where the breakdown above has it, CTRY 0.0793 -> 0.0793 and INTRO 0.0808 -> 0.0806; its INTRO gain is on the aircraft (actors 0.0439 -> 0.0431). Props loss is therefore not the in-shape `IFVIS` branch. On the paths the census walks, it is not `BZLT`, `BVIS`, `REJVEC` or `REJ2D` either: no census walk reaches them, and correcting where sections end left the seven reference films' scores unchanged to four decimals. A gate behind a `BVLT` branch, which the census does not follow, or in code no branch reaches is not ruled out ([`sod-vm.md`](../playone-exe/sod-vm.md) section 8.6, [#235](https://github.com/neilsh/stunt-reel/issues/235)).

The world light and per-vertex `GVPOLY` interpolation of [#221](https://github.com/neilsh/stunt-reel/issues/221) (2026-11-05, [log rows](../../work/2026-10/parity-log/log.md)) move props CTRY 0.0793 -> 0.0794 and INTRO 0.0806 -> 0.0770, actors 0.0133 -> 0.0135 and 0.0431 -> 0.0308. Shading scenery alone with the world light scores the same as the old stand-in to four decimals, so the INTRO props drop is most likely SSIM windows shared with the aircraft (`[Supported Inference]`). Props loss is therefore not the `SHADES` light either.

The run before that (2026-11-02, `main` at `793895e`: the whole-body, upright aircraft of [#47](https://github.com/neilsh/stunt-reel/pull/47), the `GVPOLY` ramp colour of [#48](https://github.com/neilsh/stunt-reel/pull/48) and the square-pixel, 256 px projection of [#132](https://github.com/neilsh/stunt-reel/pull/132)): CTRY 0.8291 over 114 scored frames (index agreement 0.587, IoU 0.9897): terrain 0.0783, props 0.0568, sky 0.0158, actors 0.0114, reference-only 0.0078, ocean 0.0008. INTRO 0.7154 over 209 (0.622, 0.9712): terrain 0.1281, props 0.0654, actors 0.0363, sky 0.0260, reference-only 0.0121, ocean 0.0109, props_and_actors_render_only 0.0058. Terrain is 46% of the loss on CTRY and 45% on INTRO. Against the 2026-10-24 breakdown below, with the same measure at `794daa5` (after #47 and #48, before #132) between them:

| Class | CTRY 10-24 | CTRY `794daa5` | CTRY `793895e` | INTRO 10-24 | INTRO `794daa5` | INTRO `793895e` |
|---|---|---|---|---|---|---|
| props | 0.0779 | 0.0680 | **0.0568** | 0.0727 | 0.0698 | **0.0654** |
| actors | 0.0035 | 0.0122 | **0.0114** | 0.0081 | 0.0381 | **0.0363** |
| props and actors, render only | — | 0.0010 | 0.0000 | — | 0.0062 | 0.0058 |
| actor-window IoU (`parity-probe iou`) | 0.091 | 0.227 | 0.221 | 0.062 | 0.093 | 0.097 |

The actors class grew with #47 because the aircraft are now drawn whole: loss is attributed by what our render draws (section 1), so a missing body cost the terrain class before and a drawn but miscoloured or misplaced one costs the actors class now. #132 left it nearly where #47 and #48 put it, while props and terrain fell with the corrected projection. Props remain the second class on both films. The INTRO total is not comparable with the 2026-10-24 row: since 2026-11-01 its title-card frames are below the fade floor, and the 0.7224 row predates the aircraft changes that cost INTRO.

Error readout on the same renders (the same 12 ticks per film, seed 1; two Haiku passes and a Sonnet tie-break on the disputed sheets: 10 / 9 at `794daa5`, 7 / 6 now; frames graded 2 or more of 12), against the readout taken when #47 was adopted (2026-11-01, before the orientation fix and #48):

| Category | CTRY at #47 | CTRY `794daa5` | CTRY now | INTRO at #47 | INTRO `794daa5` | INTRO now |
|---|---|---|---|---|---|---|
| `aircraft-absent` | — | 0 | 0 | 0 (from 9) | 0 | 0 |
| `aircraft-parts-missing` | — | 10 | 7 | 11 | 8 | 5 |
| `aircraft-shape-broken` | 3 (from 10) | 7 | 5 | 9 | 6 | 5 |
| `aircraft-misplaced` | — | 0 | 0 | — | 5 | 6 |
| `shadow-missing` | — | 6 | 6 | — | 5 | 5 |
| `scenery-missing` | — | 3 | 1 | — | 6 | 4 |

(— : not quoted in the #47 row; no earlier `readout.json` survives.) A count must move by 4 to clear grader noise ([`metric-bench.md`](metric-bench.md) § 2.3), so no change in the table clears it except INTRO `aircraft-parts-missing` 11 -> 5 across the three runs, and two `aircraft-shape-broken` moves that sit at the limit: CTRY 3 -> 7 -> 5 and INTRO 9 -> 6 -> 5. Graders' notes: at `794daa5` CTRY tick 4 "wing/gear drawn wrongly, no fuselage detail", tick 268 "aircraft orientation wrong", INTRO tick 2764 "main aircraft at left edge largely undrawn"; now INTRO tick 3295 "conifers drawn as round bushes".

Earlier breakdowns, superseded: CTRY on 2026-10-24 (`main`, after back-face culling) 0.7808 over 114 scored frames (index agreement 0.507, IoU 0.9780): terrain 0.1032, props 0.0779, sky 0.0183, reference-only 0.0144, actors 0.0035; INTRO 0.7224 over 209 (0.637, 0.9501): terrain 0.1382, props 0.0727, reference-only 0.0189, sky 0.0227, ocean 0.0120, actors 0.0081, terrain_render_only 0.0042. CTRY after the lighting change (2026-10-22) terrain 0.116, props 0.072, reference-only 0.035, actors 0.008, sky and ocean 0.003 (total 0.234). The INTRO baseline of 2026-10-22 (0.676, IoU 0.802, index agreement 0.482) had terrain 0.175, props 0.071, reference-only 0.051, actors 0.013, ocean 0.012, sky 0.002.

* **The CTRY-derived fixes transfer to INTRO**: index agreement was 0.482 on INTRO against 0.472 on CTRY, so the unlit colours and the 185-row viewport are not CTRY artefacts.
* INTRO is worse than CTRY, with terrain the largest class. Its capture covers ticks 769 to 3,640 and ends before tick 3,822, so it is not a full-film score.
* `INTRO.FLM` uses the partial SOD `0x7F09` (opcode `0x02FD`, `[Unknown]`) and CTRY the partial `0x0107` (`OP_ANIMATE`, `0x01F8`); their cost is not isolated by this split. `0x0107` has since been drawn ([`sod-animate.md`](../playone-exe/sod-animate.md) § 4).
* Worst terrain frames in the early CTRY run: ordinals 52, 55 and 35 (ticks 568, 601, 382), 0.22 to 0.25 each; not inspected.

_Found 2026-10-22 and 2026-10-23 at `d90a047`; re-measured 2026-11-02 at `794daa5` and again after #132 at `793895e` ([#98](https://github.com/neilsh/stunt-reel/issues/98)); see the [parity log](../../work/2026-10/parity-log/log.md)._

## 3. The loss is structural: edges, not flat colour

Recomputing the comparator's 11x11/stride-8 windows in Python over the 93 CTRY frames above the fade that still use the full palette: 70% of the total window loss sits in windows whose capture luminance standard deviation is above 10, 17% in flat windows (sd < 2) and 12% in between. Terrain-major windows (80% or more terrain pixels) are 55% of all windows and carry 39% of the loss, 75% of that at edges. Windows touching an actor carry 13%. A uniform colour error explains little; the horizon, hills, prop silhouettes, coastline, shadow and aircraft account for nearly all of it. (Absolute SSIM differs from `report.json` because this run uses the index plane and the static palette; read the shares.)

_Found 2026-10-23 at `d90a047`; see the [parity log](../../work/2026-10/parity-log/log.md)._

## 4. Flat ground owns most of the loss

Oracle, not a realisable gain: repainting the capture pixels where our render is flat terrain (layer 2, index 195) to index 195 and re-scoring gives CTRY 0.7732 -> **0.8225** (+0.0493) and INTRO 0.6799 -> **0.7492** (+0.0693); index agreement 0.505 -> 0.822 and 0.534 -> 0.713. It forces the capture to agree with the render even where the capture draws something else.

Split by what the capture draws there:

| Repainted capture pixels | CTRY | INTRO |
|---|---|---|
| green ramp 192-199 only (repaintable shade) | 0.7837 (+0.0105) | 0.6828 (+0.0029) |
| off-ramp only | 0.8038 (+0.0306) | 0.7374 (+0.0575) |

The off-ramp capture indices on our CTRY flat ground are sand 88 (66,288 px), black 0 (28,328), the aircraft's dark blue 136 (24,058), sand 91 (11,653), then 63, the beach colours 161/163, 174 and 47, over 96 of the 114 scored frames: the missing beach surface plus the aircraft and its shadow, not colour. On INTRO it is dominated by the montage's sand flats (1.39 million pixels).

Reading: the two large levers are the per-shot, depth-cued ground shade (+0.0105 CTRY / +0.0029 INTRO if a law reproduced it exactly; see [`terrain-shade.md`](../playone-exe/terrain-shade.md)) and the surfaces the capture draws where we draw airfield green (sand, aircraft, shadow on CTRY; the montage view on INTRO).

Answered 2026-11-04: the green-ramp shade and much of the off-ramp ground are scenery tiles (`SCENERY2.RES` #144-159 and others) that `PLAYONE` paints over its flat ground leaves and that our depth test hid under the terrain. `PLAYONE` puts no shade law on the ground ([`world-scene.md`](../playone-exe/world-scene.md) sections 2, 3). Drawing them as terrain decals cut the terrain class to 0.0186 (CTRY) and 0.0439 (INTRO), section 2.

_Found 2026-10-23; see the [parity log](../../work/2026-10/parity-log/log.md)._

## 5. Coastline and sea

* **The worst windows are the coastline and the sand band is misplaced.** The 20 highest-loss windows in sampled CTRY frames all sit at rows 40 to 64 (horizon band) and are beach or shoreline: the capture shows sand index 88 (210,178,113) against our props or terrain, capture sd 40 to 60. Over the 114 scored frames the capture has 106,774 sand pixels; we draw 40,480 (24,324 at 88, 16,156 at 91), every one from a prop (layer 3); the terrain layer holds one sand pixel. 74,333 capture sand pixels fall on our terrain layer (73,823 on the colour-195 airfield) at a median ray distance of 29 m: a near-field surface the capture paints sand and we paint green. At tick 590 the bands are adjacent rather than absent: 1,711 capture sand pixels against our 1,720, overlap 875, our band a few rows low. `[Unknown]`: which prop owns the band and whether its placement or scale is wrong; `SCENERY.scn` places 6,345 instances, of which `build_world` keeps 286 on CTRY after de-duplication and the sub-pixel cull.
* **Ocean colour is right; the sea is wrong by coverage.** Under our ocean pixels 544,029 of 655,011 INTRO capture pixels are index 208, the colour we draw; only 4,533 CTRY pixels are ocean at all. The ocean-class loss on ticks 2790/2800 (0.209) is structural: 50,615 of those pixels are capture sand (91) where we draw sea.
* **The land/sea boundary is nearly right.** The capture draws ocean where we draw land on 3,699 CTRY pixels (0.05%) and 41,233 INTRO pixels (0.33%); we draw airfield green where the capture is ocean on 1,997 and 8,388. A distance cull of terrain patches would move very few pixels and was not attempted.

_Found 2026-10-23 at `d90a047`; see the [parity log](../../work/2026-10/parity-log/log.md)._

## 6. Back faces

`[Bounded Observation]`. The player culls back faces; `stuntreel` did not until 2026-10-24. Our models wind clockwise for their outward faces, so the pipeline's `FrontFace::Ccw` default classified every interior wall as front-facing, and flying through a prop or the hero aircraft drew its inside. A sweep over the culling mode (`DBG_CULL` 0, 1, 2) scored 0.7733 / 0.7175, 0.6112 / 0.5799 and **0.7808 / 0.7224** (CTRY / INTRO); `FrontFace::Cw` with `Face::Back` reproduces the third. IoU is unchanged (0.9780 / 0.9501); index agreement rises 0.504 -> 0.507 and 0.636 -> 0.637. The gain is almost all actors, whose class loss falls 0.0083 -> 0.0035 on CTRY and 0.0140 -> 0.0081 on INTRO. One frame regresses: CTRY tick 832, 0.710 -> 0.681, where removing the interior exposes an actor surface the capture does not show; the actor placement residual explains that. The two-sided flag (`SodVertex::flags` bit 1) is not decoded, so the culling cannot yet exempt a two-sided polygon.

## Ruled out

* **Global framing offset** (2026-10-23): capture rows 0-184 shifted by `dy`, columns by `dx`, scored against unchanged renders (`mean_ssim_scored`). Rows -6..+6: CTRY 0.7694, **0.7776** (-4), 0.7761, 0.7732 (0), 0.7631, 0.7477, 0.7400; INTRO 0.6665, 0.6723, 0.6747, **0.6799** (0), 0.6737, 0.6655, 0.6596. Columns -8..+8 in steps of 2: CTRY 0.7615, 0.7643, 0.7687, 0.7730, 0.7732 (0), 0.7730, 0.7734, **0.7738** (+6), 0.7714; INTRO 0.6768, 0.6773, 0.6792, **0.6806** (-2), 0.6799 (0), 0.6792, 0.6798, 0.6794, 0.6768. Both films are flat horizontally (CTRY within 0.0006 over -4..+6, INTRO's best +0.0007). CTRY peaks 4 rows up (+0.0044) where INTRO loses 0.0052, so no rigid offset serves both films. Nothing adopted. See [`framing-and-actors.md`](framing-and-actors.md).
* **`BZLT`, `BVIS`, `REJVEC` or `REJ2D` on the walked paths** (2026-11-12): no census walk reaches them (`BVLT` branches and unreached code are not walked), and the corrected section end moves no score ([which stock shapes reach the gates](../../work/2026-11/235_sod-gates/journal.md#2026-11-12-which-stock-shapes-reach-the-gates)).
* **Terrain distance cull** (not attempted): the land/sea boundary is already nearly right (section 5).

## Open questions

The renderer-only levers are exhausted, so each item starts by reading one `PLAYONE.EXE` rule. An item closes when the rule is in its `playone-exe/` note at an image offset, with the change it licenses and the predicted sign on each film. Priority is by measured loss, not by which item reads easiest.

1. **The player's ground polygons and light caller** — *answered 2026-11-04*: the ground leaves are `MAP.BIN`'s polygons and colours, and the 193/194/196 (and `INTRO`'s sand 91) are scenery tiles our depth test hides under coplanar terrain; a 5 cm terrain drop measures +0.035 / +0.023 SSIM ([world-scene.md](../playone-exe/world-scene.md) section 6). The light is one world light per film ([terrain-shade.md](../playone-exe/terrain-shade.md) section 4.2). As first written: terrain is the largest class on both films (0.0783 on `CTRY`, 0.1281 on `INTRO` on 2026-11-02 after #132; 46% and 45% of the loss). On `CTRY` the error is systemic: median terrain loss 0.088, no frame above 0.30, the worst 40 frames holding 57% of it — a shading law, not a misplaced surface. The sand band, the airfield's 193/194/196 base colours and the per-shot light caller are the three parts; `MAP.BIN`'s patches are not the player's records ([world-scene.md](../playone-exe/world-scene.md) section 6; [terrain-shade.md](../playone-exe/terrain-shade.md) next probe 1). ([#65](https://github.com/neilsh/stunt-reel/issues/65), [#66](https://github.com/neilsh/stunt-reel/issues/66), [#69](https://github.com/neilsh/stunt-reel/issues/69))
2. **Actor placement, model origin and the body** — since its body draws whole and upright ([#47](https://github.com/neilsh/stunt-reel/pull/47)) the CTRY hero is no longer left of the capture, but it sits about 8 rows high while the world, since #132, needs no shift (2026-11-02 re-measure, [`hero-aircraft-placement.md`](hero-aircraft-placement.md#1-the-hero-aircraft-residual-open)); actors are now 0.0114 / 0.0363 of the loss. Read the slot and placement arrays (`0x4778` / `0x48B6`) and the model-origin rule; see [`hero-aircraft-placement.md`](hero-aircraft-placement.md#1-the-hero-aircraft-residual-open). The hero's ground shadow is a variant of this round, not a separate item: a flattened biplane collapses both wings onto one footprint, so a monoplane-shadow does not discriminate a flattened copy from a sprite, and every flattening sweep so far ran against our defective body. ([#67](https://github.com/neilsh/stunt-reel/issues/67))
3. **The `INTRO.FLM` flat-sand frames** — the sand 91 is a `SCENERY2.RES` tile under our terrain (tick 1517: 91 on all 59.2k terrain pixels once the terrain is removed; [world-scene.md](../playone-exe/world-scene.md) section 6). As first written: 11 frames lose more than 0.30 to terrain at IoU 0.97 to 1.0 and index agreement 0.00 to 0.33 (ticks 1088, 1098, 1308-1374, 1505 and 2690-2778), where the capture is 54 to 97% sand index 91 and we draw 195 or 208. Coverage is right and content is absent, so a colour rule alone cannot fix it; at tick 1505 the capture also carries about 17.8% of indices 216 to 218, which we never emit. This is not the montage tick rule: the montage window (ticks 1290 to 1500) scored 0.7807 on 2026-10-24, above that run's film mean of 0.7224 (both before #47; the window has not been re-scored since). ([#70](https://github.com/neilsh/stunt-reel/issues/70))
4. **Prop shading and detail** — props are 0.0568 / 0.0654 (2026-11-02 after #132; 0.0779 / 0.0727 on 2026-10-24), the second class on both films, and the one lever left that needs no decode. ([#74](https://github.com/neilsh/stunt-reel/issues/74))

### Where the ground-and-light goal stopped

The 2026-10-24 ground-and-light goal ran two rounds and adopted nothing, which is its own stop rule. Both rounds went at the ground question from opposite ends and both were stopped by missing evidence rather than by a negative result:

* **The stream is not in conventional memory.** The runner at `0x9161` calls the display list's first word as code, so a relocated record carries the handler's offset; `0x995C` occurs in none of the 96 dumps and `0x9A24` twice ([world-scene.md](../playone-exe/world-scene.md) section 6).
* **The light is handed in, not computed.** `0x9100` writes `L` from AX/BX/DX and fills the rest of its block from DGROUP; the caller is the binary's one genuinely unreferenced entry ([terrain-shade.md](../playone-exe/terrain-shade.md#41-the-entry-decodes-but-it-is-handed-its-light)).

So the next goal cannot open on item 1 or on the model-origin half of item 2 without evidence this one could not obtain. The two routes that would produce it are an EMS page-frame dump during playback, and the loader's relocation rule from the unpacked image — the first is a harness job, the second static work this notebook has the addresses for. Item 3 (the flat-sand frames) is untouched and does not depend on either.

Moved out of this list: the two-sided flag. `SodVertex::flags` bit 1 has no known writer, and the tick-832 regression it was meant to repair is one frame worth about 0.0003 of the film mean. It is tracked as an open question in [sod-vm.md](../playone-exe/sod-vm.md).
