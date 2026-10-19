# Technical Reference Specification: Stunt Island `.RES` Container Format

## 1. Overview & File Identification

The `.RES` file format is the foundational static resource container for *Stunt Island* (1992, Walt Disney Computer Software / The Assembly Line). The game engine relies on `.RES` packages located in the `res\` directory (`DS:05DB` in `PLAYONE.EXE`) to store all primary game assets: 3D geometry display lists (`.SOD`), 2D software bitmaps and sprites (`.SPR`), frame animations (`.ANM`), sound stage dialogue recordings (`DIALOG.RES`), UI definitions (`GAME.RES`), and world scenery models (`SCENERY1.RES`–`SCENERY6.RES`).

### Key File Attributes

| Attribute | Specification | Evidentiary Tier | Authoritative Citation |
| :--- | :--- | :---: | :--- |
| **File Extension** | `.RES` (DOS 8.3 uppercase, e.g., `ACTORS.RES`, `PLANES.RES`, `SCENERY1.RES`) | `[Established]` | `research/playone-exe/startup.md` |
| **Magic Signature** | 2-byte ASCII: `b"RS"` (`0x52, 0x53`) at byte offset `0x0000` | `[Established]` | `RIPRES.C:74`, `SIResFile.cpp:44`, `crates/stunt-core/src/vfs/res.rs:28` |
| **Byte Endianness** | Little-Endian (all 16-bit word and 32-bit dword integers) | `[Established]` | `RIPRES.C:78-82`, `sires.cpp:52` |
| **Engine Role** | Static archive container providing $O(1)$ direct indexed access to geometry, sprites, and dialogue assets without runtime disk seeks or string hashing | `[Established]` | `docs/SPEC.md § 3.1`, `indices.txt` |
| **Paired Contract** | `Seam 1: VfsArchive` (`crates/stunt-core/src/contracts/vfs.rs`) | `[Established]` | `# [FMT-RES-HEADER]`, `docs/ARCHITECTURE.md` |

---

## 2. Header & Memory Layout

Cross-corpus analysis of all 20 authentic retail `.RES` archives in `corpus/si_archive/` demonstrates that the physical on-disk file begins with an **8-byte binary header**, immediately followed by a contiguous array of 32-bit little-endian file offsets.

### 2.1 On-Disk Physical Header & Offset Table Layout (`# [FMT-RES-HEADER]`)

The executable byte layout for this section is [`res.ksy`](res.ksy). It declares the `b"RS"` (`0x52, 0x53`) magic, the raw 16-bit header word at bytes `0x0002`–`0x0003`, the little-endian `ofs[0]` at `0x0004`, and the remaining offset table entries. The schema is the single source for field widths, offsets, byte order, and the offset-count calculation; the profile, evidence, and parser-policy discussion remains below.

Bytes `0x0002`–`0x0003` are read by `parse_res` as a single little-endian 16-bit word and ignored. Historical sources also describe the same bytes as `res_index: u8` followed by `item_count: u8`. The Kaitai schema keeps the field as raw `header_word`; neither interpretation is treated as settled by the schema.

#### Payload Slicing Rules
1. In archives with an ASCII Name Table (Prop archives):
   - The Name Table is located between $\text{offsets}[0]$ and $\text{offsets}[1]$ (`data[ofs[0]..ofs[1]]`).
   - The total number of resource payloads is $N_{\text{payloads}} = N - 2 = (\text{ofs}[0]/4) - 3$.
   - Payload $i$ (for $i \in [0, N_{\text{payloads}}-1]$) begins at $\text{offsets}[i+1]$ and ends at $\text{offsets}[i+2]$.
2. In archives without an ASCII Name Table (Scenery archives):
   - $\text{offsets}[0]$ points directly to the first raw payload (`.SOD` bytecode).
   - Payload $i$ begins at $\text{offsets}[i]$ and ends at $\text{offsets}[i+1]$.
3. Strict Monotonicity:
   The offset sequence must be strictly non-decreasing:
   $$\text{offsets}[i+1] \ge \text{offsets}[i] \quad \forall i \in [0, N-2]$$
   An offset satisfying $\text{offsets}[i+1] < \text{offsets}[i]$ indicates corruption or negative entry sizes, causing the parser to abort with `VfsError::InvalidOffsetTable`.

### 2.2 On-Disk 8-Byte Header vs. Real-Mode 16-Byte Memory Descriptor

A long-standing debate in the Stunt Island developer community concerned whether `.RES` containers feature an 8-byte or a 16-byte header:

