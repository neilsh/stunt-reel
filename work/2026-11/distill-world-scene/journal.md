# Journal: distilling `world-scene.md`

The dated rounds of [`world-scene.md`](../../../research/playone-exe/world-scene.md) as of commit `61e10d2`, moved here verbatim when the note was distilled to current truth. Only relative link paths changed, and each `###` heading of the moved text is demoted to bold; a section number in the moved text names a section of the note as it stood at `61e10d2` (`git show 61e10d2:research/playone-exe/world-scene.md`).

## 2026-10-23: the ground ops in CTRY.ALL, superseded

From section 5 of the note, as it stood at `61e10d2`:

Superseded by sections 2 and 4.1. The op `0x0168` and `0x02BE` records at `CTRY.ALL` offsets `0x13FC` and `0xEFE4` are `GVPOLY` records of the film's shapes, which are `RES` items, not ground. The 110-word table at `0x79` is neither a colour list nor a ramp directory: it is the chunk-id table at `0x7A` read one byte off (section 2.1). `CTRY.FLM` holds no ground either. The ground is in `PLAYONE.EXE`.

_Found 2026-10-23 at `6ae7b31`; superseded 2026-11-04._

**Lives in** [`world-scene.md`](../../../research/playone-exe/world-scene.md) § 4.1 and § 5.

## 2026-11-04: the live ground tree

From section 2:

The tree segment is the stack segment while it is walked: `SS = 0x2AAA` in the DOSBox-X session, which is load paragraph `0x0824` plus image paragraph `0x2286`. A 64 KB dump of it at tick 312 (the first leaf call after the plan armed at 300) matches the image at `0x22860` in 118 of 128 sampled 32-byte windows, one every `0x200` bytes; the other 10 hold the stack and other mutable words. So nothing builds or loads the tree: it is part of `PLAYONE.EXE`.

