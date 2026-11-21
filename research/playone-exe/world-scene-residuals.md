---
summary: "`PLAYONE`'s ground renderer residuals: scenery tiles lie on the terrain plane and tie it in depth, flat props are snapped onto it and painted in walk order, as is any prop face within 10 cm of the ground plane, and a line on a decal now draws after it; the sub-pixel prop cull drops no drawn prop on the references, and `PLAYONE` drops far scenery by distance against its `scale_index`."
---
# `PLAYONE.EXE`: Ground Renderer Residuals

Part of [`world-scene.md`](world-scene.md): the static tree, ground leaves and scenery placement, sections 1-5, stay there.

## 6. What the renderer gets wrong, and the change it licenses

`[Bounded Observation]`, `build/parity` renders, 2026-11-04.
_Source: [2026-11-04: what the renderer drew over the airfield](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-what-the-renderer-drew-over-the-airfield-and-the-terrain-drop)._

Before the change, our render emitted `195` on most pixels it drew as terrain (71% `CTRY`, 54% `INTRO`) where the capture shows the tiles' colours (`196`, `194`, `193`, `163` on `CTRY`; `163`, `193`, `195`, `91` on `INTRO`); the worst frames were close-ups filled by one tile (`CTRY` tick 356, capture 196; `INTRO` tick 1517, capture 91).
Rendering without terrain (`DBG_NO_TERRAIN=1`) put our own tiles on those pixels with the capture's colours, so the tiles were placed and decoded; the depth test hid them under `MAP.BIN` polygons in the same plane.

The rule from sections 2 and 3: the walk paints a tile after the ground leaf it lies on, so that leaf never covers it (whether a later leaf can is open question 1).
The change it licenses lets a prop lying on the terrain win over it, while the terrain still occludes what is behind it (open question 1).
It raised `CTRY` from 0.8298 to 0.8645 and `INTRO` from 0.7745 to 0.7973 SSIM, as a 5 cm terrain drop (`DBG_TERRAIN_DROP`, not adopted) had predicted.
_Source: [2026-11-04: candidates and the ground-decal prototype](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-candidates-and-the-ground-decal-prototype)._

### 6.1 How far the tiles sit from the terrain

