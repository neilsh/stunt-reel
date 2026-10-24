# Technical Reference Specification: Stunt Island `.SOD` 3D Geometry & Bytecode Format

## 1. Overview & File Identification

The `.SOD` format is *Stunt Island*'s native procedural 3D model geometry representation. Rather than storing static vertex buffers and polygon index arrays (like modern OBJ or glTF files), a `.SOD` file is a compiled **procedural display list** executed by a dedicated 16-bit real-mode Virtual Machine embedded within `PLAYONE.EXE` and `STUNT.EXE`.

The bytecode calculates parametric vertices, evaluates hierarchical transformation matrices (`pushrelmat`), branches on viewer distance and face visibility (`ifvis`, `sorton`), and emits flat-shaded or normal-lit polygons referencing authentic 8-bit VGA Mode 13h palette indices (`0..=255`).

### Key File Attributes

| Attribute | Specification | Evidentiary Tier | Authoritative Citation |
| :--- | :--- | :---: | :--- |
| **File Extension** | `.SOD` (e.g., `CURTISS.SOD`, `SABRE.SOD`, `FOKKER.SOD`, `PLANE.SOD`) | `[Established]` | `research/playone-exe/startup.md` |
| **Magic Identifier** | 16-bit little-endian word: `0x000C` (`OP_ID`) at byte offset `0x0000` | `[Established]` | `SOD.H:26`, `vm.rs:16`, `synthetic_minimal.sod` |
| **Byte Endianness** | Little-Endian (all 16-bit signed/unsigned words and coordinates) | `[Established]` | `DECODE.C:386-404`, `vm.rs:158-182` |
| **Engine Role** | Procedural geometry generation, articulated subobject hierarchies, and real-time BSP depth sorting | `[Established]` | `research/playone-exe/sod-vm.md`, `siobj.cpp:498` |
| **Paired Contract** | `Seam 3: SodModelIr` (`crates/stunt-core/src/contracts/shape.rs`) | `[Established]` | `# [FMT-SOD-OPCODES]`, `# [FMT-SOD-IFVIS]`, `docs/ARCHITECTURE.md` |

