# Specification: .MAP / .BIN / .SCN Scenery Tables & Heightmap Format

## 1. Overview & File Identification

The static world environment of *Stunt Island* is defined by a triad of specialized scenery and terrain files: `ANCHORPT.DAT`, `MAP.BIN`, and `SCENERY.scn`. Together with auxiliary `.RES` scenery containers (`SCENERY1.RES` through `SCENERY6.RES`), these files govern the continuous island landmass, mountain elevations, coastal shorelines, ocean water quad, and the hierarchical spatial distribution of every permanent airport runway, building, hangar, and landmark on the island.

- **File Extensions / Formats:**
  - `ANCHORPT.DAT`: Discrete topological heightmap and ground-normal anchor point table.
  - `MAP.BIN`: Continuous polygonal terrain surface patch table.
  - `SCENERY.scn`: Hierarchical Binary Spatial Partitioning (BSP) and Level-of-Detail (LOD) scene graph tree.
- **Typical Container / Storage:** Loose runtime data files located in `SIDATA\` (e.g. `corpus/siarchive/Developer/FreeFlight/SIDATA/` and `corpus/siarchive/Developer/SIRes/SiData/`) or integrated directly into engine executables (`STUNT.EXE`, `PLAYONE.EXE`).
- **Embedded copies in `PLAYONE.EXE`** (`[Established]`, byte comparison of the unpacked load image with `Developer/FreeFlight/SIDATA/`, 2026-10-23):
  - The scene tree is the start of the stack segment (MZ `SS = 0x2286`, image offset `0x22860`). It is `SCENERY.scn` with 16-bit words instead of 32-bit ones, without the file's leading `0` word: all 29,558 words agree, and the 8,979 that differ are pointers 2 lower, because they lack that leading word. Alberto Marnetto's `si-free-flight-2` reads the tree from this segment (see [`corpus/README.md`](../../../corpus/README.md#external-references-not-in-the-corpus)).
  - The anchor table starts at image offset `0x15D44` and holds 231 records. Their `(x, y, z)` match `ANCHORPT.DAT`, except for 5 records whose `y` is `0` in the image and `-32768` in the file. The image's scratch words `f[11]` are all zero, so the file is a runtime dump. Its records 231–1023 are `-32768` fill.
- **Byte Endianness:** Little-endian (standard x86 16-bit real mode).
- **Engine Lifecycle Role:**
  1. *Island Landmass & Terrain Rendering:* `MAP.BIN` references vertex coordinates in `ANCHORPT.DAT` to generate 3D colored polygons representing the island topography, beaches, and hills.
  2. *Ground Collision & Shadow Clamping:* The normal vectors and tap displacement scalars in `ANCHORPT.DAT` provide real-time surface elevation lookups for aircraft ground collision (`SETGND`) and terrain-conforming shadow projection.
  3. *Hierarchical Scene Graph & LOD Culling:* `SCENERY.scn` executes a spatial partition tree that dynamically culls distant objects, calculates camera-relative positions, and swaps LOD model representations based on distance thresholds (`splitdist * 48`).

**Governing invariants:** [`[I1]`](../../../docs/SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization), [`[I2]`](../../../docs/SPEC.md#i2-flat-arena-allocation-no-recursive-pointers), [`[I3]`](../../../docs/SPEC.md#i3-authentic-vga-mode-13h-palette-indexing--flat-shading), [`[I8]`](../../../docs/SPEC.md#i8-dos-83-uppercase-path-normalization). **Contract and code:** [`contracts/shape.rs`](../../../crates/stunt-core/src/contracts/shape.rs) and [`contracts/vfs.rs`](../../../crates/stunt-core/src/contracts/vfs.rs). No synthetic terrain fixture exists yet.

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
| `+0x04`–`+0x0B` | 8 | `i16[4]` (LE) | `a, b, c, d` | Spatial bounding box limits or neighboring patch graph linkages. Field `a` is a record byte offset (always `-1` or `30 × index`); see [`[BK-MAP-03]`](#4-open-questions--reverse-engineering-backlog) | `[Bounded Observation]` |
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
| `SP_1NODE` | `2` | `NODE1_TYPE` | `obj: i32`, `ext: i32`, `splitdist: i32`, `next: u32` | Level-of-detail switch. `PLAYONE.EXE` (image `0x2121`) compares the node's view-space depth with `half + (splitdist - half) × DS:0x22A4 / 0x10000` (`half = ext / 2`; `splitdist` alone when `splitdist < half`). Near: continue to `next/2` without drawing `obj`. Far: draw `obj` (if non-zero) at $\mathbf{cp}$ as a stand-in and end the branch; `next` is not walked ([`lod.md`](../../playone-exe/lod.md) section 1.1). FreeFlight's `simap.cpp` instead returns when `approx_dist >= splitdist × 48` and `obj != 0`, and never draws `obj`; `si-free-flight-2` draws `obj` and also walks `next`. | `[Established]` |
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

If true, geometry exceeding the threshold is culled. This is FreeFlight's reading, not the original's: `PLAYONE.EXE` uses view-space depth and a threshold built from `ext` and `splitdist`, and draws the node's `obj` beyond it (section 3.2, [`lod.md`](../../playone-exe/lod.md) section 1.1).

### 3.4 Coordinate Handedness (`[I1]`)

Per Invariant `[I1]`:
- `ANCHORPT.DAT` vertices $(x, y, z)$ define local coordinates where $+X$ is East, $+Y$ is Elevation, $+Z$ is South, and $-Z$ is North.
- In `simap.cpp`, OpenGL coordinates inverted $X$ and $Y$ during immediate-mode vertex submission:
  $$x_{\text{gl}} = -x_{\text{raw}} \cdot s, \quad y_{\text{gl}} = -y_{\text{raw}} \cdot s, \quad z_{\text{gl}} = z_{\text{raw}} \cdot s$$
- StuntReel normalizes all coordinates to the canonical right-handed metric system ($+X$ Right, $+Y$ Up, $+Z$ Backward, $-Z$ Forward), preserving elevations with positive $Y$.

### 3.5 Empirical Island Terrain Ingestion & Scenery Traversal (`[Established]`)

Runtime analysis in `stuntreel` confirms the static scenery reconstruction pipeline:
1. **Anchor Inversion**: Raw coordinates $(x, y, z)$ from `ANCHORPT.DAT` map to canonical right-handed metric coordinates `[I1]` via:
   $$x_{\text{metric}} = -x_{\text{raw}}, \quad y_{\text{metric}} = -y_{\text{raw}}, \quad z_{\text{metric}} = z_{\text{raw}}$$
   where inverting raw elevation ($y \leftarrow -y$) converts negative raw elevation to positive height above sea level. Points with $y \le -32000$ or $y \ge 32000$ act as boundary sentinels.
2. **Patch Validation**: `MAP.BIN` terrain polygons require `(pos & 0xFF) != 0` and vertex indices within `0..1023` (`ANCHORPT.DAT` range). This produces exactly 166 active terrain surface patches. Those patches carry 584 vertex references in total (94 with three corners, 62 with four, 8 with five, one with six, one with eight), so `MAP.BIN` is a flat polygon list, not a tessellated mesh. The earlier figures $205{,}203$ vertices and $259{,}605$ indices were re-checked on 2026-10-24 against the corpus copy and could not be derived from these records; they are withdrawn.
3. **Prop Resolution**: `SCENERY.scn` traverses $29{,}559$ bytecode words starting at root node `1`, instantiating 6,345 static world props filtered against the companion `.ALL` bundle models.

---

## 4. Open Questions & Reverse Engineering Backlog

| Item ID | Topic | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- |
| `[BK-MAP-01]` | `ANCHORPT` Tap Scalar Array `f[11]` | Precise mathematical unpacking of the 11 short scalars in `ANCHORPT` governing slope gradients, bilinear ground interpolation, and normal reflections. | `[Bounded Observation]` |
| `[BK-MAP-02]` | `SP_HSLOPE` / `SP_VSLOPE` Normal Planes | Complete verification of plane equation parameters $(A, B, C, D)$ extracted from `slope` and `coord` words in slope nodes. | `[Supported Inference]` |
| `[BK-MAP-03]` | `MAP_AREA` Linkage Fields `a, b, c, d` | Field `a` is a byte offset to another record: it is `-1` or a multiple of 30 in every record of the corpus copy, and following it from record 0 visits 119 distinct records in non-sequential order (`0 → 25 → 7 → 68 → …`), which rules out a bounding-box limit. Whether the chain encodes adjacency is open; 50 of its 118 consecutive pairs share two or more anchor indices. `b`, `c`, `d` remain unexplained: `b` is `-1` in 154 records, `c` is 100 in 123 and 0 in 42, `d` is `-1` in 132. | `[Supported Inference]` for `a`; `[Bounded Observation]` for `b`, `c`, `d` |
| `[BK-MAP-04]` | High-Detail Scenery Patching (`si-8x`) | Alberto Marnetto's 8x patch replaces the `mul` by the detail word in the renderer's level-of-detail distance check with `mov dx, ax; shl dx, 3` ([*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island)). In `PLAYONE.EXE` that check is at image `0x212D`, scaled by `DS:0x22A4 = (0x229C × GAME.VAR detail × 2) >> 16` ([`lod.md`](../../playone-exe/lod.md)). Settled 2026-10-23: the check belongs to the `SP_1NODE` handler (type 2 of the jump tables `DS:0x0554` / `DS:0x056C`). `splitdist` enters as `half + (splitdist - half) × 0x22A4 / 0x10000`, and beyond it the node's `obj` is drawn **instead of** the subtree (section 3.2). `world.rs` applies this along the film's camera path, which raised `INTRO.FLM` from 0.6799 to 0.6856 ([`lod.md` section 4.1](../../playone-exe/lod.md)). Still open: the per-shot value of `0x229C` and its exponent `0x229E`. | `[Established]` |
| `[BK-MAP-05]` | `MAP_AREA::num_verts` Outliers | Settled against the original interpreter: `Developer/FreeFlight/src/sisland.cpp` declares `short num_verts; short v[7];` and emits vertices with `for (j = 0; j < num_verts; j++)`, so the word is a vertex count capped at seven slots. Corpus patch 131 reads `8` in all six copies, which makes the engine read past `v[7]` into the next record's `num` word (value `50` in all six corpus copies); patch 22 of `SITools/OBJECTS/Dean/MAP.BIN` reads `2`, a degenerate polygon. Both are malformed geometry data, not a layout difference, so the schema leaves the field unconstrained and `mise run verify-corpus` pins the ten known corpus defects in its baseline. | `[Established]` |
| `[BK-MAP-06]` | Terrain Per-Region Shade | `MAP.BIN` patches draw from flat anchor geometry, but the capture draws the flat colour-195 airfield at palette 196 for 58%, 194 for 24% and 193 for 15% of its pixels, varying *within* one polygon; the anchor `f[]` scalars do not explain it (`f[10]` is 31 on every airfield anchor, and the community `sisland.cpp` ignores `f[]` entirely), so the source is `PLAYONE.EXE`'s renderer ([`attribution.md`](../../parity/attribution.md#3-the-loss-is-structural-edges-not-flat-colour)). | `[Bounded Observation]` |
| `[BK-MAP-07]` | Prop Base Altitude | `SP_POS` adds a `y` term but `SP_POSXZ` does not, so a prop reached only through `SP_POSXZ` nodes sits at whatever `y` its ancestors accumulated, often 0. The shape header's `ground_y_offset` is relative to a ground the tree does not supply. Alberto Marnetto's free-flight remake shows the same gap: bridge roads sink into the water and the islet castle is buried ([*Vibe-exploring Stunt Island*](https://marnetto.net/2026/04/26/vibe-exploring-si), 2026-04-26). Open: how `PLAYONE.EXE` grounds such props, for example by sampling anchor-point terrain at the prop's `(x, z)`. | `[Hypothesis]` |
| `[BK-MAP-08]` | Runtime Sentinel Anchors | Anchors 19, 22, 51, 68 and 71 have `y = 0` in `PLAYONE.EXE`'s embedded table but `y = -32768` in `ANCHORPT.DAT`, which is a runtime dump (section 1); the image's own table already holds 29 other `-32768` anchors, so the sentinel is authored data too. Closed as not land at sea level: drawing patches 52, 62, 64, 65 and 131 at `y = 0` left `CTRY.FLM` flat (0.7733 to 0.7732) and lowered `INTRO.FLM` from 0.6856 to 0.6822, past the 0.003 bound (found 2026-10-23 at `911211a`, [parity log](../../parity/log.md)). `world.rs` keeps dropping them, as `si-free-flight-2` hand-skips 65 and 131. No instruction in the code segment stores the immediate `0x8000` into an anchor record, so the run-time writer of the five sentinels, if any, computes it (open). | `[Bounded Observation]` |

---

## 5. Attribution & Provenance

The technical specifications for the scenery tables and BSP hierarchy are synthesized from the following primary community research and reverse engineering artifacts:

- **FreeFlight & SIRes Projects (2001–2003):** Original source code implementations for terrain loading and BSP evaluation in `simap.cpp`, `simap.h`, and `sisland.cpp` (`corpus/siarchive/Developer/FreeFlight/src/`, `corpus/siarchive/Developer/SIRes/Src/`).
- **Neil Halelamien (2004):** Scenery resource extraction and set coordination research (`corpus/siarchive/Developer/Notes_SETFile/`).
- **Dave Palmowski (1999–2004):** Analysis of scenery container archives and object placement tools (`corpus/siarchive/SITools/`).
- **Doug Armknecht (2000–2002):** Island coordinate conventions and camera tracking research (`corpus/siarchive/Developer/SI_FLM_Format/`).
- **Ángel Eduardo (2004–2005):** Reverse engineering of prop placements, ground clamping (`SETGND`), and model viewing (`corpus/siarchive/Developer/Notes_SIExtractor/Angel_Eduardo_SI_Extractor.txt`).
- **Alberto Marnetto (2024):** The `si-8x` level-of-detail threshold patch, described in [*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island) (2024-11-20); the corpus copy is `corpus/siarchive/Developer/SI-8x/` (notes pointer and patch diff).
- **StuntReel Teamwork Team (2026):** Byte-level layout validation of `ANCHORPT.DAT` (28 bytes), `MAP.BIN` (30 bytes + 2), and `SCENERY.scn` ($29{,}559$ words).

---
