---
summary: "How the scenery walk places actors among world objects: the actor queue pushes one list at `DGROUP:0x4F00`, the plane nodes split it by the slot's position, and each entry is drawn just before or after the object of the `SP_LEAF` it reaches, or inside that object's display list at `OP_IPG` type 4 when its probe recorded a bucket there (`w` = twice a collision-box code); replayed for `CTRY` tick 871, it draws the explosion after the tower and before the foreground hill, as the capture does."
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
`SP_LEAF` draws an entry whose depth word exceeds the object's before the object, and the sort draws the larger depth first, so both read a larger depth word as farther (`[Supported Inference]`: the depth row's sign is not read).

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

`[Bounded Observation]`, one frame of one film, replayed statically: the slot and eye positions from `CTRY.FLM` at tick 871 walked through the image's tree as § 2's handlers split the list (`0x1EF2`, `0x200B`, `0x2059`); nothing was run.
The explosion is slot 11 (shape `0x0107`, [`sod-animate.md`](sod-animate.md)), and its entry's extent is `([es:4] >> [es:8]) + 1` (`0x1AF3..0x1AFE`), 17 for `MODEL_0107.SOD`, since the loaded segment is the `.SOD` file two bytes on.

| Object | Leaf | Place in the walk |
|---|---|---|
| Tower, shape `0x03DD` at `(−3191, 0, 2485)` and `(−3191, 0, 2491)` | `0x7C14` | far side (`x < −3188`) of the `SP_XPLANE` at `0x7BBE`, walked before the eye's side |
| Explosion, slot 11 at `(−3192.7, −1.9, 2489.4)` | `0x7BE0` | its centre is on the far side of `0x7BBE`, but its extent crosses that plane and four others on its path, so with no bucket it goes to each one's eye's side; it reaches `0x7BE0` with the larger depth (22.5 m against 10.4 m) and is drawn before the object |
| Foreground hill, shape `0x0262` at `(−3180, 0, 2488)` | `0x7BE0` | drawn after the explosion |

So the replay gives tower, explosion, hill, the order the capture shows (over the tower, under the hill).
The plane `x = −3188` separates the tower from the explosion; the hill is ordered against it by the depth compare of the leaf both reach, not by a plane.
The two shapes are named the tower and the hill by their place in the picture.
The replay assumes slot 11 recorded no bucket: with one, a plane its extent crosses sends it to its centre's side (§ 2), and it reaches leaf `0x7C14` instead.
`MODEL_0262.SOD` has a collision-box list and `MODEL_03DD.SOD` none.
_Source: [the CTRY tick 871 explosion replayed](../../work/2026-11/721_ctry-871-replay/journal.md#2026-11-18-the-ctry-tick-871-explosion-replayed-through-the-images-tree)._

## Ruled out

* **The actor queue inserts into a `DGROUP:0x2346` head** (the lead of [`sod-animate.md` § Open questions](sod-animate.md#open-questions)): it pushes onto `0x4F00`; an entry reaches a head only at the `SP_LEAF` its probe recorded (§ 1, § 3) ([the static read](../../work/2026-11/680_actor-buckets/journal.md#2026-11-18-where-the-actor-queues-entries-go-read-statically)).

## Open questions

* **Slot 11's bucket at tick 871.**
  § 4 assumes no bucket; whether slot 11 is probed and records one at `0x0262`'s leaf, which would send it to leaf `0x7C14`, is not read.
* **Which shapes carry buckets** ([#721](https://github.com/neilsh/stunt-reel/issues/721) step 2).
  Count the corpus shapes with collision boxes coded 1 to 7, and whether each one's display list runs `OP_IPG` type 4 with the matching `w` on every path; 152 walk steps reach type 4 ([`sod-vm-generators.md`](sod-vm-generators.md)).
* **The renderer** ([#741](https://github.com/neilsh/stunt-reel/issues/741)).
  `stunt-render` draws the world in one depth-tested pass; drawing each actor at its leaf's place in the partition order needs the scenery's planes at draw time.
* **Live check.**
  No breakpoint has confirmed a pending list, a split or a bucket push at run time.