**Governing invariants:** [`[I1]`](../../docs/SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization), [`[I2]`](../../docs/SPEC.md#i2-flat-arena-allocation-no-recursive-pointers), [`[I3]`](../../docs/SPEC.md#i3-authentic-vga-mode-13h-palette-indexing--flat-shading), [`[I5]`](../../docs/SPEC.md#i5-coplanar-decal-resolution). **Contract and code:** [`contracts/shape.rs`](../../crates/stunt-core/src/contracts/shape.rs), VM in [`sod/`](../../crates/stunt-core/src/sod/), tests in [`crates/stunt-core/tests/`](../../crates/stunt-core/tests/). **Fixtures:** `synthetic_minimal.sod` (76 bytes), described in [`tests/fixtures/README.md`](../../tests/fixtures/README.md). The 393 compiled corpus models are `.BIN` files beginning with `0x000C` (the corpus `.SOD` files are assembler sources); [`sod.ksy`](sod.ksy) runs over those `.BIN` files in `mise run verify-corpus`.

---

## 2. Header & Memory Layout

Every `.SOD` bytecode stream begins with an immutable **10-byte header**, followed immediately by the stream of bytecode instructions:

### 2.1 10-Byte Header Binary Layout (`# [FMT-SOD-HEADER]`)

```
+---------------------------------------------------------------------------------+
|                        .SOD FILE ON-DISK BINARY LAYOUT                          |
+-------------------+-------------------+-----------------------------------------+
| Byte Range        | Type              | Field Name / Semantic Description       |
+-------------------+-------------------+-----------------------------------------+
| 0x0000 - 0x0001   | uint16 (LE)       | op_id: Magic identifier (must be 0x000C)|
| 0x0002 - 0x0003   | uint16 (LE)       | bounding_size: Bounding sphere radius   |
| 0x0004 - 0x0005   | int16 (LE)        | ground_y_offset: Vertical placement adj |
| 0x0006            | uint8             | scale_index: Power-of-2 scale (0..19 in corpus) |
| 0x0007            | uint8             | header_flags: Bit 0 = Flat shading flag |
| 0x0008 - 0x0009   | uint16 (LE)       | collision_meta: Collision & type flags  |
| 0x000A - EOF      | uint8[]           | Bytecode Instruction Stream             |
+-------------------+-------------------+-----------------------------------------+
```

The executable header layout is [`sod.ksy`](sod.ksy). It stops at byte `0x000A`; operand widths for several opcodes remain undecoded.

### 2.2 Power-of-2 Scale Table Multiplier Constants

The scale factor converts 16-bit integer model units into metric meters per Invariant `[I1]`. The scale table constants from `SOD.H` and `siobj.cpp` are:

| Scale Index | Constant Multiplier | Metric Multiplier ($S_k = \text{const} / 10$) | Metric Equivalent | Representative Models |
| :---: | :---: | :---: | :---: | :--- |
| **0** | $10.0$ | $1.0\text{ m/unit}$ | 1 unit = 1 meter | Terrains, large hangars |
| **1** | $5.0$ | $0.5\text{ m/unit}$ | 2 units = 1 meter | Buildings, bridges |
| **2** | $2.5$ ($5/2$) | $0.25\text{ m/unit}$ | 4 units = 1 meter | Large airliners, naval ships |
| **3** | $1.25$ ($5/4$) | $0.125\text{ m/unit}$ | 8 units = 1 meter | Bombers, medium vehicles |
| **4** | $0.625$ ($5/8$) | $0.0625\text{ m/unit}$ | 16 units = 1 meter | Standard vehicles, trucks |
| **5** | $5/16$ | $1/32\text{ m/unit}$ | 32 units = 1 meter | Ground equipment |
| **6** | $5/32$ | $1/64\text{ m/unit}$ | 64 units = 1 meter | Small props |
| **7** | $5/64$ | $1/128\text{ m/unit}$ | 128 units = 1 meter | Character props |
| **8** | $5/128$ | $1/256\text{ m/unit}$ | 256 units = 1 meter | Small handheld props |
| **9** | $5/256$ | $1/512\text{ m/unit}$ | 512 units = 1 meter | Detailed instruments |
| **10** | $5/512$ | $1/1024\text{ m/unit}$ | 1024 units = 1 meter | Cockpit dials |
| **11** | $5/1024$ | $1/2048\text{ m/unit}$ | 2048 units = 1 meter | Fine fasteners |
| **12** | $5/2048$ | $1/4096\text{ m/unit}$ | 4096 units = 1 meter | `CURTISS.SOD`, `SABRE.SOD` |
| **13** | $5/4096$ | $1/8192\text{ m/unit}$ | 8192 units = 1 meter | High-precision aircraft |
| **14** | $5/8192$ | $1/16384\text{ m/unit}$ | 16384 units = 1 meter | Sub-millimeter parts |
| **15** | $5/16384$ | $1/32768\text{ m/unit}$ | 32768 units = 1 meter | Micro-geometry |
| **16** | $5/32768$ | $1/65536\text{ m/unit}$ | 65536 units = 1 meter | Extended precision |
| **17** | $5/65536$ | $1/131072\text{ m/unit}$ | 131072 units = 1 meter | Last entry in `SOD.H` |

The table above ends at 17, but the corpus goes past it (`[Bounded Observation]`): of 102,633 `.SOD` chunks across every `.ALL` in `corpus/si_archive/`, 7 have `scale_index` 18 and 6 have 19 (for example shape `0x7E09` in `COL3-1`, `COL3-2`, `COL5-1`, `COL5-7` and `CREDITS.ALL`, and `0x7E1A` in `eGALLOC7.ALL`). `compute_scale_factor` in [`vm.rs`](../../crates/stunt-core/src/sod/vm.rs) extends the pattern past the table as $5 / 2^{k-1}$. Whether `PLAYONE`'s own table covers 18 and 19, or reads past its end, is `[Unknown]`.

#### Mathematical Scaling Formula:
$$S_k = \begin{cases} 1.0 & \text{if } k = 0 \\ \dfrac{1.0}{2^k} & \text{if } k \ge 1 \end{cases}$$
The metric coordinate conversion per Invariant `[I1]` is:
$$X_{\text{metric}} = X_{\text{raw}} \times S_k$$
$$Y_{\text{metric}} = (Y_{\text{raw}} + \text{ground\_y\_offset}) \times S_k$$
$$Z_{\text{metric}} = Z_{\text{raw}} \times S_k$$

---

## 3. Data Structures & Opcode Table

### 3.1 The SOD Virtual Machine Execution Model

The SOD Virtual Machine is a stack-based, register-oriented geometry execution engine.

#### 3.1.1 1024 Vertex Registers (`regs[0..1023]`)
- **Register Storage:** The VM maintains a contiguous bank of 1024 3D vector registers (`regs[0..1023]`), each storing a 3D coordinate vector `[x, y, z]` in floating-point meters.
- **Physical Memory Stride:** In the 16-bit real-mode assembly engine, each vertex structure in RAM occupied **12 bytes** (`0x0C` bytes: 3 signed 16-bit words for coordinates, plus transformation scratchpad flags).
- **Operand Addressing:** Bytecode operands specify register targets as **byte offsets** (multiples of 12). Parsers decode register indices via:
  $$\text{reg\_index} = \left(\frac{\text{reg\_offset}}{12}\right) \ \& \ 1023$$
  The bitwise `& 1023` mask prevents out-of-bounds memory corruption.

#### 3.1.2 Vector Accumulator (`cur_vert`) & Vector Arithmetic
The VM maintains a 3D vector accumulator (`cur_vert = [x, y, z]`). Arithmetic opcodes mutate this accumulator:
- `OP_CLRV` (0x0000): Clears accumulator: `cur_vert = [0.0, 0.0, 0.0]`.
- `OP_GETV` (0x0009): Loads register: `cur_vert = regs[reg]`.
- `OP_PUTV` (0x0012): Stores accumulator into register: `regs[reg] = cur_vert`.
- `OP_INTV` (0x001B): Interpolates midpoint: `cur_vert = (cur_vert + regs[reg]) * 0.5`.
- `OP_ADDV` (0x0024): Vector addition: `cur_vert += regs[reg]`.
- `OP_SUBV` (0x002D): Vector subtraction: `cur_vert -= regs[reg]`.
- `OP_NEGV` (0x0036): Vector negation: `cur_vert = -cur_vert`.
- `OP_SHLV` (0x003F): Left shift (multiplies by $2^{\text{shift}}$): `cur_vert *= 2^shift`.
- `OP_SHRV` (0x0048): Right shift (divides by $2^{\text{shift}}$): `cur_vert /= 2^shift`.

#### 3.1.3 Procedural Primitive Generator (`OP_IPG`, 0x0063)
Generates canonical geometric wireframe vertices centered at the local origin:
- **Type 0 (Cube / Cuboid):** Operands `dx: i16`, `dy: i16`, `dz: i16`, `start_reg: u16`. Emits 8 vertices spanning $[\pm dx, \pm dy, \pm dz]$ into `regs[start .. start + 7]`.
- **Type 2 (Ground Quad):** Operands `dx: i16`, `dz: i16`, `start_reg: u16`. Emits 4 horizontal vertices at $y = 0$ into `regs[start .. start + 3]`.
- **Type 8 (Vertical Quad):** Operands `dx: i16`, `dy: i16`, `start_reg: u16`. Emits 4 vertical vertices at $z = 0$ into `regs[start .. start + 3]`.

#### 3.1.4 Raw Vertex Array Upload (`OP_VECTORS`, 0x0075)
Loads a batch of $N \times (x, y, z)$ 16-bit integer triplets from the bytecode stream into contiguous registers starting at `start_reg`. Each triplet is multiplied by `scale_factor` and offset by `ground_y_offset`.

#### 3.1.4a Terrain Anchor Load (`OP_TAP`, `0x022E`) (`# [FMT-SOD-TAP]`)

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

`[Established]` — handler at `CS:0x3E58`, dispatch entry at `CS:0x1544`.

#### 3.1.4b Animation Resource Draw (`OP_ANIMATE`, `0x01F8`) (`# [FMT-SOD-ANIMATE]`)

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

`[Established]` for the operand span and pixel-blit side effect in the saved runtime image. `[Bounded Observation]` for the `Ac.FLM`/`Ac.ALL` resource cross-reference. The direct mapping from `.FLM` `animate: u16` to this selector remains `[Unknown]`.

#### 3.1.5 Hierarchical Transform Stack & Subobject Articulation
To animate moving parts (rotating propellers, retracting landing gear, rudder deflection) without detaching subobjects from the body, the SOD VM implements a hierarchical matrix stack:
1. `pushcentre` (0x007E): Pushes current rotation origin vector onto the center stack.
2. `pushrelmat` (0x01E6): Pushes current 3x3 local orientation matrix onto the transform stack.
3. `movecentre <reg>` (0x0090): Translates origin to vertex `regs[reg]` (e.g., landing gear hinge).
4. `rotx` (0x02E2), `roty` (0x01DD), `rotz` (0x02EB): Applies local rotation around primary axis using 16-bit BAM angles driven by animation variables (`undercarriage1`, `rudder`).
5. `gosub <target>` (0x01A7): Evaluates articulated subobject geometry (e.g., `sabre_uc`).
6. `poprelmat` (0x01EF): Restores parent orientation matrix.
7. `popcentre` (0x0087): Restores parent rotation center.

#### 3.1.6 BSP Sorting & Two-Sided Visibility Logic (`# [FMT-SOD-IFVIS]`)
Because 1992 DOS real-mode software lacked hardware depth buffers:
- `sorton <face>` (0x018C): Evaluates whether camera eye is in front of or behind separating plane `<face>`. Traverses front and back geometry subtrees in back-to-front order (Binary Space Partitioning for Painter's algorithm).
- `ifvis <face>` (0x017A) / `ifhid <face>`: Evaluates whether `<face>` is front-facing (dot product $\mathbf{n} \cdot \mathbf{v}_{\text{cam}} > 0$).
  - If visible: renders front facet using `shade1` lighting ramp.
  - If hidden: renders reverse-winding rear facet using `shade2` lighting ramp.

---

### 3.2 The Authoritative 107-Opcode Reference Table (`# [FMT-SOD-OPCODES]`)

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
| **9** | `0x0051` | 81 | `OP_BLOKADD` | `src: u16, dst: u16, count: u16` | Block add: `regs[dst+i] = regs[src+i] + cur_vert` |
| **10** | `0x005A` | 90 | `OP_BLOKNEG` | `src: u16, dst: u16, count: u16` | Block negate: `regs[dst+i] = -regs[src+i]` |
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
| **28** | `0x00FC` | 252 | `OP_SPHERE` | `center_reg: u16, radius: u16` | Procedural sphere primitive; `radius` is in register (vertex) units. Tree crowns use it (19 per tree in `CTRY.ALL` `0x0504`/`0x0507`); the Rust VM approximates it with a 20-triangle icosahedron (`[Bounded Observation]`, [`parity-findings.md` § 10](../parity-findings.md#10-tree-crowns-are-op_sphere-ground-shade-is-world-fixed-ctryflm-bounded-observation)) |
| **29** | `0x0105` | 261 | `OP_DISC` | `center_reg: u16, radius: u16` | Flat circular disc primitive |
| **30** | `0x010E` | 270 | `OP_PERFDISK` | `center_reg: u16, r_in: u16, r_out: u16` | Perforated disc (ring with center shaft) |
| **31** | `0x0117` | 279 | `OP_SIDE` | `...` | Cylindrical side primitive |
| **32** | `0x0120` | 288 | `OP_INITDISC` | `...` | Disc rasterizer initialization |
| **33** | `0x0129` | 297 | `OP_FILLCOL` | `color: u16` | Set active polygon fill color index (`OP_COLOR`) |
| **34** | `0x0132` | 306 | `OP_NORMALS` | `start_reg: u16, count: u16, ...faces` | Compute surface normal vectors for faces |
| **35** | `0x013B` | 315 | `OP_MISTY` | `...` | Distance fog / atmospheric haze attenuation |
| **36** | `0x0144` | 324 | `OP_SHADE1` | `normal_reg: u16, ramp: u16` | Front-facing directional lighting ramp |
| **37** | `0x014D` | 333 | `OP_SHADE2` | `normal_reg: u16, ramp: u16` | Back-facing directional lighting ramp |
| **38** | `0x0156` | 342 | `OP_SHADES` | `count: u16, ...triplets` | Batch upload lighting normal vectors |
| **39** | `0x015F` | 351 | `OP_GOURAUD` | `...` | Smooth Gouraud-shaded polygon |
| **40** | `0x0168` | 360 | `OP_SHADEPOLY`| `count: u16, regs..., norm, shades...` | Normal-lit shaded polygon (`OP_GVPOLY`) |
| **41** | `0x0171` | 369 | `OP_AIRBRUSH` | `...` | Dithered / airbrushed soft shadow polygon |
| **42** | `0x017A` | 378 | `OP_BHID` | `cond: u16, size: u16` | Branch / hide section if condition met (`OP_IFVIS`) |
| **43** | `0x0183` | 387 | `OP_BVIS` | `cond: u16, size: u16` | Branch if facet is visible |
| **44** | `0x018C` | 396 | `OP_SORTON` | `plane: u16, left_off: i16, right_off: i16` | BSP binary space partitioning branch |
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
| **77** | `0x02B5` | 693 | `OP_SHADE16` | `norm: u16, ramp: u16` | 16-level directional lighting ramp sample |
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

### 3.3 Coplanar Decal Detection (`[I5]`)

In original DOS software rendering, decals (wing insignia, national roundels, lettering) were drawn over base facets via sequential framebuffer overwrites. In modern depth-buffered rendering, coplanar facets produce severe Z-fighting.
- **Coplanar Detection Criteria:** Two facets $A$ and $B$ are coplanar decals if:
  1. Unit normal parallelism: $\mathbf{n}_A \cdot \mathbf{n}_B \ge 1.0 - 10^{-4}$
  2. Plane constant equality: $|\mathbf{n}_A \cdot \mathbf{v}_{A0} - \mathbf{n}_B \cdot \mathbf{v}_{B0}| < 10^{-4}\text{ m}$
  3. Bounding box spatial overlap in all three dimensions within $10^{-4}\text{ m}$.
- **Resolution:** Decal facets are flagged with `flags |= 0x01` (`is_decal = true`) and their vertices are nudged along outward surface normal $\hat{\mathbf{n}}$ by:
  $$\epsilon = 0.001\text{ m} \quad (1.0\text{ mm})$$
  In modern GPU presentation (`crates/stunt-render/`), decals are rendered in a dedicated pass with hardware depth-biasing (`DepthBiasState { constant: 2, slope_scale: 2.0, clamp: 0.0 }`).

---

## 4. Open Questions & Reverse Engineering Backlog

The following backlog documents open questions regarding `.SOD` virtual machine opcodes:

| ID | Topic / Investigation Area | Current Evidence & Finding | Evidentiary Tier | Recommended Handling in Engine |
| :--- | :--- | :--- | :---: | :--- |
| **Q-SOD-01** | `OP_IFVIS` Condition Codes | Condition code 1 is evaluated as LOD distance squared ($D^2 \ge 1000.0\text{ m}^2$) or view angle culling. Community corroboration without binary evidence: dropping either branch of an `IFVIS` pair loses aircraft parts, and drawing both z-fights ([*Vibe-exploring Stunt Island*](https://marnetto.net/2026/04/26/vibe-exploring-si)), which fits alternative LOD representations. | `[Supported Inference]` | Evaluated as `VisibilityCondition::LodDistanceSq(1000.0)` in `vm.rs`. |
| **Q-SOD-02** | Slicing Opcodes (`0x0240`..`0x02AC`) | Opcodes 64 through 76 were used by the historical `Slice` tool (`.SIO`) for terrain chunk sectioning. Not used in retail prop models. | `[Bounded Observation]` | Handled as bounded no-ops or skip operands during transpilation. |
| **Q-SOD-03** | Texture & Sprite Billboard Opcodes (`0x032A`, `0x0333`) | Found in billboard props and runway signs; references `.SPR` sprite sheets in `SPRITES.RES`. | `[Bounded Observation]` | Emits placeholder quad; binds to sprite texture atlas when `.SPR` pipeline is active. |
| **Q-SOD-04** | Animation Variable Mappings (`undercarriage1`, etc.) | Macro assembler source files name specific registers/variables. Engine maps these to discrete `.FLM` actor state bits. | `[Supported Inference]` | Evaluated via `joint_angles_bam` in `ActorTransform`. |
| **Q-SOD-05** | Level-of-Detail Detail Gates (`complex1..3`) | Model source branches on `complex1..3` flags (e.g. `iftrue complex2 ;if max complexity do surface detail` in `SITools/OBJECTS/Planes/SABRE.SOD`). What sets the flags at runtime is unknown. `SI-8x` does not touch them: it patches the separate distance gate at image `0x212D`, whose threshold scales with `GAME.VAR`'s detail word and the per-shot scale ([`lod.md`](../playone-exe/lod.md)). | `[Bounded Observation]` | Transpiler exposes all detail branches; modern rendering renders maximum detail, which over-draws distant objects compared with PLAYONE's distance gate. |
| **Q-SOD-06** | Real-Mode Dynamic Memory Paging of 1024 Register Bank | In 640 KB conventional DOS memory, whether `PLAYONE.EXE` dynamically paged the 1024-vertex register bank (12 KB) into EMS/XMS or reserved a static `DGROUP` scratchpad buffer. | `[Hypothesis]` | Modern engine allocates contiguous flat arena vectors; memory constraints are eliminated. |
| **Q-SOD-07** | `OP_TAP` (`0x022E`) | Resolved: variable-width anchor-table load; handler at `CS:0x3E58`. | `[Established]` | Requires `ANCHORPT.DAT`; missing table returns a distinct stop reason. |
| **Q-SOD-08** | Unimplemented opcodes in the corpus | Corpus census (`mise run sod-census`): 49 shape IDs block on `ANIMATE`, `PUSHCENTRE`, `BVGT`, `SHADE1` or `GOSUB`, with centre-stack, matrix-stack, rotation and `GOTO` opcodes masked behind them; queue, model IDs and film use in [`../sod-opcode-coverage.md`](sod-opcode-coverage.md). | `[Bounded Observation]` | Lenient decode keeps geometry before the blocking opcode (Partial SOD). |

---

## 5. Attribution & Provenance

The `.SOD` virtual machine specification represents extensive reverse engineering across multiple decades:

### 5.1 Community Researchers & Tool Authors

- **Adrian Stephens**: Original Assembly Line Engine Developer; authored the original 8086/80286 macro-assembler display-list source files for Stunt Island aircraft (`objdef`, `ipg`, `sorton`, `pushcentre`, `pushrelmat`).
- **Chris Phillips** (`bigbang@seanet.com`): Author of `SODParse` (`ripres.c`, `DECODE.C`, `SOD.H`), `SIRes` (`SIResFile.cpp`, `Sod.h`), and `FreeFlight` (`siobj.cpp`). Decoded the 107 opcode jump table (multiples of 9), scale table constants, and OpenGL reconstruction.
- **Dave Palmowski**: Documented `.SOD` bounding boxes, scaling factors, and object coordinates in `SITools/`.
- **Doug Armknecht**: Curator of `corpus/si_archive/`, preserving developer notes and aircraft source models.
- **Neil Halelamien**: Documented 16-bit object type IDs referencing `.SOD` models in `Developer/Notes_SETFile/`.
- **Ángel Eduardo**: Analyzed subobject joint hierarchies, spheres, discs, and Set Designer models in `Developer/Notes_SIExtractor/`.
- **Alberto Marnetto**: Author of the `SI-8x` patch (2024), which raises the renderer's level-of-detail distance threshold eightfold by replacing the `mul` by the detail word with `mov dx, ax; shl dx, 3`, described in [*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island). The same site in `PLAYONE.EXE` is traced in [`lod.md`](../playone-exe/lod.md).
- **Alberto Marnetto (2026)**: Author of [`si-tools/sod-decoder`](https://github.com/AlbertoMarnetto/si-tools/tree/master/sod-decoder), an MIT-licensed C++ `.SOD` to Wavefront exporter derived from FreeFlight's `siobj.cpp`; it walks more aircraft parts than `SODParse`. Consulted for operand readings, not ported ([`sod-opcode-coverage.md`](sod-opcode-coverage.md) § 6).

### 5.2 Primary Reference Paths in `corpus/si_archive/`

- `Developer/SODParse/DECODE.C` (Chris Phillips' 107-opcode disassembler)
- `Developer/SODParse/SOD.H` (Opcode constants, scale table, data structures)
- `Developer/FreeFlight/src/siobj.cpp` (C++ OpenGL `.SOD` interpreter and transform stack)
- `SITools/OBJECTS/Planes/CURTISS.SOD` (ASCII `.objdef` assembler source; compiled models are `.BIN` files beginning with `0x000C`)
- `SITools/OBJECTS/Planes/SABRE.SOD` (ASCII `.objdef` assembler source; compiled models are `.BIN` files beginning with `0x000C`)
- `Developer/SI-8x/si-8x-notes.txt` (two-line pointer to Alberto Marnetto's article; the patch itself is the diff in `si-8x.7z`)

---

### `OP_MOVETO` / `OP_ZLINETO` / `OP_LINECOL` / `OP_DOT` in the reconstruction (`[Hypothesis]`)

Each takes a single operand word (confirmed by `FreeFlight/src/siobj.cpp`, which only consumes one word and draws nothing, and by the VM walking whole chunks without desync). The semantics are inferred from the opcode names: `MOVETO reg_off` sets the pen to `regs[reg_off / 12]`, `ZLINETO reg_off` draws pen to that register and moves the pen, `LINECOL color` sets a line colour separate from the fill colour of `OP_COLOR`, and `DOT reg_off` plots one point. The VM draws a segment as two perpendicular ribbons (both windings) 0.03 m wide and a dot as a 0.03 m octahedron, in the line colour (fill colour until `LINECOL` is seen). The original draws 1-pixel lines; the width is a stand-in. Whether the pen persists across `RETURN`/subobjects and whether `LINECOL` is reset per chunk is `[Unknown]`.
