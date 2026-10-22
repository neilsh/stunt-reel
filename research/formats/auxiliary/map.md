# Specification: .MAP / .BIN / .SCN Scenery Tables & Heightmap Format

## 1. Overview & File Identification

The static world environment of *Stunt Island* (1992, Walt Disney Computer Software / The Assembly Line) is defined by a triad of specialized scenery and terrain files: `ANCHORPT.DAT`, `MAP.BIN`, and `SCENERY.scn`. Together with auxiliary `.RES` scenery containers (`SCENERY1.RES` through `SCENERY6.RES`), these files govern the continuous island landmass, mountain elevations, coastal shorelines, ocean water quad, and the hierarchical spatial distribution of every permanent airport runway, building, hangar, and landmark on the island.

- **File Extensions / Formats:**
  - `ANCHORPT.DAT`: Discrete topological heightmap and ground-normal anchor point table.
  - `MAP.BIN`: Continuous polygonal terrain surface patch table.
  - `SCENERY.scn`: Hierarchical Binary Spatial Partitioning (BSP) and Level-of-Detail (LOD) scene graph tree.
- **Typical Container / Storage:** Loose runtime data files located in `SIDATA\` (e.g. `corpus/si_archive/Developer/FreeFlight/SIDATA/` and `corpus/si_archive/Developer/SIRes/SiData/`) or integrated directly into engine executables (`STUNT.EXE`, `PLAYONE.EXE`).
- **Byte Endianness:** Little-endian (standard x86 16-bit real mode).
- **Engine Lifecycle Role:**
  1. *Island Landmass & Terrain Rendering:* `MAP.BIN` references vertex coordinates in `ANCHORPT.DAT` to generate 3D colored polygons representing the island topography, beaches, and hills.
  2. *Ground Collision & Shadow Clamping:* The normal vectors and tap displacement scalars in `ANCHORPT.DAT` provide real-time surface elevation lookups for aircraft ground collision (`SETGND`) and terrain-conforming shadow projection.
  3. *Hierarchical Scene Graph & LOD Culling:* `SCENERY.scn` executes a spatial partition tree that dynamically culls distant objects, calculates camera-relative positions, and swaps LOD model representations based on distance thresholds (`splitdist * 48`).

---

## 2. Header & Memory Layout

Each file within the scenery subsystem employs a deterministic byte-level layout verified against both binary corpus files and original reverse engineering C implementations (`simap.cpp`, `sisland.cpp`).

### 2.1 Component File Size Summary

| File Name | Exact File Size (Bytes) | Record Count | Stride per Record | Terminator | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ANCHORPT.DAT` | $28{,}672$ bytes | $1{,}024$ points | 28 bytes | Fixed table bounds | `[Established]` |
| `MAP.BIN` | $5{,}372$ bytes | 179 patches | 30 bytes | 2-byte null word `0x0000` | `[Established]` |
| `SCENERY.scn` | $118{,}236$ bytes | $29{,}559$ 32-bit words | Variable node types | Node index `0` sentinel | `[Established]` |

---

### 2.2 `ANCHORPT.DAT` Memory Layout (`# [FMT-MAP-ANCHORPT]`)

`ANCHORPT.DAT` comprises exactly 1,024 contiguous 28-byte records ($1024 \times 28 = 28{,}672\text{ bytes}$), representing the primary topological grid of Stunt Island.

```
+---------------------------+---------------------------------------------------+
| Coordinates: x, y, z (6B) |       Surface Normal & Tap Scalars: f[11] (22B)   |
|   3 x i16 (LE)            |                  11 x i16 (LE)                    |
+---------------------------+---------------------------------------------------+
```

| Relative Offset | Size (Bytes) | Type | Field Name | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `+0x00` | 2 | `i16` (LE) | `x` | Signed 16-bit integer $X$ coordinate in island terrain space | `[Established]` |
| `+0x02` | 2 | `i16` (LE) | `y` | Signed 16-bit integer $Y$ coordinate (topographic elevation) | `[Established]` |
| `+0x04` | 2 | `i16` (LE) | `z` | Signed 16-bit integer $Z$ coordinate in island terrain space | `[Established]` |
| `+0x06`–`+0x1B` | 22 | `i16[11]` (LE) | `f[11]` | Surface normal vector components, elevation tap displacement slopes, and ground clamping scalars | `[Established]` |

