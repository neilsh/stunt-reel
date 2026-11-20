# Journal: the per-placement record (#727)

## 2026-11-19: The collision records' fields, read statically and decoded over the stock shapes

**Question**: what do the words of the probe's record types 0 and 4 hold beside the nested-list word `+0xA`, and does a decode that reads each list as the walk `0x2886..0x289E` does (types 0, 2 and 4 of 12, 16 and 12 bytes, nested lists, the list pointer two more than the file offset) end every stock list at its `0xFFFF` type word?

**Method**: on commit `6ee17e0`, `mise run re-tool -- disasm 0x2750 0x2842`, `disasm 0x2840 0x28F8`, `disasm 0x2886 0x2A96`, `disasm 0x2A96 0x2B2A` and `disasm 0x2F80 0x3143` on the unpatched image.
Then `stunt_core::sod::decode_collision`, the seam 3 decode this work adds, run by a scratch Cargo example over every chunk of `target/linked/superset/SUPERSET.ALL` (`mise run superset-all`) that starts with `OP_ID`, counting lists, records by type, box codes, nested references and lists that lead back to themselves.
Last, `research/formats/sod.ksy` compiled and run by a scratch script over the same chunks, following each nested list once.

**Result**:

- Type 0 (`0x28DB`): words `+2`, `+4`, `+6` and `+8` go to `DS:0x0A24`, `0x0A26`, `0x0A28` and `0x0A2A`, each shifted right by `DS:0x2290`, and `+8` gains 1 (`0x28F7`).
  `0x2F8E` compares, on each axis, the distance from that point to the actor's previous position (`0x0A30` plus `0x0A14..0x0A18`) and to its current one (plus `0x0A1A..0x0A1E`) with the actor's extent `0x0A36` plus `0x0A2A`, giving each position an out-code; the record is missed when the two out-codes share a bit (`0x2F8E..0x3046`, `and cl,ch` at `0x3044`, `jne` at `0x290A`).
  The two positions are those `0x2762..0x2808` stores, the slot's `+0x24..+0x2F` and `+0x04..+0x0F` less the object's position.
  So a type-0 record is a cube about `(+2, +4, +6)` of half-size `+8`, tested like the bound `0x28A1` builds from the header word 4 for an object with no list.
- Type 4 (`0x2A96`): words `+2`, `+4`, `+6` go to `0x0A24..0x0A28` unshifted and `+8` to `0x0A2A` shifted.
  `0x3104` sums the products of those three words with the actor's current position (`0x0A1A..0x0A1E` plus `0x0A30..0x0A34`) into 32 bits, subtracts `0x0A2A` from the high word, doubles the result and sets the carry, an overlap, when the high word is below `0x0A36`.
  So a type-4 record is a plane with its normal in `+2..+6` and an offset in `+8`, tested at the current position only.
- Type 2 (`0x2979`): the six words `+2..+0xC` go, shifted, to `0x0A24..0x0A2E`, which `0x3047` reads as the least and greatest `x`, `y` and `z`; `+0xE` is the code.
  A record of type 0 or 4 whose `+0xA` is 0, or a box coded 0, ends the walk with a carry when it is overlapped and the actor's shape has no list (`0x2955..0x2978`, `0x2B06..0x2B29`, `0x2A0C..0x2A2A`).
- The decode over the 2,516 stock shapes: 1,279 shapes have a list, and every list ends at its `0xFFFF` type word with no stop.
  They hold 1,978 lists, 699 of them nested; the records name a nested list 699 times (541 box codes above 8, 2 cubes and 156 planes), and no list leads back to itself, so each nested list is named once.
  The records are 3,781 boxes, 333 cubes and 173 planes; 535 boxes in 207 shapes are coded 8.
  Codes 1 to 7 occur in 83 shapes (83, 32, 21, 12, 8, 4 and 2 shapes for codes 1 to 7), 68 of them with a coded box in the top list: the figures of `scene-walk-actors.md` § 5.
  The most lists in one shape is 21.
  Every plane's normal has a length within 2 of 32,768.
- `sod.ksy` over the same chunks reads 333 type-0, 3,781 type-2 and 173 type-4 records and 1,978 end words.

**Verdict**: adopted: `decode_collision` reads the lists this way and `World::placements` keeps each placed shape's lists; the per-field reading of types 0 and 4 is the instruction sequences', and the census is one static read of the stock shapes.

**Lives in**: [`sod.md` § 2.3](../../../research/formats/sod.md#23-collision-list), [`sod.ksy`](../../../research/formats/sod.ksy) and the probe rows of [`memory-map-main.md`](../../../research/playone-exe/memory-map-main.md).
