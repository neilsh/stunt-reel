# System Architecture & 1-Hop Routing Table

This document serves as the primary routing table connecting every source module, seam contract, synthetic fixture, and research note to its governing specification anchor.

---

## 1. 1-Hop Module Routing Table

| Subsystem / Code Path | Seam Contract | Living Spec Anchor | Primary Research Note | Owning Agent Role |
|---|---|---|---|---|
| `crates/stunt-core/src/contracts/vfs.rs` | Seam 1 (`VfsArchive`) | `docs/SPEC.md#fmt-res-header` | [`research/playone-exe/startup.md`](../research/playone-exe/startup.md) | `rust-engine-worker` |
| `crates/stunt-core/src/contracts/trajectory.rs` | Seam 2 (`TrajectoryRecord`) | `docs/SPEC.md#i4-discrete-simulation-ticks` | [`research/playone-exe/memory.md`](../research/playone-exe/memory.md) | `rust-engine-worker` |
| `crates/stunt-core/src/contracts/scene.rs` | Seam 3 (`SodModelIr`) | `docs/SPEC.md#i2-flat-arena-allocation` | [`research/playone-exe/memory.md`](../research/playone-exe/memory.md) | `rust-engine-worker` |
| `crates/stunt-core/src/contracts/parity.rs` | Seam 4 (`VisualParityGate`) | `docs/SPEC.md#i6-visual-parity-acceptance-thresholds` | N/A | `parity-auditor` |
| `python/stunt_reel/tac/harness.py` | Seam 2 (`TrajectoryRecord`) | `docs/SPEC.md#33-modal-navigation` | [`research/playone-exe/navigation.md`](../research/playone-exe/navigation.md) | `re-harness-worker` |
| `python/stunt_reel/tac/memory_map.py` | Seam 2 (`TrajectoryRecord`) | `docs/MEMORY_MAP.md#mem-camera-rig` | [`research/playone-exe/memory.md`](../research/playone-exe/memory.md) | `re-harness-worker` |
| `python/stunt_reel/tac/streamer.py` | Seam 2 (`TrajectoryRecord`) | `docs/MEMORY_MAP.md#mem-flm-tick` | [`research/playone-exe/memory.md`](../research/playone-exe/memory.md) | `re-harness-worker` |
| `python/stunt_reel/gltf/` | Seam 3 (`SodModelIr`), Seam 4 | `docs/SPEC.md#i5-coplanar-decal-resolution` | N/A | `gltf-exporter-worker` |
| `crates/stunt-render/` | Seam 3 (`SodModelIr`), Seam 4 | `docs/SPEC.md#i3-authentic-vga-mode-13h-palette-indexing` | N/A | `rust-engine-worker` |

---

## 2. Invariant Anchor Directory (`[I1]` – `[I8]`)

