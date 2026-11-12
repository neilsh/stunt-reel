---
summary: "`OP_ANIMATE` (`0x01F8`) blits frame `(count × bank word) >> 16` of its image table as a square centred on a projected point; selector `0x16` is the slot's interpolated `.FLM` animate word, `0x10` the film clock."
---
# `PLAYONE.EXE`: `OP_ANIMATE` Resource-Draw Semantics

* **Binary**: `PLAYONE.EXE`, the unpatched load image (`build/re/playone.img` in the data root).
* **Method**: Static disassembly with `mise run disasm`, `mise run xref` and `mise run vm-handler`; corpus cross-check against the data root's `.ALL` archives and loose `.BIN` models, and the slot keys of `CTRY.FLM` and `INTRO.FLM`.
* **Scope**: `OP_ANIMATE` (`0x01F8`) dispatch, operands, frame selection, the slot word that drives it, and the blit.
* **Anchor**: `# [FMT-SOD-ANIMATE]`, `# [MEM-SOD-VM]`

Image offsets below are the unpatched load image's; the notebook offsets of the first session are the VM segment's (`CS:0x3AAC` is image `0xA9DC`). Nothing here was observed live: a breakpoint on the handler in the first session never stopped.

---

## 1. Dispatch and Operands

`[Established]`, static. Dispatch slot `0x01F8` (image `0x843E`) jumps to the handler at image `0xA9DC`. Its operands:

```text
OP_ANIMATE (0x01F8)
  vertex_reg_off : u16          byte offset into the 12-byte register arena
  size           : u16          side of the drawn square, in shape units
  selector       : u16          byte offset into the angle bank at work:0x810E
  resource_count : u16
  resource_ids   : u16[resource_count]
```

While the shadow mode `work:0x806C` is set, or the register's flag byte (`+0x0A`) is set, the handler skips the operands and runs the next opcode; it always consumes `4 + resource_count` words, so the walk continues after the table either way.

