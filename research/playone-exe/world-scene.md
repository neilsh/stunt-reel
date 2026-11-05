# `PLAYONE.EXE`: How the Ground Is Drawn and Where Its Colours Come From

* **Binary**: `PLAYONE.EXE`, unpacked load image, unpatched and Patch #3 builds; film `CTRY.FLM` (and `INTRO.FLM` for the renderer check)
* **Method**: DOSBox-X breakpoint plans in `tools/dosbox-x/plans/` (`ground-colours`, `ground-writer`, `ground-tiles`, `ground-filler`, `terrain-records`, `terrain-tree`, `ground-objects`, `ground-driver`; tool in [`debugger-plans.md`](debugger-plans.md)), iced-x86 disassembly of the unpacked image, byte comparison of the image with `MAP.BIN` and the `RES` shapes, and renderer probes (`DBG_NO_TERRAIN`, `DBG_TERRAIN_DROP`, a biased terrain pass; none committed) and the ground-decal prototype
* **Scope**: the code that draws the ground, where each ground colour is stored, how the airfield's scenery tiles reach the screen, and the dispatch slots of the display-list VM. How SOD polygons are *shaded* is in [`terrain-shade.md`](terrain-shade.md)
* **Anchors**: none new; the slot table is summarised in [`sod-vm.md`](sod-vm.md) section 1, the anchor table in [`memory-map.md`](memory-map.md) section 3
* **Evidence tier**: `[Established]` for the instruction sequences, the tree's place in the image and its identity with `MAP.BIN`; `[Bounded Observation]` for what the live runs drew (one emulator, `CTRY.FLM`, unpatched; each run's ticks are given where it is cited)

---

## 1. Summary

The ground is not a display-list stream. `PLAYONE` walks a BSP scenery tree that is static data in its own image (on the unpatched build paragraph `0x2286`, image `0x22860`; on the patched build its leaves start at image `0x20736`, section 2), and each ground leaf (node type 14) carries one flat polygon inline: a colour word, a vertex count and anchor-table references. Those 146 leaves are `MAP.BIN`'s polygons, the same vertices and the same colour, on both builds (section 2). The leaf routine draws them flat, with no shade.

The airfield's other colours, 193, 194 and 196 where `MAP.BIN` says 195, and the sand 91 of `INTRO.FLM`, are scenery shapes from `SCENERY2.RES` and `SCENERY3.RES`. The tree places them on top of the ground, and `OP_COLOR` sets their colour from the shape's own bytecode (section 3). The player paints in walk order, with no depth buffer, so a tile always covers the leaf under it. Our renderer places the same tiles, but its depth test hid them under the coplanar `MAP.BIN` polygons: they lie on the terrain plane to a millimetre and tie it in depth. It now snaps flat props that lie on the terrain onto it and draws them in the decal pass, which raises `CTRY.FLM` from 0.8298 to 0.8645 and `INTRO.FLM` from 0.7745 to 0.7973 SSIM (section 6).

The ops `0x0168` and `0x02BE`, which this note used to call the ground handlers, are the Gouraud polygons `GVPOLY`/`GVPOLY16`. In the airfield shot only the hero aircraft's object draws with them (section 4.1).

## 2. The ground leaves and their colour

*[Established]* for the code; *[Bounded Observation]* for the live calls (`terrain-records`, `terrain-tree`, 2026-11-04).

The scenery walker dispatches on a node's first word through the DGROUP table at `0x554` (`jmp word [bx+0x554]` at image `0x2406`). Type 12 (`SP_GROUND` in [`map.md`](../formats/auxiliary/map.md)) is `0x2360`, type 14 (`SP_GLEAF`) `0x23BF`. A leaf is:

| Offset | Content |
|---|---|
| `+0x00` | `14` |
| `+0x02` | next node, `0` at the end of the run |
| `+0x04..+0x08` | plane normal `nx, ny, nz` |
| `+0x0A..+0x0C` | plane distance, 32-bit |
| `+0x0E` | colour word (`0x00C3`), or `0` for no polygon |
| `+0x10` | vertex count |
| `+0x12...` | per vertex `0x1C * n`, which points at anchor `n` (4 bytes before record `n` of the anchor table, `work:0x0004 + n*0x1C`) |

