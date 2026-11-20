---
summary: "`.SOD` model bytecode ([FMT-SOD-HEADER]): 0x000C magic, 10-byte header, power-of-two scale table (indices 18 and 19 seen in corpus), the collision list the header word at byte 8 points to (cubes, boxes and planes the ground and collision probe walks; 1,279 of the 2,516 stock shapes have one), VM overview, coplanar decal rule, `OP_IFVIS` as a facing gate."
sidebar_label: ".SOD geometry & bytecode"
---
# Technical Reference Specification: Stunt Island `.SOD` 3D Geometry & Bytecode Format

## 1. Overview & File Identification

The `.SOD` format is *Stunt Island*'s native procedural 3D model geometry representation.
Rather than storing static vertex buffers and polygon index arrays (like modern OBJ or glTF files), a `.SOD` file is a compiled **procedural display list** executed by a dedicated 16-bit real-mode Virtual Machine embedded within `PLAYONE.EXE` and `STUNT.EXE`.

The bytecode calculates parametric vertices, evaluates hierarchical transformation matrices (`pushrelmat`), branches on viewer distance and face visibility (`ifvis`, `sorton`), and emits flat-shaded or normal-lit polygons referencing authentic 8-bit VGA Mode 13h palette indices (`0..=255`).

### Key File Attributes

| Attribute | Specification | Evidentiary Tier | Authoritative Citation |
| :--- | :--- | :---: | :--- |
| **File Extension** | `.SOD` (e.g., `CURTISS.SOD`, `SABRE.SOD`, `FOKKER.SOD`, `PLANE.SOD`) | `[Established]` | `research/playone-exe/startup.md` |
| **Magic Identifier** | 16-bit little-endian word: `0x000C` (`OP_ID`) at byte offset `0x0000` | `[Established]` | `SOD.H:26`, `vm.rs:16`, `synthetic_minimal.sod` |
| **Byte Endianness** | Little-Endian (all 16-bit signed/unsigned words and coordinates) | `[Established]` | `DECODE.C:386-404`, `vm.rs:158-182` |
| **Engine Role** | Procedural geometry generation, articulated subobject hierarchies, and real-time BSP depth sorting | `[Established]` | `research/playone-exe/sod-vm.md`, `siobj.cpp:498` |
| **Paired Contract** | `Seam 3: SodModelIr` (`crates/stunt-core/src/contracts/shape/mod.rs`) | `[Established]` | `# [FMT-SOD-OPCODES]`, `# [FMT-SOD-IFVIS]`, `docs/ARCHITECTURE.md` |

