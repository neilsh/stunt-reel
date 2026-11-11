---
summary: "`PLAYONE` draws the ground flat from `MAP.BIN`-coloured leaves of a BSP scenery tree in its own image and, in live CTRY runs, paints `SCENERY2.RES` tiles over it, licensing our ground-decal pass."
---
# `PLAYONE.EXE`: How the Ground Is Drawn and Where Its Colours Come From

* **Binary**: `PLAYONE.EXE`, unpacked load image, unpatched and Patch #3 builds; film `CTRY.FLM` (and `INTRO.FLM` for the renderer check)
* **Method**: DOSBox-X breakpoint plans in `tools/dosbox-x/plans/` (`ground-colours`, `ground-writer`, `ground-tiles`, `ground-filler`, `terrain-records`, `terrain-tree`, `ground-objects`, `ground-driver`; tool in [`debugger-plans.md`](debugger-plans.md)), iced-x86 disassembly of the unpacked image, byte comparison of the image with `MAP.BIN` and the `RES` shapes, and renderer probes (`DBG_NO_TERRAIN`, `DBG_TERRAIN_DROP`, a biased terrain pass; none committed) and the ground-decal prototype
* **Scope**: the code that draws the ground, where each ground colour is stored, how the airfield's scenery tiles reach the screen, and the dispatch slots of the display-list VM. How SOD polygons are *shaded* is in [`terrain-shade.md`](terrain-shade.md)
* **Anchors**: none new; the slot table is summarised in [`sod-vm.md`](sod-vm.md) section 1, the anchor table in [`memory-map.md`](memory-map.md) section 3

* **Evidence tier**: `[Established]` for the instruction sequences, the tree's place in the image and its identity with `MAP.BIN` and `SCENERY.scn`; `[Supported Inference]` that `PLAYONE` never draws `MAP.BIN` patches 52 to 55 and 62 to 65; `[Bounded Observation]` for what the live runs drew (one emulator, `CTRY.FLM`, unpatched; each run's ticks are in its journal entry)
* **Reproducing**: [`docs/howto/check-the-ground-against-playone.md`](../../docs/howto/check-the-ground-against-playone.md)

---

## 1. Summary

The ground is not a display-list stream. `PLAYONE` walks a BSP scenery tree that is static data in its own image (on the unpatched build paragraph `0x2286`, image `0x22860`; on the patched build its leaves start at image `0x20736`, section 2), and each ground leaf (node type 14) carries one flat polygon inline: a colour word, a vertex count and anchor-table references. Those 146 leaves are `MAP.BIN`'s polygons, the same vertices and the same colour, on both builds (section 2). The leaf routine draws them flat, with no shade. `MAP.BIN`'s sand patches 52 to 55 and 62 to 65 are in neither this tree nor FreeFlight's `SCENERY.scn`, which is the same tree, and `PLAYONE` draws them by no other route found (section 2.1).

The airfield's other colours, 193, 194 and 196 where `MAP.BIN` says 195, and the sand 91 of `INTRO.FLM`, are scenery shapes, among them the `SCENERY2.RES` tiles of section 3. The tree places them on top of the ground, and `OP_COLOR` sets their colour from the shape's own bytecode (section 3). The player paints in walk order, with no depth buffer, so a tile always covers the leaf under it. Our renderer places the same tiles, but its depth test hid them under the coplanar `MAP.BIN` polygons: they lie on the terrain plane to a millimetre and tie it in depth. It now snaps flat props that lie on the terrain onto it and draws them in the decal pass, which raises `CTRY.FLM` from 0.8298 to 0.8645 and `INTRO.FLM` from 0.7745 to 0.7973 SSIM (section 6).

The ops `0x0168` and `0x02BE`, which this note used to call the ground handlers, are the Gouraud polygons `GVPOLY`/`GVPOLY16`. In the airfield shot only the hero aircraft's object draws with them (section 4.1).

## 2. The ground leaves and their colour

*[Established]* for the code; *[Bounded Observation]* for the live calls (`terrain-records`, `terrain-tree`, 2026-11-04).

The scenery walker dispatches on a node's first word through the DGROUP table at `0x554` (`jmp word [bx+0x554]` at image `0x2406`). Type 12 (`SP_GROUND` in [`scenery.md`](../formats/auxiliary/scenery.md)) is `0x2360`, type 14 (`SP_GLEAF`) `0x23BF`. A leaf is:

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

