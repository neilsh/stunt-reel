# System Architecture & 1-Hop Routing Table

This document serves as the primary routing table connecting every source module, seam contract, synthetic fixture, technical reference catalog specification, and research note to its governing specification anchor.

---

## 1. 1-Hop Module Routing Table

| Subsystem / Code Path | Seam Contract | Living Spec Anchor | Technical Specification / Research Note | Owning Agent Role |
|---|---|---|---|---|
| `crates/stunt-core/src/contracts/vfs.rs` | Seam 1 (`VfsArchive`) | `docs/SPEC.md#fmt-res-header` | [`research/formats/res.md`](../research/formats/res.md), [`research/formats/all.md`](../research/formats/all.md), [`research/playone-exe/startup.md`](../research/playone-exe/startup.md) | `rust-engine-worker` |
| `crates/stunt-core/src/contracts/trajectory.rs` | Seam 2 (`TrajectoryRecord`) | `docs/SPEC.md#i4-discrete-simulation-ticks` | [`research/formats/flm.md`](../research/formats/flm.md), [`research/playone-exe/memory.md`](../research/playone-exe/memory.md) | `rust-engine-worker` |
| `crates/stunt-core/src/contracts/scene.rs` | Seam 3 (`SodModelIr`) | `docs/SPEC.md#i2-flat-arena-allocation` | [`research/formats/sod.md`](../research/formats/sod.md), [`research/playone-exe/memory.md`](../research/playone-exe/memory.md) | `rust-engine-worker` |
| `crates/stunt-core/src/contracts/parity.rs` | Seam 4 (`VisualParityGate`) | `docs/SPEC.md#i6-visual-parity-acceptance-thresholds` | [`research/formats/concepts/palette-and-shading.md`](../research/formats/concepts/palette-and-shading.md) | `parity-auditor` |
| `crates/stunt-core/src/vfs/` | Seam 1 (`VfsArchive`) | `# [FMT-RES-HEADER]`, `# [FMT-ALL-CHUNKS]` | [`research/formats/res.md`](../research/formats/res.md), [`research/formats/all.md`](../research/formats/all.md) | `rust-engine-worker` |
| `crates/stunt-core/src/sod/` | Seam 3 (`SodModelIr`) | `# [FMT-SOD-OPCODES]`, `# [FMT-SOD-IFVIS]` | [`research/formats/sod.md`](../research/formats/sod.md) | `rust-engine-worker` |
| `crates/stunt-core/src/flm/` | Seam 2 (`TrajectoryRecord`) | `# [FMT-FLM-OPCODES]`, `# [MEM-FLM-TICK]` | [`research/formats/flm.md`](../research/formats/flm.md) | `rust-engine-worker` |
| `python/stunt_reel/tac/harness.py` | Seam 2 (`TrajectoryRecord`) | `docs/SPEC.md#33-modal-navigation` | [`research/playone-exe/navigation.md`](../research/playone-exe/navigation.md) | `re-harness-worker` |
| `python/stunt_reel/tac/memory_map.py` | Seam 2 (`TrajectoryRecord`) | `docs/MEMORY_MAP.md#mem-camera-rig` | [`research/playone-exe/memory.md`](../research/playone-exe/memory.md) | `re-harness-worker` |
| `python/stunt_reel/tac/streamer.py` | Seam 2 (`TrajectoryRecord`) | `docs/MEMORY_MAP.md#mem-flm-tick` | [`research/playone-exe/memory.md`](../research/playone-exe/memory.md) | `re-harness-worker` |
| `python/stunt_reel/gltf/` | Seam 3 (`SodModelIr`), Seam 4 | `docs/SPEC.md#i5-coplanar-decal-resolution` | [`research/formats/sod.md`](../research/formats/sod.md) | `gltf-exporter-worker` |
| `crates/stunt-cli/src/scene.rs` | Seam 3 (`SodModelIr`), Seam 1 | `docs/SPEC.md#37-camera-look-direction--partial-model-fidelity-ctryflm-bounded-observation` | [`research/formats/all.md`](../research/formats/all.md), [`research/formats/sod.md`](../research/formats/sod.md) | `rust-engine-worker` |
| `crates/stunt-cli/src/parity.rs` | Seam 4 (`VisualParityGate`) | `docs/SPEC.md#36-visual-parity-capture-loop-playoneexe-vs-stuntreel` | [`research/formats/concepts/palette-and-shading.md`](../research/formats/concepts/palette-and-shading.md) | `parity-auditor` |
| `python/stunt_reel/tac/framebuffer.py` | Seam 4 (`VisualParityGate`) | `docs/SPEC.md#36-visual-parity-capture-loop-playoneexe-vs-stuntreel` | [`research/playone-exe/capture.md`](../research/playone-exe/capture.md), [`research/playone-exe/memory.md`](../research/playone-exe/memory.md) | `re-harness-worker` |
| `python/scripts/capture_playone_reference.py` | Seam 4 (`VisualParityGate`) | `docs/SPEC.md#36-visual-parity-capture-loop-playoneexe-vs-stuntreel` | [`research/playone-exe/capture.md`](../research/playone-exe/capture.md), [`research/playone-exe/navigation.md`](../research/playone-exe/navigation.md) | `re-harness-worker` |
| `crates/stunt-render/` | Seam 3 (`SodModelIr`), Seam 4 | `docs/SPEC.md#i3-authentic-vga-mode-13h-palette-indexing` | [`research/formats/concepts/palette-and-shading.md`](../research/formats/concepts/palette-and-shading.md) | `rust-engine-worker` |
| `research/formats/` | All Seams | `docs/SPEC.md § 3` | [`research/formats/INDEX.md`](../research/formats/INDEX.md) (Master Catalog) | `worker_fmt_m4_index` |

