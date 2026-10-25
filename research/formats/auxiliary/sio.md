# Specification: .SIO Slice Mesh Format

## 1. Overview & File Identification

The `.SIO` format is an intermediate 3D mesh and point-cloud authoring format created for *Stunt Island* (1992, Walt Disney Computer Software / The Assembly Line). It was designed and implemented by Dave Palmowski (1999–2001, Stunt Island Filmmakers Association / SIFA) as the native file format for **SLICE** ("Stunt isLand Inhouse Custom Editor"), an external visual 3D modeler originally developed in Visual Basic 5.0 to author complex curved vehicles and structural props for the community film *UFO Command Act 2*.

- **File Extension:** `.SIO`
- **Magic Bytes:** 8 bytes: `53 64 73 01 00 00 00 00` (ASCII `b"Sds\x01"` followed by four zero version bytes).
- **Typical Container / Storage:** Loose authoring files stored in project workspaces or tooling directories (e.g. `corpus/siarchive/SITools/Slice/`).
- **Byte Endianness:** Little-endian (standard x86 16-bit integer formatting).
- **Engine Lifecycle Role:**
  1. *Intermediate Geometric Modeling:* Serves as a high-level 3D point cloud and wireframe authoring format supporting geometric primitives (centralized cubes, circles, spheres, Bezier curves, and random point-cloud splats).
  2. *Upstream Feed to Official Compiler (`SD.EXE`):* Generates point-cloud structures that are ingested into the official Stunt Island object compiler (`SD.EXE`) to assemble final procedural display-list `.SOD` / `.BIN` models.
  3. *Parametric Vertex Construction:* Implements explicit coordinates alongside parametric midpoint generator opcodes, reducing file size and enforcing geometric symmetry.

**Governing invariants:** [`[I1]`](../../../docs/SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization). **Contract and code:** [`contracts/shape.rs`](../../../crates/stunt-core/src/contracts/shape.rs). No synthetic `.SIO` fixture exists yet.

---

## 2. Header & Memory Layout

A `.SIO` file starts with an 8-byte magic header, followed by a 1-byte editor magnification scalar, a variable-length stream of tagged geometry records, and a 4-byte EOF sentinel marker. The executable layout is [`sio.ksy`](sio.ksy).

### 2.1 File Layout Diagram

```
+-----------------------------------+-------+---------------------------------------+---------------+
|     Magic Signature (8 bytes)     | Grid  | Tagged Geometry Records (9B or 7B)    | Trailer (4B)  |
|  53 64 73 01 00 00 00 00 ("Sds\1")|  u8   | 0x12 (Vertex) / 0x06 (Midpoint) ...   |  FF FF 00 00  |
+-----------------------------------+-------+---------------------------------------+---------------+
```

### 2.2 Header Fields

| Offset (Hex) | Size (Bytes) | Type | Value / Field | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `0x0000`–`0x0003` | 4 | `char[4]` | `b"Sds\x01"` | Magic signature bytes (`0x53, 0x64, 0x73, 0x01`) | `[Established]` |
| `0x0004`–`0x0007` | 4 | `u8[4]` | `00 00 00 00` | Format revision and flags | `[Established]` |
| `0x0008` | 1 | `u8` | `grid_magnification` | Authoring UI grid magnification scalar (`MAG:m`) | `[Established]` |
| `0x0009`..$\text{EOF}-4$ | Variable | Stream | `records[]` | Sequential bytecode geometry stream | `[Established]` |
| $\text{EOF}-4$..$\text{EOF}$ | 4 | `u8[4]` | `FF FF 00 00` | End-of-file sentinel terminator (`0xFFFF, 0x0000`) | `[Established]` |

---

## 3. Data Structures & Opcode Table

The geometry payload from offset `0x0009` to $\text{EOF}-4$ consists of a sequential stream of tagged records. Each record begins with a 1-byte opcode tag identifying the operation.

### 3.1 Opcode Summary Table