**Governing invariants:** [`[I1]`](../../docs/SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization), [`[I2]`](../../docs/SPEC.md#i2-flat-arena-allocation-no-recursive-pointers), [`[I3]`](../../docs/SPEC.md#i3-authentic-vga-mode-13h-palette-indexing--flat-shading), [`[I5]`](../../docs/SPEC.md#i5-coplanar-decal-resolution).
**Contract and code:** [`contracts/shape/mod.rs`](../../crates/stunt-core/src/contracts/shape/mod.rs), VM in [`sod/`](../../crates/stunt-core/src/sod/), tests in [`crates/stunt-core/tests/`](../../crates/stunt-core/tests/).
**Fixtures:** `synthetic_minimal.sod` (76 bytes), described in [`tests/fixtures/README.md`](../../tests/fixtures/README.md).
The 393 compiled corpus models are `.BIN` files beginning with `0x000C` (the corpus `.SOD` files are assembler sources); [`sod.ksy`](sod.ksy) runs over those `.BIN` files in `mise run verify-corpus`.

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
| 0x0007            | uint8             | header_flags: Bit 0 = faces the view    |
| 0x0008 - 0x0009   | uint16 (LE)       | collision_meta: collision-list offset   |
| 0x000A - EOF      | uint8[]           | Bytecode Instruction Stream             |
+-------------------+-------------------+-----------------------------------------+
```

The executable header layout is [`sod.ksy`](sod.ksy).
`header_flags` bit 0 makes `PLAYONE` draw the shape through the view matrix built without the camera's yaw, so it turns with the camera's heading; the flat `OP_IPG` type 8 trees set it (`[Established]` for the instructions, `[Supported Inference]` for the byte they test, [`playone-exe/sod-vm-generators.md`](../playone-exe/sod-vm-generators.md) section 8.8).
It stops at byte `0x000A`; operand widths for several opcodes remain undecoded.

`PLAYONE.EXE` applies `ground_y_offset` when it places a scene-tree shape: it adds `−ground_y_offset >> scale_index` to the shape's position (`[Established]`, [`auxiliary/scenery.md`](auxiliary/scenery.md) section 3.3).
The collision walker tests props against the same lifted height.
No instruction in the display-list VM reads it, and the actor draw does not (`[Supported Inference]`, from one scan, same section).

### 2.2 Power-of-2 Scale Table Multiplier Constants

The scale factor converts 16-bit integer model units into metric meters per Invariant `[I1]`.
The scale table constants from `SOD.H` and `siobj.cpp` are:

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

The table above ends at 17, but the corpus goes past it (`[Bounded Observation]`): of 102,633 `.SOD` chunks across every `.ALL` in `corpus/siarchive/`, 7 have `scale_index` 18 and 6 have 19 (for example shape `0x7E09` in `COL3-1`, `COL3-2`, `COL5-1`, `COL5-7` and `CREDITS.ALL`, and `0x7E1A` in `eGALLOC7.ALL`).
`compute_scale_factor` in [`vm.rs`](../../crates/stunt-core/src/sod/vm.rs) extends the pattern past the table as $5 / 2^{k-1}$.
Whether `PLAYONE`'s own table covers 18 and 19, or reads past its end, is `[Unknown]`.

#### Mathematical Scaling Formula:
$$S_k = \begin{cases} 1.0 & \text{if } k = 0 \\ \dfrac{1.0}{2^k} & \text{if } k \ge 1 \end{cases}$$
The metric coordinate conversion per Invariant `[I1]` is:
$$X_{\text{metric}} = X_{\text{raw}} \times S_k$$
$$Y_{\text{metric}} = (Y_{\text{raw}} + \text{ground\_y\_offset}) \times S_k$$
$$Z_{\text{metric}} = Z_{\text{raw}} \times S_k$$

### 2.3 Collision List

`[Established]` for what the probe's walk reads, static, from the unpatched load image; nothing here has been run.
`collision_meta` is the offset of the shape's collision list, 0 for none, which `PLAYONE`'s ground and collision probe `0x240A` walks at each object node it reaches (`0x257A`; [`playone-exe/scene-walk-actors.md`](../playone-exe/scene-walk-actors.md) § 3 and § 5, [`playone-exe/sod-vm-frame.md`](../playone-exe/sod-vm-frame.md) section 9.1).
`PLAYONE` loads the file two bytes into the shape's segment, so this offset, and every list offset inside the list, is two more than the file offset.
A list is a run of records, each a type word and its words, ended by the type word `0xFFFF`; the byte layout is [`sod.ksy`](sod.ksy).
Position words are in the shape's units and DOS axes (`y` down), and the handlers shift them right by the shape's scale less the probe's own shift (`DS:0x2290`):

* **Type 0, a cube** (12 bytes): its centre in `+2`, `+4`, `+6` and its half-size in `+8`, to which the handler adds 1.
  The test `0x2F8E` widens it by the actor's extent and misses it only when the actor's previous and current positions both lie beyond the same face.
* **Type 2, a box** (16 bytes): its least and greatest `x`, `y` and `z` in `+2..+0xC`, tested by `0x3047` at the same two positions, and a code in `+0xE`: 0 plain, 1 to 7 a bucket, 8 the top that sets the shadow's height, and above 8 the offset of a nested list.
* **Type 4, a plane** (12 bytes): its normal in `+2`, `+4`, `+6`, not shifted, and its offset in `+8`; the test `0x3104` reads the actor's current position alone.

A cube or a plane leads to a nested list at `+0xA` when that word is nonzero.
A cube or plane with none, or a box coded 0, that the actor overlaps ends the walk with a carry when the actor's shape has no list of its own.
_Source: [the collision records' fields](../../work/2026-11/727_placement-record/journal.md#2026-11-19-the-collision-records-fields-read-statically-and-decoded-over-the-stock-shapes)._

`[Bounded Observation]`, one static decode of the 2,516 stock shapes (`SUPERSET.ALL`): the 1,279 shapes with a list hold 1,978 lists, 699 of them nested, each named by one record and none leading back to itself, and every list ends at its `0xFFFF` word.
They hold 3,781 boxes, 333 cubes and 173 planes; 535 boxes in 207 shapes are coded 8, and every plane's normal has a length within 2 of 32,768.
`sod.ksy` reads the same counts from the same shapes.
_Source: [the collision records' fields](../../work/2026-11/727_placement-record/journal.md#2026-11-19-the-collision-records-fields-read-statically-and-decoded-over-the-stock-shapes)._

The Rust probe over these lists is `PlacementRecords::shadow_top` in [`world/probe.rs`](../../crates/stunt-core/src/world/probe.rs); it leaves out the `+1` of an extent and a cube's half-size, the `SIF_MOVES` gate, the object node's range test and the nested lists of a slot with a list of its own. _Source: [the box-top rule](../../work/2026-11/727_placement-record/journal.md#2026-11-20-the-box-top-rule-read-statically-and-the-probe-over-the-reference-films)._
The Rust decode is `decode_collision` in [`sod/collision.rs`](../../crates/stunt-core/src/sod/collision.rs), which every `decode_sod` runs into the decode record's `collision`; the world keeps each placed shape's lists in its placement records ([`world/placed.rs`](../../crates/stunt-core/src/world/placed.rs)).

---

## 3. Data Structures & Opcode Table

A `.SOD` body is a display list for a stack-based, register-oriented VM: 1024 twelve-byte vertex registers, a vector accumulator, a rotation-centre stack and a relative-matrix stack, and `GOTO`/`GOSUB`/`SORTON`/`IFVIS` control flow.
The model and its `PLAYONE.EXE` evidence are in [`playone-exe/sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) section 8.
Every opcode, its operands and the opcode-specific semantics (`OP_TAP`, `OP_ANIMATE`, `OP_IFVIS`, `OP_IPG`, `OP_VECTORS`) are in [`sod-opcodes.md`](sod-opcodes.md), whose 107-opcode table is `# [FMT-SOD-OPCODES]`.
The unimplemented-opcode work queue is [`sod-opcode-coverage.md`](sod-opcode-coverage.md).