---

## 2. Technical Reference Catalog & Format Specifications (`research/formats/`)

The reverse-engineering technical catalog documents binary containers, bytecode virtual machines, kinematic choreographies, and terrain subsystems. See [`research/formats/INDEX.md`](../research/formats/INDEX.md) for the Master Format Catalog and Runtime Asset Dependency Graph.

### 2.1 Core Engine Format Specifications
* **Master Format Index**: [`research/formats/INDEX.md`](../research/formats/INDEX.md) — Master catalog table, Mermaid runtime asset dependency graph, compound resource keying `(res_index << 8) | item_index`, and cross-contract mappings.
* **`.RES` Static Resource Container**: [`research/formats/res.md`](../research/formats/res.md) — 8-byte header (`RS`, `res_index`, `item_count`, `ofs[0]`), offset table calculation $N = (\text{ofs}[0] / 4) - 1$, prop name tables vs. scenery archives, and 16-byte DOS descriptors.
* **`.ALL` Full-Scene Movie Container**: [`research/formats/all.md`](../research/formats/all.md) — Chunked scene bundle produced by `MAKEONE.EXE`, parallel `ids: u16[num]` and `offsets: u32[num]` directory layout, 240-color master palette (`0x8042`), 16-color UI sub-palette (`0x801E`), and PCM audio clips (`0xC000`–`0xCFFF`).
* **`.SOD` 3D Model Geometry & Bytecode**: [`research/formats/sod.md`](../research/formats/sod.md) — 10-byte header (`0x000C`), 18-level scale table, 107-opcode dispatch table, 1024 vertex registers, hierarchical transform stack (`pushrelmat`/`poprelmat`), and dynamic visibility branching (`ifvis`, `sorton`).
* **`.FLM` Flight Choreography Timeline**: [`research/formats/flm.md`](../research/formats/flm.md) — `FILM` signature, solved 3-byte slice header (`prev_slice_len: u16`, `tick_duration: u8`), 16-slot entity state machine, director cuts (`cut_from_previous`), and audio cue event dispatch (`0x9C`).

### 2.2 Shared Architectural Concepts
* **Coordinates, Units & Spatial Math**: [`research/formats/concepts/coordinates-and-units.md`](../research/formats/concepts/coordinates-and-units.md) — Invariant `[I1]`, metric right-handed basis ($+X$ Right, $+Y$ Up, $+Z$ Backward), fixed-point 16.16/12.4/8.8 integer math, BAM angles ($0..65535$), vertical $\text{FOV}_y$, and vertex welding.
* **Palettes, Shading Ramps & VGA Colors**: [`research/formats/concepts/palette-and-shading.md`](../research/formats/concepts/palette-and-shading.md) — Invariant `[I3]`, VGA Mode 13h ($320 \times 200$), 18-bit DAC expansion, 32-level composite shading ramps, lighting dot-product quantization, $256 \times 32$ LUT texture sampling with `@interpolate(flat)`, decal resolution `[I5]`, and visual parity `[I6]`.
* **Timeline Mechanics, Ticks & Interpolation**: [`research/formats/concepts/timeline-and-ticks.md`](../research/formats/concepts/timeline-and-ticks.md) — Invariant `[I4]`, discrete simulation clock (20/30 Hz), sub-tick continuous lerp/slerp, instantaneous cut suppression ($\alpha_{\text{eff}} = 0.0$), and audio cue triggers.
* **Compression Architecture & DOS 8.3 Paths**: [`research/formats/concepts/compression.md`](../research/formats/concepts/compression.md) — Invariant `[I8]`, MS-DOS conventional memory limits (640 KB) and 64 KB `DGROUP`, zero-CPU runtime raw streaming in `.RES`/`.ALL`, uppercase DOS 8.3 normalization, and cleanroom isolation `[I7]`.