| Tag (Hex) | Symbolic Name | Record Size | Operands | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `0x12` | `TAG_VERTEX` | 9 bytes | `id: u16`, `x: i16`, `y: i16`, `z: i16` | Explicit 3D vertex position definition | `[Established]` |
| `0x06` | `TAG_MIDPOINT` | 7 bytes | `dest_id: u16`, `src1_id: u16`, `src2_id: u16` | Computed midpoint vertex between two parent vertices | `[Established]` |
| `0xFFFF` | `TAG_TERMINATOR` | 4 bytes | `FF FF 00 00` | End-of-file stream termination sentinel | `[Established]` |

---

### 3.2 Opcode Definitions (`# [FMT-SIO-RECORDS]`)

#### 1. `TAG_VERTEX` (`0x12`) — Explicit 3D Vertex Definition (9 Bytes)

Declares a single point in 3D model space with an explicit coordinate triplet.

```
[ 0x12 ] [ id: u16 ] [ x: i16 ] [ y: i16 ] [ z: i16 ]
Offset:    +0x00      +0x01..02   +0x03..04   +0x05..06   +0x07..08
```

| Field | Size | Type | Description |
| :--- | :--- | :--- | :--- |
| `tag` | 1 | `u8` | Constant `0x12` |
| `vertex_id` | 2 | `u16` (LE) | Unique 1-based vertex handle index ($1, 2, 3, \dots, N$) |
| `coord_x` | 2 | `i16` (LE) | Signed 16-bit integer $X$ coordinate in local model space |
| `coord_y` | 2 | `i16` (LE) | Signed 16-bit integer $Y$ coordinate in local model space |
| `coord_z` | 2 | `i16` (LE) | Signed 16-bit integer $Z$ coordinate in local model space |

- **Storage Semantics:** Points are registered into the active vertex arena under `vertex_id`. If `vertex_id` already exists, its coordinates are overwritten.

#### 2. `TAG_MIDPOINT` (`0x06`) — Computed Midpoint Vertex (7 Bytes)

Creates a new vertex positioned exactly halfway between two existing parent vertices. This opcode is extensively generated by SLICE when subdividing circles, spheres, Bezier curves, and edge loops.

```
[ 0x06 ] [ dest_id: u16 ] [ src1_id: u16 ] [ src2_id: u16 ]
Offset:    +0x00          +0x01..02       +0x03..04       +0x05..06
```

| Field | Size | Type | Description |
| :--- | :--- | :--- | :--- |
| `tag` | 1 | `u8` | Constant `0x06` |
| `dest_id` | 2 | `u16` (LE) | Unique 1-based handle for the newly constructed midpoint vertex |
| `src1_id` | 2 | `u16` (LE) | Index of the first existing parent vertex |
| `src2_id` | 2 | `u16` (LE) | Index of the second existing parent vertex |

- **Mathematical Evaluation:**
  $$\mathbf{v}_{\text{dest}} = \frac{\mathbf{v}_{\text{src1}} + \mathbf{v}_{\text{src2}}}{2}$$
  $$x_{\text{dest}} = \left\lfloor \frac{x_{\text{src1}} + x_{\text{src2}}}{2} \right\rfloor, \quad y_{\text{dest}} = \left\lfloor \frac{y_{\text{src1}} + y_{\text{src2}}}{2} \right\rfloor, \quad z_{\text{dest}} = \left\lfloor \frac{z_{\text{src1}} + z_{\text{src2}}}{2} \right\rfloor$$
  Using integer arithmetic with rounding towards negative infinity or truncation.

#### 3. Stream Termination Sentinel (`FF FF 00 00`)

The stream concludes when the parser encounters the terminator tag `0xFF` followed by the filler bytes `FF 00 00`, together the four-byte sentinel `FF FF 00 00`. Match this against the vertex and midpoint layouts above: every opcode tag is a single byte, so the `0xFFFF` word reported by earlier notes is the terminator tag plus the first filler byte. [`sio.ksy`](sio.ksy) validates the filler bytes and rejects any other tag value.