**Against `MAP.BIN`.** A scan for type-14 nodes whose polygon has a byte colour, 3 to 12 vertices and vertex words that are multiples of `0x1C` (anchor 0 included) finds 146 leaves in the unpatched image (`0x22866..0x30760`), 146 in the patched one (`0x20736..0x2E630`) and 146 in the live tree at tick 312. Every one has the vertex set of a `MAP.BIN` record (FreeFlight's `SIDATA`) and that record's colour byte, and together they reach 146 of its 179 records: records 99 and 100 share one vertex set and colour, and two leaves carry it. One leaf has 8 vertices. It is record 131, whose eighth anchor `50` is the record's own eighth slot ([`map.md`](../../../research/formats/auxiliary/map.md) section 2.3). The 33 records with no leaf are the 13 inactive ones (`pos & 0xFF == 0`, anchor indices past 1023) and 20 active ones (section 2.1). An earlier scan that stopped at 7 vertices and skipped anchor 0 found 143. The colours are `205` (28 leaves), `162` to `165` (53), `195` (12), `193`, `194` (8 each), `161` (6), `197` (5), `192`, `204` (4 each), and a few others. On the live run the gateway `0x8069` drew `0xA1..0xA4`, `0xC0..0xC4`, `0xCD` and `0xE7` from this routine alone, 300 calls over ticks 310-337.

**Lives in** [`world-scene.md`](../../../research/playone-exe/world-scene.md) § 2.

## 2026-11-04: what the renderer drew over the airfield, and the terrain drop

From section 6:

*[Bounded Observation]*, `build/parity` renders at `8a0ae1e`, 2026-11-04.

On the pixels our render draws as terrain, it emits `195` on 71% (`CTRY`) and 54% (`INTRO`). The capture there shows `196` (30%), `194` (24%), `193` (9%) and `163` (22%) on `CTRY`, and `163` (28%), `193` (18%), `195` (15%) and `91` (11%) on `INTRO`. On our prop pixels the two agree within about two points. The worst frames are close-ups filled by one tile: `CTRY` tick 356 has 48k mismatched terrain pixels, the capture 196 and ours 195; `INTRO` tick 1517 has 59k, the capture 91 and ours 195.

Rendering without terrain (`DBG_NO_TERRAIN=1`) puts our own tiles on those pixels with the capture's colours: tick 356 becomes 196 on 41.8k of its 54.0k terrain pixels (capture 40.4k), and tick 1517 becomes 91 on all 59.2k (capture 55.9k). So the tiles are placed and decoded; the depth test hides them under `MAP.BIN` polygons in the same plane.

The rule from sections 2 and 3: a ground leaf never covers the scenery placed on it. The change it licenses lets a prop lying on the terrain win over it, while the terrain still occludes what is behind it (open question 1). The sign was first measured with a 5 cm drop of the terrain (`DBG_TERRAIN_DROP`), and it is up on both films:

| `DBG_TERRAIN_DROP` (m) | `CTRY` SSIM | `INTRO` SSIM | `CTRY` / `INTRO` IoU |
|---|---|---|---|
| 0 | 0.8298 | 0.7745 | 0.9897 / 0.9856 |
| 0.05 | 0.8649 | 0.7971 | 0.9897 / 0.9856 |
| 0.2 | 0.8649 | 0.7969 | 0.9896 / 0.9855 |
| 0.5 | 0.8648 | 0.7965 | 0.9896 / 0.9855 |

Predicted sign of the real change: positive on both films, about +0.035 on `CTRY` and +0.023 on `INTRO`. That prediction held (section 6.4); the terrain drop itself was not adopted.

**Lives in** [`world-scene.md`](../../../research/playone-exe/world-scene.md) § 6.

## 2026-11-04: how far the tiles sit from the terrain

From section 6.1:

*[Bounded Observation]*, answering [#176](https://github.com/neilsh/stunt-reel/issues/176): a throwaway test over `CTRY.ALL`, `INTRO.ALL` and the `FreeFlight` `SIDATA` (2026-11-04, `8b36b79`). For every placed instance (`SCENERY.scn`, `build_world` placement, de-duplicated, nothing culled), each vertex of a flat shape was set against the `MAP.BIN` triangle over its `x, z` (the fan `push_terrain` draws; where patches overlap in plan, the one nearest the vertex). Offset = tile `y` minus terrain `y`.

* **The 16 known tiles** (`SCENERY2.RES` #144-159, ids `0x0391..0x03A0`, 41 instances in each film): offset `0.000` at the median for every shape, minimum `-0.001` for 8 shapes, `0.000` for 7, and `-0.008` for `0x0391` (one instance). Maximum `0.000`. None is above the ground and none is measurably below it.
* **Where the offset comes from.** It does not come from the data. The tile geometry sits at local `y = 0` (`0.03125` for four quads) and the placement `y` is the terrain anchor height, so the tile is the terrain plane to within a millimetre. The earlier reading that the tiles sit a little below the terrain (the `LessEqual` probe, [`terrain-shade.md`](../../../research/playone-exe/terrain-shade.md) Ruled out) is withdrawn: what the 5 cm drop of the terrain removes is a depth tie, not a gap. A tile quad and the fan triangles of its patch are different triangulations of one plane, and their interpolated depths differ by rounding, so each pixel goes to one or the other and `Less` or `LessEqual` makes no difference.
* **Other flat props**, same method: the `0x03BE..0x03C3` markings (colour 174, 256 m) `-0.001` to `0.000`; `0x0370`, `0x02AA` (over terrain at 8 of its 37 vertices) and `0x06D5` (46 instances, colour 14) `-0.001` to `0.000`; the 751 m `0x064A` `-0.032` to `-0.030`; and `INTRO` shapes `0x05CB..0x05D7` (colour 205, 16-30 m, 416 instances) `0.000`.
* **Flat props that hover.** `INTRO` shapes `0x0790..0x07B4` (12 shapes, colour 177, 128-640 m) sit `+2.0` m above the ground (a few vertices `+0.2` to `+1.5`; one shape has a vertex at `-1.5`). They are not on it, and a ground-lying rule must leave them in the base pass.
* **Not over any terrain.** The four colour-193 quads `0x04A9..0x04AC` (SCENERY3 entries 168-171, 128-256 m, `y = 75.03`) have no `MAP.BIN` triangle under any vertex in either film.

**Lives in** [`world-scene.md`](../../../research/playone-exe/world-scene.md) § 6.1.

## 2026-11-04: candidates and the ground-decal prototype

From sections 6.3 and 6.4:

**6.3 Candidates**

*[Bounded Observation]*, `build/parity` renders, `8fa4e0c`, `8b36b79` and the prototype, 2026-11-04. Each row is the same two films, `mean_ssim_scored`, mask IoU in brackets (`CTRY` / `INTRO`).

| Variant | `CTRY` | `INTRO` | Per-tick cost |
|---|---|---|---|
| `8fa4e0c` (before the eighth vertex of patch 131) | 0.8298 (0.9897) | 0.7745 (0.9856) | |
| `8b36b79` (patch 131 fixed) | 0.8298 (0.9897) | 0.7745 (0.9856) | no frame of either film changes |
| (a) Terrain sunk 0.02 m | 0.8649 | 0.7968 | `CTRY` none above 0.001; 6 `INTRO` ticks above 0.002, worst 1086 (-0.006); not checked far from the camera |
| (a) Terrain sunk 0.05 m (0.10 m the same) | 0.8649 | 0.7971 | as above |
| (b) Third pipeline, terrain with slope-scale bias 0.25 | 0.8640 | 0.7943 | 37 `INTRO` ticks above 0.002, ticks 2918-2973 down to -0.04; any constant term hurt, 256 or more lowered IoU |
| **Prototype: ground decals** | **0.8645 (0.9897)** | **0.7973 (0.9856)** | `CTRY` none above 0.002 (worst 510, -0.0011); `INTRO` 2 ticks, 1086 (-0.0056) and 1317 (-0.0027); ticks 2918-2973 unchanged |

Patch 131 has no effect on either film: the leaf is not in view. The sink moves every polygon by a constant, and the bias pass changes the depth of the terrain against its own neighbours. The prototype changes only the props that the rule picks, by exactly the amount that makes them tie, and leaves the depth test to the decal pass of `[I5]`.

**6.4 The prototype**

*[Bounded Observation]*. `build_world_ir` snaps each ground decal onto the terrain at its `x, z` and puts every mesh of it in the `WORLD_DECAL` batch, which `[I5]` draws after the base pass with `LessEqual` and a negative bias. Index agreement with the capture rises from 0.587 to 0.884 (`CTRY`) and from 0.663 to 0.812 (`INTRO`); IoU is unchanged. It matches the sink to within 0.0004 SSIM on `CTRY` and 0.0002 on `INTRO` (below the 0.002 noise floor), without moving any terrain, so it does not touch a mountain leaf. Unlike the sink, its tie does not depend on the depth step, which grows with distance; the renderer tests below hold it to 8 km. The subpixel cull in `build_world` still drops a far prop before `build_world_ir` sees it, ground decal or not.

The renderer tests (`crates/stunt-render/tests/gpu/renderer.rs`) draw flat terrain with a tile built by hand at terrain height, as the snap would place it (they do not call `build_world_ir`). The tile shows over the terrain 80 m away, keeps at least 90% of the pixels it shows alone at 1, 1.5, 2, 4 and 8 km at a grazing angle of 5.7 degrees, and a wall of terrain in front of it hides it completely. `Depth24Plus` is enough for tiles snapped this way, so reversed-Z with `Depth32Float` was not built. It stays an option if a tile that is not exactly on the plane of its patch (a patch whose corners are not coplanar) is found to flicker far away; no such tile is in these films.

`INTRO` tick 1086 loses 0.0056 with the prototype and with the sink alike. Its terrain loss falls (0.0425 to 0.0378) and its props loss rises (0.1259 to 0.1358): a tile now covers pixels that a base prop used to win. Which prop was not identified (open question 4).

_Found 2026-11-04; see the [parity log](../../2026-10/parity-log/log.md)._

**Lives in** [`world-scene.md`](../../../research/playone-exe/world-scene.md) § 6.3.

## 2026-11-05: walking the tree for the eight sand patches

From section 2.1:

**The 8 patches: `PLAYONE` draws none of them** ([#175](https://github.com/neilsh/stunt-reel/issues/175)). *[Established]* for each comparison below; *[Supported Inference]* for the conclusion that no route draws them (`mise run scene-patches`, unpatched image, 2026-11-05). `mise run scene-patches -- build/re/playone.img corpus/siarchive/Developer/FreeFlight/SIDATA/MAP.BIN --scn <each SCENERY.scn> --scan corpus/stuntisl --scan corpus/stisldem --scan corpus/siarchive/Films --scan corpus/siarchive/Developer/FreeFlight/SIDATA` reproduces it.

* **FreeFlight's tree is `PLAYONE`'s.** The two copies of `SCENERY.scn` (`Developer/FreeFlight/SIDATA` and `Developer/SIRes/SiData`) are byte-identical. Read as 16-bit words without the leading `0`, the file's 29,558 words equal the image's tree except at 8,979 of the 9,033 link fields the walk reads, each exactly 2 higher (the other 54 are equal in both); no word outside a link field differs, and walked with that bias it gives the same 158 Ground polygons at the same offsets. FreeFlight's tree has no leaf the image lacks: FreeFlight shows the patches only because `sisland.cpp` draws every `MAP.BIN` record and never reads the leaves' polygons.
* **Their polygon is in no file but `MAP.BIN`.** A byte search for each patch's polygon in the tree's form (`[count][28 * k ...]`) and in `MAP.BIN`'s (`[count][k ...]`), in every vertex order, finds none in the unpacked image, which rules out an unreachable node or another table. The same search finds all 158 drawn records there, so the search itself works. It finds none in the 1,047 files under `corpus/stuntisl`, `corpus/stisldem`, `corpus/siarchive/Films` and FreeFlight's `SIDATA` (every `RES` and `.ALL` among them) either; its only hits are the 8 records in `MAP.BIN` itself. The image names no `MAP.BIN` file ([`terrain-shade.md`](../../../research/playone-exe/terrain-shade.md) section 2).
* **No shape taps their anchors.** A display-list shape reaches the anchor table only through `OP_TAP` ([`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 2). The same files hold 4,739 `OP_TAP`-shaped anchor operands (anchors 14 to 201), and none names 19, 20, 21, 22, 69, 72, 73 or 92, the only anchors the patches use.
* **What `PLAYONE` draws there instead.** Under the centroid of every patch but 64 lies the leaf at tree offset `0x00DA`, `MAP.BIN` record 7, colour 195, a quad about 4 km across. Colour-205 leaves (`0x0420` and others) cross it. The centroid of 64 has no Ground polygon over it. No shape the tree places inside a patch has the patch's outline. The four large patches each contain hundreds of placements, and 54 and 55 hold only rows of `0x056D`..`0x0572` 4 m apart, a few of `0x03A1`..`0x03A8` and `0x05CB`..`0x05D1`.

The colours, 64 to 91, are steps of the palette's sand ramp. The live Ground calls of section 2.2 carried none of them, which agrees but proves little: that shot looks away from them. They are sand-coloured triangles cut from four quads that are free records 133 to 136 of `MAP.BIN` ([`map.md`](../../../research/formats/auxiliary/map.md) section 2.3).

**Why the tree lacks them.** *[Established]*, `SITools/SD.EXE`, the scenery compiler that turns `MAP.BIN` into this tree ([`map.md`](../../../research/formats/auxiliary/map.md) section 3.2): every build route starts at the file's list head, and these two chains are linked from no record (`d` = `-1`, block 0), so they were never compiled. Drawn records 83 to 85, 87 to 89 then 86, and 166 to 164 chain the same way but hang from a parent through `b`. Earlier reading, *[Bounded Observation]*: (FreeFlight's `MAP.BIN`; `mise run scene-patches` prints both comparisons). All 8 have `pos = 0x00FF`, and so do 26 drawn records (29, 83 to 97, 169 to 178). Their `a` words (`+0x04`, a record offset or `-1`, [`map.md`](../../../research/formats/auxiliary/map.md) `[BK-MAP-03]`) form two chains that no other record links into, 52 to 55 and 62 to 65. Drawn records form chains like that too: 83 to 85, 87 to 89 then 86, and 166 to 164.

Two older readings this walk corrects. `OP_FRACTAL` (image `0xA56C`) is dead code: it pushes 14 words against a `ret 0x1A`, which leaves `ES` at `0x50`, so a stream cannot have run it. The 110-word "ramp directory" at `CTRY.ALL` offset `0x79` ([`all.md`](../../../research/formats/all.md) section 3.6) is the archive's chunk-id table at `0x7A` read one byte off.

**Lives in** [`world-scene.md`](../../../research/playone-exe/world-scene.md) § 2.1.

## 2026-11-05: the driver slot, live

From section 2.2:

**2.2 The driver slot, live**

*[Bounded Observation]* (`ground-driver`, `CTRY.FLM`, unpatched, DOSBox-X, 2026-11-05). The plan breaks on `0x7571`, the flat span filler that `DS:0x2246` points at, from tick 273, and records `CX`, three stack words and the slot's two bytes at each hit. The 300 hits it allows were spent by tick 293 (the first was at 280).

* **The slot holds `0x7571` at every hit.** `driver1..3.bin` have loaded by then, so the static reading of section 2 stands at runtime.
* **Two paths, told apart by the near return address.** `0x8072` is the return of the driver call inside the gateway `0:8069`, so it names the gateway, not the Ground by itself (91 hits). `0x802B` is the return inside the `0:8010` gateway, the VM polygon path (209 hits). The plan captured three stack words, and the Ground hits answer who called the gateway: all 91 carry `stack[1..2]` = `0x3D3B`, `0x1048`, the far return into the VM segment at image `0xBF7B`, the instruction after the `lcall 0:8069` at `0xBF76` inside the leaf routine `0xBF23` (section 2). The VM hits carry other words (`stack[1]` = `0x608A`, `0x1575`, `0x67EA`, ... with `stack[2]` = `0x1DF8`), none `0x3D3B`. A byte scan of the unpacked image finds one direct `lcall 0:8069`, that one at `0xBF76`, and no near `call`/`jmp rel16` that lands on `0x8069` in the first `0x9000` bytes; an indirect call is not excluded by the scan, but the live return words show only `0xBF7B` for the 91 hits. `[Bounded Observation]` for the exclusivity; `[Established]` for the instruction at `0xBF76`.
* **Ground colours.** The 91 hits from `0x8072` carry `CL` = `161`, `162`, `163`, `164` (4, 8, 4, 4), `192` (5), `193`, `194` (4 each), `195` (27), `205` (19) and `231` (12). Every one is a colour the static walk finds on a Ground polygon (section 2.1: 161-165, 192-198, 204, 205, 231), and none falls outside that set. A shade offset would leave it: a uniform +/-1 would land `231` on `230` and `205` on `206`, which no leaf carries, and the colours would not all sit on leaf values. The observed values are therefore consistent with the stored word reaching the filler unchanged, which the static reading of `0xBF23` establishes; the run does not pair each hit with its source leaf. (A missing run of consecutive values alone would not show this, since a uniform offset makes none.) The VM path carries 29 distinct values, 25 of them outside the Ground set, including every `229..238` and `136` (43), `39` (31), `47` (16).
* **The airfield's 193, 194 and 196.** In this window `196` came only from the VM path (4 hits) and `193` and `194` from both (5 and 4 from the VM, 4 and 4 from the Ground). The Ground leaves do carry `196` (3 of them). The 91 Ground hits come in four unbroken bursts of 21, 22, 22 and 26, four whole Ground passes, and none of them drew a `196`. The section 2 run (`ground-colours`, ticks 310-337, same shot) has the leaf routine `0xBF7B` draw `196` once. So the Ground does draw `196` occasionally. The `196` calls seen in this window came from the VM path, which is consistent with the tile evidence of section 3 but does not attribute any pixel. The hit counts are polygon calls, not pixels.

What the run does not show: one frame in full (the hits cover ticks 280-293), a pixel-level join of a call to a capture pixel, or Patch #3 (`--build patch3` was not run; the plan holds unpatched offsets and the pairing maps `0x7571` only if it is in a function of similarity 1.0).

**Lives in** [`world-scene.md`](../../../research/playone-exe/world-scene.md) § 2.2.

## 2026-11-05: dropping the eight patches, predicted and measured

From section 2.3:

**2.3 The change this licenses**

*[Bounded Observation]* for the measured outcome (`mise run parity`, both films, 2026-11-05); the bullets keep the prediction it tested.

* **Drop `MAP.BIN` patches 52 to 55 and 62 to 65 from `push_terrain`/`parse_map_bin`** (`crates/stunt-core/src/world.rs`). **Done** ([#212](https://github.com/neilsh/stunt-reel/issues/212)): `parse_map_bin` skips the records in `PATCHES_PLAYONE_NEVER_DRAWS`, and the world now holds 158 terrain patches, the tree's 158 Ground polygons (166 before; the six with invalid anchors were counted but never drawn). **Measured: every per-frame SSIM is identical (121 `CTRY`, 346 `INTRO` frames); tick 400, the nearest view, is byte-identical.** `CTRY` 0.8645 and `INTRO` 0.7973 before and after, so the predicted sign below held. Equal SSIM does not prove equal pixels, and only tick 400 was compared byte for byte. The nearest view among the captured ticks is `CTRY` tick 400: there the corners project inside the frame, on the horizon at row 40, columns 91 to 169, 2.5 to 4.4 km from an eye 3.6 m up. That is nearer than the 8.4 to 9.3 km predicted below for the airfield camera. Seen edge-on from there the patches change no pixel: `mise run frame` gives byte-identical frames before and after. The ground-decal snap of section 6 loses nothing: record 7 is a flat quad at height 0 that contains both patches whole, and their corners are at height 0 too, so a prop over them snaps to the same height. `PLAYONE` draws none of them by any route found (section 2.1, `[Supported Inference]`), so the drop is licensed. Under the two we draw, patches 54 (colour 87) and 55 (colour 91), `PLAYONE` draws `MAP.BIN` record 7 (colour 195), which our renderer also draws, so the drop leaves no hole. Predicted sign, `[Hypothesis]`, from geometry alone (no frame rendered). Our render draws only patches 54 and 55 of the eight; their corners are anchors 73, 69 and 20 (patch 54) and 73, 20 and 21 (patch 55) of `ANCHORPT.DAT`, at `(x, z)` = (-1184, 2208), (-1090, 2466), (736, 3096) and (736, 3086) m, height 0. **`CTRY`: zero, within the 0.002 noise floor.** The scored airfield camera (about `(6240, 0.3, -3247)`, pointing almost along `+Z`, [`film-segments.md`](../../../research/parity/film-segments.md) section 1.2) sees those corners 8.4 to 9.3 km away and 42 to 55 degrees off its axis, outside any ordinary field of view, and they are tiny at that range. **`INTRO`: zero to slightly positive.** The held sand shots at ticks 2690 to 2850 (eye about `(3000, 500, 0)` looking west) have no `MAP.BIN` patch under them ([`film-segments.md`](../../../research/parity/film-segments.md) section 2.1), and the corners lie 3.7 to 4.8 km from that eye, 28 to 54 degrees off its axis, so the patches can reach the edge of a wide view. Where one does, dropping it shows record 7 or a colour-205 leaf, which is what `PLAYONE` draws there (section 2.1), so the expected sign there is positive and small. This is not the `+0.035` / `+0.023` of section 6, which belong to the ground-decal change, a different one. The measured render agrees: no frame's SSIM moved on either film.
* **Keep patch 131's eighth vertex** (done in `8b36b79`; no frame of either film changes).
* **Keep colours as stored.** The 157 matching leaves (158 with 131) already agree with `MAP.BIN`; no re-baking or shade is licensed (Ruled out).

**Lives in** [`world-scene.md`](../../../research/playone-exe/world-scene.md) § 2.3.
