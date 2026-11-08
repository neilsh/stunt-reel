---
summary: "`ANCHORPT.DAT` ([FMT-MAP-ANCHORPT]): 1,024 28-byte anchor records saved by `SD.EXE`, elevation stored negated; the game images hold the 231 authored records, and the eleven words are inferred cache."
---
# Specification: `ANCHORPT.DAT` Anchor Point Table

## 1. Overview & File Identification

`ANCHORPT.DAT` is the island's table of anchor points: 1,024 records of 28 bytes, each an `(x, y, z)` point followed by eleven words. `MAP.BIN`'s terrain patches use them as corners ([`map.md`](map.md)), and `OP_TAP` copies them into a shape's vertex registers ([`sod-opcodes.md`](../sod-opcodes.md)). It is one of the three tables in a `SIDATA\` directory, beside `MAP.BIN` and `SCENERY.scn` ([`scenery.md`](scenery.md)).

- **Origin.** The file is the anchor buffer of `SITools/SD.EXE`, the developers' scenery compiler, saved as it stood in memory (`[Established]`). `SD.EXE` reads `0x1C × 0x400` bytes into that buffer at offset 4 (load image `0x8F67`) and writes the same bytes back (`0x8FA0`). It emits the table as `\stunt\anchor.asm`, which the game assembles in ([`map.md`](map.md) section 1.1).
- **Copies in the game executables** (`[Established]`, byte comparison of the unpacked load images, 2026-10-23 and 2026-11-06). The table holds 231 records in each image compared: unpatched `PLAYONE.EXE` at image `0x15D44`, Patch #3 `PLAYONE.EXE` at `0x14BF4`, and both `STUNT.EXE` copies at `0x218B4` (the retail copy is the OldPLAY build with an entry stub appended, and both unpack to the same 248,460-byte image). In all four, `(x, y, z)` agree with the corpus files, the eleven words are zero, and anchors 19, 22, 51, 68 and 71 have `y = 0`. The game's runtime copy is the work-segment table with a 4-byte header ([`memory-map.md`](../../playone-exe/memory-map.md) `# [MEM-SOD-ANCHOR-TABLE]`).
- **Corpus copies.** Two different files exist. `Developer/FreeFlight/SIDATA/`, `Developer/SIRes/SiData/` and `Developer/SODParse/` hold one; `SITools/` holds the other. Both keep the 231 records' `(x, y, z)` and pad records 231–1023 with `(-32768, -32768, -32768)` and zero words. They differ in two ways. The eleven words differ in 165 of the 231 records. And FreeFlight's copy has `y = -32768` on anchors 19, 22, 51, 68 and 71, where `SITools/` and every image have 0.
- **Rebuilding it from the game.** The image's table, padded with the fill records, gives a file that `parse_anchor_table` reads exactly as FreeFlight's except on those five anchors (`[Established]`). The eleven words cannot be rebuilt and are not read.