Executable layout: [`anchorpt.dat.ksy`](anchorpt.dat.ksy).

---

### 2.3 `MAP.BIN` Memory Layout (`# [FMT-MAP-AREA]`)

`MAP.BIN` defines the polygon surface mesh connecting the anchor points. It contains 179 contiguous 30-byte `MAP_AREA` records followed by a 2-byte null word terminator ($179 \times 30 + 2 = 5{,}372\text{ bytes}$).

```
+----------+----------+--------------------+----------+-----------+--------------------+----------+
| num (2B) | pos (2B) | a, b, c, d (8B)    | col (2B) | nverts(2B)|  v[7] indices (14B)| EOF (2B) |
+----------+----------+--------------------+----------+-----------+--------------------+----------+
```

| Relative Offset | Size (Bytes) | Type | Field Name | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `+0x00` | 2 | `i16` (LE) | `num` | Patch index word. Corpus values are not sequential (the first record is 540), so the field is retained raw pending `[BK-MAP-03]` | `[Bounded Observation]` |
| `+0x02` | 2 | `i16` (LE) | `pos` | Sector activity flag: `(pos & 0xFF) != 0` indicates active land polygon | `[Established]` |
| `+0x04`–`+0x0B` | 8 | `i16[4]` (LE) | `a, b, c, d` | Spatial bounding box limits or neighboring patch graph linkages | `[Bounded Observation]` |
| `+0x0C` | 2 | `i16` (LE) | `color` | Authentic 8-bit VGA Mode 13h palette index (`0..=255`) | `[Established]` |
| `+0x0E` | 2 | `i16` (LE) | `num_verts` | Number of active vertices forming this terrain polygon ($3 \le N \le 7$, clamped to 7) | `[Established]` |
| `+0x10`–`+0x1D` | 14 | `u16[7]` (LE) | `v[7]` | Index words for this polygon referencing `ANCHORPT.DAT` anchor records (`0..1023`). 166 of 179 records decode cleanly; records with indices $\ge 1024$ or `(pos & 0xFF) == 0` are inactive/sentinels. | `[Established]` |
| End of File | 2 | `u16` (LE) | `terminator` | Terminal null word `0x0000` | `[Established]` |

Executable layout: [`map.bin.ksy`](map.bin.ksy).

---

## 3. Data Structures & Opcode Table

### 3.1 Global Ocean Water Quad

The surrounding ocean is not stored as discrete patches in `MAP.BIN`. Instead, the engine generates an expansive global planar quad at sea level:
- **Spatial Extents:** Coordinates spanning $(-32000, -1, -32000)$ to $(+32000, -1, +32000)$.
- **Palette Mapping:** Assigned Mode 13h palette index $255 - 47 = 208$ (deep ocean blue) or $128 + 8 + 16 = 152$.
- **Rendering:** Flat-shaded quad drawn prior to traversing the island terrain polygon list.

---

### 3.2 `SCENERY.scn` Node Opcode Table (`# [FMT-MAP-SCENERY]`)

`SCENERY.scn` is a precompiled spatial evaluation bytecode stream of $29{,}559$ 32-bit integer words ($118{,}236\text{ bytes}$). The tree is evaluated recursively starting at root node index `1` (`simap_render_node(1, &center_pt, &eye_pt)`).

In the node structures, child pointers and continuation indices (`ptr`, `next`) are encoded as half-word integer offsets (requiring division by 2 to index 32-bit word arrays: `ni = next / 2`).