### 3.1 Coplanar Decal Detection (`[I5]`)

In original DOS software rendering, decals (wing insignia, national roundels, lettering) were drawn over base facets via sequential framebuffer overwrites.
In modern depth-buffered rendering, coplanar facets produce severe Z-fighting.
- **Coplanar Detection Criteria:** a polygon $B$ is a decal when an earlier polygon $A$ of the same stream satisfies all three, on each polygon's **front normal** (the side `FrontFace::Cw` keeps, the negated edge cross product of its winding; a line or a polygon of fewer than three vertices has none), not on the stored shading normal (`crates/stunt-core/src/sod/decal.rs`):
  1. Unit normal parallelism: $\mathbf{n}_A \cdot \mathbf{n}_B \ge 1.0 - 10^{-4}$
  2. Plane constant equality: $|\mathbf{n}_A \cdot \mathbf{v}_{A0} - \mathbf{n}_B \cdot \mathbf{v}_{B0}| \le 10^{-4}\text{ m}$
  3. Bounding box spatial overlap in all three dimensions within $10^{-4}\text{ m}$.
- **Lines:** a `MOVETO`/`ZLINETO` segment is a decal when both its ends lie within $10^{-4}\text{ m}$ of an earlier decal's front plane and their bounds meet (criterion 3), so it draws after that decal as `PLAYONE` draws it; a segment on a facet that is no decal stays in the base pass ([`render-model.md`](../parity/render-model.md) section 3).
- **Resolution:** decal facets are flagged `flags |= 0x01` (`is_decal = true`) and keep their decoded positions.
  How they are drawn is the renderer's policy, in [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) and [`render-model.md`](../parity/render-model.md) section 3.