- **On-Disk Reality (`[Established]`):** Every physical file on the retail floppy and CD-ROM distributions begins with the 8-byte structure (`b"RS"`, a raw 16-bit header word at bytes 2–3, `ofs[0]: u32` at byte 4). Historical sources describe the header word as `res_index: u8` followed by `item_count: u8`; `parse_res` reads one ignored 16-bit word. There is no 16-byte file header on disk.
- **In-Memory DOS Descriptor (`[Hypothesis]` / `[Supported Inference]`):**
  In MS-DOS 16-bit real-mode conventional memory (`DGROUP`), `PLAYONE.EXE` maintains an internal table of loaded resource containers. Each active `.RES` handle is managed by a 16-byte Memory Control Block (MCB) descriptor structure:
  ```c
  struct DosResDescriptor {
      uint16_t dos_file_handle;     // +0x00: Active DOS file handle (INT 21h)
      uint8_t  res_index;           // +0x02: Resource Category ID (0..255)
      uint8_t  flags;               // +0x03: Bitflags (0x01=Locked, 0x02=Purgeable)
      uint16_t ofs_table_seg;       // +0x04: Segment address of cached offset array
      uint16_t ofs_table_off;       // +0x06: Offset address of cached offset array
      uint32_t linear_cache_base;   // +0x08: 32-bit linear address of EMS/XMS buffer
      uint16_t entry_count;         // +0x0C: Total items in archive
      uint16_t lru_counter;         // +0x0E: LRU cache eviction tick counter
  };
  ```
  This 16-byte descriptor was preserved in early reverse-engineering notes by researchers who inspected runtime memory dumps rather than the static files on disk.

---

## 3. Data Structures & Opcode Table

### 3.1 Name Table Layout: Prop Archives vs. Scenery Archives

The engine distinguishes two primary `.RES` operational profiles based on the Resource Category Index `res_index`:

```
                    +-----------------------------+
                    | Check res_index (Byte 0x02) |
                    +--------------+--------------+
                                   |
                  +----------------+----------------+
                  |                                 |
         res_index > 0x0F                  res_index <= 0x0F
         (idBase > 0x0F00)                 (idBase <= 0x0F00)
                  |                                 |
                  v                                 v
        [ PROP RESOURCE ARCHIVE ]         [ SCENERY RESOURCE ARCHIVE ]
        ofs[0]..ofs[1] = ASCII Strings    ofs[0] points directly to SOD
        String 0 = Category Menu Title    No ASCII string table on disk
        String 1..N = Prop Names          Synthetic names: 0000.BIN..
```

#### 1. Prop Resource Archives (`res_index > 0x0F` / `idBase > 0x0F00`)
- **Containers:** `ACTORS.RES` (`0x3B`), `LETTERS.RES` (`0x3C`), `MARKERS.RES` (`0x3D`), `MILITARY.RES` (`0x3E`), `MISCELLA.RES` (`0x3F`), `STRUCTUR.RES` (`0x40`), `VEHICLES.RES` (`0x41`), `PLANES.RES` (`0x7F`).
- **Name Slice (`data[ofs[0]..ofs[1]]`):** Contains a packed list of null-terminated (`0x00`) ASCII strings.
- **String 0 (Category Title):** The human-readable group name displayed at the top of the Set Designer menu (e.g., `"Mammals and Plants"`, `"Military Equipment"`, `"Vehicles and Vessels"`, `"Aeroplanes"`).
- **Strings $1 \dots N_{\text{items}}$:** The human-readable catalog names for each individual 3D prop (e.g., `"Bad Guy"`, `"Boom Mike"`, `"Fokker Dr.I"`, `"Control Tower"`, `"Cactus #1"`).
- **String Table Termination:** The string table ends with an extra null byte (`0x00\0x00`) or is bounded by `ofs[1]`.

#### 2. Scenery Resource Archives (`res_index <= 0x0F` / `idBase <= 0x0F00`)
- **Containers:** `SCENERY1.RES` (`0x02`) through `SCENERY6.RES` (`0x07`).
- **Absence of Names:** Scenery models are never selected through the interactive Set Designer GUI. They are placed automatically across the island landscape by `MAP.BIN` using global scenery object IDs.
- **Data Layout:** The ASCII string table is omitted. The first offset $\text{ofs}[0]$ points directly to the first raw `.SOD` geometry model (starting with the 2-byte magic word `0x000C`).
- **Parser Fallback:** When a parser encounters a scenery file, it detects that `data[ofs[0]..ofs[1]]` starts with `0x000C` (or contains non-ASCII graphics bytes) and automatically generates synthetic 8.3 entry names: `0000.BIN`, `0001.BIN`, etc.

