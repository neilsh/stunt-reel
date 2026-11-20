# Journal: actor buckets

## 2026-11-18: where the actor queue's entries go, read statically

- **Question**: Does the actor queue `0x1A90` (via `0x1AD8`) insert into a `DGROUP:0x2346` head, and which bucket `w` does an entry get?
- **Method**: static, on the unpatched load image (`mise run unlzexe`, then `mise run re-tool -- disasm` over `0x1A90..0x2410`, `0x257A..0x2A96` and `0x0000..0xD510` grepped for `2346h`, `4F00h`, `232Eh`, `2330h`, `233Ah` and `226Ah`; `mise run re-tool -- xref` on `0x4F00`, `0x2346` and `0x22D2`).
  A scratch walk of the image's scenery tree (paragraph `0x2286`, root at `SS:0`) followed the draw walk's handling of `DI` node by node: the second child of `SP_2NODE` and both children of the plane and slope nodes carry it, `SP_1NODE` carries it to `next`, the first child of `SP_2NODE` and every child of `SP_LIST` get an empty list.
  Nothing was run in DOSBox.
- **Result**:
  - `0x1AD8` takes a 16-byte entry from the arena pointer `DGROUP:0x22D2` (reset to `0x4A00` at `0x1E00`) and pushes it onto the one list at `DGROUP:0x4F00` (`0x1B02..0x1B09`; cleared at `0x1DFA`). It writes no `0x2346` head.
  - After the slot loop, `0x1E3C` loads `DI = [0x4F00]` and starts the scenery walk at `SS:0` (`0x1E82`, `jmp [bx+0x554]`), with `DI` as the list.
    `SP_XPLANE`/`SP_ZPLANE` (`0x1EF2`/`0x1EF6`) and `SP_HSLOPE`/`SP_VSLOPE` (`0x200B`/`0x2059`) split it into `DGROUP:0x232E` (child `+2`) and `0x2330` (child `+4`) by the slot's position and walk the side away from the eye first; `SP_2NODE` (`0x1EC0`) gives it to its second child; `SP_1NODE` carries it to `next` when near and draws it through `0x1B8C` after the stand-in when far or culled.
  - `SP_LEAF` (`0x220B`) sends an entry whose slot names this node at `+0x18` (or `+0x1A`) to the head `0x2346 + [slot+0x1C]` (or `+0x1D`) (`0x2294..0x22BC`); every other entry goes to `0x232E` when its depth word `+0xA` exceeds the object's (scales aligned), drawn through `0x1B8C` before the object (`0x22EE..0x22FA`), else to `0x2330`, drawn after it (`0x2354`).
  - The probe's per-object routine `0x26D0` stores the node at `DGROUP:0x233A` (`0x2730`) and clears `0x226A` (`0x275A`); a box of the object that passes `0x3047` with code word `+0xE` in 1..7 records `w = 2 × code` (`0x2A2D..0x2A56`): into `+0x1C` with the node at `+0x18` when the word `+0x1C` is zero (so `+0x1D` is 0), else into `+0x1D` with the node at `+0x1A`; once per object (`0x226A`). `0x2417` zeroes the word `+0x1C` at each probe.
  - A linear disassembly of `0x0000..0xD510` finds four references to `0x2346`: the two pushes (`0x22A8`, `0x22B8`), the test in `OP_IPG` type 4 (`0xB557`) and the take in `0x1B75` (`0x1B7F`); none clears the heads at the frame start.
  - Scratch tree walk: the list reaches 496 `SP_LEAF` nodes and 866 `SP_1NODE` nodes; it never reaches an `SP_GROUND`, `SP_GLEAF` or `SP_LIST` node, whose handlers would return without drawing it.
- **Verdict**: the queue does not feed a bucket directly. It feeds one list that the scenery walk splits by the planes; an entry joins a bucket only at the object leaf its slot's probe recorded, with `w` twice that object's collision-box code; otherwise it is drawn just before or just after the object of the leaf it reaches. Which corpus shapes have code 1..7 boxes, and whether their display lists carry `OP_IPG` type 4 with the matching `w`, was not counted. The `CTRY` tick 871 order was not replayed through the tree.
- **Lives in**: [`scene-walk-actors.md`](../../../research/playone-exe/scene-walk-actors.md).