**Governing invariants:** [`[I1]`](../../../docs/SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization), [`[I8]`](../../../docs/SPEC.md#i8-dos-83-uppercase-path-normalization). **Code:** [`anchor.rs`](../../../crates/stunt-core/src/anchor.rs). No synthetic terrain fixture exists yet.

---

## 2. Header & Memory Layout

### 2.1 `ANCHORPT.DAT` Memory Layout (`# [FMT-MAP-ANCHORPT]`)

`ANCHORPT.DAT` has no header: exactly 1,024 contiguous 28-byte records ($1024 \times 28 = 28{,}672$ bytes). In memory, both `SD.EXE` and `PLAYONE.EXE` put a 4-byte header in front, so a vertex pointer is `4 + 28 × index` in `SD.EXE` and `28 × index` from the table's base in `PLAYONE`'s tree.

| Field | Meaning | Evidentiary Tier |
| :--- | :--- | :--- |
| `x` | $X$ coordinate in island units | `[Established]` |
| `y` | Elevation, stored negated; `-32768` marks no point | `[Established]` |
| `z` | $Z$ coordinate in island units | `[Established]` |
| `f[11]` | Per-frame cache of the program that saved the file: zero in every game image, different in the two corpus files. The runtime fields are listed under `# [MEM-SOD-ANCHOR-TABLE]` | `[Supported Inference]` |

Executable layout: [`anchorpt.dat.ksy`](anchorpt.dat.ksy).

---

## 3. Data Structures & Opcode Table

### 3.1 Coordinates

Per Invariant `[I1]`, raw `(x, y, z)` maps to the canonical right-handed metric frame as $x_{\text{metric}} = -x$, $y_{\text{metric}} = -y$, $z_{\text{metric}} = z$: elevation is stored negated, so height above sea level is $-y$. FreeFlight's `simap.cpp` makes the same inversion of $X$ and $Y$ when it submits vertices to OpenGL. `AnchorPoint::register_position` applies it, and reads a `y` with $|y| \ge 32000$ as a sentinel at height 0 (`[Established]`).

### 3.2 Sentinel anchors

The image's own table holds 29 anchors with `y = -32768`, so the sentinel is authored data. FreeFlight's copy adds five more, anchors 19, 22, 51, 68 and 71 (`[BK-MAP-08]`). 19 and 22 are corners of `MAP.BIN` patches the game never draws, and 51, 68 and 71 are corners of patch 131, which it draws ([`map.md`](map.md) section 3.2).

---

## 4. Open Questions & Analysis Backlog

| Item ID | Topic | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- |
| `[BK-MAP-01]` | `f[11]` | The eleven words are cache, not authored data (section 2.1). How `PLAYONE` fills them per frame is in [`sod-vm.md`](../../playone-exe/sod-vm.md); nothing reads them from the file. | `[Supported Inference]` |
| `[BK-MAP-08]` | Sentinel anchors in FreeFlight's copy | Anchors 19, 22, 51, 68 and 71 have `y = 0` in all four game images and in `SITools/ANCHORPT.DAT`, but `y = -32768` in FreeFlight's copy, so only that save carries them. Closed as not land at sea level: drawing patches 52, 62, 64, 65 and 131 at `y = 0` left `CTRY.FLM` flat (0.7733 to 0.7732) and lowered `INTRO.FLM` from 0.6856 to 0.6822, past the 0.003 bound (2026-10-23 at `911211a`, [parity log](../../parity/log.md)). No instruction in `PLAYONE`'s code segment stores the immediate `0x8000` into an anchor record. | `[Bounded Observation]` |

### 4.1 Ruled out

- **`f[11]` as authored data** (section 2.1, 2026-11-06): the two corpus saves disagree in 165 of 231 records, and every game image has the words zero.
- **The five sentinels as land at sea level** (`[BK-MAP-08]`): drawing them at `y = 0` lowered `INTRO.FLM` past the bound.

### 4.2 Open questions

1. **Who wrote `-32768` into the five anchors of FreeFlight's copy** (`[BK-MAP-08]`). `SD.EXE`'s height prompt, `Anchor point height (ft) :` (load image `0xBA8D`), is one candidate.

---

## 5. Attribution & Provenance

- **Chris Phillips (2000–2003):** FreeFlight, SIRes and SODParse, whose `SIDATA` directories carry the FreeFlight copy and whose `sisland.cpp` and `simap.cpp` read it (`corpus/siarchive/Developer/FreeFlight/`, `corpus/siarchive/Developer/SIRes/`, `corpus/siarchive/Developer/SODParse/`).
- **Dave Palmowski (1999–2004):** the `SITools` collection, which carries the second copy and `SD.EXE` (`corpus/siarchive/SITools/`).
- **Stunt Reel contributors (2026):** the record layout, the comparison with the four game images, and `SD.EXE`'s load and save code.