`[Bounded Observation]`, answering [#176](https://github.com/neilsh/stunt-reel/issues/176), over `CTRY.ALL`, `INTRO.ALL` and the `FreeFlight` `SIDATA`: each vertex of every placed flat shape set against the `MAP.BIN` triangle over its `x, z`; offset = tile `y` minus terrain `y`.
_Source: [2026-11-04: how far the tiles sit from the terrain](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-how-far-the-tiles-sit-from-the-terrain)._

* **The 16 known tiles** (`SCENERY2.RES` #144-159, ids `0x0391..0x03A0`, 41 instances in each film) lie on the terrain plane: median offset `0.000` for every shape, none above it, the lowest `-0.008` (`0x0391`, one instance).
  The tile geometry sits at local `y = 0` (`0.03125` for four quads) and its placement `y` is the terrain anchor height.
* **So the hiding was a depth tie, not a gap.**
  A tile quad and the fan triangles of its patch are different triangulations of one plane whose interpolated depths differ by rounding, so each pixel goes to one or the other, and `Less` or `LessEqual` makes no difference.
  The earlier reading that the tiles sit a little below the terrain is withdrawn (Ruled out).
* **Other flat props on the ground**, within 3.2 cm: the `0x03BE..0x03C3` markings (colour 174, 256 m), `0x0370`, `0x02AA` (over terrain at 8 of its 37 vertices), `0x06D5` (46 instances, colour 14), the 751 m `0x064A` (`-0.032` to `-0.030`), and `INTRO` shapes `0x05CB..0x05D7` (colour 205, 16-30 m, 416 instances).
* **Flat props that hover.**
  `INTRO` shapes `0x0790..0x07B4` (12 shapes, colour 177, 128-640 m) sit about `+2.0` m above the ground (a few vertices `+0.2` to `+1.5`, one at `-1.5`), so a ground-lying rule must leave them in the base pass.
* **Not over any terrain.**
  The four colour-193 quads `0x04A9..0x04AC` (SCENERY3 entries 168-171, 128-256 m, `y = 75.03`) have no `MAP.BIN` triangle under any vertex in either film.

### 6.2 A rule for ground-lying props

A prop is a ground decal when its shape is flat (all vertices within 5 cm of one height), at least one vertex has terrain below it, and every vertex that does is within 10 cm of it.
On the two films it picks the 16 known tiles and nothing that stands up.
It also picks, as the same kind of object, the markings and patches listed in 6.1 (`0x02AA`, `0x0370`, `0x03BE..0x03C3`, `0x064A`, `0x06D5`, and on `INTRO` `0x05CB..0x05D7`).
The gap between the groups is wide: the largest offset of anything it picks is 3.2 cm, the smallest of anything it rejects is 22 cm.
`ground_decal_vertices` in `crates/stunt-core/src/world/terrain.rs` implements it.

The rule does not pick `SCENERY3.RES` #1, 2, 5 and 6 (`0x0402`, `0x0403`, `0x0406`, `0x0407`), and should not.
They are not tiles but vertical fins standing in the hills.
`OP_TAP` loads each anchor less the shape's origin, and our decode first got this wrong ([`sod-vm.md`](sod-vm.md) sections 4 and 5).
_Source: [2026-11-11: what the 14 TAP shapes are](../../work/2026-11/254_tap-anchors/journal.md#2026-11-11-what-the-14-tap-shapes-are)._

In `CTRY`'s airfield shot no fin shows through the hill patches in front of it, in the capture or in ours, at the captured ticks checked.
Our walk places all seven fins `0x0402`–`0x0408` there and the gate keeps them, but at ticks 287, 298 and 309 drawing them changes no pixel of our render.
At tick 287 `0x0408` projects into the hills at the frame's right edge, and there, by eye, the capture shows the same hill faces and ridges as ours, as it does in the same crop at tick 309.
A fin shares the hill patches' colour range, so one drawn over a patch of its own shade would not show in either picture. `[Bounded Observation]`, three ticks of one shot.
_Source: [2026-11-11: do the CTRY hill fins show through the hills](../../work/2026-11/403_intro-cam1-lod/journal.md#2026-11-11-do-the-ctry-hill-fins-show-through-the-hills)._

### 6.3 Candidates

`[Bounded Observation]`, both films, `mean_ssim_scored` (`CTRY` / `INTRO`).
_Source: [2026-11-04: candidates and the ground-decal prototype](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-candidates-and-the-ground-decal-prototype)._

* **Ground decals (adopted)**: 0.8645 / 0.7973 from 0.8298 / 0.7745; IoU unchanged, index agreement 0.587 to 0.884 / 0.663 to 0.812.
  No `CTRY` tick loses more than 0.002 (worst 510, -0.0011); on `INTRO` tick 1086 loses 0.0056 and 1317 0.0027 (open question 3).
* **Terrain sunk 0.02 to 0.10 m**: 0.8649 / 0.7968 to 0.7971 (0.05 m: within 0.0004 / 0.0002 of the decals), but it moves every polygon and its tie depends on the depth step, which grows with distance.
  No `CTRY` tick lost more than 0.001; 6 `INTRO` ticks lost more than 0.002, worst 1086 (-0.006); ticks far from the camera were not checked.
* **A third pipeline drawing terrain with slope-scale bias 0.25**: 0.8640 / 0.7943, losing 37 `INTRO` ticks (ticks 2918-2973 down to -0.04); any constant bias term hurt.

### 6.4 The ground-decal pass

`[Bounded Observation]` for the measured and tested behaviour.
`build_world_ir` snaps each ground decal onto the terrain at its `x, z` and puts every mesh of it in the `WORLD_DECAL` batch, which `[I5]` draws after the base pass with `GreaterEqual` and a bias toward the viewer ([ADR 0035](../../docs/adr/0035-ground-lying-props-are-terrain-decals.md)); its triangles on the ground plane `y = base_y` go to the ground pass instead (section 6.6, [ADR 0045](../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md)).
It moves no terrain, so it does not touch a mountain leaf.
_Source: [2026-11-04: candidates and the ground-decal prototype](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-candidates-and-the-ground-decal-prototype)._

**The sub-pixel cull drops nothing drawn on the references** (`[Bounded Observation]`, the seven reference films and 13 corpus films, lavapipe).
`build_world` drops a placement whose bounding radius never covers half a pixel along the camera path (`reaches_a_pixel`, `MIN_PROP_PIXELS`), before `build_world_ir` sees it, ground decal or not.
It drops no placement of `ctry`, `intro`, `land`, `balloon`, `traintnl` or `bomb`; of `location` it drops 190, all inside the raster on some scored tick and 34 behind gates that hold there, but every one a shape that decodes to no vertices (`0x0797`, `0x03F4`, `0x0729`, `0x0451`, `0x0453`).
Without it, `INTRO.FLM`'s world is the same 819,169 vertices, and of the 13 corpus films only `BALLOON` played with `SUPERSET.ALL` gains geometry: 258 vertices in 35 placements.
The props `build_world` leaves out are those `place_props`' walk does not reach (the `SP_1NODE` reach) and repeats; the props loss is not far props this cull removes.
_Source: [how many placements the sub-pixel cull drops](../../work/2026-11/777_far-prop-cull/journal.md#2026-11-18-how-many-placements-the-sub-pixel-cull-drops)._

**`PLAYONE` culls far scenery by distance against its scale** (`[Established]` for the instructions, static; `[Supported Inference]` for the distance in metres, which takes the walk position as 16.16 metres from the eye, and for the pixel bound).
`SP_LEAF` (`0x220B`) and the `SP_1NODE` stand-in (`0x2152`) normalise the object's eye-relative position at `0x31CF` and skip the object when the cull `0x1B0C` sets carry (`0x226A`, `0x21A0`).
Besides an object behind the eye and one outside the radius-widened frustum, `0x1B0C` drops one whose largest eye-relative coordinate reaches `2^(22 + [0x229E] - k)` metres, `k` its `scale_index` (`0x1B28`).
It never divides the radius word `R` by the depth, but a shape's radius is under `2^(16 - k)` metres, so at the default lens the cut comes where the shape spans at most about `R / 2^15` pixels in radius: at most 0.68 pixels for every shape of six reference archives and up to 1.22 in `location`'s.
So `PLAYONE` drops far props whole at about the size our half-pixel cull drops, by a coarser test: it can drop a large shape a little above half a pixel that ours keeps, and keeps a small one far below it that ours drops.
Inside the 25 km far plane the cut falls only for `scale_index` 9 and above ([`memory-map-main.md`](memory-map-main.md) `CS:0x1B0C`, `CS:0x31CF`).
_Source: [whether PLAYONE culls a whole scenery object by screen size](../../work/2026-11/777_far-prop-cull/journal.md#2026-11-18-whether-playone-culls-a-whole-scenery-object-by-screen-size)._

The renderer tests (`crates/stunt-render/tests/gpu/renderer.rs`) draw flat terrain with a tile built by hand at terrain height, as the snap would place it (they do not call `build_world_ir`).
The tile shows over the terrain 80 m away, keeps at least 90% of the pixels it shows alone at 1, 1.5, 2, 4 and 8 km at a grazing angle of 5.7 degrees, and a wall of terrain in front of it hides it completely.
`Depth24Plus` is enough for tiles snapped this way, and the same tests pass with depth reversed ([ADR 0054](../../docs/adr/0054-depth-is-reversed-and-infinite.md)).
Reversing depth in `Depth32Float` was measured and rejected for another reason: the GPU and lavapipe disagreed on more pixels (same ADR).

### 6.5 A later leaf lies over an earlier one on the same plane

`[Bounded Observation]`, `INTRO` ticks 3279 and 3301 (capture and render, compared by eye) and one static tree walk of the unpatched image; the painter order is `[Supported Inference]`, since the runtime order was not observed.
_Source: [2026-11-12: INTRO's lake](../../work/2026-11/428_intro-lake/journal.md#2026-11-12-intros-lake-under-the-camera)._

At `INTRO` tick 3301 the capture's bottom-left corner (pixels 0-40 x 140-180) is all index 205, and ours was 195 there.
The camera hangs 51 m over `MAP.BIN` records 126 and 127 (colour 205, about 100 m across, flat at height 0), which lie in the plane of record 7, the colour-195 quad 4 km across.
Dropping record 7 (`DBG_SKIP`, not committed) draws the lake in ours, so the patches were built and projected: they lost the depth tie to record 7, which our terrain draws first (`Less`, standard depth).
Switching the whole base pass to `LessEqual` changed no pixel, consistent with the two triangulations rounding their depths differently.

In a depth-first walk of the tree, record 7 is the leaf at `0x00DA` and records 127 and 126 are the leaves at `0x0274` and `0x028E`, later in the same list.
If `PLAYONE` visits the list in that order (not shown at run time), it paints them over record 7, as the capture's pixels show.
A throwaway script found 31 of the 34 `MAP.BIN` colour-205 records, and the colour-231 records 84 and 85, lying inside record 7's fan in its plane; it did not check which of them our parse draws, nor how they relate to section 2's 28 colour-205 leaves.

* **The change.**
  `terrain_overlays` (`crates/stunt-core/src/world/terrain.rs`) marks a patch whose corners all lie inside the fan of an earlier patch (in `MAP.BIN` order) of another colour, within 10 cm of its plane, and `build_world_ir` draws it in the decal batch (`[I5]`), which wins the tie against base geometry.
  Overlays tie with one another under one bias and are unresolved, and an overlay can now also beat a coplanar prop in the base pass; neither was checked.
  An overlay flat on the ground plane is now painted in `MAP.BIN` order in the ground pass instead (section 6.6).
* **Not shown.**
  `MAP.BIN`'s order was checked against the tree's for record 7 against 126 and 127 only.
  The rule fires on other films (index agreement rises on `BALLOON` by 0.001, `INTRO` 0.005, `LOCATION` 0.007), and no capture of theirs was compared pixel by pixel.

### 6.6 Ocean-coloured tile polygons over land

`[Bounded Observation]`, `LOCATION` tick 2124 (capture and render; the pixels counted per index and layer) and the `LOCATION` and `BOMB` scores of one candidate (two films), then seven-film `mise run parity` runs for the adopted ground pass; the intra-shape bytecode order and `SP_2NODE` walk are `[Established]`.
_Source: [2026-11-12: which prop paints the ocean under LOCATION's houses](../../work/2026-11/435_location-ground/journal.md#2026-11-12-which-prop-paints-the-ocean-under-locations-houses)._ _Source: [2026-11-13: SP_2NODE order, decal forward order, coplanar y=0 painter pass, and TRAINTNL rails](../../work/2026-11/435_location-ground/journal.md#2026-11-13-sp_2node-order-decal-forward-order-coplanar-y0-painter-pass-and-traintnl-rails)._

At `LOCATION` tick 2124 the eye hangs 11 m over `MAP.BIN` records 17, 18 and 22 (colour 195, flat at height 0), and the capture shows their dark green under the houses.
Ours showed ocean blue: the terrain was built as base geometry, and 32,241 of the 185 x 320 pixels were index 208 on the *prop* layer.
The ocean-coloured props at the eye include the town-block tiles `0x03E4` to `0x03E6` and the stand-in `0x03E9` of `LOCATION.ALL` (the pixels were not attributed per tile).
`0x03E4`, read in full, opens behind one `IFVIS` with `COLOR 0x00D0` (208) over its whole square (`0x00E0`), then paints smaller `COLOR 0x00C3` (195) polygons (`0x00F6`) and a trailing `COLOR 0x00D0` inlet (`0x012C`); `0x03E5`, `0x03E6` and `0x03E9` similarly emit `COLOR 0x00D0` then `COLOR 0x00C3`, and all lie flat at height 0 on the ground.

* **Adopted partial fix (forward `decal_meshes` in `collect_visible_meshes`).**
  `base_pipeline` uses `CompareFunction::Less` (first writer wins an exact tie, requiring LIFO order so later nodes draw first), whereas `decal_pipeline` uses `CompareFunction::LessEqual` (last writer wins an exact tie); under reversed depth (ADR 0054) they are `Greater` and `GreaterEqual`, with the same tie rules.
  Walking `decal_meshes` in LIFO order (`mesh.rs`) inverted `0x03E4..0x03E9`'s `208 -> 195 -> 208` stream so the initial `208` base square painted last over `195`.
  Walking `decal_meshes` forward (`VisibleWalk::walk(true, ...)` in `crates/stunt-render/src/mesh.rs`) while keeping `base_meshes` LIFO restores `PLAYONE`'s intra-shape decal order (`195` over `208`, keeping `0x03E4`'s `0x012C` inlet last).
* **`SP_2NODE` (`0x1EC0`) does not reverse on eye side.**
  `[Established]` At `0x1EC0..0x1EEE`, `SP_2NODE` saves `DS:0x49F4/0x49F8/0x49FC`, dispatches its first child `[bp+2]` via `DS:0x0554`, restores those coordinates, and tail-calls `[bp+4]` with no eye-side check or child swap.
* **Coplanar `y = 0` gaps at `LOCATION` ticks 2124 and 4665 before the ground pass.**
  On the ground plane the ground pass below takes items (1) to (3) off `decal_pipeline`; at tick 2124 the roads and lawns of (1) and (2) now draw, and tick 4665 lies in a `LOCATION` run (4027 to 5193) that falls by 0.005 to 0.008 with the pass and was not examined; item (4) is [#448](https://github.com/neilsh/stunt-reel/issues/448).
  Under `decal_pipeline` (`constant: -2, slope_scale: -2.0`), coplanar `y = 0` props misordered: (1) `0x06D5` (palette `14` grey roads) ties `0x03E4`'s biased `195`/`208` on `±1 ULP` depth rounding; (2) `0x068F`'s first slice (`0x01EA IFVIS 0000`, `0x01F0 COLOR 0x00C5` lawn `197`) and `0x037C`'s initial slices (`0x025A COLOR 0x00A2`, `0x026A COLOR 0x0032`) have `is_decal = false` at `y = 0` and lose to `MAP.BIN` record 18 and biased decals; (3) CW upward `OP_POLYZ`/`OP_GVPOLY` faces produce `[0, -1, 0]` normals (`compute_polygon_normal` in `crates/stunt-core/src/sod/vm.rs`), so `displace_decal_polygon` (`sod/decal.rs`) shifted ungrounded decals `-0.001` m downward (`y = -0.0010` in `0x03E4` and `0x037C`; since [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) no decal is moved); and (4) `build_sod_model_ir` (`sod/tessellate.rs`) grouped `0x037C`'s `LINECOL 0x0032` `MOVETO`/`ZLINETO` lines (`0x028A`), which were no decals, into `SOD_BASE` ahead of `SOD_DECAL` (`0x027A COLOR 0x00A9`) despite appearing after `0x027A` in bytecode; item (4) outlived the ground pass and is fixed by the line rule below.
* **Adopted: flat ground painted in walk order ([ADR 0045](../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md)).**
  The ocean, the `MAP.BIN` patches flat at `y = base_y` and every prop triangle on that plane (decals included; since [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) they carry no `[I5]` lift) are `WORLD_GROUND` nodes, drawn first in a forward walk with `CompareFunction::Always` and depth write; raised terrain and the rest of each prop keep the base and decal passes.
  In the 2026-11-13 prototype (`line_lies_on_facet` included), `model_draw_ground_slice` drew a prop mesh's outline after all of its triangles, so on `TRAINTNL` tick 12 the `132` ties' `boundary_edges` (`outline.rs`) could cover the 1-pixel `40` `ZLINETO` rail drawn after them (`(cap, head, p3)` diff pixels: `(40,11,132)=165`, `(132,11,132)=67`, `(11,11,132)=62`); the capture shows two `40` rails in rows 155 to 184, where the gate draws `0x06CE`, whose two `LINECOL` lines are the two rails (section 6.7).
  The adopted pass splits each prop mesh's flat triangles into runs of fill and line triangles, one node per run, each run's outline drawn right after it; no score separates this from one node per mesh, since with the decal lift handled correctly the adopted code scores within 0.0001, on every film, of the [#446 triage](https://github.com/neilsh/stunt-reel/issues/446)'s re-measurement of the issue's diff without `line_lies_on_facet` (one node per mesh).
  All seven films pass the evidence-backed guards and six rise; `TRAINTNL` falls by 0.0005, and in its distant opening shot ticks 12, 34, 100, 111 and 133 fall by 0.011 to 0.014 (no other tick in 12 to 133 by more than 0.0141).
  At tick 12 our gate draws the same stand-in as `PLAYONE` (`0x06CE` in rows 155 to 184, section 6.7), and `0x06CE` and `0x06CF` decode with the bed and the `LINECOL 0x0028` rails in `SOD_BASE` and the `132` tie in `SOD_DECAL` (`export-gltf` of each), so the tie, in the later mesh, painted over the rails although the bytecode draws them last, until the line rule below.
  Before this pass ours held no index-40 pixel in rows 100 to 184 (missing rails, not single ones), and with it the render shows a solid tie-coloured band there.
  At `LOCATION` tick 2124 the snapped `0x06D5` roads and `0x068F` lawns now draw where the capture shows them (SSIM 0.6185 to 0.6641).
  _Source: [2026-11-13: A WORLD_GROUND painter pass whose outlines stay off line runs](../../work/2026-11/446_world-ground-pass/journal.md#2026-11-13-a-world_ground-painter-pass-whose-outlines-stay-off-line-runs)._ _Source: [2026-11-13: Snapped decals lost their lift twice and missed the ground pass](../../work/2026-11/446_world-ground-pass/journal.md#2026-11-13-snapped-decals-lost-their-lift-twice-and-missed-the-ground-pass)._
* **Adopted: a line on a decal is a decal ([#448](https://github.com/neilsh/stunt-reel/issues/448)).**
  `PLAYONE` draws a `ZLINETO` segment when it runs, with no depth test ([`sod-vm-lines-spans.md`](sod-vm-lines-spans.md) section 8.10), so a line after the decal it lies on covers it.
  `identify_coplanar_decals` (`sod/decal.rs`) now flags a `MOVETO`/`ZLINETO` segment as a decal when both its ends lie within 0.1 mm of an earlier decal's plane and their bounds meet, and the ordered decal pass and the ground pass draw it after that decal in stream order.
  At `LOCATION` tick 4665, after the ground pass had landed, `0x037C`'s yard lines were still missing: the line's classification, not the ground pass, buried them.
  With the rule they draw (SSIM 0.7977 to 0.8094), as do `TRAINTNL`'s rails on their `132` ties (tick 12: 0.8210 to 0.8348).
  All seven films pass the evidence-backed guards on lavapipe and on the GPU; `TRAINTNL` rises by 0.0030 and `BOMB` falls by 0.0003 on both.
  `[Bounded Observation]`: two films' target frames and seven films' scores, on lavapipe and the GPU.
  _Source: [2026-11-17: lines lying on an earlier facet are decals of it](../../work/2026-11/448_zlineto-under-facet/journal.md#2026-11-17-lines-lying-on-an-earlier-facet-are-decals-of-it)._ _Source: [2026-11-20: the line rule adopts on the GPU](../../work/2026-11/448_zlineto-under-facet/journal.md#2026-11-20-the-line-rule-adopts-on-the-gpu)._
* **Earlier candidate, not adopted.**
  Dropping, from a ground-snapped prop, each triangle whose three vertices are palette 208 and lie over a terrain triangle draws the capture's green at tick 2124.
  Scores: `BOMB` 0.8202 to 0.8216, `LOCATION` 0.8144 to 0.8151, the other five films unchanged to four decimals; on `LOCATION`, 33 of 745 frames change, 27 closer, none falling by more than 0.005 and 20 rising by more than 0.005.
  It meets neither adoption track (no gain of 0.004, no cited `PLAYONE` rule; [`loop-rules.md`](../../.agents/skills/improving-render-parity/loop-rules.md)), so the code is not in the tree.

### 6.7 `TRAINTNL` tick 12 draws the two-rail stand-in `0x06CE`

`[Bounded Observation]`, one capture frame and our render of it.
The threshold and the lens words are `[Established]`.
That `CX` is depth / 8 is `[Supported Inference]` ([`lod.md`](lod.md) sections 1.1 and 2.2).
So are the depths, which come from our film evaluator's camera.
No breakpoint was run.
_Source: [2026-11-13: which track stand-in TRAINTNL draws at tick 12](../../work/2026-11/452_traintnl-rails/journal.md#2026-11-13-which-track-stand-in-traintnl-draws-at-tick-12)._

The track's `SP_1NODE` chain, at unpatched tree offsets (image `0x22860` + offset; Patch #3 holds the same nodes from image `0x2B1BA`), is `0xAA8A` (`0x06D0`, `ext` 296, `splitdist` 250), `0xAAAC` (`0x06CF`, 56, 50), `0xAACE` (`0x06CE`, 16, 10) and `0xAAEC` (`0x06CD`, 10, 5) above the leaf `0x06D1`.
View camera 7's lens 24576 gives `0x229E = 2` and `0x22A4 = 0xBFFD`.
So the gate at `0x2121` compares depth / 8 with 44 at `0xAAAC` and 9 at `0xAACE`.
In the capture's rows 155 to 184, the `0x06CE` pieces lie 121 to 153 m deep (`CX` 15 to 19), under an `0xAAAC` node 161 m deep (`CX` 20).
So `PLAYONE` descends past `0x06CF` and draws `0x06CE`, whose two `LINECOL 0x0028` lines are the two rails.
`0x06CF` is drawn only from the node 447 m deep outward.
The last `0x06CE` pieces before it end about 399 m deep, at about row 79.
The capture shows that switch.
The track's bed is colour 11 from row 79 down and `0x06CF`'s colour 12 in rows 73 to 78.
Bed 11 rules out `0x06CF`; it does not tell `0x06CE` from the finer `0x06CD` and `0x06D1`, which the depths rule out.
Our render on `main` before the ground pass (`ba11061e`) picks the same stand-ins, with the same switch row, but holds no index-40 pixel in rows 100 to 184.
Its rails are missing, not single, which fits the tie-over-rail grouping that [#448](https://github.com/neilsh/stunt-reel/issues/448) fixed (section 6.6), so no level-of-detail change follows.

### 6.8 `LOCATION`'s infield and the plaza under it

`[Established]` for the heights in our world IR, read from the code and `export-gltf --shape`; `[Bounded Observation]` that this was the tie of [#651](https://github.com/neilsh/stunt-reel/issues/651) at `LOCATION` 2586 to 2872 (the eye 30 m up, 86 m from the stadium, at 2586).
_Source: [2026-11-18: the infield, the plaza under it and the order PLAYONE paints them](../../work/2026-11/701_location-infield/journal.md#2026-11-18-the-infield-the-plaza-under-it-and-the-order-playone-paints-them)._

`PLAYONE` paints `MAP.BIN` record 1, the plaza `0x064A` (14) and the stadium `0x0265`'s infield (169) in that order, which no eye test changes ([`world-scene.md`](world-scene.md) section 3.1).
In the source the plaza lies 31.25 mm below height 0 and the infield 7.8125 mm below it.
Our IR moves only the plaza: it is flat, within 0.1 m of record 1, so `ground_decal_vertices` snaps it to `y = 0` and it joins the `WORLD_GROUND` pass (`Always`, depth write).
`0x0265` is not flat (it rises to 9.5 m), so its infield keeps `y = -0.0078125`.
While the ground pass took only prop triangles within 1e-4 m of the plane (`GROUND_PLANE_TOLERANCE`), the infield stayed a base polygon that had to pass `Less` (standard depth) against the plaza 7.8125 mm above it, and an exact depth test drew the plaza, as both backends did after #636 at the ticks it measured (2586, 2599, 2840, 2859, 2862).
Before #636 the tie flipped (`[Supported Inference]`: a 7.8125 mm offset seen from about 85 m (near plane 0.5 m) is a depth gap of at most `0.5 / 85² × 0.0078125 = 5.4e-7`, while #595 read 3.2e-6 and 2.9e-6, of opposite sign, near depth 0.994; so the f32 vertex-stage error that #636 removed flipped it, not depth precision).

**Adopted: a prop face near the ground plane is ground.**
The ground pass now takes every prop triangle whose three corners lie within 0.1 m (`GROUND_LIE_TOLERANCE`, the snap's tolerance) of `y = base_y` and puts its corners on the plane (`lies_on_ground_plane`, `crates/stunt-core/src/world/terrain.rs`), so the infield is painted after the plaza in placement order.
Our walk keeps the tree's order of the two: on `LOCATION` the plaza is placement 13821 and the stadium 13899, after its stand-ins `0x026B` (13891) and `0x026A` (13892).
`[Bounded Observation]`, seven reference films on the RTX 4070: `LOCATION` rises by 0.0039, `LAND` by 0.0022 and `BOMB` by 0.0005, all 27 scored frames from 2586 to 2872 rise (2586 from 0.7711 to 0.8537), and no frame of any film falls by more than 0.005.
The rule also takes the `OP_DOT` octahedra lying on the ground (radius 3 cm), now flattened onto the plane, `LAND`'s colour-218 faces of `0x073B` and `0x073C`, their corners from 4.6 cm below it to 1.4 cm above, and line runs 1 to 7.8 mm below it on `BOMB` and `LOCATION`.
At `LAND` 221 the runway now shows where the baseline drew grass; which of those faces it is was not traced.
_Source: [2026-11-20: a non-flat prop's faces near the ground plane in the ground pass](../../work/2026-11/651_infield-ground-pass/journal.md#2026-11-20-a-non-flat-props-faces-near-the-ground-plane-in-the-ground-pass)._

A depth rule could not have fixed it: in our IR the plaza is the nearer surface, under any depth format.
The decal pass could not either: it holds faces coplanar with an earlier face of their own shape's stream ([ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)), and the infield is the first face of `0x0265`, 23.4375 mm above the plaza in the source.

## Ruled out

* **The tiles sit below the terrain** (section 6.1): they are on its plane to a millimetre; the 5 cm drop removes a depth tie.
  The earlier reading came from the `LessEqual` probe.
* **Sinking the terrain, or a biased third terrain pass** (section 6.3): they score 0.8649 / 0.7971 and 0.8640 / 0.7943, but the first moves every polygon and the second loses 37 `INTRO` ticks; the ground-decal pass matches the first without moving terrain, and its tie holds in the renderer tests to 8 km.
* **`SCENERY3.RES` #1, 2, 5, 6 as airfield tiles** (sections 3, 6.2): they are `OP_TAP` hill fins, vertical triangles from a hill's foot to its ridge (`0x0402` 155 m, `0x0403` 196 m, `0x0406` 155 m, `0x0407` 196 m), once the anchors are loaded less the shape's origin as `PLAYONE` loads them.
  They share the tiles' colours only because the hill patches use the same range.
  _Source: [2026-11-11: what the 14 TAP shapes are](../../work/2026-11/254_tap-anchors/journal.md#2026-11-11-what-the-14-tap-shapes-are)._
* **Tiles missing from our world** (section 6): `CTRY.ALL` carries them and `SCENERY.scn` places them; removing the terrain shows them.
* **`SP_2NODE` BSP order reversal on eye side** (section 6.6): `0x1EC0..0x1EEE` unconditionally visits `[bp+2]` then `[bp+4]`, never swapping on eye position.
  _Source: [2026-11-13: SP_2NODE order, decal forward order, coplanar y=0 painter pass, and TRAINTNL rails](../../work/2026-11/435_location-ground/journal.md#2026-11-13-sp_2node-order-decal-forward-order-coplanar-y0-painter-pass-and-traintnl-rails)._
* **One flat-ground node per prop mesh, its outline drawn after all of it** (section 6.6): the outline of `TRAINTNL`'s ties covers the rails drawn after them; not ruled out by score: one node per run scored 0.0005 higher on `TRAINTNL`, but that sweep ran with a bug that kept snapped decals out of the ground pass, and with it fixed the two differ by at most 0.0001 at four decimals ([#446 triage](https://github.com/neilsh/stunt-reel/issues/446) figures); the run split stays as a mechanism.
  _Source: [2026-11-13: A WORLD_GROUND painter pass whose outlines stay off line runs](../../work/2026-11/446_world-ground-pass/journal.md#2026-11-13-a-world_ground-painter-pass-whose-outlines-stay-off-line-runs)._
* **A `BZLT` or extra detail gate hiding `TRAINTNL` `132` ties inside `0x06CD..0x06CF`** (section 6.6): none of `0x06CD..0x06D0` carries `BZLT` or a sub-shape distance branch; only the `SP_1NODE` chain gates them.
  _Source: [2026-11-13: SP_2NODE order, decal forward order, coplanar y=0 painter pass, and TRAINTNL rails](../../work/2026-11/435_location-ground/journal.md#2026-11-13-sp_2node-order-decal-forward-order-coplanar-y0-painter-pass-and-traintnl-rails)._
* **`0x06CF`'s single rail in `TRAINTNL` tick 12's rows 155 to 184, in `PLAYONE` or in ours** (section 6.7): the gate descends past `0x06CF` there (its node 161 m deep, `CX` 20, at most its threshold 44) and keeps `0x06CE` (`CX` 15 to 19, above its threshold 9), the capture's bed there is colour 11, not `0x06CF`'s 12, and ours before the ground pass shows no rail there, not one.
  _Source: [2026-11-13: which track stand-in TRAINTNL draws at tick 12](../../work/2026-11/452_traintnl-rails/journal.md#2026-11-13-which-track-stand-in-traintnl-draws-at-tick-12)._

* **A line on any earlier facet as a decal** (section 6.6): it draws `0x037C`'s lines and `TRAINTNL`'s rails as the adopted rule does and adopts on the same branch, but at `BOMB` 2652 to 2740 it draws red line segments over a near white wall that the capture does not show (worst 2675, −0.0107); the adopted rule flags a line only on a decal.
  _Source: [2026-11-17: lines lying on an earlier facet are decals of it](../../work/2026-11/448_zlineto-under-facet/journal.md#2026-11-17-lines-lying-on-an-earlier-facet-are-decals-of-it)._
* **`ZLINETO` decals as the cause of `INTRO` tick 848's loss** (section 6.6): with either rule tick 848 scores 0.7411, as on `main`; the issue's 0.7509 to 0.7409 came from a renderer that still lifted decals off their facet, and the capture's road sits lower than ours under every variant.
  _Source: [2026-11-17: lines lying on an earlier facet are decals of it](../../work/2026-11/448_zlineto-under-facet/journal.md#2026-11-17-lines-lying-on-an-earlier-facet-are-decals-of-it)._
* **`LOCATION`'s infield in the ground's plane, so a tie any depth format keeps** (section 6.8): it lies 7.8125 mm below the snapped plaza in our IR, so an exact depth test hides it; the flips were the f32 vertex-stage error #636 removed (`[Supported Inference]`: a depth gap of at most 5.4e-7 against #595's 3e-6).
  _Source: [2026-11-18: the infield, the plaza under it and the order PLAYONE paints them](../../work/2026-11/701_location-infield/journal.md#2026-11-18-the-infield-the-plaza-under-it-and-the-order-playone-paints-them)._
* **A depth rule or the decal pass as #651's fix** (section 6.8): the first draws the plaza, the nearer surface in our IR; the second takes a face coplanar with an earlier face of its own shape, and the infield is `0x0265`'s first.
  _Source: [2026-11-18: the infield, the plaza under it and the order PLAYONE paints them](../../work/2026-11/701_location-infield/journal.md#2026-11-18-the-infield-the-plaza-under-it-and-the-order-playone-paints-them)._
* **Lowering or removing the sub-pixel prop cull** (section 6.4): with no size test the seven references score the same to four decimals and no frame moves by more than 0.005, since the cull drops nothing they draw.
  _Source: [removing the size test from the cull](../../work/2026-11/777_far-prop-cull/journal.md#2026-11-18-removing-the-size-test-from-the-cull)._

## Open questions

1. **Leaves drawn after props** ([#176](https://github.com/neilsh/stunt-reel/issues/176)).
   The walk is back to front, so a mountain leaf in front of a prop is drawn after it and covers it.
   The renderer keeps that with its depth test: only flat props within 10 cm of the ground leave the base pass (section 6.2), the decal pass still loses to nearer terrain (tested), and the ground pass is drawn before any raised terrain, which then wins by depth.
   What is open is whether `PLAYONE` ever draws a leaf *after* a tile lying on it, which would hide the tile again; the order of the airfield leaves in the tree, read from the image, would say.
   The tie was not a gap (section 6.1): the tiles are on the plane to a millimetre.
2. **Hill fins in other shots.**
   The `OP_TAP` fins (`0x0202`–`0x0208`, `0x0402`–`0x0408`) stand in hills ([`sod-vm.md`](sod-vm.md) section 5).
   In `CTRY`'s airfield shot none shows through the hill patches at the ticks checked (287, 298 and 309 in ours, 287 and 309 in the capture; section 6.2).
   `INTRO`'s walk places `0x0402`–`0x0404` too; no other shot has been compared with a capture.
   _Source: [2026-11-11: do the CTRY hill fins show through the hills](../../work/2026-11/403_intro-cam1-lod/journal.md#2026-11-11-do-the-ctry-hill-fins-show-through-the-hills)._
3. **`INTRO` ticks 1086 (-0.0056) and 1317 (-0.0027)** lose with the prototype: the props loss rises where a tile now covers pixels that a base prop won.
   The prop was not identified; `mise run frame -- --film intro --ticks 1086` would show it.
4. **Flat patches against props in `PLAYONE`'s tree order** (section 6.6, [ADR 0045](../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md)).
   The pass paints every flat `MAP.BIN` patch, in `MAP.BIN` order, before any prop; `PLAYONE`'s tree interleaves them.
   `INTRO` tick 936 falls by 0.015 with the pass, where sand covers more of the capture's green; whether that sand is a patch or a prop, and where the tree puts it, was not read.
   _Source: [2026-11-13: A WORLD_GROUND painter pass whose outlines stay off line runs](../../work/2026-11/446_world-ground-pass/journal.md#2026-11-13-a-world_ground-painter-pass-whose-outlines-stay-off-line-runs)._
5. **`BOMB`'s near white wall at ticks 2652 to 2740.**
   On `main` a grey roof outline shows over it where the capture shows bare wall, and flagging every line on a facet as a decal adds red segments there (Ruled out).
   Which shapes the wall and the outline belong to, and why the wall does not hide them, was not traced.
   _Source: [2026-11-17: lines lying on an earlier facet are decals of it](../../work/2026-11/448_zlineto-under-facet/journal.md#2026-11-17-lines-lying-on-an-earlier-facet-are-decals-of-it)._
6. **What the ground pass's 0.1 m rule moves beyond the infield** (section 6.8).
   At `LAND` 221 it draws the runway the capture shows; which shape's faces make that runway, and what costs `LOCATION` 3268 its 0.0044 at the foot of a tower, were not traced.
   _Source: [2026-11-20: a non-flat prop's faces near the ground plane in the ground pass](../../work/2026-11/651_infield-ground-pass/journal.md#2026-11-20-a-non-flat-props-faces-near-the-ground-plane-in-the-ground-pass)._