### 3.2 Direct 16-Bit Compound Key Resource Addressing

*Stunt Island* does not use string hashing, linear filename scans, or B-trees at runtime to resolve assets. Instead, it employs **direct 16-bit compound keys**:

$$\text{Resource ID} = (\text{res\_index} \ll 8) \mid \text{item\_index}$$

```
 15                  8   7                   0
+-----------------------+---------------------+
|   res_index (8-bit)   |  item_index (8-bit) |
+-----------------------+---------------------+
    Archive Slot (0..255)   Payload Index (0..N)
```

When `PLAYONE.EXE`, a `.FLM` choreography stream, or a `.SET` scenery file references an entity:
1. **High Byte (`Resource ID >> 8`):** Indexes directly into the engine's global loaded `.RES` package table (slots $0 \dots 255$).
2. **Low Byte (`Resource ID & 0xFF`):** Indexes directly into that container's cached 32-bit offset array.
3. **Execution Cost:** Memory lookup is $O(1)$ arithmetic without hash collisions or string comparisons.

### 3.3 Master Resource Index Enumeration Table

The authoritative catalog of `.RES` indices, recovered from `SITools/ResMaker/indices.txt` and verified against the retail CD-ROM file set:

| Index (Dec) | Index (Hex) | Archive Filename | Contents & Engine Role | String Table Present? |
| :---: | :---: | :--- | :--- | :---: |
| **1** | `0x01` | `GAME.RES` | Core UI dialog strings, fonts, menus, and system bitmaps | Yes |
| **2** | `0x02` | `SCENERY1.RES` | Island terrain scenery models (Sector 1: Airfield & Coast) | No (`ofs[0]` direct to SOD) |
| **3** | `0x03` | `SCENERY2.RES` | Island terrain scenery models (Sector 2: Mountain Range) | No (`ofs[0]` direct to SOD) |
| **4** | `0x04` | `SCENERY3.RES` | Island terrain scenery models (Sector 3: City & Downtown) | No (`ofs[0]` direct to SOD) |
| **5** | `0x05` | `SCENERY4.RES` | Island terrain scenery models (Sector 4: Canyons & Desert) | No (`ofs[0]` direct to SOD) |
| **6** | `0x06` | `SCENERY5.RES` | Island terrain scenery models (Sector 5: Farmland & Hills) | No (`ofs[0]` direct to SOD) |
| **7** | `0x07` | `SCENERY6.RES` | Island terrain scenery models (Sector 6: Offshore Islands) | No (`ofs[0]` direct to SOD) |
| **31** | `0x1F` | `FASTSPR.RES` | Software rasterizer fast 2D sprites and blit masks | Yes |
| **58** | `0x3A` | `PRODTOOL.RES` | Production tools: film slates, camera tripods, light stands | Yes |
| **59** | `0x3B` | `ACTORS.RES` | Animated character props: humans, animals, trees, plants | Yes (`"Mammals and Plants"`) |
| **60** | `0x3C` | `LETTERS.RES` | 3D alphabet characters, digits, and roadside signage | Yes |
| **61** | `0x3D` | `MARKERS.RES` | Runway pylons, target markers, navigation buoys, cones | Yes |
| **62** | `0x3E` | `MILITARY.RES` | Military equipment: tanks, artillery, missiles, radar | Yes |
| **63** | `0x3F` | `MISCELLA.RES` | Clutter props: barrels, furniture, crates, ladders, tools | Yes |
| **64** | `0x40` | `STRUCTUR.RES` | Architecture: hangars, bridges, skyscrapers, warehouses | Yes |
| **65** | `0x41` | `VEHICLES.RES` | Vehicles: cars, trucks, trains, speedboats, ground tugs | Yes |
| **127** | `0x7F` | `PLANES.RES` | Primary flyable aircraft models (Curtiss Jenny, F-86, etc.) | Yes |
| **128** | `0x80` | `SPRITES.RES` | Particle effects: explosions, bullet hits, fire, smoke | Yes |
| **129** | `0x81` | `ANIMS.RES` | Pre-rendered cinematics and UI transition animations | Yes |
| **144** | `0x90` | `SCENES.RES` | Set templates and stage backdrop definitions | Yes |
| **191** | `0xBF` | `DIALOG.RES` | Sound stage dialogue audio clips (8-bit PCM) | Yes |

