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

## 2026-11-20: The box-top rule read statically, and the probe over the reference films

**Question**: what does `0x240A` do between an overlapped code-8 box and the stored shadow height, which segment is which in its walk, and does adding that probe to the film scene move any reference film on lavapipe?

**Method**: on commit `fd3f84a`, `mise run re-tool -- disasm 0x2750 0x2842`, `disasm 0x2840 0x28DB`, `disasm 0x28DB 0x2979`, `disasm 0x2979 0x2A96`, `disasm 0x2A96 0x2B2A`, `disasm 0x2F8E 0x3047`, `disasm 0x3047 0x3104`, `disasm 0x3104 0x3143`, `disasm 0x19FC 0x1A90` and `disasm 0x257A 0x2631` on the unpatched image.
Then the Rust probe (`PlacementRecords::shadow_top`, [`world/probe.rs`](../../../crates/stunt-core/src/world/probe.rs)) behind a temporary `DBG_SHADOW_BOX` switch (0 skips it), and `mise run parity -- --software-only` on lavapipe (`mesa-25.2.8`; the report names `llvmpipe (LLVM 21.1.7, 256 bits)`, class `cpu`) once with the switch at 0 and once unset, compared by `mise run judge -- <base reports> <candidate reports> --track evidence`.
Both runs used this commit's `crates/` plus the switch, which is not in the commit.
A third run, with a line appended to a scratch file for each probe, was stopped before it finished.

**Result**:

- `DS:0x0A20` is the object's shape segment (the object node's shape word, which `0x25CB` pushes for `0x26D0`) and `0x0A22` the slot's (`0x2753`, from slot `+2`).
  `0x284E..0x2867` takes the slot's extent `0x0A36` from the slot's header word `+4`, shifted, plus 1; `0x2886` walks the object's list `[es:0xA]` through the `0x09FC` table.
  The slot's own list is the `di` the handlers test (`0x290C`, `0x29C5`, `0x2ABD`): with none, a cube or plane with no nested list and a box coded 0 end the walk with a carry, and a nested list is entered through the same table; with one, the nested list is walked through the `0x0A02`, `0x0A08` or `0x0A0E` table against the slot's records, which the Rust probe does not model (it enters no nested list and sets no carry then).
- A code-8 box that passes `0x3047` reaches `0x2A5B`: `0x0A32 + 0x0A16` is the slot's previous `y` in the object's frame (y down), and when it less the extent exceeds the box's least `y` (`0x2A6A`, `jg`) the handler returns with carry (`0x2A29`), which ends the whole probe (`0x25D2..0x25D7`) with the height not stored.
  Otherwise `0x2A6C..0x2A8F` stores the box's least `y` shifted by the shape's scale as a 16.16 value, plus the object's `y` (the 16.16 value at `DS:0x2320..0x2323`), at slot `+0x20/+0x22`.
- `0x19FC` reads `+0x20/+0x22` when the high word `+0x22` is nonzero (`0x19FD`), so a stored `y`-down height in `[0, 1)` m falls back to the plane's.
- `0x3047` builds one out-code per axis and face for the previous and the current position (`0x0A14..0x0A18`, `0x0A1A..0x0A1E`, each plus `0x0A30..0x0A34`, which `0x286C` zeroes) with the extent added to both faces, and the box is missed when `cl & ch` is nonzero (a face shared by both positions).
  `0x3104` computes `n . p` in 32 bits from the current position, subtracts the offset from the high word and doubles the pair, so the signed distance is `n . p / 32768 - 2d` in the shifted unit, and carries when it is below the extent.
- Rust: 9 unit tests of the probe and a scene test over a hand-built placement record (one slot over a code-8 box at its top, one beside it at the ground height) pass; the tilt is tested on `through_height`, because a `TerrainSurface` is not constructible from a test.
  Not modelled: the `+1` of the extent and of a cube's half-size, the shifted-integer rounding of positions, the slot's `SIF_MOVES` gate (the trajectory contract carries no flag for it), the object node's own range test (`0x2581..0x25BE`), the own-list contexts above and the probe's own tree walk (`0x584`): its order versus the records' eye-based pruning and dedup.
  The previous position is the slot's at `tick - PREVIOUS_FRAME_TICKS`, which is 0, so the previous and the current positions are the same until that constant moves.
- `mise run judge`, seven reference films, switch 0 against unset: every film's SSIM and IoU agree to four decimals (ctry 0.9190, intro 0.8625, land 0.8944, balloon 0.8836, traintnl 0.8635, bomb 0.8462, location 0.8394), index agreement is equal on every scored frame (0 better, 0 worse), no class loss moves, and the winner line is `none adopts (best run=candidate: no film rises)`.
- The scratch count of the stopped run: 22,414 probes logged, none returned a height; the placed worlds held 19, 2,984 and 4,272 placements with a collision list, so the probe ran over lists and no slot overlapped a code-8 box.

**Verdict**: the probe is a faithful read of the static rule and moves no reference film; the `evidence` track's film-mean branch has no film that rises, so by [`loop-rules.md`](../../../.agents/skills/improving-render-parity/loop-rules.md) it is not an adoption on score.
The issue's own acceptance is a test and no regression, which hold; no film in the reference set shows the case (#499's triage said the same of the corpus films with an archive).

**Lives in**: [`sod-vm-frame.md` § 9.1](../../../research/playone-exe/sod-vm-frame.md#91-the-actor-shadow-draw) and the probe rows of [`memory-map-main.md`](../../../research/playone-exe/memory-map-main.md).