* **`[I1]` Metric Right-Handed Coordinate Basis**: Defined in [`docs/SPEC.md#22-mathematical--spatial-invariants`](SPEC.md#22-mathematical--spatial-invariants). Metric units ($1.0 = 1.0\text{ m}$), $+X$ Right, $+Y$ Up, $+Z$ Backward. Attribute-preserving vertex welding and BAM angle conversions.
* **`[I2]` Flat Arena Allocation**: Defined in [`docs/SPEC.md#23-software-architecture-guardrails`](SPEC.md#23-software-architecture-guardrails). Contiguous `Vec<SodNode>` indexed via `NodeId(u32)`; zero `Rc`/`RefCell`/`Arc`.
* **`[I3]` Authentic Mode 13h Palette Indexing**: Defined in [`docs/SPEC.md#23-software-architecture-guardrails`](SPEC.md#23-software-architecture-guardrails). 8-bit palette index (`0..=255`) preserved in geometry; $256 \times 32$ palette LUT with `@interpolate(flat)`.
* **`[I4]` Discrete Simulation Ticks & Cut-Aware Sub-Tick Interpolation**: Defined in [`docs/SPEC.md#22-mathematical--spatial-invariants`](SPEC.md#22-mathematical--spatial-invariants). Authored at 20/30 Hz, unlocked presentation. Instantaneous cuts suppress sub-tick lerp/slerp.
* **`[I5]` Coplanar Decal Resolution**: Defined in [`docs/SPEC.md#22-mathematical--spatial-invariants`](SPEC.md#22-mathematical--spatial-invariants). Geometric normal displacement by $\epsilon = 0.001\text{ m}$ in glTF; hardware depth bias in `wgpu`.
* **`[I6]` Visual Parity Acceptance Thresholds**: Defined in [`docs/SPEC.md#22-mathematical--spatial-invariants`](SPEC.md#22-mathematical--spatial-invariants). Aspect-corrected $4:3$ frames ($320 \times 240$); mean $\text{SSIM} \ge 0.88$ for Phase 1 glTF, $\ge 0.90$ for Phase 2 `wgpu`.
* **`[I7]` Cleanroom Asset Isolation**: Defined in [`docs/SPEC.md#23-software-architecture-guardrails`](SPEC.md#23-software-architecture-guardrails). Zero proprietary binary bytes committed; 100% offline tests using cleanroom synthetic fixtures.
* **`[I8]` Uppercase DOS 8.3 Normalization**: Defined in [`docs/SPEC.md#23-software-architecture-guardrails`](SPEC.md#23-software-architecture-guardrails). Case-insensitive lookups via uppercase normalization.

---

## 3. Format Contract Anchors (`# [FMT-*]`)

### # [FMT-RES-HEADER]
* **Target Container**: `.RES` resource archive.
* **Format Specification**: `RS` magic (`0x52, 0x53`), 16-bit version (`0x0001`), directory offset table, null-separated uppercase filename table, raw byte payloads.
* **Evidentiary Tier**: `[Established]` (Verified in `RIPRES.C` and `tests/fixtures/synthetic_minimal.res`).

### # [FMT-ALL-CHUNKS]
* **Target Container**: `.ALL` full-scene movie container.
* **Format Specification**: Chunked block structure ($\approx 64\text{ KB}$ segments) produced by `MAKEONE.EXE`, embedding paired `.FLM` choreography, `.SOD` models, and `.VOC` audio clips.
* **Evidentiary Tier**: `[Supported Inference]`.

### # [FMT-SOD-OPCODES]
* **Target Container**: `.SOD` 3D model geometry.
* **Format Specification**: 16-bit fixed-point vertex stream ($12.4$ / $8.8$), polygon face records, surface normals, palette color indices, and procedural primitives (fans, discs, spheres).
* **Evidentiary Tier**: `[Supported Inference]` (Verified in `DECODE.C`).

### # [FMT-SOD-IFVIS]
* **Target Container**: `.SOD` dynamic visibility branching.
* **Format Specification**: Conditional visibility opcodes evaluated per-frame (`Always`, `LodDistanceSq`, `ActorState`, `AngleCone`).
* **Evidentiary Tier**: `[Supported Inference]`.

### # [FMT-FLM-OPCODES]
* **Target Container**: `.FLM` choreography timeline stream.
* **Format Specification**: `FILM` magic signature, time-slice header (`inctime`, `declared_len`), opcode stream (`0x80` var set, `0x90` view obj, `0x98` credits, `0xFF` end slice), camera channel updates, and audio cues.
* **Evidentiary Tier**: `[Established]` (Verified in `tests/fixtures/synthetic_minimal.flm`).

---

## 4. Runtime Memory Anchors (`# [MEM-*]`)

See [`docs/MEMORY_MAP.md`](MEMORY_MAP.md) for full physical linear translation and segment:offset tables:
* **`# [MEM-VSYNC-03DA]`**: VGA status register 1 vertical retrace loop (`in al, 0x03DA`, `test al, 08h`).
* **`# [MEM-FLM-TICK]`**: Internal 16-bit simulation tick counter in `DGROUP`.
* **`# [MEM-CAMERA-RIG]`**: Active camera position, target, vertical FOV zoom scalar, and roll.
* **`# [MEM-ACTOR-TABLE]`**: Active actor transforms, model pointers, bitmasks, and subobject joint angles.