### 3.4 Compression Flags & Payload Encodings

- **Container-Level Compression (`[Established]`):**
  All 20 authentic `.RES` archives in the reference corpus store **raw uncompressed entries** (`was_compressed = false`). Dave Palmowski documented in `RESMaker 1.0`:
  > *"‘compressed’ is quoted because technically, in a RES file, nothing is compressed any further than it already is. Everything is just kinda clumped."*
- **Payload-Specific Encodings:**
  While `.RES` acts as an uncompressed packfile, payloads embedded within it utilize internal compression or bytecode schemes:
  - `.SOD`: Procedural bytecode display lists (self-contained VM execution streams).
  - `.SPR`: Run-Length Encoded (RLE) 8-bit paletted scanlines with transparency keying (`0x00`).
  - `.VOC`: 8-bit unsigned PCM audio blocks with Creative Voice File headers.

---

## 4. Architectural Invariants & Coordinate Mapping

### 4.1 Invariant `[I8]` — Uppercase DOS 8.3 Filename Normalization

System invariant `[I8]` mandates that all virtual filesystem keys are normalized to uppercase ASCII 8.3 filenames:
- When extracting names from the internal Name Table, leading and trailing whitespace is stripped.
- All ASCII characters are converted via `.to_ascii_uppercase()`.
- If an entry name is empty or contains non-ASCII characters, the parser deterministically generates an uppercase 4-digit hexadecimal identifier: `format!("{:04X}.BIN", entry_index)`.
- Lookups in `VfsArchive` are strictly case-insensitive: querying `"fokker.sod"`, `"FOKKER.SOD"`, or `"Fokker.Sod"` accesses the exact same underlying byte payload.

### 4.2 Invariant `[I7]` — Cleanroom Asset Isolation

Under Invariant `[I7]`, no proprietary binary data from original disks or archives may ever be checked into Git:
- All CI test runs and unit test suites execute against offline cleanroom synthetic fixtures (`tests/fixtures/synthetic_minimal.res`).
- The parser implementation in `crates/stunt-core/src/vfs/res.rs` is 100% cleanroom: it was written exclusively against public structural specifications (`RIPRES.C`, `indices.txt`) without copying assembly or proprietary runtime routines.

---

## 5. Open Questions & Reverse Engineering Backlog

The following backlog documents unresolved questions and their empirical status:

| ID | Topic / Investigation Area | Current Evidence & Finding | Evidentiary Tier | Recommended Handling in Engine |
| :--- | :--- | :--- | :---: | :--- |
| **Q-RES-01** | 16-byte header vs. 8-byte header discrepancy | All 20 corpus archives have 8-byte headers on disk. A 16-byte descriptor existed in real-mode `DGROUP` memory. | `[Established]` (disk) / `[Hypothesis]` (memory) | On-disk parsers mandate 8-byte header; memory descriptor documented in `docs/MEMORY_MAP.md`. |
| **Q-RES-02** | Scenery `.RES` name table omission | Scenery packages (`res_index <= 0x0F`) omit the string table; `ofs[0]` points directly to `.SOD` bytecode. | `[Established]` | Implement automatic heuristic: if string slice begins with `0x000C`, synthesize names `0000.BIN..`. |
| **Q-RES-03** | Third-party compression flags | Retail floppy/CD-ROM archives contain zero compressed entries. Community tools occasionally hinted at LZSS compression flags. | `[Bounded Observation]` | Flag `was_compressed` remains `false`. Hook LZSS decoder if modded compressed archives are encountered. |
| **Q-RES-04** | Dynamic memory caching & LRU eviction | Real-mode `PLAYONE.EXE` cached `.RES` offset tables in conventional RAM while streaming payloads on demand. | `[Supported Inference]` | Modern engine loads archive tables fully into memory; zero disk thrashing. |
| **Q-RES-05** | European CD-ROM multilingual string tables | French/German releases may include localized prop display strings in `GAME.RES` or `ACTORS.RES`. | `[Bounded Observation]` | Ensure UTF-8 / CP437 decoding handles extended Latin characters gracefully without panic. |

---

## 6. Attribution & Provenance

The reverse engineering of the `.RES` archive container format represents decades of dedicated community research:

### 6.1 Community Researchers & Tool Authors