---

## 4. Open Questions & Analysis Backlog

The following backlog documents open questions regarding `.SOD` virtual machine opcodes:

| ID | Topic / Investigation Area | Current Evidence & Finding | Evidentiary Tier | Recommended Handling in Engine |
| :--- | :--- | :--- | :---: | :--- |
| **Q-SOD-01** | `OP_IFVIS` Condition Codes | Resolved: the operand is not a condition code but the byte offset of a facing flag in `work:0x7C68`, which `REJ`/`REJVEC`/`REJ2D` set when their face points at the eye; `OP_IFVIS` (`0x9BCC`) runs its section while the flag is set and `OP_BVIS` (`0x9BB3`) while it is clear. There is no distance form; the old $D^2 \ge 1000\text{ m}^2$ reading had no binary basis. This also fits the community report that dropping either branch of an `IFVIS` pair loses aircraft parts ([*Vibe-exploring Stunt Island*](https://marnetto.net/2026/04/26/vibe-exploring-si)). Handlers in [`playone-exe/sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) section 8.6. | `[Established]` | `REJ`, `REJ2D` and `REJVEC` faces become `VisibilityCondition::FacesEye`, evaluated per frame against the eye; `OP_BVIS` takes the face turned away. No census walk reaches `REJVEC`, `REJ2D` or `OP_BVIS`. |
| **Q-SOD-02** | Slicing Opcodes (`0x0240`..`0x02AC`) | Opcodes 64 through 76 were used by the historical `Slice` tool (`.SIO`) for terrain chunk sectioning. Not used in retail prop models. | `[Bounded Observation]` | Handled as bounded no-ops or skip operands during transpilation. |
| **Q-SOD-03** | Texture & Sprite Billboard Opcodes (`0x032A`, `0x0333`) | Found in billboard props and runway signs; references `.SPR` sprite sheets in `SPRITES.RES`. | `[Bounded Observation]` | Emits placeholder quad; binds to sprite texture atlas when `.SPR` pipeline is active. |
| **Q-SOD-04** | Animation Variable Mappings (`undercarriage1`, etc.) | Macro assembler source files name specific registers/variables. Engine maps these to discrete `.FLM` actor state bits. | `[Supported Inference]` | Superseded: `ROTX`, `ROTY` and `ROTZ` read `PLAYONE`'s angle bank, filled from the film clock, film variables 10 and 12 and the slot's animate word ([`angle-bank.md`](../playone-exe/angle-bank.md)), and the renderer poses an actor's parts from it ([`sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) § 8.7). |
| **Q-SOD-05** | Level-of-Detail Detail Gates (`complex1..3`) | Model source branches on `complex1..3` flags (e.g. `iftrue complex2 ;if max complexity do surface detail` in `SITools/OBJECTS/Planes/SABRE.SOD`). What sets the flags at runtime is unknown. `SI-8x` does not touch them: it patches the separate distance gate at image `0x212D`, whose threshold scales with `GAME.VAR`'s detail word and the per-shot scale ([`lod.md`](../playone-exe/lod.md)). The one in-shape depth gate found in the binary is `BZLT` (`0x9BE5`, [`sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) section 8.6), decoded into `VisibilityCondition::BeyondDepth` and tested per frame, though no census walk of a stock shape reaches it; `IFVIS` is a facing gate (Q-SOD-01). | `[Bounded Observation]` | Transpiler exposes all detail branches; modern rendering renders maximum detail, which over-draws distant objects compared with PLAYONE's distance gate. |
| **Q-SOD-06** | Real-Mode Dynamic Memory Paging of 1024 Register Bank | In 640 KB conventional DOS memory, whether `PLAYONE.EXE` dynamically paged the 1024-vertex register bank (12 KB) into EMS/XMS or reserved a static `DGROUP` scratchpad buffer. | `[Hypothesis]` | Modern engine allocates contiguous flat arena vectors; memory constraints are eliminated. |
| **Q-SOD-07** | `OP_TAP` (`0x022E`) | Resolved: variable-width anchor-table load; handler at `CS:0x3E58`. | `[Established]` | Requires `ANCHORPT.DAT`; missing table returns a distinct stop reason. |
| **Q-SOD-08** | Unimplemented opcodes in the corpus | Corpus census (`mise run sod-census`, 2026-11-12): of 3,432 unique `MODEL_%04X.SOD` chunks, 3,418 walk clean to `OP_RETURN`, 14 stop only at `OP_TAP` without an anchor table, and 0 step over an unimplemented opcode; 393 loose `.BIN` models add 146 unique models not in archives, of which 145 walk clean and only `TESTTEXT.BIN` stops on `OP_TEXTURE`; see [`sod-opcode-coverage.md`](sod-opcode-coverage.md). | `[Bounded Observation]` | Lenient decode keeps geometry before the blocking opcode (Partial SOD). |

---

## 5. Attribution & Provenance

The `.SOD` virtual machine specification draws on extensive community analysis across multiple decades:

### 5.1 Community Researchers & Tool Authors

- **Adrian Stephens**: Original Assembly Line Engine Developer; authored the original 8086/80286 macro-assembler display-list source files for Stunt Island aircraft (`objdef`, `ipg`, `sorton`, `pushcentre`, `pushrelmat`).
- **Chris Phillips**: Author of `SODParse` (`ripres.c`, `DECODE.C`, `SOD.H`), `SIRes` (`SIResFile.cpp`, `Sod.h`), and `FreeFlight` (`siobj.cpp`).
  Decoded the 107 opcode jump table (multiples of 9), scale table constants, and OpenGL reconstruction.
- **Dave Palmowski**: Documented `.SOD` bounding boxes, scaling factors, and object coordinates in `SITools/`.
- **Doug Armknecht**: Curator of `corpus/siarchive/`, preserving developer notes and aircraft source models.
- **Neil Halelamien**: Documented 16-bit object type IDs referencing `.SOD` models in `Developer/Notes_SETFile/`.
- **Ángel Eduardo**: Analyzed subobject joint hierarchies, spheres, discs, and Set Designer models in `Developer/Notes_SIExtractor/`.
- **Alberto Marnetto**: Author of the `SI-8x` patch (2024), which raises the renderer's level-of-detail distance threshold eightfold by replacing the `mul` by the detail word with `mov dx, ax; shl dx, 3`, described in [*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island).
  The same site in `PLAYONE.EXE` is traced in [`lod.md`](../playone-exe/lod.md).
- **Alberto Marnetto (2026)**: Author of [`si-tools/sod-decoder`](https://github.com/AlbertoMarnetto/si-tools/tree/master/sod-decoder), an MIT-licensed C++ `.SOD` to Wavefront exporter derived from FreeFlight's `siobj.cpp`; it walks more aircraft parts than `SODParse`.
  Consulted for operand readings, not ported ([`sod-opcodes.md`](sod-opcodes.md) § 3).

### 5.2 Primary Reference Paths in `corpus/siarchive/`

- `Developer/SODParse/DECODE.C` (Chris Phillips' 107-opcode disassembler)
- `Developer/SODParse/SOD.H` (Opcode constants, scale table, data structures)
- `Developer/FreeFlight/src/siobj.cpp` (C++ OpenGL `.SOD` interpreter and transform stack)
- `SITools/OBJECTS/Planes/CURTISS.SOD` (ASCII `.objdef` assembler source; compiled models are `.BIN` files beginning with `0x000C`)
- `SITools/OBJECTS/Planes/SABRE.SOD` (ASCII `.objdef` assembler source; compiled models are `.BIN` files beginning with `0x000C`)
- `Developer/SI-8x/si-8x-notes.txt` (two-line pointer to Alberto Marnetto's article; the patch itself is the diff in `si-8x.7z`)

---
