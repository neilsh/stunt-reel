# Stunt Island Technical Reference: Compression Architecture & DOS 8.3 Path Normalization

**Document Identifier:** `research/formats/concepts/compression.md`  
**Author:** `worker_fmt_concepts`  
**Governing Invariant:** `[I8]` (DOS 8.3 Uppercase Path Normalization), `[I7]` (Cleanroom Asset Isolation)  
**Status:** Cleanroom Technical Reference Specification  

---

## 1. Overview & Mathematical / Hardware Principles

In the 1992 MS-DOS computing environment, game developers faced severe physical and architectural constraints:
1. **Physical Storage:** Retail releases were distributed on 1.44 MB 3.5-inch or 1.2 MB 5.25-inch high-density floppy disks.
2. **Memory Architecture:** Real-mode execution was restricted to 640 KB of conventional memory, with the static data segment (`DGROUP`) limited to 64 KB ($65{,}536\text{ bytes}$).
3. **CPU Throughput:** Target hardware (16 MHz to 33 MHz Intel 80386 systems) lacked the CPU cycles to decompress complex compressed asset streams on the fly during 3D flight simulation.

To reconcile these competing demands, *Stunt Island* implemented a tiered storage strategy:
- **Offline / Floppy Distribution:** Executable binaries were packed with dedicated executable packers (**LZEXE 0.91**), and installation scripts unpacked raw containers to the user's hard drive.
- **Runtime Asset Archives (`.RES`, `.ALL`):** Container formats prioritized zero-CPU-overhead random-access streaming. Retail resource archives store **uncompressed raw byte payloads**, using flat offset tables for instant seek and memory-mapping.
- **2D Asset Tooling:** Intermediate sprite creation pipelines utilized **PCX Run-Length Encoding (RLE)** before baking into uncompressed `.SPR` bitmaps.
- **Filesystem Mapping (`[I8]`):** All virtual filesystem lookups, container directory tables, and asset hashes conform to MS-DOS 8.3 uppercase naming rules.

```
+-------------------------------------------------------------------------------+
| STUNT ISLAND STORAGE & PATH CONVENTIONS                                       |
+-------------------------------------------------------------------------------+
| 1. Executables (PLAYONE.EXE, MAKEONE.EXE)                                      |
|    - LZEXE 0.91 Header Compression (plain LZSS, no Huffman stage)             |
|    - Decompressed into conventional memory at startup by 16-bit real-mode stub|
+-------------------------------------------------------------------------------+
| 2. Runtime Asset Archives (.RES, .ALL)                                         |
|    - Uncompressed raw byte streams (was_compressed = false in VfsEntry)       |
|    - Instantaneous O(1) slice access via parallel offset arrays                |
+-------------------------------------------------------------------------------+
| 3. Filesystem Normalization ([I8])                                            |
|    - MS-DOS 8.3 filename layout: 8-char base, optional dot, 3-char extension   |
|    - Invariant [I8]: All VFS lookups normalized via to_ascii_uppercase()      |
|    - Resolves case sensitivity collisions across Linux/macOS/Windows hosts    |
+-------------------------------------------------------------------------------+
```