### 2.3 Auxiliary & World Scenery Formats
* **`.SET` Scenery & World Layout**: [`research/formats/auxiliary/set.md`](../research/formats/auxiliary/set.md) — 96-byte global environment header, time-of-day lighting, 64-byte prop placement records (correcting historical 80-byte typo), and 12-byte scripted event triggers.
* **`.SPR` Sprite Bitmap Format**: [`research/formats/auxiliary/spr.md`](../research/formats/auxiliary/spr.md) — Uncompressed 8-bit billboard rasters ($W \times H + 6\text{ bytes}$), Mode 13h texel sampling, color index 0 transparency, bound to `.SOD` displays.
* **`.SIO` SLICE Authoring Mesh**: [`research/formats/auxiliary/sio.md`](../research/formats/auxiliary/sio.md) — SLICE tool 3D point cloud format (`b"Sds\x01\x00\x00\x00\x00"`), grid scalar, tagged vertex (`0x12`) and midpoint (`0x06`) opcodes, trailer `FF FF 00 00`.
* **`.MAP` / `.BIN` / `.SCN` Terrain Triad**: [`research/formats/auxiliary/map.md`](../research/formats/auxiliary/map.md) — Island terrain subsystem: `ANCHORPT.DAT` (topological heightmap anchor points, $28{,}672$ bytes), `MAP.BIN` (polygonal terrain surface patches, $5{,}372$ bytes), and `SCENERY.scn` (hierarchical BSP spatial partition tree, $118{,}236$ bytes).

---

## 3. Invariant Anchor Directory (`[I1]` – `[I8]`)