---

### 3.3 Reference File Empirical Validation

Validating against test models bundled in `corpus/siarchive/SITools/Slice/`:

| File Name | File Size | Header Check | Vertex Count (`0x12`) | Midpoint Count (`0x06`) | Terminator Check |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `SantaHat.SIO` | 328 bytes | `Sds\x01\0\0\0\0` | 35 | 0 | `FF FF 00 00` Verified |
| `JabbaEyes.SIO` | 589 bytes | `Sds\x01\0\0\0\0` | 64 | 0 | `FF FF 00 00` Verified |
| `JabbaHead.SIO` | 949 bytes | `Sds\x01\0\0\0\0` | 104 | 0 | `FF FF 00 00` Verified |
| `GTXtire.SIO` | 1,165 bytes | `Sds\x01\0\0\0\0` | 128 | 0 | `FF FF 00 00` Verified |
| `Derby2.SIO` | 1,318 bytes | `Sds\x01\0\0\0\0` | 145 | 0 | `FF FF 00 00` Verified |
| `LUKSABER.SIO` | 1,479 bytes | `Sds\x01\0\0\0\0` | 152 | 14 | `FF FF 00 00` Verified |
| `HEAD-S.SIO` | 1,476 bytes | `Sds\x01\0\0\0\0` | 70 | 119 | `FF FF 00 00` Verified |
| `Tube.SIO` | 4,333 bytes | `Sds\x01\0\0\0\0` | 480 | 0 | `FF FF 00 00` Verified |

These counts are produced by [`sio.ksy`](sio.ksy) over the eight corpus models; the earlier table mixed vertex and midpoint totals. Sizes reconcile exactly: `9 + 9·vertices + 7·midpoints + 4 = file size`.

### 3.4 Integer Model Space Scaling

Coordinates in `TAG_VERTEX` records are signed 16-bit integers ($[-32768, 32767]$). When converting `.SIO` models into modern intermediate representation (`Seam 3: SodModelIr`), coordinates are converted to metric floating-point coordinates using a model scale factor $s$:

$$\mathbf{p}_{\text{metric}} = \mathbf{p}_{\text{raw}} \times s$$

Where $s = 0.005\text{ m}$ (standard $1:200$ editor scaling) or derived from the target `.SOD` model header.

---

## 4. Open Questions & Reverse Engineering Backlog

| Item ID | Topic | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- |
| `[BK-SIO-01]` | Polygon Face Definitions in `.SIO` | Determining whether SLICE stored polygon face connectivity opcodes (e.g. quad/tri indices) in extended `.SIO` files or purely emitted point clouds for external polygon assembly in `SD.EXE`. | `[Supported Inference]` |
| `[BK-SIO-02]` | Extended Tag Opcodes | Investigating whether additional opcode tags ($0x01..0x05, 0x07..0x11$) existed for splat zones, rotation groups, or axis mirroring. | `[Bounded Observation]` |
| `[BK-SIO-03]` | Visual Basic 5.0 Serialization Format | Confirming whether Visual Basic's random-access binary file IO (`Put #1, ...`) imposed any hidden record padding on non-standard Windows versions. | `[Established]` |

---

## 5. Attribution & Provenance

The technical specifications for the `.SIO` format are synthesized from the following primary community research and development artifacts:

- **Dave Palmowski (1999–2001):** Author of SLICE ("Stunt isLand Inhouse Custom Editor"), original designer of the `.SIO` bytecode format, and author of the operator's manual (`corpus/siarchive/SITools/Slice/manual.txt`).
- **Dean Newbury & SIFA Community:** Testing and asset preservation of UFO Command Act 2 props, `Tube.SIO`, `LUKSABER.SIO`, and `Derby2.SIO`.
- **StuntReel Teamwork Team (2026):** Reverse engineering of binary opcode tags (`0x12` `TAG_VERTEX`, `0x06` `TAG_MIDPOINT`), verification of the 8-byte magic signature and trailer sentinels across all 8 corpus test models.

---
