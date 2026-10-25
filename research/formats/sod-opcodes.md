# `.SOD` Opcode Reference

This is the opcode-level companion to [`sod.md`](sod.md): the 107-opcode table, the semantics established for individual opcodes, and the community readings of opcodes not yet traced in the binary. The general VM model (registers, accumulator, transform stack, dispatch) is lab-notebook evidence in [`playone-exe/sod-vm.md`](../playone-exe/sod-vm.md); the implementation queue for unhandled opcodes is [`sod-opcode-coverage.md`](sod-opcode-coverage.md). Byte layouts of the container are in [`sod.ksy`](sod.ksy).

---

## 1. The Authoritative 107-Opcode Reference Table (`# [FMT-SOD-OPCODES]`)

In the original x86 16-bit real-mode Assembly Line engine, the SOD virtual machine dispatched bytecode instructions through an internal jump table where every handler entry was spaced by **9 bytes**. Consequently, **every opcode `PLAYONE` dispatches is an exact multiple of 9** ($\text{Opcode} = \text{Index} \times 9$). Two constants in `SOD.H` and `vm.rs` are not: `0x000C` (`OP_ID`) is the header magic, which `vm.rs` also skips when it meets it mid-stream, and `0x004B` (`OP_VEC`, `SOD.H:35`) has no handler slot: in the unpacked image the table sits at `0x8246` (runtime `CS:0x1316`), and the bytes at `+0x0C` and `+0x4B` are gap filler (`26 C7 44`), not `E9` jumps (`[Bounded Observation]`, static). Neither is a dispatched opcode, so neither appears below:

