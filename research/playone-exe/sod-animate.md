# `PLAYONE.EXE`: `OP_ANIMATE` Resource-Draw Semantics

* **Binary**: `PLAYONE.EXE` (LZEXE 0.91, DOSBox-X runtime image)
* **Method**: Capstone 16-bit disassembly of the local saved memory image in `build/re/playone_lo.bin`, `build/re/playone_hi.bin`, and `build/re/mem/seg_1000.bin`; corpus cross-check against `Ac.ALL` and `Ac.FLM`.
* **Scope**: `OP_ANIMATE` (`0x01F8`) dispatch, operand span, resource lookup, and pixel blit.
* **Anchor**: `# [FMT-SOD-ANIMATE]`, `# [MEM-SOD-VM]`

The memory image is local build evidence and is not committed. A live DOSBox breakpoint attempt at the saved `CS:0F17` address did not stop in this session; the findings below come from the saved runtime image and corpus bytes, not a live invocation of the handler.

---

## 1. Dispatch and Operand Span

The saved image has `CS = 0x0F17`. The dispatch entry for `0x01F8` is `CS:0x150E` (`0x1316 + 0x01F8`): bytes `E9 9B 25` jump to `CS:0x3AAC`.

At `CS:0x3AAC`, the handler uses the following wire layout:

```text
OP_ANIMATE (0x01F8)
  vertex_reg_off : u16
  parameter      : u16
  selector       : u16
  resource_count : u16
  resource_ids   : u16[resource_count]
```

The names `parameter` and `selector` are neutral field labels; their complete domain meaning is not established.

The handler’s inactive path advances over three fixed words, reads `resource_count`, skips `2 * resource_count` bytes, and dispatches the next opcode. The active path reads the same fields and indexes the variable-length `resource_ids` table. Thus a fixed-width skip is invalid.

`vertex_reg_off` is a byte offset into the 12-byte register arena. The handler reads the record at `DS:0x4450 + vertex_reg_off`, including its depth at `+4`, projected coordinates at `+6`/`+8`, and flag byte at `+0x0A`.

---

## 2. Resource Selection and Draw Effect

The active path uses the vertex depth plus view-origin Z (`[0x8088]`) and projection scale (`[0x8070]`) with `parameter`. It uses `selector` to read a factor from the work-segment table addressed by `selector - 0x7EF2`; `resource_count` and that factor determine the selected `u16` resource ID. The handler passes that ID through the resource cache lookup at `CS:0x0824:0x8073`.

The lookup returns the resource segment. Its callback pointer at `DS=0x1575:0x2260` is `0x7DE6` in the saved image. The routine at `CS=0x0824:0x7DE6` clips the resource to the screen and writes nonzero source bytes with `STOSB`; zero bytes are skipped. This is a screen-space raster draw, not polygon emission or a BAM joint rotation.

The work-segment projection term `[0x8070]` is assigned by `CS:0x0F17:0x21D0` from `[0x8108]`, shifted by the high-byte count saved at `[0x806F]`. The setup routine stores its `CX` word at `[0x806E]`; the higher-level meaning of `[0x8108]` is not established.

---

## 3. Corpus Cross-Check

In `corpus/si_archive/Films/MultiFLM/AmCrisis/Ac.all`:

* Chunk `0x0105` is 58 bytes and contains one `OP_ANIMATE` record at byte `0x16`: register offset `0`, parameter `0x2000`, selector `0x16`, count `12`, and resource IDs `0x1F01`–`0x1F0C`.
* The referenced chunks `0x1F01`–`0x1F0C` are each 3,206 bytes and begin with width `64`, height `50`; `64 * 50 = 3,200` bytes, consistent with image resources plus a 6-byte header.
* Chunk `0x3A80` is 288 bytes and contains 11 repeated `OP_ANIMATE` records, each with four resource IDs.
* `Ac.flm` carries `SIF_ANIMATES` updates for shape IDs `0x0105` and `0x0108`, with changing `animate: u16` values. This co-occurrence does **not** by itself establish how the `.FLM` value reaches the SOD selector or draw routine.

The corpus scan found 847 `OP_ANIMATE` stop sites: 705 share the 58-byte body, 130 share the 288-byte body, and 12 are other sites. The 58-byte CTRY chunk `0x0107` emits no polygons, but that does not imply the opcode has no visible effect: its handler can draw a raster resource.

---

## 4. Rust Mapping and Open Items

The Rust SOD VM currently has no `OP_ANIMATE` arm; it stops/errors through the unknown-opcode path. `ActorTransform.joint_angles_bam` is not evidence for this opcode’s behavior, and the current mapping of `.FLM` `animate` into joint angle slot 0 is unverified.

T10 remains open. Remaining work: establish whether and how the `.FLM` `animate: u16` value affects resource selection, then implement the selected resource draw in the native renderer. Do not treat the opcode as a 3D joint-angle instruction or silently rename the unknown operand fields as `var_id`/`limit`.

`[Established]` for the dispatch target, operand widths, resource lookup, and pixel-blit side effect in the saved runtime disassembly. `[Bounded Observation]` for the `Ac.ALL` resource cross-reference. `[Unknown]` for the `.FLM.animate`-to-SOD selection mapping and the complete semantics of `parameter` and `selector`.

---

## 5. Open questions

* Establish whether `.FLM` `animate: u16` (co-occurring with SOD resource tables in `Ac`: shapes `0x0105`, `0x0108`) reaches the selector at `selector - 0x7EF2`; the dataflow is unresolved.
* A live breakpoint on the handler (`CS:0F17`) did not stop in the first session; retry before implementing the draw.

_Found 2026-10-20 at `f9f0cfd`. No parity measurement was taken; T10 stays open._
