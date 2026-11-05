# `PLAYONE.EXE`: How the Ground Is Drawn and Where Its Colours Come From

* **Binary**: `PLAYONE.EXE`, unpacked load image, unpatched and Patch #3 builds; film `CTRY.FLM` (and `INTRO.FLM` for the renderer check)
* **Method**: DOSBox-X breakpoint plans in `tools/dosbox-x/plans/` (`ground-colours`, `ground-writer`, `ground-tiles`, `ground-filler`, `terrain-records`, `terrain-tree`, `ground-objects`; tool in [`debugger-plans.md`](debugger-plans.md)), iced-x86 disassembly of the unpacked image, byte comparison of the image with `MAP.BIN` and the `RES` shapes, and one renderer probe (`DBG_NO_TERRAIN`, `DBG_TERRAIN_DROP`, not committed)
* **Scope**: the code that draws the ground, where each ground colour is stored, how the airfield's scenery tiles reach the screen, and the dispatch slots of the display-list VM. How SOD polygons are *shaded* is in [`terrain-shade.md`](terrain-shade.md)
* **Anchors**: none new; the slot table is summarised in [`sod-vm.md`](sod-vm.md) section 1, the anchor table in [`memory-map.md`](memory-map.md) section 3
* **Evidence tier**: `[Established]` for the instruction sequences, the tree's place in the image and its identity with `MAP.BIN`; `[Bounded Observation]` for what the live runs drew (one emulator, `CTRY.FLM`, unpatched; each run's ticks are given where it is cited)

---

## 1. Summary

The ground is not a display-list stream. `PLAYONE` walks a BSP scenery tree that is static data in its own image (on the unpatched build paragraph `0x2286`, image `0x22860`; on the patched build its leaves start at image `0x20736`, section 2), and each ground leaf (node type 14) carries one flat polygon inline: a colour word, a vertex count and anchor-table references. Those 146 leaves are `MAP.BIN`'s polygons, the same vertices and the same colour, on both builds (section 2). The leaf routine draws them flat, with no shade.

The airfield's other colours, 193, 194 and 196 where `MAP.BIN` says 195, and the sand 91 of `INTRO.FLM`, are scenery shapes from `SCENERY2.RES` and `SCENERY3.RES`. The tree places them on top of the ground, and `OP_COLOR` sets their colour from the shape's own bytecode (section 3). The player paints in walk order, with no depth buffer, so a tile always covers the leaf under it. Our renderer places the same tiles, but its depth test hides them under the coplanar `MAP.BIN` polygons. Lowering the terrain 5 cm under them raises `CTRY.FLM` from 0.8298 to 0.8649 and `INTRO.FLM` from 0.7745 to 0.7971 SSIM (section 6).

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

157 of the 158 match a `MAP.BIN` record's vertices and colour. The other, a leaf at tree offset `0x060E`, is record 131 with its eighth vertex (anchor `50`) kept, which the record itself loses (section 2). `MAP.BIN` records 52 to 55 and 62 to 65, eight sand patches, have no polygon in the tree.