**Governing invariants:** [`[I2]`](../../../docs/SPEC.md#i2-flat-arena-allocation-no-recursive-pointers), [`[I7]`](../../../docs/SPEC.md#i7-cleanroom-asset-isolation--small-pure-rust-core-dependencies), [`[I8]`](../../../docs/SPEC.md#i8-dos-83-uppercase-path-normalization). **Contract and code:** [`contracts/`](../../../crates/stunt-core/src/contracts/mod.rs). Fixtures: [`tests/fixtures/README.md`](../../../tests/fixtures/README.md).

---

## 2. Memory Layout & Bitfield Representations

### 2.1 MS-DOS 8.3 Directory Representation

MS-DOS FAT directory entries allocate a fixed 11-byte ASCII record for file names:
- **Bytes 0..7 (8 bytes):** Base file name, space-padded (`0x20`) on the right.
- **Bytes 8..10 (3 bytes):** File extension, space-padded on the right without the dot separator.

```
Byte Offset:   0  1  2  3  4  5  6  7    8  9  10
Raw Record:   [F][O][K][K][E][R][ ][ ]  [S][O][D]  --> "FOKKER.SOD"
```

In `.RES` archive name tables (offset `0x0014` in `synthetic_minimal.res`), entry names are serialized as a null-terminated (`\0`) or null-separated continuous ASCII string list:

```
+-------------------------------------------------------------------------------+
| Offset 0x14: "PLANE.SOD\0PROP.SOD\0\0"                                        |
| Payload offsets: ofs[0]=20, ofs[1]=40 (PLANE), ofs[2]=56 (PROP), ofs[3]=72    |
+-------------------------------------------------------------------------------+
```

### 2.2 Container Compression Flags

In the `VfsEntry` contract (`crates/stunt-core/src/contracts/vfs.rs`), entry metadata tracks compression status:

```rust
pub struct VfsEntry {
    pub name: String,           // Uppercase normalized DOS 8.3 name [I8]
    pub data: Vec<u8>,          // Raw payload bytes
    pub source_offset: u32,     // Container file offset
    pub was_compressed: bool,   // True if decompressed from packed format
}
```

In authentic retail disk containers (`corpus/` archives), `was_compressed` is universally `false`: payloads are stored byte-exact as authored. The engine retains the `was_compressed` field to accommodate potential third-party mods, compressed `.VOC` audio chunks, or historical LZSS variants.

### 2.3 LZEXE 0.91 Executable Header Structure

Retail `PLAYONE.EXE` is packed with Fabrice Bellard's **LZEXE 0.91**:
- **Packed Size:** $102{,}703\text{ bytes}$
- **Unpacked Image Size:** $200{,}524\text{ bytes}$ of load image, or $201{,}548\text{ bytes}$ as an MZ-wrapped file with the 1,024-byte header [`unlzexe.py`](../../../python/scripts/unlzexe.py) writes
- **Bitstream:** plain LZSS, no Huffman stage — a 16-bit little-endian flag word read LSB-first; `1` is a literal; `0`+`0` is a 2-bit length plus an 8-bit span; `0`+`1` is a 13-bit span plus a 3-bit length, with an extended length byte where `0` ends the stream and `1` skips a segment. [`unlzexe.py`](../../../python/scripts/unlzexe.py) implements exactly this and reproduces `build/re/playone.img` (`[Established]`)
- **Loader layout:** the eight-word info block sits at `(CS + header_paragraphs) × 16`, and the relocations at `loader + 0x158`. [`unlzexe.py`](../../../python/scripts/unlzexe.py) raises `IndexError` on `target_bin/StuntIsl/STUNT.EXE` (138,318 bytes) while it unpacks `corpus/siarchive/Films/OldPLAY/STUNT.EXE` (137,240 bytes) cleanly, so that copy carries a different loader layout or is not a plain 0.91 build (`[Bounded Observation]`; see `[BK-COMP-05]`)
- **Header Structure:** Standard MS-DOS `MZ` signature (`0x4D, 0x5A`) followed by a 28-byte MZ header and a small real-mode decompression stub located at segment `0x0000:0x0020`.
- **Relocation Table:** The LZEXE stub reads a compressed relocation table appended to the compressed payload, relocates segment references in conventional memory, and jumps to the unpacked entry point at `0000:0C5Eh`.

### 2.4 PCX Run-Length Encoding (RLE) Representation

In source art assets processed by `PCX2SPR.EXE` (Dave Palmowski), 8-bit palette images are compressed using classic ZSoft PCX run-length encoding:

```
Byte Value >= 0xC0 (11000000b):
  Bits 0..5 (Mask 0x3F): Repeat count (run length: 1..63)
  Next Byte:             Palette index byte to repeat

Byte Value < 0xC0 (00xxxxxxb .. 10xxxxxxb):
  Literal single pixel of that palette index (run length = 1)
```

During sprite baking (`PCX2SPR`), these runs are expanded into uncompressed raster buffers ($W \times H\text{ bytes}$) and written to `.SPR` files.

---

## 3. Data Structures, Tables & Conversion Algorithms

### 3.1 DOS 8.3 Path Normalization Algorithm (`[I8]`)

Under Invariant **`[I8]`**, all VFS operations, archive index constructions, and asset queries enforce strict uppercase 8.3 normalization.

```
Input Filename: "  models/fokker.sod  "
                      │
                      ▼ 1. Path Stripping & Separator Normalization
                "fokker.sod"
                      │
                      ▼ 2. ASCII Uppercase Conversion
                "FOKKER.SOD"
                      │
                      ▼ 3. 8.3 Validation & Key Lookup
                archive.get("FOKKER.SOD") -> Some(&VfsEntry)
```

#### Exact Normalization Rules
1. **Whitespace Trimming:** Strip leading and trailing ASCII whitespace characters (`0x20`, `\t`, `\r`, `\n`).
2. **Directory Separator Normalization:** Convert all forward slashes (`/`) and backward slashes (`\`) to canonical base filename extraction. (Containers store flat filenames without folder hierarchies).
3. **ASCII Uppercasing:** Transform all lowercase ASCII characters (`a`–`z`) to uppercase (`A`–`Z`) via `to_ascii_uppercase()`.
4. **8.3 Length Validation:**
   - Base name: Maximum 8 ASCII characters.
   - Extension: Maximum 3 ASCII characters.
   - Separator: Single dot (`.`).
5. **Forbidden Character Rejection:** Characters prohibited by FAT filesystems (`*`, `?`, `<`, `>`, `|`, `"`, `:`, control characters $< 0x20$) are rejected.

#### Rust Reference Implementation (`crates/stunt-core/src/contracts/vfs.rs`)
```rust
impl VfsArchive {
    /// Retrieves an entry by its case-insensitive filename per [I8].
    pub fn get(&self, filename: &str) -> Option<&VfsEntry> {
        let key = filename.to_ascii_uppercase();
        self.entries.get(&key)
    }

    /// Inserts an entry, ensuring the key is normalized to uppercase per [I8].
    pub fn insert(&mut self, entry: VfsEntry) {
        let key = entry.name.to_ascii_uppercase();
        self.entries.insert(key, entry);
    }
}
```

### 3.2 Container Direct-Slice Extraction Algorithm

Because retail `.RES` and `.ALL` containers contain uncompressed payloads, ingestion executes with zero allocation copying:

```rust
/// Unpacks a slice directly from container memory.
pub fn slice_payload<'a>(
    container_bytes: &'a [u8],
    offset: usize,
    length: usize,
) -> Result<&'a [u8], VfsError> {
    let end = offset
        .checked_add(length)
        .ok_or(VfsError::OffsetOverflow)?;
    if end > container_bytes.len() {
        return Err(VfsError::UnexpectedEof);
    }
    Ok(&container_bytes[offset..end])
}
```

### 3.3 PCX RLE Decompression Algorithm

Used when decoding community source artwork in `corpus/siarchive/SITools/SpriteMaker/`:

```rust
pub fn decode_pcx_rle(encoded_bytes: &[u8], expected_pixel_count: usize) -> Vec<u8> {
    let mut pixels = Vec::with_capacity(expected_pixel_count);
    let mut i = 0;

    while i < encoded_bytes.len() && pixels.len() < expected_pixel_count {
        let byte = encoded_bytes[i];
        i += 1;

        if (byte & 0xC0) == 0xC0 {
            let run_count = (byte & 0x3F) as usize;
            if i < encoded_bytes.len() {
                let pixel_value = encoded_bytes[i];
                i += 1;
                pixels.resize(pixels.len() + run_count, pixel_value);
            }
        } else {
            pixels.push(byte);
        }
    }

    pixels
}
```

---

## 4. Open Questions & Reverse Engineering Backlog

1. **`[BK-COMP-01]` European Multilingual Release Sub-Chunk Compression** (`[Bounded Observation]`): Certain non-English release disks feature non-zero flags in `.ALL` chunk tables. Verification is needed to determine if an LZSS variant was used to fit multiple language subtitles onto floppy disks.
2. **`[BK-COMP-02]` Trailing Space Padding in Authoring Tool Filenames** (`[Supported Inference]`): In `MAKERES.EXE`, filenames with fewer than 8 characters are occasionally padded with spaces (`0x20`) rather than null terminators (`0x00`). The VFS normalization pipeline cleanly strips these spaces.
3. **`[BK-COMP-03]` LZEXE 0.91 Relocation Table Fixups** (`[Established]`): Confirmed from static disassembly that `PLAYONE.EXE`'s relocation fixups occur prior to setting up `DGROUP` (`0x0D51`), allowing static analysis of unpacked binary offsets.
4. **`[BK-COMP-04]` Undocumented RLE Huffman Chunk in Sound Stage** (`[Hypothesis]`): Hypothesis that high-sample-rate speech clips in sound stage scenes used adaptive ADPCM or Huffman compression rather than raw 8-bit PCM.
5. **`[BK-COMP-05]` `STUNT.EXE` Loader Variant** (`[Bounded Observation]`): `target_bin/StuntIsl/STUNT.EXE` (138,318 bytes) carries an `LZ91` stamp but no readable eight-word info block at `(CS + header_paragraphs) × 16`, so the `unlzexe.py` relocation walk runs off the end. Identify the loader variant (or confirm the file is not a plain 0.91 build) before any static analysis of that copy; the corpus `OldPLAY/STUNT.EXE` (137,240 bytes) unpacks normally.

---

## 5. Attribution & Provenance

- **Fabrice Bellard (1990):** Creator of the LZEXE 0.91 MS-DOS executable compressor.
- **Dave Palmowski (1999–2001):** Author of SpriteMaker and PCX2SPR, documenting PCX RLE decoding and `.SPR` uncompressed raster layouts in `corpus/siarchive/SITools/SpriteMaker/`.
- **Adrian Stephens & FreeFlight Team:** Implementation of `ripres.c` and `sires.cpp` establishing uncompressed `.RES` and `.ALL` payload slicing in `corpus/siarchive/Developer/SODParse/` and `Developer/FreeFlight/`.
- **Doug Armknecht (2002):** Corpus-wide extraction of uncompressed film streams and chunk boundaries via `flm_extract.py` in `corpus/siarchive/Developer/SI_FLM_Format/`.
- **Neil Halelamien (2004):** Reverse engineering of `.SET` scene files and documentation of uppercase 8.3 filename conventions in `corpus/siarchive/Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt`.
- **StuntReel Teamwork Team (2026):** Invariant `[I8]` specification, `VfsArchive` case-normalization contract, and cleanroom test fixtures (`crates/stunt-core/src/contracts/vfs.rs`, `tests/fixtures/synthetic_minimal.res`).

---