* **`[I1]` Metric Right-Handed Coordinate Basis**: Defined in [`docs/SPEC.md#22-mathematical--spatial-invariants`](SPEC.md#22-mathematical--spatial-invariants) and detailed in [`research/formats/concepts/coordinates-and-units.md`](../research/formats/concepts/coordinates-and-units.md). Metric units ($1.0 = 1.0\text{ m}$), $+X$ Right, $+Y$ Up, $+Z$ Backward. Attribute-preserving vertex welding and BAM angle conversions.
* **`[I2]` Flat Arena Allocation**: Defined in [`docs/SPEC.md#23-software-architecture-guardrails`](SPEC.md#23-software-architecture-guardrails) and [`crates/stunt-core/src/contracts/scene.rs`](../crates/stunt-core/src/contracts/scene.rs). Contiguous `Vec<SodNode>` indexed via `NodeId(u32)`; zero `Rc`/`RefCell`/`Arc`.
* **`[I3]` Authentic Mode 13h Palette Indexing**: Defined in [`docs/SPEC.md#23-software-architecture-guardrails`](SPEC.md#23-software-architecture-guardrails) and detailed in [`research/formats/concepts/palette-and-shading.md`](../research/formats/concepts/palette-and-shading.md). 8-bit palette index (`0..=255`) preserved in geometry; $256 \times 32$ palette LUT with `@interpolate(flat)`.
* **`[I4]` Discrete Simulation Ticks & Cut-Aware Sub-Tick Interpolation**: Defined in [`docs/SPEC.md#22-mathematical--spatial-invariants`](SPEC.md#22-mathematical--spatial-invariants) and detailed in [`research/formats/concepts/timeline-and-ticks.md`](../research/formats/concepts/timeline-and-ticks.md). Authored at 20/30 Hz, unlocked presentation. Instantaneous cuts suppress sub-tick lerp/slerp.
* **`[I5]` Coplanar Decal Resolution**: Defined in [`docs/SPEC.md#22-mathematical--spatial-invariants`](SPEC.md#22-mathematical--spatial-invariants) and [`research/formats/sod.md`](../research/formats/sod.md). Geometric normal displacement by $\epsilon = 0.001\text{ m}$ in glTF; hardware depth bias in `wgpu`.
* **`[I6]` Visual Parity Acceptance Thresholds**: Defined in [`docs/SPEC.md#22-mathematical--spatial-invariants`](SPEC.md#22-mathematical--spatial-invariants) and [`crates/stunt-core/src/contracts/parity.rs`](../crates/stunt-core/src/contracts/parity.rs). Aspect-corrected $4:3$ frames ($320 \times 240$); mean $\text{SSIM} \ge 0.88$ for Phase 1 glTF, $\ge 0.90$ for Phase 2 `wgpu`.
* **`[I7]` Cleanroom Asset Isolation**: Defined in [`docs/SPEC.md#23-software-architecture-guardrails`](SPEC.md#23-software-architecture-guardrails) and [`research/formats/concepts/compression.md`](../research/formats/concepts/compression.md). Zero proprietary binary bytes committed; 100% offline tests using cleanroom synthetic fixtures.
* **`[I8]` Uppercase DOS 8.3 Normalization**: Defined in [`docs/SPEC.md#23-software-architecture-guardrails`](SPEC.md#23-software-architecture-guardrails) and [`research/formats/concepts/compression.md`](../research/formats/concepts/compression.md). Case-insensitive lookups via uppercase normalization.

---

## 4. Format Contract Anchors (`# [FMT-*]`)

### # [FMT-RES-HEADER]
* **Target Container**: `.RES` resource archive.
* **Format Specification**: `RS` magic (`0x52, 0x53`), 16-bit version (`0x0001`), directory offset table, null-separated uppercase filename table, raw byte payloads. Detailed in [`research/formats/res.md`](../research/formats/res.md).
* **Evidentiary Tier**: `[Established]` (Verified in `RIPRES.C` and `tests/fixtures/synthetic_minimal.res`).

### # [FMT-ALL-CHUNKS]
* **Target Container**: `.ALL` full-scene movie container.
* **Format Specification**: Chunked block structure ($\approx 64\text{ KB}$ segments) produced by `MAKEONE.EXE`, embedding paired `.FLM` choreography, `.SOD` models, and `.VOC` audio clips. Detailed in [`research/formats/all.md`](../research/formats/all.md).
* **Evidentiary Tier**: `[Supported Inference]`.

### # [FMT-SOD-OPCODES]
* **Target Container**: `.SOD` 3D model geometry.
* **Format Specification**: 16-bit fixed-point vertex stream ($12.4$ / $8.8$), polygon face records, surface normals, palette color indices, and procedural primitives (fans, discs, spheres). Detailed in [`research/formats/sod.md`](../research/formats/sod.md).
* **Evidentiary Tier**: `[Supported Inference]` (Verified in `DECODE.C`).

### # [FMT-SOD-IFVIS]
* **Target Container**: `.SOD` dynamic visibility branching.
* **Format Specification**: Conditional visibility opcodes evaluated per-frame (`Always`, `LodDistanceSq`, `ActorState`, `AngleCone`). Detailed in [`research/formats/sod.md`](../research/formats/sod.md).
* **Evidentiary Tier**: `[Supported Inference]`.

### # [FMT-FLM-OPCODES]
* **Target Container**: `.FLM` choreography timeline stream.
* **Format Specification**: `FILM` magic signature, time-slice header (`prev_slice_len`: u16, `tick_duration`: u8), opcode stream (`0x80` var set, `0x90` view obj, `0x98` credits, `0xFF` end slice), camera channel updates, and audio cues. Detailed in [`research/formats/flm.md`](../research/formats/flm.md).
* **Evidentiary Tier**: `[Established]` (Verified in `tests/fixtures/synthetic_minimal.flm`).

---

## 5. Runtime Memory Anchors (`# [MEM-*]`)

See [`docs/MEMORY_MAP.md`](MEMORY_MAP.md) for full physical linear translation and segment:offset tables:
* **`# [MEM-VSYNC-03DA]`**: VGA status register 1 vertical retrace loop (`in al, 0x03DA`, `test al, 08h`).
* **`# [MEM-FLM-TICK]`**: Internal 16-bit simulation tick counter in `DGROUP`.
* **`# [MEM-CAMERA-RIG]`**: Active camera position, target, vertical FOV zoom scalar, and roll.
* **`# [MEM-ACTOR-TABLE]`**: Active actor transforms, model pointers, bitmasks, and subobject joint angles.