That accounts for the 20 active records with no leaf in open question 1 ([#175](https://github.com/neilsh/stunt-reel/issues/175)): the 12 coarse `SP_GROUND` polygons, which that scan did not look for, and these 8 patches. Whether `PLAYONE` draws the 8 patches another way, or only FreeFlight has them, is not settled.

Two older readings this walk corrects. `OP_FRACTAL` (image `0xA56C`) is dead code: it pushes 14 words against a `ret 0x1A`, which leaves `ES` at `0x50`, so a stream cannot have run it. The 110-word "ramp directory" at `CTRY.ALL` offset `0x79` ([`all.md`](../formats/all.md) section 3.6) is the archive's chunk-id table at `0x7A` read one byte off.

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

The rule from sections 2 and 3: a ground leaf never covers the scenery placed on it. The change it licenses is a depth bias that lets a prop lying on the terrain win over it, while the terrain still occludes what is behind it (open question 2). The sign was measured with a 5 cm drop of the terrain (`DBG_TERRAIN_DROP`), and it is up on both films:

| `DBG_TERRAIN_DROP` (m) | `CTRY` SSIM | `INTRO` SSIM | `CTRY` / `INTRO` IoU |
|---|---|---|---|
| 0 | 0.8298 | 0.7745 | 0.9897 / 0.9856 |
| 0.05 | 0.8649 | 0.7971 | 0.9897 / 0.9856 |
| 0.2 | 0.8649 | 0.7969 | 0.9896 / 0.9855 |
| 0.5 | 0.8648 | 0.7965 | 0.9896 / 0.9855 |

Predicted sign of the real change: positive on both films, about +0.035 on `CTRY` and +0.023 on `INTRO`. It is not adopted here; it belongs to [#69](https://github.com/neilsh/stunt-reel/issues/69). Re-baking the terrain colours would be wrong: they already match.

_Found 2026-11-04; see the [parity log](../parity/log.md)._

## Tools

* `mise run debug-x -- --plan tools/dosbox-x/plans/<plan>.toml` runs the plans named above ([`debugger-plans.md`](debugger-plans.md)). `terrain-tree` dumps the tree segment and the work segment once; the ground leaves are walked offline from that dump or from the image.
* `mise run scene-ground -- build/re/playone.img <MAP.BIN>` walks the tree from the image and compares its Ground with `MAP.BIN` (section 2.1); `mise run unlzexe` writes the image.
* `mise run gvpoly-stream -- <jsonl>` decodes `GVPOLY` records captured at `0x995C`/`0x9A24` (section 4.1).
* `mise run frame -- --film ctry --ticks 356 --var DBG_X=0,1` and `mise run sweep` for the renderer side; see [`method.md`](../parity/method.md).

## Ruled out

* **Re-baking `MAP.BIN`'s colours** (section 2): all 146 leaves in the image carry `MAP.BIN`'s colour byte, on both builds.
* **A shaded or Gouraud ground** (section 2): the leaf routine `0xBF23` hands its stored colour word to `0:8069` unchanged; the Gouraud filler `0:75DB` was called only for the aircraft in the airfield shot.
* **Ops `0x0168`/`0x02BE` as the ground** (section 4.1): they are `GVPOLY`/`GVPOLY16`, used there only by object `608A`.
* **The ground in `CTRY.ALL` or `VDATA.BIN`** (sections 2, 5): the tree is in the image; no 8-byte window of a live leaf polygon occurs in `VDATA.BIN` or any other file of the install (`PLAYONE.EXE` itself is LZEXE-packed on disk; the tree is in its unpacked image).
* **Tiles missing from our world** (section 6): `CTRY.ALL` carries them and `SCENERY.scn` places them; removing the terrain shows them.
* **The earlier memory scans** (2026-10-23/24): they looked for a display-list stream of `0x995C`/`0x9A24` words in conventional memory. The ground was never in that form, so "no resident list" was true but beside the point. The image region `0x23200-0x24E80` they flagged as "a serialised scenery program" is the tree.

## Open questions

1. **The 8 sand patches with no polygon in the image** ([#175](https://github.com/neilsh/stunt-reel/issues/175)). Section 2.1 accounts for 12 of the 20 active `MAP.BIN` records without a leaf: they are the coarse `SP_GROUND` polygons. `MAP.BIN` patches 52 to 55 and 62 to 65 are in no node the walk reaches. Do they exist only in FreeFlight's map, or does `PLAYONE` draw them another way? Comparing FreeFlight's `SCENERY.scn` `SP_GLEAF` positions with the image's tree would settle it.
2. **Leaves drawn after props** ([#176](https://github.com/neilsh/stunt-reel/issues/176)). The walk is back to front, so a mountain leaf in front of a prop is drawn after it and covers it. A depth bias keeps that occlusion; drawing all terrain first without depth writes would lose it. The #69 change should keep the depth test and bias only coplanar ties. The tie is not exact: `LessEqual` in place of `Less` changed neither film ([`terrain-shade.md`](terrain-shade.md) Ruled out), while a 5 cm drop does, so the bias has to exceed the tiles' small offset below the terrain.