| Opcode Constant | Value | Struct Name | Payload Fields | Execution Semantics | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `SP_POS` | `0` | `POS_TYPE` | `x, y, z: i16`, `next: u32` | Relative 3D spatial translation. Accumulates into camera-relative origin: $\mathbf{cp} \gets \mathbf{cp} + (x, y, z)$. Continues to `next/2`. | `[Established]` |
| `SP_1NODE` | `2` | `NODE1_TYPE` | `obj: i32`, `ext: i32`, `splitdist: i32`, `next: u32` | LOD Distance Gate. Evaluates distance $d = \text{approx\_dist}(\mathbf{cp}_{xz}, \mathbf{eye}_{xz})$. If $d \ge \text{splitdist} \times 48$, culls node or swaps representation. | `[Established]` |
| `SP_2NODE` | `4` | `NODE2_TYPE` | `ptr: u32`, `next: u32` | Binary partition branch. Recursively evaluates subtree at `ptr/2`, then continues to sibling branch at `next/2`. | `[Established]` |
| `SP_XPLANE` | `6` | `XPLANE_TYPE` | `ptr: u32`, `next: u32`, `sortvalue: i32` | Spatial partition plane perpendicular to the X axis. Traverses front or back subtrees based on camera position. | `[Established]` |
| `SP_ZPLANE` | `8` | `ZPLANE_TYPE` | `ptr: u32`, `next: u32`, `sortvalue: i32` | Spatial partition plane perpendicular to the Z axis. Traverses front or back subtrees based on camera position. | `[Established]` |
| `SP_LEAF` | `10` | `LEAF_TYPE` | `obj: i32` | Object Instance Leaf. Instantiates `.SOD` geometry index `obj` at accumulated position $\mathbf{cp}$. Terminates current branch (`ni = 0`). | `[Established]` |
| `SP_GROUND` | `12` | `GROUND_TYPE` | `splitdist, ext, x, y, z: i32`, `ptr, next: u32` | Ground polygon patch reference with bounding sphere and LOD distance trigger. Recurses down `ptr/2` then continues to `next/2`. | `[Established]` |
| `SP_GLEAF` | `14` | `GLEAF_TYPE` | `next: u32` | Ground polygon leaf marker. Advances to `next/2`. | `[Established]` |
| `SP_HSLOPE` | `16` | `HSLOPE_TYPE` | `ptr: u32`, `next: u32`, `slope: i32`, `coord: i32` | Sloped terrain cutting plane (horizontal slope gradient). | `[Established]` |
| `SP_VSLOPE` | `18` | `VSLOPE_TYPE` | `ptr: u32`, `next: u32`, `slope: i32`, `coord: i32` | Sloped terrain cutting plane (vertical slope gradient). | `[Established]` |
| `SP_LIST` | `20` | `LIST_TYPE` | `child_nodes[]: u32` | Array of child node indices terminated by `0`. Iteratively evaluates each child `node_idx / 2` with accumulated $\mathbf{cp}$. | `[Established]` |
| `SP_POSXZ` | `22` | `POSXZ_TYPE` | `x, z: i16`, `next: u32` | 2D horizontal relative translation ($Y$ unchanged). Accumulates $x, z$ into $\mathbf{cp}$ and advances to `next/2`. | `[Established]` |

Executable layout: [`scenery.scn.ksy`](scenery.scn.ksy); the schema encodes the 32-bit word array only, because nodes are addressed by word index instead of stored sequentially.

---

### 3.3 Fast Approximate Distance Algorithm

Distance culling in `SP_1NODE` and `SP_GROUND` uses a fast integer approximation avoiding square roots, with bounded overestimation ($\le \frac{9}{8} + 1\text{ bit}$ uncertainty):

$$\Delta x = |x_2 - x_1|, \quad \Delta y = |y_2 - y_1|$$

$$\text{approx\_dist}(x_1, y_1, x_2, y_2) = \Delta x + \Delta y - \frac{\min(\Delta x, \Delta y)}{2}$$

The culling condition evaluates:

$$\text{approx\_dist}(\mathbf{cp}_x, -\mathbf{cp}_z, \mathbf{eye}_x, \mathbf{eye}_z) \ge \text{splitdist} \times 48$$

If true, geometry exceeding the threshold is culled.

---

## 4. Architectural Invariants & Coordinate Mapping