`0x23C5..0x23EC` dots the normal with the eye `[0x2A6A..0x2A72]` and subtracts the distance; a leaf facing the eye is drawn by `lcall 0824:3CE3` (image `0xBF23`) at `0x23F6` with `ES = SS` and `SI` on the colour word. `0xBF23` pushes the colour word and takes the count. For each vertex it re-transforms the anchor through VM `0x2C27` (image `0xAE67`) when the anchor's frame stamp `[si+0x1F]` differs from `work:0x19A8`, and copies it into the vertex arena at `0x4450`. It then calls VM `0x3D42` (image `0xBF82`, at `0xBF6C`), which returns carry to skip the polygon; otherwise `0xBF71` pops the colour into `CX` and `0xBF76` calls the raw gateway `lcall 0:8069` (return `0xBF7B`), which calls the driver through `DGROUP:[0x2246]` (`0x7175` live). The colour arrives as stored: every colour the gateway drew from this routine is a leaf colour. A ground leaf is one flat palette index.

The tree segment is the stack segment while it is walked: `SS = 0x2AAA` in the DOSBox-X session, which is load paragraph `0x0824` plus image paragraph `0x2286`. A 64 KB dump of it at tick 312 (the first leaf call after the plan armed at 300) matches the image at `0x22860` in 118 of 128 sampled 32-byte windows, one every `0x200` bytes; the other 10 hold the stack and other mutable words. So nothing builds or loads the tree: it is part of `PLAYONE.EXE`.