| Index | Opcode (Hex) | Opcode (Dec) | Mnemonic | Operands & Memory Signature | Semantic Description |
| :---: | :---: | :---: | :--- | :--- | :--- |
| **0** | `0x0000` | 0 | `OP_CLRV` | *none* | Clear accumulator: `cur_vert = [0, 0, 0]` |
| **1** | `0x0009` | 9 | `OP_GETV` | `reg_off: u16` | Load register: `cur_vert = regs[reg]` |
| **2** | `0x0012` | 18 | `OP_PUTV` | `reg_off: u16` | Store register: `regs[reg] = cur_vert` |
| **3** | `0x001B` | 27 | `OP_INTV` | `reg_off: u16` | Interpolate midpoint: `cur_vert = (cur_vert + regs[reg])/2` |
| **4** | `0x0024` | 36 | `OP_ADDV` | `reg_off: u16` | Vector addition: `cur_vert += regs[reg]` |
| **5** | `0x002D` | 45 | `OP_SUBV` | `reg_off: u16` | Vector subtraction: `cur_vert -= regs[reg]` |
| **6** | `0x0036` | 54 | `OP_NEGV` | *none* | Vector negate: `cur_vert = -cur_vert` |
| **7** | `0x003F` | 63 | `OP_SHLV` | `shift: u16` | Vector left shift: `cur_vert <<= shift` |
| **8** | `0x0048` | 72 | `OP_SHRV` | `shift: u16` | Vector arithmetic right shift: `cur_vert >>= shift` |
| **9** | `0x0051` | 81 | `OP_BLOKADD` | `src: u16, dst: u16, count: u16` † | Block add: `regs[dst+i] = regs[src+i] + cur_vert` |
| **10** | `0x005A` | 90 | `OP_BLOKNEG` | `src: u16, dst: u16, count: u16` † | Block negate: `regs[dst+i] = -regs[src+i]` |
| **11** | `0x0063` | 99 | `OP_IPG` | `type: u16, ...dims, reg: u16` | Procedural primitive generator (Cube, Ground, Quad) |
| **12** | `0x006C` | 108 | `OP_CHECKPOINT`| *unknown* | Debug / synchronization checkpoint |
| **13** | `0x0075` | 117 | `OP_VECTORS` | `count: u16, reg: u16, count*3 words` | Batch upload 3D vectors into registers |
| **14** | `0x007E` | 126 | `OP_PUSHCENTRE`| *none* | Push rotation center origin onto stack |
| **15** | `0x0087` | 135 | `OP_POPCENTRE` | *none* | Pop rotation center origin from stack |
| **16** | `0x0090` | 144 | `OP_MOVECENTRE`| `reg_off: u16` | Move rotation center to `regs[reg]` |
| **17** | `0x0099` | 153 | `OP_PERS` | `start_reg: u16, count: u16` | Perspective divide 3D vectors into screen space |
| **18** | `0x00A2` | 162 | `OP_MOVETO` | `reg_off: u16` | Move pen to vertex `regs[reg]` |
| **19** | `0x00AB` | 171 | `OP_LINETO` | `reg_off: u16` | Draw line from pen to vertex `regs[reg]` |
| **20** | `0x00B4` | 180 | `OP_LINECOL` | `color: u16` | Set active line color index (`0..=255`) |
| **21** | `0x00BD` | 189 | `OP_ZLINETO` | `reg_off: u16` | Depth-tested line drawing to `regs[reg]` |
| **22** | `0x00C6` | 198 | `OP_HUGELINETO`| `reg_off: u16` | Extended coordinates line drawing |
| **23** | `0x00CF` | 207 | `OP_VLINETO` | `reg_off: u16` | Vertical axis constrained line drawing |
| **24** | `0x00D8` | 216 | `OP_VOTEVIS` | `face: u16` | Vote facet visible in culling accumulator |
| **25** | `0x00E1` | 225 | `OP_VOTEHID` | `face: u16` | Vote facet hidden in culling accumulator |
| **26** | `0x00EA` | 234 | `OP_POLY` | `count: u16, ...regs` | Unsorted flat polygon emission |
| **27** | `0x00F3` | 243 | `OP_POLYZ` | `count: u16, ...regs` | Depth-sorted flat polygon emission |
| **28** | `0x00FC` | 252 | `OP_SPHERE` | `center_reg: u16, radius: u16` | Procedural sphere primitive; `radius` is in register (vertex) units. Tree crowns use it: 19 per tree in `CTRY.ALL` `0x0504`/`0x0507` (1,399 and 933 placements), radius 600 to 1,100 at scale index 10 (crowns of about 1.2 to 2.1 m). `FreeFlight/src/siobj.cpp` leaves it unimplemented. The Rust VM draws a 20-triangle icosahedron at 0.92 of the radius (80 triangles would give a 700 MB vertex buffer on `CTRY.FLM`, over wgpu's 256 MiB); crowns match the capture's position and colour but are faceted (`[Bounded Observation]`; found 2026-10-22 at `16a3170`, [parity log](../parity/log.md)) |
| **29** | `0x0105` | 261 | `OP_DISC` | `center_reg: u16, radius: u16` | Flat circular disc primitive |
| **30** | `0x010E` | 270 | `OP_PERFDISK` | `center_reg: u16, r_in: u16, r_out: u16` † | Perforated disc (ring with center shaft) |
| **31** | `0x0117` | 279 | `OP_SIDE` | `...` | Cylindrical side primitive |
| **32** | `0x0120` | 288 | `OP_INITDISC` | `...` | Disc rasterizer initialization |
| **33** | `0x0129` | 297 | `OP_FILLCOL` | `color: u16` | Set active polygon fill color index (`OP_COLOR`) |
| **34** | `0x0132` | 306 | `OP_NORMALS` | `start_reg: u16, count: u16, ...faces` | Compute surface normal vectors for faces |
| **35** | `0x013B` | 315 | `OP_MISTY` | `...` | Distance fog / atmospheric haze attenuation |
| **36** | `0x0144` | 324 | `OP_SHADE1` | `normal_reg: u16, ramp: u16` | Front-facing directional lighting ramp |
| **37** | `0x014D` | 333 | `OP_SHADE2` | `normal_reg: u16, ramp: u16` | Back-facing directional lighting ramp |
| **38** | `0x0156` | 342 | `OP_SHADES` | `count: u16, ...triplets` | Batch upload lighting normal vectors. Parsed and deliberately not applied; per-vertex shade words observed 4 to 68 in `CTRY.ALL`, and `siobj.cpp` discards them too (`[Bounded Observation]`). The props loss is structural, not tonal: 79% of prop-layer pixels already matched in the first index comparison |
| **39** | `0x015F` | 351 | `OP_GOURAUD` | `...` | Smooth Gouraud-shaded polygon |
| **40** | `0x0168` | 360 | `OP_SHADEPOLY`| `count: u16, regs..., norm, shades...` | Normal-lit shaded polygon (`OP_GVPOLY`) |
| **41** | `0x0171` | 369 | `OP_AIRBRUSH` | `...` | Dithered / airbrushed soft shadow polygon |
| **42** | `0x017A` | 378 | `OP_BHID` | `cond: u16, size: u16` | Branch / hide section if condition met (`OP_IFVIS`) |
| **43** | `0x0183` | 387 | `OP_BVIS` | `cond: u16, size: u16` | Branch if facet is visible |
| **44** | `0x018C` | 396 | `OP_SORTON` | `plane: u16, left_off: i16, right_off: i16` † | BSP binary space partitioning branch |
| **45** | `0x0195` | 405 | `OP_RETURN` | *none* | Return from subroutine / end display list (`OP_END`) |
| **46** | `0x019E` | 414 | `OP_GOTO` | `rel_offset: i16` | Unconditional relative jump: $PC += \text{offset}/2 - 1$ |
| **47** | `0x01A7` | 423 | `OP_GOSUB` | `rel_offset: i16` | Call subroutine: push return PC, jump to target |
| **48** | `0x01B0` | 432 | `OP_REJVEC` | `...` | Vector bounding rejection |
| **49** | `0x01B9` | 441 | `OP_REJ3D` | `box_reg: u16, count: u16, ...faces` | 3D bounding box culling test (`OP_REJ`) |
| **50** | `0x01C2` | 450 | `OP_REJ2D` | `...` | 2D screen bounding box culling test |
| **51** | `0x01CB` | 459 | `OP_HUGEREJ3D`| `...` | Large-scale scenery bounding box culling |
| **52** | `0x01D4` | 468 | `OP_FRACTAL` | `...` | Procedural fractal terrain generator |
| **53** | `0x01DD` | 477 | `OP_ROTY` | `angle_bam: u16` | Rotate around Y axis by 16-bit BAM angle |
| **54** | `0x01E6` | 486 | `OP_PUSHRELMAT`| *none* | Push relative orientation matrix onto stack |
| **55** | `0x01EF` | 495 | `OP_POPRELMAT` | *none* | Pop relative orientation matrix from stack |
| **56** | `0x01F8` | 504 | `OP_ANIMATE` | `reg_off: u16, parameter: u16, selector: u16, resource_count: u16, resource_ids: u16[resource_count]` | Selects an image resource and emits a projected pixel draw (`# [FMT-SOD-ANIMATE]`); selector semantics and `.FLM` input mapping remain open. |
| **57** | `0x0201` | 513 | `OP_HUGEVECS` | `...` | Large-coordinate vector ingest |
| **58** | `0x020A` | 522 | `OP_HUGEPERSPEC`| `...`| Large-coordinate perspective divide |
| **59** | `0x0213` | 531 | `OP_HUGEPOLY` | `...` | Large-scale scenery polygon |
| **60** | `0x021C` | 540 | `OP_REJHUGEPOLY`| `...`| Large-scale scenery rejection |
| **61** | `0x0225` | 549 | `OP_GNDHUGEPOLY`| `...`| Ground terrain mesh polygon |
| **62** | `0x022E` | 558 | `OP_TAP` | `reg_off: u16, count: u16, count × anchor_offset: u16` | Load anchor points into the vertex register bank (`# [FMT-SOD-TAP]`) |
| **63** | `0x0237` | 567 | `OP_HUGETAP` | *unimplemented* | Dispatches to `int3` in `PLAYONE.EXE`; no encoding established |
| **64** | `0x0240` | 576 | `OP_POLYSL` | `...` | Sliced polygon geometry |
| **65** | `0x0249` | 585 | `OP_POLYZSL` | `...` | Depth-sorted sliced polygon |
| **66** | `0x0252` | 594 | `OP_SPHERESL` | `...` | Sliced sphere primitive |
| **67** | `0x025B` | 603 | `OP_DISCSL` | `...` | Sliced disc primitive |
| **68** | `0x0264` | 612 | `OP_PERFDISCSL`| `...` | Sliced perforated disc primitive |
| **69** | `0x026D` | 621 | `OP_SIDESL` | `...` | Sliced cylinder side primitive |
| **70** | `0x0276` | 630 | `OP_PUSHSL` | `...` | Push slicing plane onto stack |
| **71** | `0x027F` | 639 | `OP_POPSL` | `...` | Pop slicing plane from stack |
| **72** | `0x0288` | 648 | `OP_DISPSL` | `...` | Display sliced mesh geometry |
| **73** | `0x0291` | 657 | `OP_INTSL` | `...` | Slicing plane intersection |
| **74** | `0x029A` | 666 | `OP_SUBSL` | `...` | Slicing plane subtraction |
| **75** | `0x02A3` | 675 | `OP_ADDSL` | `...` | Slicing plane addition |
| **76** | `0x02AC` | 684 | `OP_DUPSL` | `...` | Duplicate slicing plane |
| **77** | `0x02B5` | 693 | `OP_SHADE16` | `norm: u16, ramp: u16` | 16-level directional lighting ramp sample. Parsed and not applied, like `OP_SHADES` |
| **78** | `0x02BE` | 702 | `OP_GVPOLY16` | `count: u16, regs..., norm, shades...` | 16-level shaded polygon emission |
| **79** | `0x02C7` | 711 | `OP_SHADE216` | `norm: u16, ramp: u16` | 16-level back-facing lighting ramp sample |
| **80** | `0x02D0` | 720 | `OP_DOT` | `reg_off: u16` | Draw single point / pixel dot at `regs[reg]` |
| **81** | `0x02D9` | 729 | `OP_BLOCK` | `reg_off: u16, size: u16` | Draw solid rectangular box block |
| **82** | `0x02E2` | 738 | `OP_ROTX` | `angle_bam: u16` | Rotate around X axis by 16-bit BAM angle |
| **83** | `0x02EB` | 747 | `OP_ROTZ` | `angle_bam: u16` | Rotate around Z axis by 16-bit BAM angle |
| **84** | `0x02F4` | 756 | `OP_BVLT` | `reg: u16, val: i16, rel_off: i16` | Branch if vector coordinate is less than threshold |
| **85** | `0x02FD` | 765 | `OP_BVGT` | `reg: u16, val: i16, rel_off: i16` | Branch if vector coordinate is greater than threshold |
| **86** | `0x0306` | 774 | `OP_WIDELINE` | `p1: u16, p2: u16, width: u16` | Thick anti-aliased or multi-pixel wire line |
| **87** | `0x030F` | 783 | `OP_SPLITQUAD`| `...` | Split quadrilateral into two triangles |
| **88** | `0x0318` | 792 | `OP_BZLT` | `val: i16, rel_off: i16` | Branch if viewer Z distance is less than threshold |
| **89** | `0x0321` | 801 | `OP_SCALEIT` | `scale_idx: u16` | Dynamic runtime scale modification |
| **90** | `0x032A` | 810 | `OP_SPRITE` | `sprite_id: u16, reg: u16` | Billboarding decal sprite billboard |
| **91** | `0x0333` | 819 | `OP_TEXTURE` | `tex_id: u16, ...coords` | Texture-mapped quad polygon |
| **92** | `0x033C` | 828 | `OP_VECELLIPSE`| `...` | Vector elliptical arc |
| **93** | `0x0345` | 837 | `OP_VECELLSL` | `...` | Sliced vector ellipse |
| **94** | `0x034E` | 846 | `OP_LETTER` | `char_code: u16, reg: u16` | Vector font glyph rendering |
| **95** | `0x0357` | 855 | `OP_VECTORS2D`| `count: u16, ...` | 2D UI screen vector ingest |
| **96** | `0x0360` | 864 | `OP_CLR2D` | *none* | Clear 2D vector accumulator |
| **97** | `0x0369` | 873 | `OP_GET2D` | `reg: u16` | Load 2D vector register |
| **98** | `0x0372` | 882 | `OP_PUT2D` | `reg: u16` | Store 2D vector register |
| **99** | `0x037B` | 891 | `OP_INT2D` | `reg: u16` | 2D vector interpolation |
| **100** | `0x0384` | 900 | `OP_ADD2D` | `reg: u16` | 2D vector addition |
| **101** | `0x038D` | 909 | `OP_SUB2D` | `reg: u16` | 2D vector subtraction |
| **102** | `0x0396` | 918 | `OP_SHL2D` | `shift: u16` | 2D vector left shift |
| **103** | `0x039F` | 927 | `OP_SHR2D` | `shift: u16` | 2D vector right shift |
| **104** | `0x03A8` | 936 | `OP_BLOKADD2D`| `...` | 2D block vector addition |
| **105** | `0x03B1` | 945 | `OP_CIRCLE` | `center: u16, r: u16` | 2D circle outline |
| **106** | `0x03BA` | 954 | `OP_CIRCLESL` | `...` | Sliced circle outline |

† Operand reading is disputed by si-tools; see [§ 3.1](#31-operand-order-disagreements).

---

## 2. Opcode Semantics

### 2.1 Procedural Primitive Generator (`OP_IPG`, 0x0063)

`[Supported Inference]` — operand shapes from `SOD.H` and FreeFlight, rendered by `vm.rs`; the handler is not traced in `PLAYONE.EXE`.

Generates canonical geometric wireframe vertices centered at the local origin:
- **Type 0 (Cube / Cuboid):** Operands `dx: i16`, `dy: i16`, `dz: i16`, `start_reg: u16`. Emits 8 vertices spanning $[\pm dx, \pm dy, \pm dz]$ into `regs[start .. start + 7]`.
- **Type 2 (Ground Quad):** Operands `dx: i16`, `dz: i16`, `start_reg: u16`. Emits 4 horizontal vertices at $y = 0$ into `regs[start .. start + 3]`.
- **Type 8 (Vertical Quad):** Operands `dx: i16`, `dy: i16`, `start_reg: u16`. Emits 4 vertical vertices at $z = 0$ into `regs[start .. start + 3]`.

### 2.2 Raw Vertex Array Upload (`OP_VECTORS`, 0x0075)

`[Supported Inference]` — as for `OP_IPG`.

Loads a batch of $N \times (x, y, z)$ 16-bit integer triplets from the bytecode stream into contiguous registers starting at `start_reg`. Each triplet is multiplied by `scale_factor` and offset by `ground_y_offset`.

### 2.3 Terrain Anchor Load (`OP_TAP`, `0x022E`) (`# [FMT-SOD-TAP]`)

`[Established]` — handler at `CS:0x3E58`, dispatch entry at `CS:0x1544`.

`OP_TAP` resolves terrain points rather than emitting geometry directly:

```text
OP_TAP (0x022E)
  reg_off : u16        ; byte offset into the 12-byte vertex arena
  count   : u16        ; number of anchor records (1..=64 in practice 2 or 3)
  anchors : u16[count] ; byte offsets into the 28-byte anchor table
```

- The operand width is **variable**: `2 + count` words.
- Each `anchor_offset` is a multiple of 28 and points four bytes before the 28-byte record (`record = table + offset + 4`); the table has a four-byte header.
- Record layout: `x: i16` at `+0`, `y: i16` at `+2`, `z: i16` at `+4`, then runtime transform cache and projection fields through `+0x1B`.
- `PLAYONE.EXE` transforms the record through the current 3×3 matrix, caches the 32-bit result per frame, shifts by `[0x806E]`, subtracts the view origin, and writes `x/y/z` into `regs[reg_off/12 + i]`.
- The reconstruction applies the `[I1]` basis mapping `(-x, -y, z)` and treats sentinel elevations `|y| >= 32000` as zero; see [`research/playone-exe/sod-vm.md`](../playone-exe/sod-vm.md).
- The anchor table is **external** to `.ALL`: it is the same 28-byte record array indexed by `ANCHORPT.DAT` / `MAP.BIN` terrain patches. A model that uses TAP cannot decode without it.

Corpus: 2,413 stop sites across 14 unique model payloads; every operand is a multiple of 28. CTRY chunks `0x0402`–`0x0408` reference anchors 141–193.

### 2.4 Animation Resource Draw (`OP_ANIMATE`, `0x01F8`) (`# [FMT-SOD-ANIMATE]`)

`[Established]` for the operand span and pixel-blit side effect in the saved runtime image. `[Bounded Observation]` for the `Ac.FLM`/`Ac.ALL` resource cross-reference. The direct mapping from `.FLM` `animate: u16` to this selector remains `[Unknown]`.

The saved `PLAYONE.EXE` runtime disassembly establishes this variable-width record:

```text
OP_ANIMATE (0x01F8)
  vertex_reg_off : u16
  parameter      : u16
  selector       : u16
  resource_count : u16
  resource_ids   : u16[resource_count]
```

`vertex_reg_off` addresses the 12-byte vertex arena at `DS:0x4450`; the handler reads depth, projected coordinates, and the register flag. It combines the register depth with the view-origin/projection terms, uses `selector` to access a work-segment lookup value, and selects a resource ID from the variable-length table. `parameter` and `selector` are neutral field names; their complete domain meaning is not established. A nonzero mode gate skips the same record using three fixed words, `resource_count`, and `2 * resource_count` bytes.

The selected ID is resolved through the resource cache and passed to a screen-space pixel blitter. The blitter clips the image and writes nonzero source bytes; zero bytes are skipped. This opcode emits a raster draw, not a polygon or BAM joint rotation. Corpus chunks `Ac.ALL:0x0105` and `0x0108` contain the 58-byte form; `0x0105` references `0x1F01`–`0x1F0C`, matching 64×50 image resources in that archive. See [`research/playone-exe/sod-animate.md`](../playone-exe/sod-animate.md) for the disassembly and evidence limits.

### 2.5 BSP Sorting & Two-Sided Visibility Logic (`# [FMT-SOD-IFVIS]`)

`[Supported Inference]` — from the assembler macro sources and `SODParse`; not traced in the binary (open question Q-SOD-01 in [`sod.md`](sod.md#4-open-questions--analysis-backlog)).

Because 1992 DOS real-mode software lacked hardware depth buffers:
- `sorton <face>` (0x018C): Evaluates whether camera eye is in front of or behind separating plane `<face>`. Traverses front and back geometry subtrees in back-to-front order (Binary Space Partitioning for Painter's algorithm).
- `ifvis <face>` (0x017A) / `ifhid <face>`: Evaluates whether `<face>` is front-facing (dot product $\mathbf{n} \cdot \mathbf{v}_{\text{cam}} > 0$).
  - If visible: renders front facet using `shade1` lighting ramp.
  - If hidden: renders reverse-winding rear facet using `shade2` lighting ramp.

### 2.6 `OP_MOVETO` / `OP_ZLINETO` / `OP_LINECOL` / `OP_DOT` in the reconstruction

`[Hypothesis]`

Each takes a single operand word (confirmed by `FreeFlight/src/siobj.cpp`, which only consumes one word and draws nothing, and by the VM walking whole chunks without desync). The semantics are inferred from the opcode names: `MOVETO reg_off` sets the pen to `regs[reg_off / 12]`, `ZLINETO reg_off` draws pen to that register and moves the pen, `LINECOL color` sets a line colour separate from the fill colour of `OP_COLOR`, and `DOT reg_off` plots one point. The VM draws a segment as two perpendicular ribbons (both windings) 0.03 m wide and a dot as a 0.03 m octahedron, in the line colour (fill colour until `LINECOL` is seen). The original draws 1-pixel lines; the width is a stand-in. Whether the pen persists across `RETURN`/subobjects and whether `LINECOL` is reset per chunk is `[Unknown]`.

---

## 3. Community Semantics from si-tools

`[Hypothesis]`

Alberto Marnetto's MIT-licensed [`si-tools/sod-decoder`](https://github.com/AlbertoMarnetto/si-tools/tree/master/sod-decoder) (2026, a C++ rewrite of FreeFlight's `siobj.cpp`) decodes the opcodes whose geometry it exports and skips the rest by a one-word default. Its readings are leads only: confirm each one against the opcode's `PLAYONE.EXE` handler (reached through the dispatch slots in [`sod-vm.md`](../playone-exe/sod-vm.md) section 1) before `vm.rs` implements it. Where it disagrees with the operand reading assumed for the census skips ([`sod-opcode-coverage.md` § 1](sod-opcode-coverage.md#1-summary)), the disagreement is marked.

Only **stream constraints** are recorded here — readings that must match the byte stream for any parse to succeed. A decoder that omits shading, culling or projection says nothing about the engine, and none of those omissions are kept (section 3.3).

| Opcode | si-tools reading | Against coverage § 1 |
| :--- | :--- | :--- |
| `PUSHCENTRE` / `POPCENTRE` | Push and pop the relative origin `relpos`, which is added to every emitted vertex | agrees |
| `MOVECENTRE` | `relpos += register[reg_off / 12]` | agrees |
| `PUSHRELMAT` / `POPRELMAT` | Push and pop a 3×3 matrix that `VECTORS` applies to raw input points | agrees |
| `ROTX` / `ROTY` / `ROTZ` | The operand is a **variable byte offset** (`variable[w / 2]`), not an immediate; the variable is an angle with 4096 units per turn, post-multiplied into the matrix | **differs**: coverage § 1 assumes an immediate `angle_bam` |
| `BVLT` / `BVGT` | `reg` is a **variable byte offset**; branch when `variable <= val` (`BVLT`) or `variable >= val` (`BVGT`), unsigned | **differs**: coverage § 1 reads `reg` as a register |
| `BZLT` | Branch when the register's local Z `<= val - relpos.z`; the handler's `shift` scaling is not modelled | not in coverage § 1 |
| `GOTO` / `GOSUB` | Target = address of the operand word + `rel_offset` bytes; `GOSUB` runs the target until `RETURN` | agrees; coverage § 1 leaves the base unstated |
| `SHADE1` | Two operand words, no geometry | agrees |
| `ANIMATE` | `point_reg`, `radius / 2`, `variable offset`, `count`, then `count` words | agrees with [`sod-animate.md`](../playone-exe/sod-animate.md) |
| `REJ` | `face_base`, `count`, then `count` register triples; backface test truncates the cross-product components to 16 bits before the dot product (`getnorm` / `reject3d`) | not in coverage § 1 |
| `GVPOLY` | Colour in the high byte of the trailing word, then one shade word per vertex | not in coverage § 1 |
| `IPG` types 0, 2, 8 | Cube, ground quad and XY quad; fill registers only, draw no faces | not in coverage § 1 |

### 3.1 Operand-Order Disagreements

`[Hypothesis]` — four readings that contradict § 1 or § 2.5. None of the opcodes is reached by any of the corpus models in [`sod-opcode-coverage.md` § 3](sod-opcode-coverage.md#3-census), so no render depends on them: this is a note for whoever implements a handler, not a work item.

| Opcode | § 1 / § 2.5 says | si-tools reads | Source |
| :--- | :--- | :--- | :--- |
| `BLOKADD` (`0x0051`), `BLOKNEG` (`0x005A`) | `src, dst, count` | `count, dest/12, src/12` | `siobj_lib.cpp:900-939` |
| `SORTON` (`0x018C`) | `plane, left_off, right_off`; § 2.5 reads it as a BSP plane test | First word is the **block size in bytes**, next two are skipped; block end = opcode index + `size/2` | `siobj_lib.cpp:1246-1260` |
| `PERFDISK` (`0x010E`) | `center_reg, r_in, r_out` | `center_reg, radius`; the second operand is a normal/orientation register (`/12`), one radius only | `siobj_lib.cpp:1098-1126` |
| `SHADES` (`0x0156`) | `count, ...triplets` | Two leading words (the first discarded, the second is the count), then 3 words per entry | `siobj_lib.cpp:1235-1244` |

`SHADE2` (`0x014D`) and `SHADE216` (`0x02C7`) have no case at all and take the one-word default, so their silence is not evidence of a one-word operand.

### 3.2 Primitive Recipes

`[Hypothesis]` — geometry si-tools generates, not observed in `PLAYONE`:

* `SPHERE` is a 12-vertex, 20-triangle icosahedron at exactly `1.0 × radius`, radius used raw (not multiplied by the shape scale), vertices `centre + trunc(v · radius)`. `vm.rs` uses the same icosahedron at `0.92 ×` (`vm.rs:208`), tuned against `CTRY`; that factor is ours, not the format's.
* `DISC` is a 16-segment fan at parse-time `radius × scale`, and `PERFDISK` reuses the builder. Orientation snaps to the dominant axis of the normal register (`|nz| > 0.9` → XY plane, else `|ny| > 0.9` → XZ, else YZ) with the sign ignored, so the winding is a stand-in rather than a decode.
* The disc radius is multiplied by scale at parse and again at export, so exported radii come out `scale²`; that is an exporter bug, not a format fact.

### 3.3 What A Decoder's Silences Are Worth

si-tools is an OBJ exporter, not an emulator. It never shades, never culls, never projects, never writes the animation variables, and skips a dozen opcodes of known width with a single word. None of that is evidence about `PLAYONE.EXE`, and this note records none of it. What survives is the byte layout: the five-word shape header (magic `0x000C`, size, `y_offset`, scale/flags, collision), `GVPOLY`'s high-byte colour, `SHADES`' leading word, `IPG`'s per-type operand counts, `ANIMATE`'s field order, and the `0x000C` first word that identifies a `.SOD` chunk inside a `.RES`, which [`res.md`](res.md) already derives from the archive structure.