The tree segment is the stack segment while it is walked (`SS = 0x2AAA` under DOSBox-X: load paragraph `0x0824` plus image paragraph `0x2286`), and in a live dump of it 118 of 128 sampled 32-byte windows, one every `0x200` bytes, match the image at `0x22860`; the other 10 hold the stack and other mutable words. Nothing builds or loads the tree: it is part of `PLAYONE.EXE`. _Source: [2026-11-04: the live ground tree](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-the-live-ground-tree)._

**Against `MAP.BIN`.** A scan for type-14 nodes whose polygon has a byte colour, 3 to 12 vertices and vertex words that are multiples of `0x1C` (anchor 0 included) finds 146 leaves in the unpatched image (`0x22866..0x30760`), 146 in the patched one (`0x20736..0x2E630`) and 146 in the live tree. Every one has the vertex set of a `MAP.BIN` record (FreeFlight's `SIDATA`) and that record's colour byte, and together they reach 146 of its 179 records: records 99 and 100 share one vertex set and colour, and two leaves carry it. One leaf has 8 vertices: record 131, whose eighth anchor `50` is the record's own eighth slot ([`map.md`](../formats/auxiliary/map.md) section 2.3). The 33 records with no leaf are the 13 inactive ones (`pos & 0xFF == 0`, anchor indices past 1023) and 20 active ones (section 2.1). The colours are `205` (28 leaves), `162` to `165` (53), `195` (12), `193`, `194` (8 each), `161` (6), `197` (5), `192`, `204` (4 each), and a few others. In the live run every colour the gateway drew from the leaf routine was a leaf colour. _Source: [2026-11-04: the live ground tree](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-the-live-ground-tree)._

So `MAP.BIN`'s colours are the player's ground colours. What a per-polygon colour does not explain is the subject of section 3.

### 2.1 Walking the tree statically

*[Bounded Observation]* (the unpacked image of the unpatched build and FreeFlight's `MAP.BIN`; `mise run scene-ground`).

The tree can be walked from the image alone. `python/stunt_reel/scene_tree.py` starts at `SS:0000` and follows the node types of [`scenery.md`](../formats/auxiliary/scenery.md), and `mise run scene-ground` prints the result ([how-to](../../docs/howto/check-the-ground-against-playone.md#walk-the-tree-and-compare-it-with-mapbin)). It visits 7,009 nodes, with no node of an unknown type, and finds 158 Ground polygons: 146 `SP_GLEAF` leaves and 12 coarse `SP_GROUND` polygons. A type-12 node jumps into the leaf code at `0x23BC`, three bytes before the type-14 entry at `0x23BF`, so it draws through the same routine.

All 158 match a `MAP.BIN` record's vertices and colour once the records are read as the engine reads them: the leaf at tree offset `0x060E` is record 131, whose eighth vertex is anchor `50` (section 2). `MAP.BIN` records 52 to 55 and 62 to 65, eight sand patches, have no polygon in the tree.

That accounts for the 20 active records with no leaf that section 2 counted: the 12 coarse `SP_GROUND` polygons, which that scan did not look for, and these 8 patches. `mise run scene-ground` lists the 12 as record and tree offset of the polygon, each with the record's colour:

| Records | Colour | Tree offsets (in record order) |
|---|---|---|
| 0 | 14 | `0x00A6` |
| 56, 68, 70, 71, 72, 82 | 205 | `0x0126`, `0x0100`, `0x014C`, `0x0172`, `0x0198`, `0x01BE` |
| 157, 158, 159 | 163, 162, 161 | `0x18E6`, `0x18C0`, `0x190A` |
| 160, 163 | 204 | `0x1948`, `0x196E` |

**The 8 patches: `PLAYONE` draws none of them** ([#175](https://github.com/neilsh/stunt-reel/issues/175)). *[Established]* for each comparison below; *[Supported Inference]* for the conclusion that no route draws them (unpatched image). _Source: [2026-11-05: walking the tree for the eight sand patches](../../work/2026-11/distill-world-scene/journal.md#2026-11-05-walking-the-tree-for-the-eight-sand-patches)._

* **FreeFlight's tree is `PLAYONE`'s.** Both copies of `SCENERY.scn` are byte-identical, and read as 16-bit words without the leading `0` their 29,558 words equal the image's tree except at 8,979 of the 9,033 link fields the walk reads, each exactly 2 higher (the other 54 are equal in both); no word outside a link field differs, and walked with that bias they give the same 158 Ground polygons at the same offsets. FreeFlight shows the patches only because `sisland.cpp` draws every `MAP.BIN` record and never reads the leaves' polygons.
* **Their polygon is in no file but `MAP.BIN`.** A byte search for each patch's polygon in the tree's form (`[count][28 * k ...]`) and in `MAP.BIN`'s (`[count][k ...]`), in every vertex order, finds none in the unpacked image, while it finds all 158 drawn records there. It finds none in the 1,047 files under `corpus/stuntisl`, `corpus/stisldem`, `corpus/siarchive/Films` and FreeFlight's `SIDATA` (every `RES` and `.ALL` among them) either, outside `MAP.BIN` itself. The image names no `MAP.BIN` file ([`terrain-shade.md`](terrain-shade.md) section 2).
* **No shape taps their anchors.** A display-list shape reaches the anchor table only through `OP_TAP` ([`sod-vm.md`](sod-vm.md) section 2). The same files hold 4,739 `OP_TAP`-shaped anchor operands (anchors 14 to 201), and none names 19, 20, 21, 22, 69, 72, 73 or 92, the only anchors the patches use.
* **What `PLAYONE` draws there instead.** Under the centroid of every patch but 64 lies the leaf at tree offset `0x00DA`, `MAP.BIN` record 7, colour 195, a quad about 4 km across, crossed by colour-205 leaves (`0x0420` and others). The centroid of 64 has no Ground polygon over it. No shape the tree places inside a patch has the patch's outline: the four large patches each contain hundreds of placements, and 54 and 55 hold only rows of `0x056D`..`0x0572` 4 m apart, a few of `0x03A1`..`0x03A8` and `0x05CB`..`0x05D1`.

| Patch | Colour | Anchors | Under its centroid in `PLAYONE` | Note | Verdict |
|---|---|---|---|---|---|
| 52 | 69 | 73, 21, 22 | leaf `0x00DA` (195) | 22 is `-32768` high in `ANCHORPT.DAT`, 0 in the image's table | ruled out |
| 53 | 64 | 73, 22, 92 | `0x00DA` | 92 is `-32768` high in the image's own table too, so not a ground point | ruled out |
| 54 | 87 | 73, 69, 20 | `0x00DA` | drawn by our renderer | ruled out |
| 55 | 91 | 73, 20, 21 | `0x00DA`, `0x0420` (205) | drawn by our renderer; 2.1 km long, 10 m wide at one end | ruled out |
| 62 | 82 | 22, 19, 72 | `0x00DA` | 22 as for 52; 19 is likewise `-32768` high in `ANCHORPT.DAT` and 0 in the image's table (`anchorpt.md` `[BK-MAP-08]`; `scene-patches` prints the image's value) | ruled out |
| 63 | 77 | 22, 72, 92 | `0x00DA` | 92 as for 53 | ruled out |
| 64 | 79 | 69, 72, 19 | none | 19 as for 62 | ruled out |
| 65 | 82 | 69, 19, 20 | `0x00DA` | 19 as for 62 | ruled out |

The colours, 64 to 91, are steps of the palette's sand ramp; the live Ground calls of section 2.2 carried none of them, but that shot looks away from the patches. They are sand-coloured triangles cut from four quads that are free records 133 to 136 of `MAP.BIN` ([`map.md`](../formats/auxiliary/map.md) section 2.3). _Source: [2026-11-05: walking the tree for the eight sand patches](../../work/2026-11/distill-world-scene/journal.md#2026-11-05-walking-the-tree-for-the-eight-sand-patches)._

**Why the tree lacks them.** *[Established]*, `SITools/SD.EXE`, the scenery compiler that turns `MAP.BIN` into this tree ([`map.md`](../formats/auxiliary/map.md) section 3.2): every build route starts at the file's list head, and these two chains (52 to 55 and 62 to 65, through their `a` words, `+0x04`, [`map.md`](../formats/auxiliary/map.md) `[BK-MAP-03]`) are linked from no record (`d` = `-1`, block 0), so they were never compiled. Drawn records 83 to 85, 87 to 89 then 86, and 166 to 164 chain the same way but hang from a parent through `b`. No field of the patches' own marks them: all 8 have `pos = 0x00FF`, as do 26 drawn records (Ruled out). _Source: [2026-11-05: walking the tree for the eight sand patches](../../work/2026-11/distill-world-scene/journal.md#2026-11-05-walking-the-tree-for-the-eight-sand-patches)._

`OP_FRACTAL` (image `0xA56C`) is dead code: it pushes 14 words against a `ret 0x1A`, which leaves `ES` at `0x50`, so a stream cannot have run it. The 110-word "ramp directory" at `CTRY.ALL` offset `0x79` ([`all.md`](../formats/all.md) section 3.6) is the archive's chunk-id table at `0x7A` read one byte off. _Source: [2026-11-05: walking the tree for the eight sand patches](../../work/2026-11/distill-world-scene/journal.md#2026-11-05-walking-the-tree-for-the-eight-sand-patches)._

### 2.2 The driver slot, live

*[Bounded Observation]* (`ground-driver`, `CTRY.FLM`, unpatched, ticks 280-293; Patch #3 not run). _Source: [2026-11-05: the driver slot, live](../../work/2026-11/distill-world-scene/journal.md#2026-11-05-the-driver-slot-live)._

* **The slot holds the flat span filler `0x7571` at every hit**, after `driver1..3.bin` have loaded, so the static reading of section 2 stands at runtime.
* **The Ground's calls are the leaf routine's.** A hit through the gateway `0:8069` returns to `0x8072`; one through `0:8010`, the VM polygon path, to `0x802B`. All 91 Ground hits carry the far return `0x3D3B`:`0x1048`, image `0xBF7B`, just after the `lcall 0:8069` at `0xBF76` in the leaf routine `0xBF23`; none of the 209 VM hits does. A byte scan of the image finds one direct `lcall 0:8069`, that one at `0xBF76`, and no near `call`/`jmp rel16` onto `0x8069` in the first `0x9000` bytes; an indirect call is not excluded. `[Established]` for the instruction at `0xBF76`, `[Bounded Observation]` for the exclusivity.
* **Ground colours.** The 91 Ground hits carry `CL` = `161`..`164`, `192`, `193`, `194`, `195`, `205` and `231`, each a colour the static walk finds on a Ground polygon (161-165, 192-198, 204, 205, 231). A uniform shade offset of +/-1 would move `231` to `230` or `205` to `206`, which no leaf carries. This is consistent with the static reading of `0xBF23`; the run does not pair each hit with its leaf. The VM path carries 29 distinct values, 25 outside the Ground set.
* **The airfield's 193, 194 and 196.** Leaves carry `196` (3 of them), and the leaf routine drew it once in the `ground-colours` run (section 2), but none of the four whole Ground passes of this run did; its `196` calls came from the VM path, and `193` and `194` from both. That is consistent with the tiles of section 3 but attributes no pixel: hit counts are polygon calls, not pixels.

Not shown: one frame in full, a join of a call to a capture pixel, or Patch #3 (the plan holds unpatched offsets, and the build pairing maps `0x7571` only if it is in a function of similarity 1.0).

### 2.3 The change this licenses

*[Bounded Observation]* for the measured outcome (`mise run parity`, both films). _Source: [2026-11-05: dropping the eight patches](../../work/2026-11/distill-world-scene/journal.md#2026-11-05-dropping-the-eight-patches-predicted-and-measured)._

* **`MAP.BIN` patches 52 to 55 and 62 to 65 are dropped** ([#212](https://github.com/neilsh/stunt-reel/issues/212)): `parse_map_bin` (`crates/stunt-core/src/world.rs`) skips the records in `PATCHES_PLAYONE_NEVER_DRAWS`, and the world holds 158 terrain patches, the tree's 158 Ground polygons. Every per-frame SSIM stayed identical (121 `CTRY`, 346 `INTRO` frames; `CTRY` 0.8645, `INTRO` 0.7973), and `CTRY` tick 400, the nearest view of the patches among the captured ticks, is byte-identical. Equal SSIM does not prove equal pixels elsewhere. Under the two patches we drew (54 and 55), `PLAYONE` draws record 7 (colour 195), which our renderer also draws, so the drop leaves no hole, and the ground-decal snap of section 6 is unchanged: record 7 is a flat quad at height 0 that contains both patches whole, and their corners are at height 0 too.
* **Patch 131 keeps its eighth vertex** (`8b36b79`; no frame of either film changes).
* **Colours stay as stored.** The 158 Ground polygons already agree with `MAP.BIN`; no re-baking or shade is licensed (Ruled out).

## 3. Scenery shapes drawn over the ground

*[Bounded Observation]*, `ground-colours`, `ground-writer`, `ground-tiles` (2026-11-04).

Every other flat polygon goes through the gateway `lcall 0:8010`, which reads `CX = work:0x41E8` (colour in the low byte). On the airfield shot nearly all of them come from `OP_POLYZ` (op `0x00F3`, handler `0x9B78`: `call [0x8080]`, then `lcall 0:8010` on no carry). A memory watch on `work:0x41E8` names its writer: `0x975C`, inside `OP_COLOR` (op `0x0129`, `0x975A`), 246 of 300 changing writes. In 225 of those 246 the stream after the stop is the patched `OP_POLYZ` word `0x1938` and its vertex count; 2 show the still unpatched `0x00F3` and 19 show `0x1E00`. The rest are the sky gradient (`0x8E86`, `DGROUP`) and the shade op `0xA549`.

The objects drawing `0xC1..0xC6`, tiles and hill fins, are each a byte-for-byte copy of a `RES` shape. The only differences are opcode words the dispatch slots had already patched into handler IPs:

| Object segment (live) | Shape (`.ALL` id) | `OP_COLOR` operands |
|---|---|---|
| `6B71`, `6B75`, `6B79`, `6BBA`, `6BC2`, `6BC6`, `6BEC` | `SCENERY2.RES` #159, 158, 157, 151, 149, 148, 144 (`0x03A0`, `0x039F`, `0x039E`, `0x0398`, `0x0396`, `0x0395`, `0x0391`) | `0x5B`, `0x58`, `0xC4`, `0xC1`, `0x5B`, `0xC2`, `0x58` |
| `6B7D`, `6B8A`, `6BD8`, `6BE0` | `SCENERY2.RES` #156, 155, 146, 145 | `0x5E 0x58 0xB8 0xB8`, `0x52 0xC3`, `0xC1 0x0E`, `0xC6 0x0E` |
| `6A97`, `6A9F`, `6AB5`, `6ABC` | `SCENERY3.RES` #6, 5, 2, 1 (hill fins, not tiles) | `0xC5 0xC4`, `0xC6 0xC5`, `0xC1 0xC0`, `0xC2 0xC1` |
| `67EA` | `SCENERY4.RES` #105 | `0x27` |

An `.ALL` id is `(res_index << 8) | (entry + 1)` ([`all.md`](../formats/all.md) section 3.7); `CTRY.ALL` carries every one of these, and FreeFlight's `SCENERY.scn` places them as `SP_LEAF` nodes. So the colour of a tile is an operand of its own shape. The four `SCENERY3.RES` rows are not tiles, though. They are `OP_TAP` shapes, vertical fins standing in hills, coloured like the hill patches they stand in ([`sod-vm.md`](sod-vm.md) section 5). The run shows only that they were drawn in that shot, not where. The shape is drawn after the ground leaf it lies on, because the walk paints in order. In the capture at ticks 290 and 301, `0xC4`, the colour of `SCENERY2` #157, is 52-57% of the 3D view.

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

_Source: found 2026-10-23 at `6ae7b31`; see the [parity log](../../work/2026-10/parity-log/log.md)._

### 4.1 The Gouraud records (ops `0x0168`, `0x02BE`)

*[Established]* for the layout. `0x995C` tests `work:0x806C/0x806B`, then runs the simple path at `0x9982` or the clipped path `0x99A6`; `0x9A24` does the same at `0x9A43`. The shared tail at `0x996E` is `lodsw; and ax, 0xF; shl ax, 1; add si, ax; lodsw; jmp ax`. A record is `w0 = (ramp base << 8) | (count & 0x0F)`, then `count` indexes into the per-vertex shades `work:0x7468` written by `SHADES`, then the next code address. The base is `mov ch, es:[si+1]` at `0x9988` (or `0x9A50`), and `0x99E9..0x99F5` builds each vertex's 8.8 index as `base + max(0, (s >> 1) + G)` ([`terrain-shade.md`](terrain-shade.md) section 5). The filler is the Gouraud span routine `lcall 0:75DB`, called directly at `0x9A15` and `0x9AE5`, not through the gateway. The `0x806C == 0` path also stores the colour at `work:0x41E8` (`0x999C`) and calls `lcall 0:8010` (2026-10-23 static reading, not observed live).

*[Bounded Observation]* (`ground-objects`, `ground-filler`, `CTRY.FLM`). `ground-objects` armed both handlers at tick 270; the `0x9A24` probe spent its 300 hits by tick 313, the `0x995C` probe stayed armed to tick 900, and the filler probe covered ticks 301-354. In those spans only object `608A`, the hero aircraft (`PLANES.RES` #54, byte for byte with opcode words masked), reached these handlers: 32 distinct records, all with base `0x00`, and op `0x0168` fired 4 times, at ticks 695 and 698. All 300 calls of `0:75DB` from tick 301 came from `0x9AEA` on the same object.

## 5. The ground ops are in `CTRY.ALL`

Superseded by sections 2 and 4.1. The op `0x0168` and `0x02BE` records at `CTRY.ALL` offsets `0x13FC` and `0xEFE4` are `GVPOLY` records of the film's `RES` shapes, not ground, and `CTRY.FLM` holds no ground either: the ground is in `PLAYONE.EXE`. _Source: [2026-10-23: the ground ops in CTRY.ALL](../../work/2026-11/distill-world-scene/journal.md#2026-10-23-the-ground-ops-in-ctryall-superseded)._

## 6. What the renderer gets wrong, and the change it licenses

*[Bounded Observation]*, `build/parity` renders, 2026-11-04. _Source: [2026-11-04: what the renderer drew over the airfield](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-what-the-renderer-drew-over-the-airfield-and-the-terrain-drop)._

Before the change, our render emitted `195` on most pixels it drew as terrain (71% `CTRY`, 54% `INTRO`) where the capture shows the tiles' colours (`196`, `194`, `193`, `163` on `CTRY`; `163`, `193`, `195`, `91` on `INTRO`); the worst frames were close-ups filled by one tile (`CTRY` tick 356, capture 196; `INTRO` tick 1517, capture 91). Rendering without terrain (`DBG_NO_TERRAIN=1`) put our own tiles on those pixels with the capture's colours, so the tiles were placed and decoded; the depth test hid them under `MAP.BIN` polygons in the same plane.

The rule from sections 2 and 3: the walk paints a tile after the ground leaf it lies on, so that leaf never covers it (whether a later leaf can is open question 1). The change it licenses lets a prop lying on the terrain win over it, while the terrain still occludes what is behind it (open question 1). It raised `CTRY` from 0.8298 to 0.8645 and `INTRO` from 0.7745 to 0.7973 SSIM, as a 5 cm terrain drop (`DBG_TERRAIN_DROP`, not adopted) had predicted. _Source: [2026-11-04: candidates and the ground-decal prototype](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-candidates-and-the-ground-decal-prototype)._

### 6.1 How far the tiles sit from the terrain

*[Bounded Observation]*, answering [#176](https://github.com/neilsh/stunt-reel/issues/176), over `CTRY.ALL`, `INTRO.ALL` and the `FreeFlight` `SIDATA`: each vertex of every placed flat shape set against the `MAP.BIN` triangle over its `x, z`; offset = tile `y` minus terrain `y`. _Source: [2026-11-04: how far the tiles sit from the terrain](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-how-far-the-tiles-sit-from-the-terrain)._

* **The 16 known tiles** (`SCENERY2.RES` #144-159, ids `0x0391..0x03A0`, 41 instances in each film) lie on the terrain plane: median offset `0.000` for every shape, none above it, the lowest `-0.008` (`0x0391`, one instance). The tile geometry sits at local `y = 0` (`0.03125` for four quads) and its placement `y` is the terrain anchor height.
* **So the hiding was a depth tie, not a gap.** A tile quad and the fan triangles of its patch are different triangulations of one plane whose interpolated depths differ by rounding, so each pixel goes to one or the other, and `Less` or `LessEqual` makes no difference. The earlier reading that the tiles sit a little below the terrain is withdrawn (Ruled out).
* **Other flat props on the ground**, within 3.2 cm: the `0x03BE..0x03C3` markings (colour 174, 256 m), `0x0370`, `0x02AA` (over terrain at 8 of its 37 vertices), `0x06D5` (46 instances, colour 14), the 751 m `0x064A` (`-0.032` to `-0.030`), and `INTRO` shapes `0x05CB..0x05D7` (colour 205, 16-30 m, 416 instances).
* **Flat props that hover.** `INTRO` shapes `0x0790..0x07B4` (12 shapes, colour 177, 128-640 m) sit about `+2.0` m above the ground (a few vertices `+0.2` to `+1.5`, one at `-1.5`), so a ground-lying rule must leave them in the base pass.
* **Not over any terrain.** The four colour-193 quads `0x04A9..0x04AC` (SCENERY3 entries 168-171, 128-256 m, `y = 75.03`) have no `MAP.BIN` triangle under any vertex in either film.

### 6.2 A rule for ground-lying props

A prop is a ground decal when its shape is flat (all vertices within 5 cm of one height), at least one vertex has terrain below it, and every vertex that does is within 10 cm of it. On the two films it picks the 16 known tiles and nothing that stands up. It also picks, as the same kind of object, the markings and patches listed in 6.1 (`0x02AA`, `0x0370`, `0x03BE..0x03C3`, `0x064A`, `0x06D5`, and on `INTRO` `0x05CB..0x05D7`). The gap between the groups is wide: the largest offset of anything it picks is 3.2 cm, the smallest of anything it rejects is 22 cm. `ground_decal_vertices` in `crates/stunt-core/src/world.rs` implements it.

The rule does not pick `SCENERY3.RES` #1, 2, 5 and 6 (`0x0402`, `0x0403`, `0x0406`, `0x0407`), and should not. They are not tiles but vertical fins standing in the hills. `OP_TAP` loads each anchor less the shape's origin, and our decode first got this wrong ([`sod-vm.md`](sod-vm.md) sections 4 and 5). _Source: [2026-11-11: what the 14 TAP shapes are](../../work/2026-11/254_tap-anchors/journal.md#2026-11-11-what-the-14-tap-shapes-are)._

### 6.3 Candidates

*[Bounded Observation]*, both films, `mean_ssim_scored` (`CTRY` / `INTRO`). _Source: [2026-11-04: candidates and the ground-decal prototype](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-candidates-and-the-ground-decal-prototype)._

* **Ground decals (adopted)**: 0.8645 / 0.7973 from 0.8298 / 0.7745; IoU unchanged, index agreement 0.587 to 0.884 / 0.663 to 0.812. No `CTRY` tick loses more than 0.002 (worst 510, -0.0011); on `INTRO` tick 1086 loses 0.0056 and 1317 0.0027 (open question 4).
* **Terrain sunk 0.02 to 0.10 m**: 0.8649 / 0.7968 to 0.7971 (0.05 m: within 0.0004 / 0.0002 of the decals), but it moves every polygon and its tie depends on the depth step, which grows with distance. No `CTRY` tick lost more than 0.001; 6 `INTRO` ticks lost more than 0.002, worst 1086 (-0.006); ticks far from the camera were not checked.
* **A third pipeline drawing terrain with slope-scale bias 0.25**: 0.8640 / 0.7943, losing 37 `INTRO` ticks (ticks 2918-2973 down to -0.04); any constant bias term hurt.

### 6.4 The ground-decal pass

*[Bounded Observation]* for the measured and tested behaviour. `build_world_ir` snaps each ground decal onto the terrain at its `x, z` and puts every mesh of it in the `WORLD_DECAL` batch, which `[I5]` draws after the base pass with `LessEqual` and a negative bias ([ADR 0035](../../docs/adr/0035-ground-lying-props-are-terrain-decals.md)). It moves no terrain, so it does not touch a mountain leaf. The subpixel cull in `build_world` still drops a far prop before `build_world_ir` sees it, ground decal or not. _Source: [2026-11-04: candidates and the ground-decal prototype](../../work/2026-11/distill-world-scene/journal.md#2026-11-04-candidates-and-the-ground-decal-prototype)._

The renderer tests (`crates/stunt-render/tests/gpu/renderer.rs`) draw flat terrain with a tile built by hand at terrain height, as the snap would place it (they do not call `build_world_ir`). The tile shows over the terrain 80 m away, keeps at least 90% of the pixels it shows alone at 1, 1.5, 2, 4 and 8 km at a grazing angle of 5.7 degrees, and a wall of terrain in front of it hides it completely. `Depth24Plus` is enough for tiles snapped this way, so reversed-Z with `Depth32Float` was not built; it stays an option if a tile not exactly on the plane of its patch is found to flicker far away. No such tile is in these films.

## Ruled out

* **Re-baking `MAP.BIN`'s colours** (section 2): all 146 leaves in the image carry `MAP.BIN`'s colour byte, on both builds.
* **A shaded or Gouraud ground** (section 2): the leaf routine `0xBF23` hands its stored colour word to `0:8069` unchanged. On unpatched `CTRY.FLM`, a break on the driver filler `0x7571` at ticks 280-293 saw only leaf-set colours from the Ground caller (section 2.2, `[Bounded Observation]`; Patch #3 not observed). The Gouraud filler `0:75DB` was called only for the aircraft in the airfield shot, on the same build (section 4.1).
* **Ops `0x0168`/`0x02BE` as the ground** (section 4.1): they are `GVPOLY`/`GVPOLY16`, used there only by object `608A`.
* **The ground in `CTRY.ALL` or `VDATA.BIN`** (sections 2, 5): the tree is in the image; no 8-byte window of a live leaf polygon occurs in `VDATA.BIN` or any other file of the install (`PLAYONE.EXE` itself is LZEXE-packed on disk; the tree is in its unpacked image).
* **The tiles sit below the terrain** (section 6.1): they are on its plane to a millimetre; the 5 cm drop removes a depth tie. The earlier reading came from the `LessEqual` probe.
* **Sinking the terrain, or a biased third terrain pass** (section 6.3): they score 0.8649 / 0.7971 and 0.8640 / 0.7943, but the first moves every polygon and the second loses 37 `INTRO` ticks; the ground-decal pass matches the first without moving terrain, and its tie holds in the renderer tests to 8 km.
* **`SCENERY3.RES` #1, 2, 5, 6 as airfield tiles** (sections 3, 6.2): they are `OP_TAP` hill fins, vertical triangles from a hill's foot to its ridge (`0x0402` 155 m, `0x0403` 196 m, `0x0406` 155 m, `0x0407` 196 m), once the anchors are loaded less the shape's origin as `PLAYONE` loads them. They share the tiles' colours only because the hill patches use the same range. _Source: [2026-11-11: what the 14 TAP shapes are](../../work/2026-11/254_tap-anchors/journal.md#2026-11-11-what-the-14-tap-shapes-are)._
* **Tiles missing from our world** (section 6): `CTRY.ALL` carries them and `SCENERY.scn` places them; removing the terrain shows them.
* **A leaf for patches 52 to 55 and 62 to 65 in FreeFlight's tree** (section 2.1): both copies of `SCENERY.scn` are the image's tree, links aside, with the same 158 Ground polygons.
* **Another node, table or shape that draws those patches** (section 2.1): their polygon occurs in no file but `MAP.BIN`, the image included, while the same search finds all 158 drawn records there; no `OP_TAP` operand in the image, the `RES` files or any `.ALL` names one of their anchors.
* **A field of the record that marks those patches** (section 2.1): their `pos` is `0x00FF`, as it is for 26 drawn records. What sets them apart is that nothing links to their chains, not a field of their own.
* **A leaf of `PLAYONE`'s tree that `MAP.BIN` lacks** (section 2.1, open question 2): `mise run scene-ground` finds no tree-only polygon; all 158 are `MAP.BIN` records.
* **The earlier memory scans** (2026-10-23/24): they looked for a display-list stream of `0x995C`/`0x9A24` words in conventional memory. The ground was never in that form, so "no resident list" was true but beside the point. The image region `0x23200-0x24E80` they flagged as "a serialised scenery program" is the tree.

## Open questions

1. **Leaves drawn after props** ([#176](https://github.com/neilsh/stunt-reel/issues/176)). The walk is back to front, so a mountain leaf in front of a prop is drawn after it and covers it. The renderer keeps that with its depth test: only flat props within 10 cm of the ground leave the base pass (section 6.2), and the decal pass still loses to nearer terrain (tested). What is open is whether `PLAYONE` ever draws a leaf *after* a tile lying on it, which would hide the tile again; the order of the airfield leaves in the tree, read from the image, would say. The tie was not a gap (section 6.1): the tiles are on the plane to a millimetre.
2. **The four floating quads** `0x04A9..0x04AC` (colour 193, `y = 75.03`) have no `MAP.BIN` polygon under them in our parse. The tree of `PLAYONE` has no leaf that `MAP.BIN` lacks (section 2.1, Ruled out), so either the polygon under them is among the records our parse drops, or nothing is.
3. **Where `PLAYONE` draws the hill fins.** The `OP_TAP` fins (`0x0202`–`0x0208`, `0x0402`–`0x0408`) stand in hills ([`sod-vm.md`](sod-vm.md) section 5). Section 3's run saw four of them drawn in `CTRY`'s airfield shot, but our scene walk places none of them on `CTRY`: each sits behind an `SP_1NODE` whose far stand-in our path-distance stand-in for `PLAYONE`'s per-frame test picks instead ([`lod.md`](lod.md)). On `INTRO` it places `0x0402`–`0x0404`, and no scored frame changed when they were resolved correctly. So whether a fin shows through the hill patches in front of it, as the painter might draw it, is not seen in either film. _Source: [2026-11-11: rescoring both films](../../work/2026-11/254_tap-anchors/journal.md#2026-11-11-rescoring-both-films)._
4. **`INTRO` ticks 1086 (-0.0056) and 1317 (-0.0027)** lose with the prototype: the props loss rises where a tile now covers pixels that a base prop won. The prop was not identified; `mise run frame -- --film intro --ticks 1086` would show it.