- **Adrian Stephens**: Original Assembly Line Engine Developer; designed the memory clump layout and 16-bit resource ID addressing architecture for the 8086/80286 DOS engine.
- **Chris Phillips** (`bigbang@seanet.com`): Author of `SODParse` (`ripres.c`, `DECODE.C`, `SOD.H`), `SIRes` (`SIResFile.cpp`, `Sod.h`), and `FreeFlight` (`sires.cpp`). Decoded the 8-byte header, offset table slicing, and string table extraction logic.
- **Dave Palmowski**: Author of `RESMaker 1.0` (August 15, 2000). Compiled `indices.txt`, documented index categories 0–255, and proved that `.RES` files store uncompressed asset clumps.
- **Doug Armknecht**: Curator of the Stunt Island Community Developer Archive (`corpus/si_archive/`, February 2026). Preserved original source files, utilities, and documentation.
- **Neil Halelamien**: Author of `.SET` scenery format research (2004); documented 16-bit compound keys `(res_index << 8) | item_index` in `Stunt_Island_SET_fileformat_notes.txt`.
- **Ángel Eduardo** (`arcnorj@yahoo.es`): Author of Stunt Island Extractor (2004–2005); analyzed binary models, prop clumps, and subobject hierarchies.
- **Alberto Marnetto**: Author of `SI-8x` high-detail engine patch (2024); explored resource streaming limits and LOD bytecode execution.

### 6.2 Primary Reference Paths in `corpus/si_archive/`

- `Developer/SODParse/ripres.c` (Chris Phillips' original C extraction tool)
- `Developer/SIRes/SIResFile.cpp` (C++ resource archive reader)
- `Developer/FreeFlight/src/sires.cpp` (OpenGL flight simulator `.RES` ingest)
- `SITools/ResMaker/indices.txt` (Authoritative master resource index table)
- `SITools/ResMaker/readme.txt` (Dave Palmowski's technical notes on clump storage)
- `Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt` (Neil Halelamien's 16-bit key analysis)

---

## 7. Codebase Seam Contracts & Fixtures

### 7.1 Seam 1: `VfsArchive` Contract

The `.RES` container parser implements `Seam 1: VfsArchive` defined in `crates/stunt-core/src/contracts/vfs.rs`:

```rust
// contracts/vfs.rs
pub enum ArchiveFormat {
    Res,
    All,
}

pub struct VfsEntry {
    pub name: String,
    pub data: Vec<u8>,
    pub source_offset: u32,
    pub was_compressed: bool,
}

pub struct VfsArchive {
    pub format: ArchiveFormat,
    pub entries: BTreeMap<String, VfsEntry>,
}
```

### 7.2 Native Rust Implementation

- **Parser Function**: `crates/stunt-core/src/vfs/res.rs::parse_res(data: &[u8]) -> Result<VfsArchive, VfsError>`
- **Error Handling**: `crates/stunt-core/src/vfs/mod.rs::VfsError`
  - `UnexpectedEof { expected, actual }`: File smaller than 8 bytes or offset exceeds length.
  - `InvalidMagic { expected: "RS", actual }`: First 2 bytes do not match `b"RS"`.
  - `InvalidOffsetTable { reason }`: `ofs[0] < 8`, non-4-byte aligned, or non-monotonic offsets.

### 7.3 Cleanroom Synthetic Fixture: `synthetic_minimal.res`

Located at `tests/fixtures/synthetic_minimal.res` (72 bytes total):
- **Bytes 0..1**: Magic signature `b"RS"` (`0x52, 0x53`)
- **Bytes 2..3**: Raw header word `0x0001`
- **Offset Table** ($N = (20/4) - 1 = 4$ offsets):
  - `ofs[0] = 20` (`0x14`): Name Table start
  - `ofs[1] = 40` (`0x28`): Payload 0 (`PLANE.SOD`, 16 bytes)
  - `ofs[2] = 56` (`0x38`): Payload 1 (`PROP.SOD`, 16 bytes)
  - `ofs[3] = 72` (`0x48`): EOF sentinel offset
- **Name Table (`20..40`)**: `"PLANE.SOD\0PROP.SOD\0\0"`
- **Payloads**: Deterministic test bytes verifying 100% byte-accurate extraction without data corruption.

### 7.4 Verification Test Suite

- `crates/stunt-core/tests/vfs_test.rs`: Basic extraction, empty containers, corrupted headers, synthetic fixture ingest.
- `crates/stunt-core/tests/vfs_challenge_test.rs`: Case insensitivity stress test (100 permutations), zero-byte entries, large containers.
- `crates/stunt-core/tests/vfs_stress_test.rs`: Fuzzing mutations, offset table out-of-bounds wrapping, adversarial malformed buffers.