_Source: [what picks the OP_ANIMATE frame](../../work/2026-11/222_op-animate/journal.md#2026-11-11-what-picks-the-op_animate-frame)._

---

## 2. Frame Selection

`[Established]`, static. The handler reads `[selector − 0x7EF2]`, which is `work:0x810E + selector`: the same word bank `ROTX`, `ROTY` and `ROTZ` read ([`sod-vm.md`](sod-vm.md) § 8.7). The frame is `resource_ids[(resource_count × word) >> 16]` (`mul` at `0xAA13`, the product's high word as the index), so the word sweeps the table once per 65,536.

| Selector | Bank word | Written by | Value |
|---|---|---|---|
| `0x16` | `work:0x8124` | `0x1D66`, on every actor draw | The slot record's `+0x16`: the `.FLM` `animate` word, interpolated (below) |
| `0x10` | `work:0x811E` | `0x1DCA`, in the frame step | `[0x4888 + 0x0E] << 12`: the film clock `DS:0x4896` times 4,096, one sweep every 16 ticks |
| `0x12`, `0x14`, `0x18`, `0x1A` | `work:0x8120`..`0x8128` | `0x1D96` | Words derived from film variables 10 and 12 ([`palette-fade.md`](palette-fade.md)) |

The frame step that writes `0x811E` is `0x0F4A`, which `0x4A2F` calls with `BX = 0x4888` ([`lod.md`](lod.md) § 2.1), so `[BX + 0x0E]` there is the active film clock.

**The slot record.** `0x39AE` snapshots each slot as 12 words: the flag byte at `+1` (`SIF_MOVES` `0x08`, `SIF_ROTATES` `0x10`, `SIF_ANIMATES` `0x20`), position `+0x04..+0x0F`, angles `+0x10..+0x14` and the animate word at `+0x16`. Each frame `0x3E6C` interpolates the slot between its start (`[di + 0x32]`) and end (`[di + 0x34]`) records by `frac = work:0x22E0`. For the animate word (`0x3EF8..0x3F13`, while `SIF_ANIMATES` is set) it is `start + ((end − start) × frac) >> 16` taken unsigned: when `end < start` the subtraction borrows and the result is corrected by `frac`, so the value falls straight from `start` to `end` and never wraps through 0.

**Corpus use.** `[Bounded Observation]`. The multi-frame tables use `0x16` (shapes `0x0105`–`0x010C` and `EXP1.BIN`–`EXP8.BIN`, 12 frames each) or `0x10` (`0x3A80`/`SMOKE.BIN`, 4 frames; `0x7E49`, 8 frames). The single-frame ones (`MINE`, `DAVEFIRE`, the Death Star, the `MAC` logos, the `0x7Cxx` and `0x7E22`/`0x7E26` shapes) use `0x10` or `0`; with one frame the word does not matter. `CTRY.FLM` keys its explosion slot (11, shape `0x0107`) at 0, 24576, 47104 and 4096 over ticks 851–885, and `CTRY.ALL` holds only frames `0x1F02`, `0x1F06` and `0x1F07` of the twelve: values the interpolated sweep passes through, not the keys themselves (`[Supported Inference]`, one film).

_Source: [what picks the OP_ANIMATE frame](../../work/2026-11/222_op-animate/journal.md#2026-11-11-what-picks-the-op_animate-frame)._

---

## 3. The Draw

`[Established]`, static.

* **Size.** `(size × work:0x8070) >> 8`, the 32-bit product shifted by the byte moves at `0xA9FC`, divided by the register's depth plus `work:0x8088`. A size of 0 pixels draws nothing. `OP_SPHERE`'s screen radius is the same expression ([`sod-vm.md`](sod-vm.md) § 8.8), so a sprite of size `p` is as wide on screen as a sphere of radius `p` is in radius.
* **Placement.** The handler passes the projected point (`+6`, `+8`), the size and the chosen id to `0x8073`, which looks the id up in the resource cache (`0x4C41`), puts the top-left corner at the point less half the size on both axes, and calls the blitter through `DS:0x2260` (`0x7DE6`).
* **Blit.** `0x7DE6` stretches the image to a square `size` pixels on a side, stepping the source by `width / size` and `height / size` in 16.16, clips it to the view rectangle `[0x2294..0x229A]`, and stores every non-zero byte; index 0 is transparent. There is no depth test: the sprite lands in the object's place in the painter's order.
* **Image layout.** The cache allocates two bytes more than a chunk (`0x4CD3`) and sets `DI = 2` before its read (`0x4CE0`); the blitter reads width at `es:2`, height at `es:4` and the first pixel at `es:8`. So a frame is `width`, `height`, a third word, then `width × height` pixels from chunk byte 6 (`[Supported Inference]` that `0x024B` is the read, from the width and height the blitter finds at `es:2` and `es:4`). All 2,815 frame chunks the corpus's tables name and its archives hold are `width × height + 6` bytes with a zero word at byte 4 and at the end (`[Bounded Observation]`); the layout is [`spr.ksy`](../formats/auxiliary/spr.ksy).

_Source: [what picks the OP_ANIMATE frame](../../work/2026-11/222_op-animate/journal.md#2026-11-11-what-picks-the-op_animate-frame)._

---

## 4. Rust Mapping

* `sod/vm.rs` runs `OP_ANIMATE`: each one becomes a `ShapeSprite` on the shape (anchor and size in metres through the shape's scale, the selector and the id table). Its census skip entry is gone.
* `flm/interpolate.rs` interpolates the animate word, joint slot 0 of `ActorTransform::joint_angles_bam`, as `0x3EFE` does.
* `scene.rs` picks each sprite's frame from its bank word (`bank_word`: `0x16` the actor's animate word, `0x10` the film tick's low four bits shifted left 12, any other word 0) and places it at the actor; a frame the archive lacks is not drawn. Images are read from the `.ALL` chunks or `RES` items the tables name (`sprite.rs`).
* `stunt-render` draws each sprite as a camera-facing square of its size at its centre, one quad per run of equal pixels, depth-tested in its actor's layer and absent from the shadow pass.

Drawing it raised `INTRO` from 0.8344 to 0.8357 and `CTRY` from 0.8973 to 0.8974 (evidence-backed, adopted).

_Source: [drawing the OP_ANIMATE sprite](../../work/2026-11/222_op-animate/journal.md#2026-11-11-drawing-the-op_animate-sprite)._

---

## Ruled out

* **A joint rotation.** The opcode draws an image; it does not rotate geometry. The `.FLM` `animate` word reaches it only through the bank word `0x8124` (§ 2).
* **Pushing the square toward the eye** by a fraction of its size, kept at its screen size, to approximate the painter's order: 0, 0.25, 0.5 and 1 times the size scored `CTRY` 0.8974 / 0.8974 / 0.8975 / 0.8971 and `INTRO` 0.8357 / 0.8360 / 0.8361 / 0.8362; heuristic, below the adoption bar ([pushing the sprite toward the eye](../../work/2026-11/222_op-animate/journal.md#2026-11-11-pushing-the-sprite-toward-the-eye)).

## Open questions

* **Draw order.** `PLAYONE` blits the sprite over whatever was painted before its object and under what comes after; our depth test cuts it where an object stands inside its square (`CTRY` tick 871: the capture draws the explosion over the tower beside it, we draw it behind). Matching it needs the painter's order of whole objects, not a per-pixel depth.
* **Bank words other than `0x10` and `0x16`.** The scene reads them as 0; no multi-frame stock table uses them.
* **Visibility gates.** Only an `ActorState` gate is evaluated for a sprite; no stock shape puts `OP_ANIMATE` under any gate.
* **Live check.** No breakpoint has confirmed the frame index or the image's pixel offset at run time.
