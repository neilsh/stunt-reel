---
summary: "`SCENERY.scn` ([FMT-MAP-SCENERY]) is `PLAYONE.EXE`'s stack-segment scenery tree widened to 32-bit words; node types `SP_POS` to `SP_POSXZ`, the `SP_1NODE` level-of-detail rule, and prop placement."
---
# Specification: `SCENERY.scn` Scenery Tree

## 1. Overview & File Identification

`SCENERY.scn` is the island's scenery tree: a BSP of partition, level-of-detail, position and leaf nodes that places every permanent prop and carries the ground polygons. It is one of the three tables in a `SIDATA\` directory, beside [`ANCHORPT.DAT`](anchorpt.md) and [`MAP.BIN`](map.md). The renderer walks it in `world.rs` for prop placements.

- **Origin.** The game does not ship this file. `SITools/SD.EXE`, the developers' scenery compiler, writes the tree as assembler source (`\stunt\landscape.asm`) from `MAP.BIN` and `REGIONS.BIN`, and the game assembles it in ([`map.md`](map.md) section 3.2).
- **Copy in `PLAYONE.EXE`** (`[Established]`, byte comparison of the unpacked load image, 2026-10-23). The tree is the start of the stack segment: MZ `SS = 0x2286`, image offset `0x22860`, running to the image's end (29,558 words). Patch #3 `PLAYONE.EXE` holds it too ([`world-scene.md`](../../playone-exe/world-scene.md) section 2), and both `STUNT.EXE` builds hold its ground polygons. Alberto Marnetto's `si-free-flight-2` reads the tree from this segment (see [`corpus/README.md`](../../../corpus/README.md#external-references-not-in-the-corpus)).
- **The file is that copy, widened** (`[Established]`, 2026-11-06). Start with the image from `0x22860` to its end, then:
  1. Zero-extend every 16-bit word to 32 bits.
  2. Add 2 to every non-zero link field that `scene_tree.walk` reads.
  3. Put a `0` word in front.

  The result is FreeFlight's 118,236-byte file exactly. Sign-extending instead leaves 3,654 words wrong. The links are 2 higher only because of that leading word.
- **Corpus copies.** `Developer/FreeFlight/SIDATA/` and `Developer/SIRes/SiData/` hold byte-identical files.

**Governing invariants:** [`[I1]`](../../../docs/SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization), [`[I2]`](../../../docs/SPEC.md#i2-flat-arena-allocation-no-recursive-pointers), [`[I8]`](../../../docs/SPEC.md#i8-dos-83-uppercase-path-normalization). **Contract and code:** [`contracts/shape.rs`](../../../crates/stunt-core/src/contracts/shape.rs), [`world.rs`](../../../crates/stunt-core/src/world.rs) and [`scene_tree.py`](../../../python/stunt_reel/scene_tree.py). No synthetic terrain fixture exists yet.

---

## 2. Header & Memory Layout

### 2.1 File Summary

| Property | Value | Evidentiary Tier |
| :--- | :--- | :--- |
| Size | $118{,}236$ bytes | `[Established]` |
| Words | $29{,}559$ unsigned 32-bit words: a leading `0`, then the image's 29,558 | `[Established]` |
| Links | Byte offsets into the 16-bit tree, plus 2; word index `= link / 2` | `[Established]` |
| Root | Word 1, the image's offset 0 | `[Established]` |

Executable layout: [`scenery.scn.ksy`](scenery.scn.ksy). The schema encodes the 32-bit word array only, because nodes are addressed by word index instead of stored sequentially.

---

## 3. Data Structures & Opcode Table

### 3.1 Node Opcode Table (`# [FMT-MAP-SCENERY]`)

In the node structures, child pointers and continuation indices (`ptr`, `next`) are half-word offsets; divide by 2 to index the 32-bit word array (`ni = next / 2`). FreeFlight starts the walk at word 1 (`simap_render_node(1, &center_pt, &eye_pt)`).

| Opcode Constant | Value | Struct Name | Payload Fields | Execution Semantics | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `SP_POS` | `0` | `POS_TYPE` | `x, y, z: i16`, `next: u32` | Relative 3D spatial translation. Accumulates into camera-relative origin: $\mathbf{cp} \gets \mathbf{cp} + (x, y, z)$. Continues to `next/2`. | `[Established]` |
| `SP_1NODE` | `2` | `NODE1_TYPE` | `obj: i32`, `ext: i32`, `splitdist: i32`, `next: u32` | Level-of-detail switch. `PLAYONE.EXE` (image `0x2121`) compares the node's view-space depth with `half + (splitdist - half) × DS:0x22A4 / 0x10000` (`half = ext / 2`; `splitdist` alone when `splitdist < half`). Near: continue to `next/2` without drawing `obj`. Far: draw `obj` (if non-zero) at $\mathbf{cp}$ as a stand-in and end the branch; `next` is not walked ([`lod.md`](../../playone-exe/lod.md) section 1.1). FreeFlight's `simap.cpp` instead returns when `approx_dist >= splitdist × 48` and `obj != 0`, and never draws `obj`; `si-free-flight-2` draws `obj` and also walks `next`. | `[Established]` |
| `SP_2NODE` | `4` | `NODE2_TYPE` | `ptr: u32`, `next: u32` | Binary partition branch. Recursively evaluates subtree at `ptr/2`, then continues to sibling branch at `next/2`. | `[Established]` |
| `SP_XPLANE` | `6` | `XPLANE_TYPE` | `ptr: u32`, `next: u32`, `sortvalue: i32` | Spatial partition plane perpendicular to the X axis. Traverses front or back subtrees based on camera position. | `[Established]` |
| `SP_ZPLANE` | `8` | `ZPLANE_TYPE` | `ptr: u32`, `next: u32`, `sortvalue: i32` | Spatial partition plane perpendicular to the Z axis. Traverses front or back subtrees based on camera position. | `[Established]` |
| `SP_LEAF` | `10` | `LEAF_TYPE` | `obj: i32` | Object instance leaf. Instantiates `.SOD` geometry `obj` at accumulated position $\mathbf{cp}$. Terminates the current branch (`ni = 0`). | `[Established]` |
| `SP_GROUND` | `12` | `GROUND_TYPE` | `splitdist, ext, x, y, z: i32`, `ptr, next: u32` | Coarse ground patch with bounding sphere and level-of-detail distance. Recurses down `ptr/2` (its finer patches), then continues to `next/2`. Compiled from a `MAP.BIN` record with children; `splitdist` is that record's `c >> 1` ([`map.md`](map.md) section 3.2). | `[Established]` |
| `SP_GLEAF` | `14` | `GLEAF_TYPE` | `next: u32` | Ground leaf. Advances to `next/2`. In `PLAYONE`'s own 16-bit tree the leaf also carries a plane and its polygon inline (colour, count, anchor pointers `28 × index`); see [`world-scene.md`](../../playone-exe/world-scene.md) section 2. | `[Established]` |
| `SP_HSLOPE` | `16` | `HSLOPE_TYPE` | `ptr: u32`, `next: u32`, `slope: i32`, `coord: i32` | Sloped cutting plane (horizontal slope gradient). The 33 in the tree are the type-16 nodes of `REGIONS.BIN` ([`map.md`](map.md) section 2.4). | `[Established]` |
| `SP_VSLOPE` | `18` | `VSLOPE_TYPE` | `ptr: u32`, `next: u32`, `slope: i32`, `coord: i32` | Sloped cutting plane (vertical slope gradient). The 20 in the tree are the type-18 nodes of `REGIONS.BIN`. | `[Established]` |
| `SP_LIST` | `20` | `LIST_TYPE` | `child_nodes[]: u32` | Array of child node indices terminated by `0`. Iteratively evaluates each child `node_idx / 2` with accumulated $\mathbf{cp}$. | `[Established]` |
| `SP_POSXZ` | `22` | `POSXZ_TYPE` | `x, z: i16`, `next: u32` | 2D horizontal relative translation ($Y$ unchanged). Accumulates $x, z$ into $\mathbf{cp}$ and advances to `next/2`. | `[Established]` |

### 3.2 Fast Approximate Distance Algorithm

FreeFlight culls `SP_1NODE` and `SP_GROUND` with an integer distance that avoids square roots and overestimates by at most $\frac{9}{8}$ plus one bit:

$$\Delta x = |x_2 - x_1|, \quad \Delta y = |y_2 - y_1|$$

$$\text{approx\_dist}(x_1, y_1, x_2, y_2) = \Delta x + \Delta y - \frac{\min(\Delta x, \Delta y)}{2}$$

$$\text{approx\_dist}(\mathbf{cp}_x, -\mathbf{cp}_z, \mathbf{eye}_x, \mathbf{eye}_z) \ge \text{splitdist} \times 48$$

This is FreeFlight's reading, not the original's: `PLAYONE.EXE` uses view-space depth and a threshold built from `ext` and `splitdist`, and draws the node's `obj` beyond it (section 3.1, [`lod.md`](../../playone-exe/lod.md) section 1.1).

### 3.3 Prop Resolution in `stuntreel`

`world.rs` walks the 29,559 words from word 1 and places 6,345 static props, keeping those whose shapes the film's `.ALL` bundle carries (`[Established]`).

---

## 4. Open Questions & Analysis Backlog

| Item ID | Topic | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- |
| `[BK-MAP-02]` | `SP_HSLOPE` / `SP_VSLOPE` planes | Complete verification of plane equation parameters $(A, B, C, D)$ extracted from `slope` and `coord` words in slope nodes. `REGIONS.BIN` stores the same two words per node ([`map.md`](map.md) section 2.4). | `[Supported Inference]` |
| `[BK-MAP-04]` | High-detail scenery patching (`si-8x`) | Alberto Marnetto's 8x patch replaces the `mul` by the detail word in the level-of-detail check with `mov dx, ax; shl dx, 3` ([*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island)). In `PLAYONE.EXE` that check is at image `0x212D` in the `SP_1NODE` handler (type 2 of the jump tables `DS:0x0554` / `DS:0x056C`), scaled by `DS:0x22A4 = (0x229C × GAME.VAR detail × 2) >> 16` ([`lod.md`](../../playone-exe/lod.md)). `world.rs` applies it along the film's camera path, which raised `INTRO.FLM` from 0.6799 to 0.6856 ([`lod.md` section 4.1](../../playone-exe/lod.md)). Still open: the per-shot value of `0x229C` and its exponent `0x229E`. | `[Established]` |
| `[BK-MAP-07]` | Prop base altitude | `SP_POS` adds a `y` term but `SP_POSXZ` does not, so a prop reached only through `SP_POSXZ` nodes sits at whatever `y` its ancestors accumulated, often 0. The shape header's `ground_y_offset` is relative to a ground the tree does not supply. Alberto Marnetto's free-flight remake shows the same gap: bridge roads sink into the water and the islet castle is buried ([*Vibe-exploring Stunt Island*](https://marnetto.net/2026/04/26/vibe-exploring-si), 2026-04-26). Open: how `PLAYONE.EXE` grounds such props, for example by sampling anchor-point terrain at the prop's `(x, z)`. | `[Hypothesis]` |

### 4.1 Ruled out

- **`SCENERY.scn` made from `SITools/SCENERY.BIN` or `SQUISHED.BIN`** (2026-11-06): none of 200 probes of 32 bytes each, taken from the tree in 16-bit or 32-bit form, occurs in either file.
- **Signed words** (section 1): sign-extending the image's words leaves 3,654 of them different from the file.

### 4.2 Open questions

1. **How `PLAYONE` grounds props reached only through `SP_POSXZ`** (`[BK-MAP-07]`).
2. **The per-shot detail scale `0x229C`** (`[BK-MAP-04]`).

---

## 5. Attribution & Provenance

- **Chris Phillips (2000–2003):** FreeFlight and SIRes, whose `simap.cpp` first walked the tree and whose `SIDATA` directories carry the file (`corpus/siarchive/Developer/FreeFlight/`, `corpus/siarchive/Developer/SIRes/`).
- **Alberto Marnetto (2024–2026):** the `si-8x` level-of-detail patch ([*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island); corpus copy `corpus/siarchive/Developer/SI-8x/`) and `si-free-flight-2`, which reads the tree from `PLAYONE`'s stack segment.
- **Ángel Eduardo (2004–2005):** prop placement and ground clamping (`SETGND`) notes (`corpus/siarchive/Developer/Notes_SIExtractor/Angel_Eduardo_SI_Extractor.txt`).
- **Stunt Reel contributors (2026):** the byte-exact rebuild from `PLAYONE.EXE`, and the node handlers in the image.
