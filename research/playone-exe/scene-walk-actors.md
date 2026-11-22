---
summary: "How the scenery walk places actors among world objects: the actor queue pushes one list at `DGROUP:0x4F00`, the plane nodes split it by the slot's position, and each entry is drawn just before or after the object of the `SP_LEAF` it reaches, or inside that object's display list at `OP_IPG` type 4 when its probe recorded a bucket there (`w` = twice a collision-box code); replayed for `CTRY` tick 871, from the image's tree or from the world's placement records, it draws the explosion after the tower and before the foreground hill, as the capture does; at `INTRO` tick 1398 the explosion and the vehicle beside it reach one leaf, so the depth sort orders them, by the depth of the slots' own positions; 83 of the 2,516 stock shapes carry a box coded 1 to 7, and 75 of them a matching bucket on their traced path."
sidebar_label: "Actors in the scenery walk"
---
# `PLAYONE.EXE`: Actors in the Scenery Walk

`[Established]` for the instruction sequences, static, read from the unpatched load image `build/re/playone.img` with `mise run re-tool` (2026-11-18, [#680](https://github.com/neilsh/stunt-reel/issues/680)); nothing here has been run.
The walk's node layouts are [`scenery.md`](../formats/auxiliary/scenery.md)'s and its dispatch tables are in [`lod.md` § 1.1](lod.md#11-it-is-the-sp_1node-handler-and-obj-is-a-far-stand-in).

## 1. The Pending List

The actor queue `0x1A90` and the shadow queue `0x19FC` ([`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)) both end at `0x1AD8`, which takes a 16-byte entry from the arena pointer `DGROUP:0x22D2` and pushes it onto one list headed at `DGROUP:0x4F00` (`0x1B02..0x1B09`).
They write no `DGROUP:0x2346` head.
The scene walk `0x1DD5` clears `0x4F00` (`0x1DFA`) and sets `0x22D2` to `0x4A00` (`0x1E00`) before its slot loop.

| Entry offset | Holds |
|---|---|
| `+0x0` | next entry; the left child once `0x1B8C` sorts the list |
| `+0x2` | right child, once `0x1B8C` sorts the list ([`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)) |
| `+0x4` | the slot record |
| `+0x6`, `+0x8`, `+0xA` | the view-space point after `0x1B0C` (`DX`, `BP`, `DI`); `+0xA` is the depth word the sort compares |
| `+0xC` | extent: shape header word 4 shifted right by header byte 8, plus 1 |
| `+0xE` | scale byte (`CH` from `0x1B0C`) |
| `+0xF` | `AL` from `0x1B0C` (shape header byte 9), with bit `0x80` set by the actor queue (`0x1AD6`) |

After the loop, `0x1E3C` loads `DI = [0x4F00]` and starts the scenery walk at `SS:0` (`0x1E82`, `jmp [bx+0x554]`).
`DI` is the pending list, handed from node to node.

## 2. How Each Node Passes It On

| Node | Handler | What happens to the list |
|---|---|---|
| `SP_POS`, `SP_POSXZ` | `0x1E89`, `0x1EA8` | passed on unchanged |
| `SP_2NODE` | `0x1EC0` | the first child is walked with an empty list; the second gets the list |
| `SP_XPLANE`, `SP_ZPLANE` | `0x1EF2`, `0x1EF6` | split by the high word of the slot's `x` (`+6`) or `z` (`+0xE`) against the plane `[bp+6]` at the accumulated position: a slot whose extent `+0xC` lies wholly on one side goes to that side's list; a slot the plane cuts goes to its centre's side when its probe recorded one bucket (word `+0x1C` nonzero, byte `+0x1D` zero), else to the eye's side. The side away from the eye is walked first with its list, then the eye's side with its own |
| `SP_HSLOPE`, `SP_VSLOPE` | `0x200B`, `0x2059` | split the same way by the slot's centre alone, no extent |
| `SP_1NODE` | `0x20A7`, `0x2121` | near: carried to `next`; far (`0x2152`): drawn by `0x1B8C` after the stand-in; culled (`0x2149`): drawn by `0x1B8C` |
| `SP_LEAF` | `0x220B` | no object (`0x2211`) or culled (`0x226E`): drawn by `0x1B8C`. Else per entry (`0x228F..0x22EC`): if the slot's `+0x18` is this node, pushed onto the head `0x2346 + [slot+0x1C]`, or if `+0x1A` is, onto `0x2346 + [slot+0x1D]`; otherwise compared with the object's own depth word, scales aligned: a larger depth goes to `0x232E`, drawn by `0x1B8C` before the object (`0x22EE..0x22FA`), the rest to `0x2330`, drawn after it (`0x2354`) |
| `SP_GROUND`, `SP_GLEAF`, `SP_LIST` | `0x2360`, `0x23BF`, `0x1FD0` | not drawn: a ground-leaf chain returns at its end and `SP_LIST` walks each child with an empty list |

The split lists are `DGROUP:0x232E` (child `+2`) and `DGROUP:0x2330` (child `+4`).
`0x1B8C` sorts a list into the tree of [`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw) and draws it, so the entry sort there is also the list draw of the `SP_1NODE` and `SP_LEAF` handlers.
`SP_LEAF` draws an entry whose depth word exceeds the object's before the object, and the sort draws the larger depth first, so both read a larger depth word as farther.
The cull `0x1B0C` confirms the sign: it rejects a point whose depth word plus half its scaled extent is negative, behind the eye (`0x1B3C..0x1B3E`), so the depth word grows away from the eye (`[Established]`, static, [§ 6](#6-intro-tick-1398)).

In the image's tree the list never reaches the nodes that would drop it (`[Established]`, static, for the image's tree): a scratch walk that hands the list on as the table does reaches 496 `SP_LEAF` and 866 `SP_1NODE` nodes with it, and no `SP_GROUND`, `SP_GLEAF` or `SP_LIST` node.

So an actor is ordered against world objects by the scenery's partition planes, the eye's side last; against the object of the leaf it reaches, by depth; and after a far `SP_1NODE`'s stand-in.
No step compares it with an object of another leaf by distance.
_Source: [the actor queue's entries, read statically](../../work/2026-11/680_actor-buckets/journal.md#2026-11-18-where-the-actor-queues-entries-go-read-statically)._

## 3. Buckets

The probe `0x240A` ([`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw), run for slots with `SIF_MOVES`) zeroes the word at slot `+0x1C` (`0x2417`).
Its per-object routine `0x26D0` stores the object node at `DGROUP:0x233A` (`0x2730`) and clears the byte `DGROUP:0x226A` (`0x275A`) before walking the object's collision boxes.
A box that passes `0x3047` with code word `+0xE` from 1 to 7 records `w = 2 × code` (`0x2A2D..0x2A56`), once per object (`0x226A`):

* when the word at `+0x1C` is zero, into it, so `+0x1C = w` and `+0x1D = 0`, with the node at `+0x18`;
* else into the byte `+0x1D`, with the node at `+0x1A`, so a third object overwrites the second.

Code 8 is the box top that sets `+0x20/+0x22`, and a code above 8 points at a nested box list (`0x29C5..0x2A0B`).
A slot without `SIF_MOVES` is never probed, so its `+0x1C` keeps what it held, zero in the load image's records.

At that object's `SP_LEAF` the entry goes onto the head `DGROUP:0x2346 + w`.
The object's display list then draws the head where it runs `OP_IPG` type 4 with operand `w` (`0xB54C`, [`sod-vm-generators.md`](sod-vm-generators.md)): `0x1B75` takes the head, leaving it 0, and sorts and draws the list with `0x1B8C`.
So an actor with a bucket is painted among that object's own polygons, at the place the object's author put the bucket.
A linear disassembly of `0x0000..0xD510` finds four references to `0x2346`: the two pushes (`0x22A8`, `0x22B8`), the test at `0xB557` and the take at `0x1B7F`; none clears the heads at the frame start, so an entry pushed to a head that the object's display list does not reach stays there.
_Source: [the actor queue's entries, read statically](../../work/2026-11/680_actor-buckets/journal.md#2026-11-18-where-the-actor-queues-entries-go-read-statically)._

## 4. `CTRY` Tick 871

`[Bounded Observation]`, one frame of one film, replayed statically: the slot and eye positions from `CTRY.FLM` at tick 871 walked through the image's tree as § 2's handlers split the list (`0x1EF2`, `0x200B`, `0x2059`); nothing was run in the game.
The explosion is slot 11 (shape `0x0107`, [`sod-animate.md`](sod-animate.md)), and its entry's extent is `([es:4] >> [es:8]) + 1` (`0x1AF3..0x1AFE`), 17 for `MODEL_0107.SOD`, since the loaded segment is the `.SOD` file two bytes on.

| Object | Leaf | Place in the walk |
|---|---|---|
| Tower, shape `0x03DD` at `(−3191, 0, 2485)` and `(−3191, 0, 2491)` | `0x7C14` | far side (`x < −3188`) of the `SP_XPLANE` at `0x7BBE`, walked before the eye's side |
| Explosion, slot 11 at `(−3192.7, −1.9, 2489.4)` | `0x7BE0` | its centre is on the far side of `0x7BBE`, but its extent crosses that plane and four others on its path, so with no bucket it goes to each one's eye's side; it reaches `0x7BE0` with the larger depth (22.5 m against 10.4 m) and is drawn before the object |
| Foreground hill, shape `0x0262` at `(−3180, 0, 2488)` | `0x7BE0` | drawn after the explosion |

`mise run scene-walk -- corpus/stisldem/VAULT/CTRY.FLM --tick 871 --slot 11` reproduces this replay: it samples the film with `stuntreel film-slots`, reads the extent from the shapes' headers and walks the image's tree with `scene_tree.walk_slot`, which splits the entry as § 2's handlers do.
It reports leaf `0x7BE0`, the five cutting planes above, each sent to the eye's side, and the five `SP_1NODE` nodes on the path, taken as near.
It also reports five slope nodes (`0x0622`, `0x062C`, `0x5126`, `0x75DE`, `0x75E8`, each split by the slot's centre) and five plane nodes whose planes the extent clears (`0x77C4`, `0x77E4`, `0x7A4C`, `0x7A54`, `0x7BAE`).
Without `--slot` it prints each slot's DOS-axes position, shape and extent, and the eye and look target.
The draw order it prints around the explosion is the `0x03DD` tower twice, shape `0x060A` at `(−3156, 0, 2482)` in leaf `0x7BF6`, the explosion, then the hill; `0x060A` has depth −12.2 m, behind the eye.
It prints each step's view depth, taken along the eye-to-target axis at the shape's origin without its ground offset: 22.5 m for the explosion, 10.4 m for the hill and 21.7 and 20.7 m for the two towers.
The handler compares a plane at the high word of the eye plus the high word of the negated eye plus the node's sum (`0x1F05..0x1F0D`, with the walk's start at `0x1E43..0x1E7E`), which is one metre below the sum for an eye with a fractional part; the command prints the sum (`x = −3188` for `0x7BBE`) and compares at the lower value.

So the replay gives tower, explosion, hill, the order the capture shows (over the tower, under the hill).
The plane `x = −3188` separates the tower from the explosion; the hill is ordered against it by the depth compare of the leaf both reach, not by a plane.
The hill's place rests on § 2's reading that a larger depth word is farther.
The two shapes are named the tower and the hill by their place in the picture.
The replay assumes slot 11 recorded no bucket: with one, a plane its extent crosses sends it to its centre's side (§ 2), and it reaches leaf `0x7C14` instead.
`MODEL_0262.SOD` has a collision-box list and `MODEL_03DD.SOD` none.
_Source: [the CTRY tick 871 explosion replayed](../../work/2026-11/721_ctry-871-replay/journal.md#2026-11-18-the-ctry-tick-871-explosion-replayed-through-the-images-tree)._

`PlacementRecords::slot_order` ([`world/slot_order.rs`](../../crates/stunt-core/src/world/slot_order.rs)) orders an entry against the world's placement records by their partition steps, without walking the tree: a record's path agrees with the entry's down to the node where they part, whose walk order decides, and a record at the end of the entry's path is its leaf, ordered by depth, or a stand-in, drawn before it.
From `SCENERY.scn` at tick 871 it gives the same order: the towers and `0x060A` before the explosion, the hill after (`[Bounded Observation]`, one frame).
_Source: [the Rust walk at CTRY tick 871](../../work/2026-11/737_sprite-partition-order/journal.md#2026-11-20-the-rust-walk-at-ctry-tick-871)._

## 5. Which Shapes Carry Buckets

`[Bounded Observation]`, one static census of the game's own shapes: the 2,516 shapes of the stock `RES` files (`SUPERSET.ALL`; FreeFlight's six `SCENERY*.RES` are byte-identical to the game's), every box their collision lists reach, nested lists included, read as the probe's object walk `0x2886..0x289E` reads them (record types and sizes: the tables at `DGROUP:0x09FC` in [`memory-map.md`](memory-map.md); each record's words: [`sod.md` § 2.3](../formats/sod.md#23-collision-list)); nothing was run.
The list starts at the shape segment's word `+0xA`, the `.SOD` header's `collision_meta` ([`sod.md`](../formats/sod.md)), an offset that counts from two bytes before the file's first byte: read so, all 1,279 lists end at a type word `0xFFFF`; read as a file offset, none does.
Types 0 and 4 (12 bytes) lead to a nested list at `+0xA` when that word is nonzero (`0x2922`, `0x295D`, `0x2AD3`, `0x2B0E`); type 2 (16 bytes) carries § 3's code word at `+0xE`.
A code records only in the walk's first context, the table `0x09FC` (`0x2979`).
The walk holds the actor's own collision list in `DI` (`0x285B`): when the actor's shape has none, a nested list is walked in that context once its object record overlaps the actor's extent (`0x290A`, `0x29B6`, `0x2ABB`; then `0x2955`, `0x2A0C`, `0x2B06`); when it has one, a nested list is walked through the actor's records instead (tables `0x0A02`, `0x0A08`, `0x0A0E`), which skip an actor box coded 1 to 8 (`0x2B31`, `0x2D05`), every actor box met by an object record of type 4 (`0x2CFA`) and every actor record of type 4 (`0x2CF6`), and return to `0x09FC` on the object's nested list only after an actor record passes the overlap test (`0x2BD9`, `0x2CA2`, `0x2DAA`, `0x2E74`, `0x2F3A`).
So the census counts the codes an actor with no collision list can reach; 68 of the 83 coded shapes have a coded box in the top list itself, and the other 15 only in nested lists.

| Shapes | Count |
|---|---|
| With a collision list | 1,279 |
| With a box coded 1 to 7 | 83, every one with a code-1 box; codes 2 to 7 in 32, 21, 12, 8, 4 and 2 |
| Whose traced display list runs `OP_IPG` type 4 with `w` for each of its codes, and with no other `w` | 75 |
| With a code whose `w` no `OP_IPG` type 4 in the shape's bytes carries | 8: `0x024A` (`w` 2 and 4), `0x02DE` (6 and 8), and `0x03FD`, `0x3F08`, `0x3F18`, `0x3F1E`, `0x3F24` and `0x4059` (2) |
| With an `OP_IPG` type 4 and no box coded 1 to 7 | 0 |

The traced display list is the path `stuntreel sod-trace` walks; a branch it does not take is not checked.
The image's scenery tree places 72 of the 83 at an `SP_LEAF`, `0x024A`, `0x02DE` and `0x03FD` among them (846 of its 68,035 distinct leaf placements).
An actor whose probe records one of those three shapes' missing `w` goes onto a head that shape's display list does not take (§ 3).
_Source: [the collision-code census](../../work/2026-11/721_ctry-871-replay/journal.md#2026-11-18-which-stock-shapes-carry-buckets-counted-statically)._

## 6. `INTRO` Tick 1398

`[Bounded Observation]` for the leaf, one frame of one film replayed statically as in § 4; `[Established]`, static, for where the depth word comes from.
The explosion is slot 15 (shape `0x0105`) and the dark vehicle drawn beside it is slot 12 (shape `0x4150`), named by their place in the picture.
Their entries, and those of the triplane `0x7F04` (slot 10) and the second `0x4150` (slot 13), take one path to leaf `0x5FD8`: five slopes split by the centre and nine planes their extents clear, none cutting them.
So they share that leaf's pending list, and the entry sort `0x1B8C` orders them by the depth word, the larger first (§ 2); no plane decides.
`mise run scene-walk -- corpus/stisldem/VAULT/INTRO.FLM --tick 1398 --slot 15` (and `--slot 12`, `10`, `13`) reproduces it, with view depths 56.6 m for the vehicle, 55.8 m for the explosion, 53.4 m for the triplane and 52.9 m for slot 13, so the sort draws the vehicle, then the explosion, then the other two: the explosion over the vehicle, as the capture shows.

The depth word is the slot's own position: the actor queue `0x1A90` subtracts the eye `0x2A68` from the slot's `+4..+0xE` (`0x1A91..0x1AB7`), normalises the difference (`0x31CF`) and turns it by the view matrix `0x80C0` (`0x1AC4`), leaving the depth in `DI`, which the cull `0x1B0C` only shifts to align scales (`0x1B1D`).
No header word but `[es:4]`, `[es:8]` and `[es:9]` is read between them, so the shape's ground offset, which the renderer takes out of an actor's model matrix ([`projection.rs`](../../crates/stunt-core/src/scene/projection.rs) `lifted`), does not move the point the sort compares.
_Source: [the `INTRO` tick 1398 entries replayed through the walk](../../work/2026-11/819_actor-slot-depth/journal.md#2026-11-22-the-intro-tick-1398-entries-replayed-through-the-walk)._

`stunt-render` orders a 3D actor against a placed sprite by the two slots' view depths taken at `ActorDraw::position`, the slot's position, the nearer actor after the sprite; it took them at the model matrix's origin before, which the explosion's ground offset puts 4.0 m below its slot, and so drew the vehicle over the explosion at this frame.
Taking the slots' positions puts the explosion over the vehicle, as the capture does, and raised `INTRO` (evidence-backed, adopted; one run on one GPU; the other six reference films did not move a scored frame).
_Source: [actors and placed sprites by their slots' depth](../../work/2026-11/819_actor-slot-depth/journal.md#2026-11-22-actors-and-placed-sprites-by-their-slots-depth)._

## Ruled out

* **The actor queue inserts into a `DGROUP:0x2346` head** (the lead of [`sod-animate.md` § Open questions](sod-animate.md#open-questions)): it pushes onto `0x4F00`; an entry reaches a head only at the `SP_LEAF` its probe recorded (§ 1, § 3) ([the static read](../../work/2026-11/680_actor-buckets/journal.md#2026-11-18-where-the-actor-queues-entries-go-read-statically)).

## Open questions

* **Slot 11's bucket at tick 871.**
  § 4 assumes no bucket; whether slot 11 is probed and records one at `0x0262`'s leaf, which would send it to leaf `0x7C14`, is not read.
* **The three tree shapes without a matching bucket.**
  Whether an actor's probe ever records `0x024A`'s, `0x02DE`'s or `0x03FD`'s missing `w` (§ 5), and which object's display list then takes that head, is not read.
* **Buckets beyond the stock shapes and the traced path.**
  § 5 leaves out the shapes of `corpus/siarchive` beyond FreeFlight, which only `local-windows` holds, and the display-list branches `sod-trace` does not take.
* **Actors other than `OP_ANIMATE` sprites in the renderer.**
  `stunt-render` draws an `OP_ANIMATE` sprite at its slot's place in the walk, by the records' order of § 4 ([`sod-animate.md`](sod-animate.md) § 4); 3D actors stay depth-tested against props and are ordered against a placed sprite by their slots' view depths (§ 6), the sort of a shared leaf.
  An actor whose entry parts from the sprite's at a plane is ordered by that plane in `PLAYONE`, which the renderer does not model; no frame has been searched for one.
* **Live check.**
  No breakpoint has confirmed a pending list, a split or a bucket push at run time.