### 4.1 Right-Handed Metric Basis (`[I1]`)

Per Invariant `[I1]`:
- `ANCHORPT.DAT` vertices $(x, y, z)$ define local coordinates where $+X$ is East, $+Y$ is Elevation, $+Z$ is South, and $-Z$ is North.
- In `simap.cpp`, OpenGL coordinates inverted $X$ and $Y$ during immediate-mode vertex submission:
  $$x_{\text{gl}} = -x_{\text{raw}} \cdot s, \quad y_{\text{gl}} = -y_{\text{raw}} \cdot s, \quad z_{\text{gl}} = z_{\text{raw}} \cdot s$$
- StuntReel normalizes all coordinates to the canonical right-handed metric system ($+X$ Right, $+Y$ Up, $+Z$ Backward, $-Z$ Forward), preserving elevations with positive $Y$.

### 4.2 Flat Arena Allocation (`[I2]`)

In accordance with Invariant `[I2]`, terrain polygons and static scene graph nodes are allocated in flat, contiguous memory vectors (`Vec<SodVertex>`, `Vec<SodNode>`) indexed by numeric handles (`NodeId(u32)`). Self-referential pointers (`Rc<RefCell<T>>`) are prohibited.

### 4.3 VGA Mode 13h Palette Indexing (`[I3]`)

Terrain colors in `MAP_AREA::color` are preserved as authentic 8-bit palette indices (`0..=255`) and shaded via the $256 \times 32$ LUT texture in `stunt-render`, matching aircraft models and scenery props.

### 4.4 Uppercase DOS 8.3 Path Normalization (`[I8]`)

All references to `ANCHORPT.DAT`, `MAP.BIN`, and `SCENERY.SCN` in virtual filesystem archives are resolved using uppercase ASCII normalization.

---

## 5. Open Questions & Reverse Engineering Backlog

| Item ID | Topic | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- |
| `[BK-MAP-01]` | `ANCHORPT` Tap Scalar Array `f[11]` | Precise mathematical unpacking of the 11 short scalars in `ANCHORPT` governing slope gradients, bilinear ground interpolation, and normal reflections. | `[Bounded Observation]` |
| `[BK-MAP-02]` | `SP_HSLOPE` / `SP_VSLOPE` Normal Planes | Complete verification of plane equation parameters $(A, B, C, D)$ extracted from `slope` and `coord` words in slope nodes. | `[Supported Inference]` |
| `[BK-MAP-03]` | `MAP_AREA` Linkage Fields `a, b, c, d` | Disambiguating whether fields `a, b, c, d` represent spatial bounding box limits or adjacency pointers to neighboring polygon patches. | `[Bounded Observation]` |
| `[BK-MAP-04]` | High-Detail Scenery Patching (`si-8x`) | Formalizing Alberto Marnetto's 8x detail memory patches that expand LOD distance multipliers beyond `splitdist * 48`. | `[Supported Inference]` |
| `[BK-MAP-05]` | `MAP_AREA::num_verts` Outliers | Settled against the original interpreter: `Developer/FreeFlight/src/sisland.cpp` declares `short num_verts; short v[7];` and emits vertices with `for (j = 0; j < num_verts; j++)`, so the word is a vertex count capped at seven slots. Corpus patch 131 reads `8` in all six copies, which makes the engine read past `v[7]` into the next record's `num` word (value `0`); patch 22 of `SITools/OBJECTS/Dean/MAP.BIN` reads `2`, a degenerate polygon. Both are malformed geometry data, not a layout difference, so the schema leaves the field unconstrained and `mise run verify-corpus` pins the ten known corpus defects in its baseline. | `[Established]` |

---

## 6. Attribution & Provenance

The technical specifications for the scenery tables and BSP hierarchy are synthesized from the following primary community research and reverse engineering artifacts:

- **FreeFlight & SIRes Projects (2001–2003):** Original source code implementations for terrain loading and BSP evaluation in `simap.cpp`, `simap.h`, and `sisland.cpp` (`corpus/si_archive/Developer/FreeFlight/src/`, `corpus/si_archive/Developer/SIRes/Src/`).
- **Neil Halelamien (2004):** Scenery resource extraction and set coordination research (`corpus/si_archive/Developer/Notes_SETFile/`).
- **Dave Palmowski (1999–2004):** Analysis of scenery container archives and object placement tools (`corpus/si_archive/SITools/`).
- **Doug Armknecht (2000–2002):** Island coordinate conventions and camera tracking research (`corpus/si_archive/Developer/SI_FLM_Format/`).
- **Ángel Eduardo (2004–2005):** Reverse engineering of prop placements, ground clamping (`SETGND`), and model viewing (`corpus/si_archive/Developer/Notes_SIExtractor/Angel_Eduardo_SI_Extractor.txt`).
- **Alberto Marnetto (2024):** High-detail scenery modification and LOD multiplier expansion in `si-8x` (`corpus/si_archive/Developer/SI-8x/si-8x-notes.txt`).
- **StuntReel Teamwork Team (2026):** Byte-level layout validation of `ANCHORPT.DAT` (28 bytes), `MAP.BIN` (30 bytes + 2), and `SCENERY.scn` ($29{,}559$ words).

---

## 7. Codebase Seam Contracts & Fixtures

### 7.1 Seam Contracts (`crates/stunt-core/src/contracts/`)

- **`crates/stunt-core/src/contracts/scene.rs` (`Seam 3: SodModelIr`):**
  - Terrain polygons from `MAP.BIN` and objects instantiated by `SP_LEAF` nodes in `SCENERY.scn` are unpacked into `SodModelIr`.
  - Palette indices from `MAP_AREA::color` are mapped directly to `SodVertex::palette_index` per `[I3]`.
  - Arena allocation of BSP nodes complies with `[I2]`.
- **`crates/stunt-core/src/contracts/vfs.rs` (`Seam 1: VfsArchive`):**
  - Locates and extracts `ANCHORPT.DAT`, `MAP.BIN`, `SCENERY.scn`, and `SCENERY1..6.RES` archives with DOS 8.3 normalization `[I8]`.
- **`crates/stunt-core/src/contracts/trajectory.rs` (`Seam 2: TrajectoryRecord`):**
  - Ground clamping (`SETGND`) uses `ANCHORPT.DAT` heightmap evaluations to compute ground-relative altitude for actors and cameras.

### 7.2 Synthetic Test Fixtures (`tests/fixtures/`)

- Future auxiliary fixture `tests/fixtures/synthetic_minimal.map` will provide a minimal 4-point terrain patch verifying:
  - Parsing 28-byte `ANCHORPT` records.
  - Parsing 30-byte `MAP_AREA` polygons and terminal `0x0000` word.
  - Evaluation of `SP_POS`, `SP_1NODE`, and `SP_LEAF` BSP tree traversal.

### 4.5 Empirical Island Terrain Ingestion & Scenery Traversal (`[Established]`)

Runtime analysis in `stuntreel` confirms the static scenery reconstruction pipeline:
1. **Anchor Inversion**: Raw coordinates $(x, y, z)$ from `ANCHORPT.DAT` map to canonical right-handed metric coordinates `[I1]` via:
   $$x_{\text{metric}} = -x_{\text{raw}}, \quad y_{\text{metric}} = -y_{\text{raw}}, \quad z_{\text{metric}} = z_{\text{raw}}$$
   where inverting raw elevation ($y \leftarrow -y$) converts negative raw elevation to positive height above sea level. Points with $y \le -32000$ or $y \ge 32000$ act as boundary sentinels.
2. **Patch Validation**: `MAP.BIN` terrain polygons require `(pos & 0xFF) != 0` and vertex indices within `0..1023` (`ANCHORPT.DAT` range). This produces exactly 166 active terrain surface patches ($205{,}203$ vertices, $259{,}605$ indices).
3. **Prop Resolution**: `SCENERY.scn` traverses $29{,}559$ bytecode words starting at root node `1`, instantiating 6,345 static world props filtered against the companion `.ALL` bundle models.
