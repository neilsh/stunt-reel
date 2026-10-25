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

The table above ends at 17, but the corpus goes past it (`[Bounded Observation]`): of 102,633 `.SOD` chunks across every `.ALL` in `corpus/siarchive/`, 7 have `scale_index` 18 and 6 have 19 (for example shape `0x7E09` in `COL3-1`, `COL3-2`, `COL5-1`, `COL5-7` and `CREDITS.ALL`, and `0x7E1A` in `eGALLOC7.ALL`). `compute_scale_factor` in [`vm.rs`](../../crates/stunt-core/src/sod/vm.rs) extends the pattern past the table as $5 / 2^{k-1}$. Whether `PLAYONE`'s own table covers 18 and 19, or reads past its end, is `[Unknown]`.

#### Mathematical Scaling Formula:
$$S_k = \begin{cases} 1.0 & \text{if } k = 0 \\ \dfrac{1.0}{2^k} & \text{if } k \ge 1 \end{cases}$$
The metric coordinate conversion per Invariant `[I1]` is:
$$X_{\text{metric}} = X_{\text{raw}} \times S_k$$
$$Y_{\text{metric}} = (Y_{\text{raw}} + \text{ground\_y\_offset}) \times S_k$$
$$Z_{\text{metric}} = Z_{\text{raw}} \times S_k$$

---

## 3. Data Structures & Opcode Table

## 3. Data Structures & Opcode Table

A `.SOD` body is a display list for a stack-based, register-oriented VM: 1024 twelve-byte vertex registers, a vector accumulator, a rotation-centre stack and a relative-matrix stack, and `GOTO`/`GOSUB`/`SORTON`/`IFVIS` control flow. The model and its `PLAYONE.EXE` evidence are in [`playone-exe/sod-vm.md`](../playone-exe/sod-vm.md) section 8. Every opcode, its operands and the opcode-specific semantics (`OP_TAP`, `OP_ANIMATE`, `OP_IFVIS`, `OP_IPG`, `OP_VECTORS`) are in [`sod-opcodes.md`](sod-opcodes.md), whose 107-opcode table is `# [FMT-SOD-OPCODES]`. The unimplemented-opcode work queue is [`sod-opcode-coverage.md`](sod-opcode-coverage.md).

### 3.1 Coplanar Decal Detection (`[I5]`)

In original DOS software rendering, decals (wing insignia, national roundels, lettering) were drawn over base facets via sequential framebuffer overwrites. In modern depth-buffered rendering, coplanar facets produce severe Z-fighting.
- **Coplanar Detection Criteria:** Two facets $A$ and $B$ are coplanar decals if:
  1. Unit normal parallelism: $\mathbf{n}_A \cdot \mathbf{n}_B \ge 1.0 - 10^{-4}$
  2. Plane constant equality: $|\mathbf{n}_A \cdot \mathbf{v}_{A0} - \mathbf{n}_B \cdot \mathbf{v}_{B0}| < 10^{-4}\text{ m}$
  3. Bounding box spatial overlap in all three dimensions within $10^{-4}\text{ m}$.
- **Resolution:** Decal facets are flagged with `flags |= 0x01` (`is_decal = true`) and their vertices are nudged along outward surface normal $\hat{\mathbf{n}}$ by:
  $$\epsilon = 0.001\text{ m} \quad (1.0\text{ mm})$$
  In modern GPU presentation (`crates/stunt-render/`), decals are rendered in a dedicated pass with hardware depth-biasing (`DepthBiasState { constant: 2, slope_scale: 2.0, clamp: 0.0 }`).

---

## 4. Open Questions & Analysis Backlog

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
| **Q-SOD-08** | Unimplemented opcodes in the corpus | Corpus census (`mise run sod-census`): 49 shape IDs block on `ANIMATE`, `PUSHCENTRE`, `BVGT`, `SHADE1` or `GOSUB`, with centre-stack, matrix-stack, rotation and `GOTO` opcodes masked behind them; queue, model IDs and film use in [`sod-opcode-coverage.md`](sod-opcode-coverage.md). | `[Bounded Observation]` | Lenient decode keeps geometry before the blocking opcode (Partial SOD). |

---

## 5. Attribution & Provenance

The `.SOD` virtual machine specification draws on extensive community analysis across multiple decades:

### 5.1 Community Researchers & Tool Authors

- **Adrian Stephens**: Original Assembly Line Engine Developer; authored the original 8086/80286 macro-assembler display-list source files for Stunt Island aircraft (`objdef`, `ipg`, `sorton`, `pushcentre`, `pushrelmat`).
- **Chris Phillips**: Author of `SODParse` (`ripres.c`, `DECODE.C`, `SOD.H`), `SIRes` (`SIResFile.cpp`, `Sod.h`), and `FreeFlight` (`siobj.cpp`). Decoded the 107 opcode jump table (multiples of 9), scale table constants, and OpenGL reconstruction.
- **Dave Palmowski**: Documented `.SOD` bounding boxes, scaling factors, and object coordinates in `SITools/`.
- **Doug Armknecht**: Curator of `corpus/siarchive/`, preserving developer notes and aircraft source models.
- **Neil Halelamien**: Documented 16-bit object type IDs referencing `.SOD` models in `Developer/Notes_SETFile/`.
- **Ángel Eduardo**: Analyzed subobject joint hierarchies, spheres, discs, and Set Designer models in `Developer/Notes_SIExtractor/`.
- **Alberto Marnetto**: Author of the `SI-8x` patch (2024), which raises the renderer's level-of-detail distance threshold eightfold by replacing the `mul` by the detail word with `mov dx, ax; shl dx, 3`, described in [*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island). The same site in `PLAYONE.EXE` is traced in [`lod.md`](../playone-exe/lod.md).
- **Alberto Marnetto (2026)**: Author of [`si-tools/sod-decoder`](https://github.com/AlbertoMarnetto/si-tools/tree/master/sod-decoder), an MIT-licensed C++ `.SOD` to Wavefront exporter derived from FreeFlight's `siobj.cpp`; it walks more aircraft parts than `SODParse`. Consulted for operand readings, not ported ([`sod-opcodes.md`](sod-opcodes.md) § 3).

### 5.2 Primary Reference Paths in `corpus/siarchive/`

- `Developer/SODParse/DECODE.C` (Chris Phillips' 107-opcode disassembler)
- `Developer/SODParse/SOD.H` (Opcode constants, scale table, data structures)
- `Developer/FreeFlight/src/siobj.cpp` (C++ OpenGL `.SOD` interpreter and transform stack)
- `SITools/OBJECTS/Planes/CURTISS.SOD` (ASCII `.objdef` assembler source; compiled models are `.BIN` files beginning with `0x000C`)
- `SITools/OBJECTS/Planes/SABRE.SOD` (ASCII `.objdef` assembler source; compiled models are `.BIN` files beginning with `0x000C`)
- `Developer/SI-8x/si-8x-notes.txt` (two-line pointer to Alberto Marnetto's article; the patch itself is the diff in `si-8x.7z`)

---