**Against `MAP.BIN`.** A scan for type-14 nodes whose polygon has a byte colour, 3 to 12 vertices and vertex words that are multiples of `0x1C` (anchor 0 included) finds 146 leaves in the unpatched image (`0x22866..0x30760`), 146 in the patched one (`0x20736..0x2E630`) and 146 in the live tree at tick 312. Every one has the vertex set of a `MAP.BIN` record (FreeFlight's `SIDATA`) and that record's colour byte, and together they reach 146 of its 179 records: records 99 and 100 share one vertex set and colour, and two leaves carry it. One leaf has 8 vertices. It is record 131, whose eighth anchor `50` is the word `MAP.BIN` stores as the next record's `num` ([`map.md`](../formats/auxiliary/map.md) `[BK-MAP-05]`). The 33 records with no leaf are the 13 inactive ones (`pos & 0xFF == 0`, anchor indices past 1023) and 20 active ones (open question 1). An earlier scan that stopped at 7 vertices and skipped anchor 0 found 143. The colours are `205` (28 leaves), `162` to `165` (53), `195` (12), `193`, `194` (8 each), `161` (6), `197` (5), `192`, `204` (4 each), and a few others. On the live run the gateway `0x8069` drew `0xA1..0xA4`, `0xC0..0xC4`, `0xCD` and `0xE7` from this routine alone, 300 calls over ticks 310-337.

So `MAP.BIN`'s colours are the player's ground colours. What a per-polygon colour does not explain is the subject of section 3.

### 2.1 Walking the tree statically

*[Bounded Observation]* (the unpacked image of the unpatched build and FreeFlight's `MAP.BIN`; `mise run scene-ground`).

The tree can be walked from the image alone. `python/stunt_reel/scene_tree.py` starts at `SS:0000` and follows the node types of [`map.md`](../formats/auxiliary/map.md), and `mise run scene-ground -- build/re/playone.img <MAP.BIN>` prints the result. It visits 7,009 nodes, with no node of an unknown type, and finds 158 Ground polygons: 146 `SP_GLEAF` leaves and 12 coarse `SP_GROUND` polygons. A type-12 node jumps into the leaf code at `0x23BC`, three bytes before the type-14 entry at `0x23BF`, so it draws through the same routine.

All 158 match a `MAP.BIN` record's vertices and colour once the records are read as the engine reads them: the leaf at tree offset `0x060E` is record 131, whose eighth vertex (anchor `50`) is the next record's first word (section 2). `MAP.BIN` records 52 to 55 and 62 to 65, eight sand patches, have no polygon in the tree.

That accounts for the 20 active records with no leaf in open question 1 ([#175](https://github.com/neilsh/stunt-reel/issues/175)): the 12 coarse `SP_GROUND` polygons, which that scan did not look for, and these 8 patches. Whether `PLAYONE` draws the 8 patches another way, or only FreeFlight has them, is not settled.

Two older readings this walk corrects. `OP_FRACTAL` (image `0xA56C`) is dead code: it pushes 14 words against a `ret 0x1A`, which leaves `ES` at `0x50`, so a stream cannot have run it. The 110-word "ramp directory" at `CTRY.ALL` offset `0x79` ([`all.md`](../formats/all.md) section 3.6) is the archive's chunk-id table at `0x7A` read one byte off.

### 2.2 The driver slot, live

*[Bounded Observation]* (`ground-driver`, `CTRY.FLM`, unpatched, DOSBox-X, 2026-11-05). The plan breaks on `0x7571`, the flat span filler that `DS:0x2246` points at, from tick 273, and records `CX`, three stack words and the slot's two bytes at each hit. The 300 hits it allows were spent by tick 293 (the first was at 280).

* **The slot holds `0x7571` at every hit.** `driver1..3.bin` have loaded by then, so the static reading of section 2 stands at runtime.
* **Two callers, told apart by the near return address.** `0x8072` is the Ground drawer's call to the gateway `0:8069` (91 hits). `0x802B` is the VM polygon path (209 hits), the same gateway reached from `0:8010`.
* **Ground colours.** The 91 hits from `0x8072` carry `CL` = `161`, `162`, `163`, `164` (4, 8, 4, 4), `192` (5), `193`, `194` (4 each), `195` (27), `205` (19) and `231` (12). Every one is a colour the static walk finds on a Ground polygon (section 2.1: 161-165, 192-198, 204, 205, 231), and none falls outside that set. A shade offset would leave it: a uniform +/-1 would land `231` on `230` and `205` on `206`, which no leaf carries, and the colours would not all sit on leaf values. The observed values are therefore consistent with the stored word reaching the filler unchanged, which the static reading of `0xBF23` establishes; the run does not pair each hit with its source leaf. (A missing run of consecutive values alone would not show this, since a uniform offset makes none.) The VM path carries 29 distinct values, 25 of them outside the Ground set, including every `229..238` and `136` (43), `39` (31), `47` (16).
* **The airfield's 193, 194 and 196.** In this window `196` came only from the VM path (4 hits) and `193` and `194` from both (5 and 4 from the VM, 4 and 4 from the Ground). The Ground leaves do carry `196` (3 of them). The 91 Ground hits come in four unbroken bursts of 21, 22, 22 and 26, four whole Ground passes, and none of them drew a `196`. The section 2 run (`ground-colours`, ticks 310-337, same shot) has the leaf routine `0xBF7B` draw `196` once. So the Ground does draw `196` occasionally. The `196` calls seen in this window came from the VM path, which is consistent with the tile evidence of section 3 but does not attribute any pixel. The hit counts are polygon calls, not pixels.

What the run does not show: one frame in full (the hits cover ticks 280-293), a pixel-level join of a call to a capture pixel, or Patch #3 (`--build patch3` was not run; the plan holds unpatched offsets and the pairing maps `0x7571` only if it is in a function of similarity 1.0).

### 2.3 The change this licenses

*[Hypothesis]* for the sign; it was not built.

* **Drop `MAP.BIN` patches 52 to 55 and 62 to 65 from `push_terrain`/`parse_map_bin`** (`crates/stunt-core/src/world.rs`). The tree walk reaches no polygon for them (section 2.1; whether `PLAYONE` draws them another way is still open), so dropping them remains a hypothesis until other draw paths are excluded. We draw patches 54 (colour 87) and 55 (colour 91). Predicted sign, `[Hypothesis]`, from geometry alone (no frame rendered). Our render draws only patches 54 and 55 of the eight; their corners are anchors 73, 69 and 20 (patch 54) and 73, 20 and 21 (patch 55) of `ANCHORPT.DAT`, at `(x, z)` = (-1184, 2208), (-1090, 2466), (736, 3096) and (736, 3086) m, height 0. **`CTRY`: zero, within the 0.002 noise floor.** The scored airfield camera (about `(6240, 0.3, -3247)`, pointing almost along `+Z`, [`film-segments.md`](../parity/film-segments.md) section 1.2) sees those corners 8.4 to 9.3 km away and 42 to 55 degrees off its axis, outside any ordinary field of view, and they are tiny at that range. **`INTRO`: zero to slightly positive.** The held sand shots at ticks 2690 to 2850 (eye about `(3000, 500, 0)` looking west) have no `MAP.BIN` patch under them ([`film-segments.md`](../parity/film-segments.md) section 2.1), and the corners lie 3.7 to 4.8 km from that eye, 28 to 54 degrees off its axis, so the patches can reach the edge of a wide view. Where one does, dropping it shows what lies behind it, a coarse `SP_GROUND` polygon or a tile (`push_terrain` was not checked for which), which is what `PLAYONE` draws, so the expected sign there is positive and small; if a hole showed the clear colour, the sign would be unknown. This is not the `+0.035` / `+0.023` of section 6, which belong to the ground-decal change, a different one. A measured render of the drop is the next step ([#212](https://github.com/neilsh/stunt-reel/issues/212)).
* **Keep patch 131's eighth vertex** (done in `8b36b79`; no frame of either film changes).
* **Keep colours as stored.** The 157 matching leaves (158 with 131) already agree with `MAP.BIN`; no re-baking or shade is licensed (Ruled out).

## 3. Scenery tiles drawn over the ground

*[Bounded Observation]*, `ground-colours`, `ground-writer`, `ground-tiles` (2026-11-04).

Every other flat polygon goes through the gateway `lcall 0:8010`, which reads `CX = work:0x41E8` (colour in the low byte). On the airfield shot nearly all of them come from `OP_POLYZ` (op `0x00F3`, handler `0x9B78`: `call [0x8080]`, then `lcall 0:8010` on no carry). A memory watch on `work:0x41E8` names its writer: `0x975C`, inside `OP_COLOR` (op `0x0129`, `0x975A`), 246 of 300 changing writes. In 225 of those 246 the stream after the stop is the patched `OP_POLYZ` word `0x1938` and its vertex count; 2 show the still unpatched `0x00F3` and 19 show `0x1E00`. The rest are the sky gradient (`0x8E86`, `DGROUP`) and the shade op `0xA549`.

The objects drawing `0xC1..0xC6` are each a byte-for-byte copy of a `RES` shape. The only differences are opcode words the dispatch slots had already patched into handler IPs:

| Object segment (live) | Shape (`.ALL` id) | `OP_COLOR` operands |
|---|---|---|
| `6B71`, `6B75`, `6B79`, `6BBA`, `6BC2`, `6BC6`, `6BEC` | `SCENERY2.RES` #159, 158, 157, 151, 149, 148, 144 (`0x03A0`, `0x039F`, `0x039E`, `0x0398`, `0x0396`, `0x0395`, `0x0391`) | `0x5B`, `0x58`, `0xC4`, `0xC1`, `0x5B`, `0xC2`, `0x58` |
| `6B7D`, `6B8A`, `6BD8`, `6BE0` | `SCENERY2.RES` #156, 155, 146, 145 | `0x5E 0x58 0xB8 0xB8`, `0x52 0xC3`, `0xC1 0x0E`, `0xC6 0x0E` |
| `6A97`, `6A9F`, `6AB5`, `6ABC` | `SCENERY3.RES` #6, 5, 2, 1 | `0xC5 0xC4`, `0xC6 0xC5`, `0xC1 0xC0`, `0xC2 0xC1` |
| `67EA` | `SCENERY4.RES` #105 | `0x27` |

An `.ALL` id is `(res_index << 8) | (entry + 1)` ([`all.md`](../formats/all.md) section 3.7); `CTRY.ALL` carries every one of these, and FreeFlight's `SCENERY.scn` places them as `SP_LEAF` nodes. So the colour of a tile is an operand of its own shape. The shape is drawn after the ground leaf it lies on, because the walk paints in order. In the capture at ticks 290 and 301, `0xC4`, the colour of `SCENERY2` #157, is 52-57% of the 3D view.

## 4. The dispatch slots patch the stream themselves

A search for `26 C7 44 FE` finds 108 consecutive 9-byte slots at image `0x8240..0x860B` (paragraph `0x824`), plus two handler-side patches at `0x92CD` (op `0x15F`, writes `0x1241`) and `0x93DD`. Each slot is `mov word es:[si-2], imm16; jmp rel16`, and for all 108, `imm16 + 0x8240` is the jump target. An opcode word is the offset of its own slot; on first execution the slot overwrites that word with the handler IP. There is no first-pass dispatcher to find.

| Op | Slot (`0x8246 + op`) | Handler | Patched word in the stream |
|---|---|---|---|
| `0x0156` `SHADES` | `0x839C` | `0x9481` | `0x1241` |
| `0x0168` `GVPOLY` | `0x83AE` | `0x995C` | `0x171C` |
| `0x02BE` `GVPOLY16` | `0x8504` | `0x9A24` | `0x17E4` |
| `0x0129` `OP_COLOR` | `0x836F` | `0x975A` | `0x151A` |
| `0x00F3` `OP_POLYZ` | `0x8339` | `0x9B78` | `0x1938` |

The `26 C7 44 FE imm16` tail seen after a slot's jump is a per-op module-A thunk (`0x1072`, `0x18B4`, `0x231D`), not a handler IP. Coordinates matter: IPs quoted in notebook `CS = 0x0F17` terms (`0x2551`, `0x2A2C`, `0x146C`, `0x147E`, `0x15D4`) differ from the VM's `CS = 0x824` terms by `0x1310` (notebook = image - `0x6F30`, VM = image - `0x8240`). Ghidra (12.1.4 via `rea` 6.7.0) recovers 222 functions, none in image `0x9100..0xB85C` where the handlers live, since every handler is reached through a slot; it reports no xrefs to the handlers, slots, the light-setup entry `0x9100`, `OP_IPG` or `OP_FRACTAL`, and cannot follow `jmp ax`. Its `search-bytes` is what exposed the slot run.

_Found 2026-10-23 at `6ae7b31`; see the [parity log](../parity/log.md)._

### 4.1 The Gouraud records (ops `0x0168`, `0x02BE`)

*[Established]* for the layout. `0x995C` tests `work:0x806C/0x806B`, then runs the simple path at `0x9982` or the clipped path `0x99A6`; `0x9A24` does the same at `0x9A43`. The shared tail at `0x996E` is `lodsw; and ax, 0xF; shl ax, 1; add si, ax; lodsw; jmp ax`. A record is `w0 = (ramp base << 8) | (count & 0x0F)`, then `count` indexes into the per-vertex shades `work:0x7468` written by `SHADES`, then the next code address. The base is `mov ch, es:[si+1]` at `0x9988` (or `0x9A50`), and `0x99E9..0x99F5` builds each vertex's 8.8 index as `base + max(0, (s >> 1) + G)` ([`terrain-shade.md`](terrain-shade.md) section 5). The filler is the Gouraud span routine `lcall 0:75DB`, called directly at `0x9A15` and `0x9AE5`, not through the gateway. The `0x806C == 0` path also stores the colour at `work:0x41E8` (`0x999C`) and calls `lcall 0:8010` (2026-10-23 static reading, not observed live).

*[Bounded Observation]* (`ground-objects`, `ground-filler`, `CTRY.FLM`). `ground-objects` armed both handlers at tick 270; the `0x9A24` probe spent its 300 hits by tick 313, the `0x995C` probe stayed armed to tick 900, and the filler probe covered ticks 301-354. In those spans only object `608A`, the hero aircraft (`PLANES.RES` #54, byte for byte with opcode words masked), reached these handlers: 32 distinct records, all with base `0x00`, and op `0x0168` fired 4 times, at ticks 695 and 698. All 300 calls of `0:75DB` from tick 301 came from `0x9AEA` on the same object.

## 5. The ground ops are in `CTRY.ALL`

Superseded by sections 2 and 4.1. The op `0x0168` and `0x02BE` records at `CTRY.ALL` offsets `0x13FC` and `0xEFE4` are `GVPOLY` records of the film's shapes, which are `RES` items, not ground. The 110-word table at `0x79` is neither a colour list nor a ramp directory: it is the chunk-id table at `0x7A` read one byte off (section 2.1). `CTRY.FLM` holds no ground either. The ground is in `PLAYONE.EXE`.

_Found 2026-10-23 at `6ae7b31`; superseded 2026-11-04._

## 6. What the renderer gets wrong, and the change it licenses

*[Bounded Observation]*, `build/parity` renders at `8a0ae1e`, 2026-11-04.

On the pixels our render draws as terrain, it emits `195` on 71% (`CTRY`) and 54% (`INTRO`). The capture there shows `196` (30%), `194` (24%), `193` (9%) and `163` (22%) on `CTRY`, and `163` (28%), `193` (18%), `195` (15%) and `91` (11%) on `INTRO`. On our prop pixels the two agree within about two points. The worst frames are close-ups filled by one tile: `CTRY` tick 356 has 48k mismatched terrain pixels, the capture 196 and ours 195; `INTRO` tick 1517 has 59k, the capture 91 and ours 195.

Rendering without terrain (`DBG_NO_TERRAIN=1`) puts our own tiles on those pixels with the capture's colours: tick 356 becomes 196 on 41.8k of its 54.0k terrain pixels (capture 40.4k), and tick 1517 becomes 91 on all 59.2k (capture 55.9k). So the tiles are placed and decoded; the depth test hides them under `MAP.BIN` polygons in the same plane.

The rule from sections 2 and 3: a ground leaf never covers the scenery placed on it. The change it licenses lets a prop lying on the terrain win over it, while the terrain still occludes what is behind it (open question 2). The sign was first measured with a 5 cm drop of the terrain (`DBG_TERRAIN_DROP`), and it is up on both films:

| `DBG_TERRAIN_DROP` (m) | `CTRY` SSIM | `INTRO` SSIM | `CTRY` / `INTRO` IoU |
|---|---|---|---|
| 0 | 0.8298 | 0.7745 | 0.9897 / 0.9856 |
| 0.05 | 0.8649 | 0.7971 | 0.9897 / 0.9856 |
| 0.2 | 0.8649 | 0.7969 | 0.9896 / 0.9855 |
| 0.5 | 0.8648 | 0.7965 | 0.9896 / 0.9855 |

Predicted sign of the real change: positive on both films, about +0.035 on `CTRY` and +0.023 on `INTRO`. That prediction held (section 6.4); the terrain drop itself was not adopted.

### 6.1 How far the tiles sit from the terrain

*[Bounded Observation]*, answering [#176](https://github.com/neilsh/stunt-reel/issues/176): a throwaway test over `CTRY.ALL`, `INTRO.ALL` and the `FreeFlight` `SIDATA` (2026-11-04, `8b36b79`). For every placed instance (`SCENERY.scn`, `build_world` placement, de-duplicated, nothing culled), each vertex of a flat shape was set against the `MAP.BIN` triangle over its `x, z` (the fan `push_terrain` draws; where patches overlap in plan, the one nearest the vertex). Offset = tile `y` minus terrain `y`.

* **The 16 known tiles** (`SCENERY2.RES` #144-159, ids `0x0391..0x03A0`, 41 instances in each film): offset `0.000` at the median for every shape, minimum `-0.001` for 8 shapes, `0.000` for 7, and `-0.008` for `0x0391` (one instance). Maximum `0.000`. None is above the ground and none is measurably below it.
* **Where the offset comes from.** It does not come from the data. The tile geometry sits at local `y = 0` (`0.03125` for four quads) and the placement `y` is the terrain anchor height, so the tile is the terrain plane to within a millimetre. The earlier reading that the tiles sit a little below the terrain (the `LessEqual` probe, [`terrain-shade.md`](terrain-shade.md) Ruled out) is withdrawn: what the 5 cm drop of the terrain removes is a depth tie, not a gap. A tile quad and the fan triangles of its patch are different triangulations of one plane, and their interpolated depths differ by rounding, so each pixel goes to one or the other and `Less` or `LessEqual` makes no difference.
* **Other flat props**, same method: the `0x03BE..0x03C3` markings (colour 174, 256 m) `-0.001` to `0.000`; `0x0370`, `0x02AA` (over terrain at 8 of its 37 vertices) and `0x06D5` (46 instances, colour 14) `-0.001` to `0.000`; the 751 m `0x064A` `-0.032` to `-0.030`; and `INTRO` shapes `0x05CB..0x05D7` (colour 205, 16-30 m, 416 instances) `0.000`.
* **Flat props that hover.** `INTRO` shapes `0x0790..0x07B4` (12 shapes, colour 177, 128-640 m) sit `+2.0` m above the ground (a few vertices `+0.2` to `+1.5`; one shape has a vertex at `-1.5`). They are not on it, and a ground-lying rule must leave them in the base pass.
* **Not over any terrain.** The four colour-193 quads `0x04A9..0x04AC` (SCENERY3 entries 168-171, 128-256 m, `y = 75.03`) have no `MAP.BIN` triangle under any vertex in either film.

### 6.2 A rule for ground-lying props

A prop is a ground decal when its shape is flat (all vertices within 5 cm of one height), at least one vertex has terrain below it, and every vertex that does is within 10 cm of it. On the two films it picks the 16 known tiles and nothing that stands up. It also picks, as the same kind of object, the markings and patches listed in 6.1 (`0x02AA`, `0x0370`, `0x03BE..0x03C3`, `0x064A`, `0x06D5`, and on `INTRO` `0x05CB..0x05D7`). The gap between the groups is wide: the largest offset of anything it picks is 3.2 cm, the smallest of anything it rejects is 22 cm. `ground_decal_vertices` in `crates/stunt-core/src/world.rs` implements it.

The tile list in section 3 names `SCENERY3.RES` #1, 2, 5, 6. Those are ids `0x0402`, `0x0403`, `0x0406`, `0x0407`, and the rule does not pick them: they are `OP_TAP` shapes, six vertices each, that our decode stands up 3 to 197 m, with offsets from -13 m to +233 m against the ground (open question 4).

### 6.3 Candidates

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

### 6.4 The prototype

*[Bounded Observation]*. `build_world_ir` snaps each ground decal onto the terrain at its `x, z` and puts every mesh of it in the `WORLD_DECAL` batch, which `[I5]` draws after the base pass with `LessEqual` and a negative bias. Index agreement with the capture rises from 0.587 to 0.884 (`CTRY`) and from 0.663 to 0.812 (`INTRO`); IoU is unchanged. It matches the sink to within 0.0004 SSIM on `CTRY` and 0.0002 on `INTRO` (below the 0.002 noise floor), without moving any terrain, so it does not touch a mountain leaf. Unlike the sink, its tie does not depend on the depth step, which grows with distance; the renderer tests below hold it to 8 km. The subpixel cull in `build_world` still drops a far prop before `build_world_ir` sees it, ground decal or not.

The renderer tests (`crates/stunt-render/tests/gpu/renderer.rs`) draw flat terrain with a tile built by hand at terrain height, as the snap would place it (they do not call `build_world_ir`). The tile shows over the terrain 80 m away, keeps at least 90% of the pixels it shows alone at 1, 1.5, 2, 4 and 8 km at a grazing angle of 5.7 degrees, and a wall of terrain in front of it hides it completely. `Depth24Plus` is enough for tiles snapped this way, so reversed-Z with `Depth32Float` was not built. It stays an option if a tile that is not exactly on the plane of its patch (a patch whose corners are not coplanar) is found to flicker far away; no such tile is in these films.

`INTRO` tick 1086 loses 0.0056 with the prototype and with the sink alike. Its terrain loss falls (0.0425 to 0.0378) and its props loss rises (0.1259 to 0.1358): a tile now covers pixels that a base prop used to win. Which prop was not identified (open question 5).

_Found 2026-11-04; see the [parity log](../parity/log.md)._

## Tools

* `mise run debug-x -- --plan tools/dosbox-x/plans/<plan>.toml` runs the plans named above ([`debugger-plans.md`](debugger-plans.md)). `terrain-tree` dumps the tree segment and the work segment once; the ground leaves are walked offline from that dump or from the image.
* `mise run scene-ground -- build/re/playone.img <MAP.BIN>` walks the tree from the image and compares its Ground with `MAP.BIN` (section 2.1); `mise run unlzexe` writes the image.
* `mise run gvpoly-stream -- <jsonl>` decodes `GVPOLY` records captured at `0x995C`/`0x9A24` (section 4.1).
* `mise run frame -- --film ctry --ticks 356 --var DBG_X=0,1` and `mise run sweep` for the renderer side; see [`method.md`](../parity/method.md).

## Ruled out

* **Re-baking `MAP.BIN`'s colours** (section 2): all 146 leaves in the image carry `MAP.BIN`'s colour byte, on both builds.
* **A shaded or Gouraud ground** (section 2): the leaf routine `0xBF23` hands its stored colour word to `0:8069` unchanged. On unpatched `CTRY.FLM`, a break on the driver filler `0x7571` at ticks 280-293 saw only leaf-set colours from the Ground caller (section 2.2, `[Bounded Observation]`; Patch #3 not observed). The Gouraud filler `0:75DB` was called only for the aircraft in the airfield shot, on the same build (section 4.1).
* **Ops `0x0168`/`0x02BE` as the ground** (section 4.1): they are `GVPOLY`/`GVPOLY16`, used there only by object `608A`.
* **The ground in `CTRY.ALL` or `VDATA.BIN`** (sections 2, 5): the tree is in the image; no 8-byte window of a live leaf polygon occurs in `VDATA.BIN` or any other file of the install (`PLAYONE.EXE` itself is LZEXE-packed on disk; the tree is in its unpacked image).
* **The tiles sit below the terrain** (section 6.1): they are on its plane to a millimetre; the 5 cm drop removes a depth tie. The earlier reading came from the `LessEqual` probe.
* **Sinking the terrain, or a biased third terrain pass** (section 6.3): they score 0.8649 / 0.7971 and 0.8640 / 0.7943, but the first moves every polygon and the second loses 37 `INTRO` ticks; the ground-decal prototype matches the first with no range limit.
* **Tiles missing from our world** (section 6): `CTRY.ALL` carries them and `SCENERY.scn` places them; removing the terrain shows them.
* **The earlier memory scans** (2026-10-23/24): they looked for a display-list stream of `0x995C`/`0x9A24` words in conventional memory. The ground was never in that form, so "no resident list" was true but beside the point. The image region `0x23200-0x24E80` they flagged as "a serialised scenery program" is the tree.

## Open questions

1. **The 8 sand patches with no polygon in the image** ([#175](https://github.com/neilsh/stunt-reel/issues/175)). Section 2.1 accounts for 12 of the 20 active `MAP.BIN` records without a leaf: they are the coarse `SP_GROUND` polygons. `MAP.BIN` patches 52 to 55 and 62 to 65 are in no node the walk reaches. Do they exist only in FreeFlight's map, or does `PLAYONE` draw them another way? Comparing FreeFlight's `SCENERY.scn` `SP_GLEAF` positions with the image's tree would settle it.
2. **Leaves drawn after props** ([#176](https://github.com/neilsh/stunt-reel/issues/176)). The walk is back to front, so a mountain leaf in front of a prop is drawn after it and covers it. The renderer keeps that with its depth test: only flat props within 10 cm of the ground leave the base pass (section 6.2), and the decal pass still loses to nearer terrain (tested). What is open is whether `PLAYONE` ever draws a leaf *after* a tile lying on it, which would hide the tile again; the order of the airfield leaves in the tree, read from the image, would say. The tie was not a gap (section 6.1): the tiles are on the plane to a millimetre.
3. **The four floating quads** `0x04A9..0x04AC` (colour 193, `y = 75.03`) have no `MAP.BIN` polygon under them in our parse. Either they cover a hole that the tree of `PLAYONE` fills with a leaf `MAP.BIN` lacks, or the polygon is among those our parse drops. It bears on [#175](https://github.com/neilsh/stunt-reel/issues/175).
4. **`SCENERY3.RES` #1, 2, 5, 6 (`0x0402`, `0x0403`, `0x0406`, `0x0407`).** Section 3 names them by colour (`0xC1`..`0xC6`), but our decode makes them `OP_TAP` shapes standing 3 to 197 m high that miss the terrain by -13 to +233 m. Whether the anchors resolve the way `PLAYONE` resolves them is not checked.
5. **`INTRO` ticks 1086 (-0.0056) and 1317 (-0.0027)** lose with the prototype: the props loss rises where a tile now covers pixels that a base prop won. The prop was not identified; `mise run frame -- --film intro --ticks 1086` would show it.
