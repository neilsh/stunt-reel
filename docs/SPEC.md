# SPEC: StuntReel (`stunt-reel`) — Stunt Island Film Playback, Reconstruction & glTF Exporter

* **Project Name:** StuntReel; binary CLI `stuntreel`.
* **Status:** Phases 0–2 delivered (Milestone 1 and 2 gates passed); Milestone 3 fidelity backlog open.
  Work items and their status: [GitHub issues][issues].

[issues]: https://github.com/neilsh/stunt-reel/issues
[notice]: ../NOTICE.md

---

## 1. Goal & Strategic Objectives

### 1.1 Executive Summary & Core Purpose

**StuntReel** is a GPU-accelerated cinematic player and ahead-of-time (AOT) animation exporter for the standalone films of Disney and The Assembly Line's 1992 *Stunt Island*, at arbitrary modern resolutions (4K, Ultrawide) and unlocked framerates ($\ge 60\text{ FPS}$).

It scopes to the film playback runtime (`PLAYONE.EXE`) and its batch linker (`MAKEONE.EXE`), not the interactive flight simulator (`STUNT.EXE`, § 2.1).
A *Stunt Island* film is a deterministic, pre-recorded choreography whose static stage setups, camera cuts, actor world trajectories, articulated subobject states and sound triggers are baked into a `.FLM` choreography stream and its paired `.ALL` scene archive.

Three principles govern the method, which is asset-isolated format analysis, evidence-tiered documentation and offline test-driven verification:
1. **Asset isolation:** Retail executables and assets are only an external specification oracle, never committed or distributed with engine code; the few documented, credited exceptions are in `[I7]`.
2. **Evidentiary Confidence Tiering:** every recovered struct, offset and opcode carries a machine-checked tier tag (§ 2.4).
3. **Hierarchical Routing & Tokenized Contract Anchors:** 1-hop routing tables (`docs/ARCHITECTURE.md`) and test-verified contract anchors (§ 2.4) keep agents free of context bloat and citation drift.

### 1.2 Phased Delivery Architecture

Delivery is sequential; open work is in [GitHub issues][issues].
_Source: the Milestone 1 and 2 sign-offs (Phases 0–2) in the frozen [`TEAM_SHEET.md`](../work/2026-10/team-sheet/TEAM_SHEET.md)._

1. **Phase 0: Foundation & Static Analysis *(Status: Complete)***
   * Cargo workspace and Python package (`stunt_reel`), managed reproducibly via `mise`.
   * The four Seam contracts (§ 4), the 100% offline synthetic fixture suite, and the unified quality gate (`mise run check`).
   * `PLAYONE.EXE` unpacked and disassembled for startup, memory, navigation and the display-list VM ([`research/playone-exe/`](../research/playone-exe/)).

2. **Phase 1: Capture Harness & AOT glTF 2.0 Exporter *(Status: Complete; Milestone 1 gate passed)***
   * Treats `PLAYONE.EXE` as a reference black-box kinematics compiler inside dosbox-automation, driven as a Lua plan over its REST API, with snapshots gated on the film clock ([`capture-dosbox-automation.md`](../research/playone-exe/capture-dosbox-automation.md), [`MEMORY_MAP.md`](../research/playone-exe/memory-map.md)).
   * Emits a synthetic trajectory oracle (hand-written kinematics under `build/oracle/`, not captured from `PLAYONE.EXE`; [ADR 0022](adr/0022-captures-are-add-only-beside-a-read-only-corpus.md)) and self-contained animated glTF 2.0 files (capture in `python/stunt_reel/tac/`; glTF export in `crates/stunt-gltf/`).

3. **Phase 2: Native Rust Engine *(Status: Complete; Milestone 2 gate passed)***
   * A zero-emulator Rust runtime (`stunt-core`, `stunt-render`, `stunt-cli`) on `wgpu`: native `.ALL`/`.RES` parsing, `.SOD` display-list transpilation into a flat arena IR, `.FLM` evaluation through `FilmTimeline`, and authentic Mode 13h flat-shaded rendering.
   * Asserts position error ($\text{RMSE} \le 0.01\text{ m}$) against the synthetic Phase 1 oracle trajectory and visual parity against captured frames (gates `G04` and `G07`).

4. **Ongoing: Fidelity Backlog *(Status: Open; Milestone 3)***
   * Decode and timing gaps found by the `CTRY.FLM` export audit, such as `OP_ANIMATE` semantics.
     Findings: [`research/parity/`](../research/parity/).

---

## 2. System Architectural Invariants & Guardrails

### 2.1 Explicit Scope Boundaries & Non-Goals

* **No Interactive Aerodynamics:** Real-time 6-DOF flight integration (Runge-Kutta/Euler), lift/drag polar tables, stall physics and joystick control loops (`STUNT.EXE`) are excluded.
  The engine evaluates pre-recorded keyframe trajectories and discrete timeline events only.
* **No Authoring GUI Systems & Timeline Scrubbing:** The Set Designer, Prop Placement, Sound Stage and Editing Room 16-bit DOS interfaces are excluded.
  In Milestone 2, immediate-mode GUI chrome and timeline scrubbing are deferred; playback launches by CLI argument with basic keyboard controls (Space=Pause/Resume, Esc=Quit).
* **No CPU Software Rasterizer:** Mode 13h span filling, Sutherland-Hodgman CPU clipping and Painter's Algorithm / BSP sorting give way to GPU rasterization and depth buffering (reversed, infinite depth in `Depth24Plus`, [ADR 0054](adr/0054-depth-is-reversed-and-infinite.md)).
  Where the two orders disagree, and the rules that imitate the painter at coplanar ties: [`render-model.md`](../research/parity/render-model.md).
* **No Direct Audio Hardware Output (Milestone 2 Deferral):** Sound output through audio devices (WASAPI/CPAL/rodio) is deferred; `AudioCue` events are parsed and evaluated as data-only metadata in `TrajectoryRecord` (Seam 2).
* **No Analog CRT Post-Processing Shaders (Milestone 2 Deferral):** Scanlines, phosphor bloom, barrel curvature and temporal dithering are deferred; visual reproduction uses the $256 \times 32$ palette LUT and `@interpolate(flat)`.

### 2.2 Mathematical & Spatial Invariants

#### [I1] Metric Right-Handed Coordinates, Attribute-Preserving Vertex Welding & Angle/FOV Normalization

  * glTF 2.0's right-handed metric basis: $+X$ right, $+Y$ up, $+Z$ backward (toward viewer), $-Z$ forward.
  * Signed 16-bit fixed-point coordinates ($12.4$ and $8.8$) are converted at ingest to IEEE 754 32-bit float meters ($1.0 = 1.0\text{ m}$).
  * **Attribute-Preserving Vertex Welding:** Positions within $\epsilon_{\text{weld}} = 10^{-4}\text{ m}$ snap together, closing fixed-point T-junction cracks; to keep flat-shaded facet edges, index deduplication in `SodModelIr` keys on the full attribute tuple, not position alone:
    $$\text{WeldKey} = \left(\text{quantize}(\mathbf{position}, 10^{-4}),\; \text{quantize}(\mathbf{normal}, 10^{-3}),\; \text{palette\_index},\; \text{flags}\right)$$
  * **Binary Angular Measurement (BAM):** 16-bit BAM angles ($\text{raw\_u16} \in [0, 65535]$) convert to radians as $\theta_{\text{rad}} = \left(\frac{\text{raw\_u16}}{65536.0}\right) \times 2\pi$.
  * **Vertical Field of View ($\text{FOV}_y$) Convention:** `CameraTransform::fov_degrees` is strictly the **vertical field of view** in degrees.
    The unverified camera-rig mock converts a positive DOS focal-length zoom scalar (`focal_dist`) against the aspect-corrected half-height ($H_{\text{half}} = 120.0$):
    $$\text{FOV}_y = 2 \arctan\left(\frac{H_{\text{half}}}{\text{focal\_dist}}\right) \times \frac{180}{\pi}$$
    Films take a separate path: square pixels on the $320 \times 200$ raster and $\text{FOV}_y = 2\arctan(100/256) = 42.67^\circ$ at the default lens (aspect $320/200$), then the 4:3 stretch of `[I6]` ([`framing-and-actors.md`](../research/parity/framing-and-actors.md) § 2).

#### Real-Mode Physical Address Translation

  * Every 16-bit MS-DOS `Segment:Offset` pointer inspected through dosbox-automation's Lua memory reads, GDB or static disassembly must be normalized to a 20-bit linear address in the $1\text{ MB}$ conventional memory space (`0x00000`–`0xFFFFF`): $\text{Address}_{\text{linear}} = (\text{Segment} \ll 4) + \text{Offset}$.

#### [I4] Discrete Simulation Ticks & Cut-Aware Sub-Tick Interpolation

  * `.FLM` choreography advances at the runtime's fixed $50\text{ Hz}$ tick ($20.0\text{ ms}$; `PLAYONE.EXE` PIT divisor `0x5D38`).
    A slice's `tick_duration` is the ticks since the previous slice, so slice $i$'s timestamp is $\sum_{k \le i}\text{tick\_duration}_k$.
  * **Record tick semantics:** `TrajectoryRecord.tick` is always this cumulative 50 Hz authored tick, never a slice ordinal; a slice's ordinal is only its index in the timeline.
    Oracle ticks, `AudioCue.tick` and parity sample points share this clock.
  * **Single sampling interface:** `FilmTimeline` (`crates/stunt-core/src/flm/timeline.rs`) is the only public path from a `.FLM` film to trajectory records, sampled by tick (`sample`) or read per slice (`slices()`); no per-slice-ordinal evaluator is public, and `FlmPlayer` and the interpolation helpers are crate-private.
  * **Partial films:** a slice that fails to decode keeps the slices before it, and `stop_reason()` says why decoding stopped, mirroring the Partial SOD convention ([`GLOSSARY.md`](../GLOSSARY.md)).
    Only an invalid header is an error.
  * Presentation runs unlocked ($\ge 60\text{ FPS}$).
    For sub-tick factor $\alpha \in [0.0, 1.0)$ between consecutive slices at $T_t$ and $T_{t+1} = T_t + 20\text{ ms} \times \text{tick\_duration}_{t+1}$:
    * **Continuous Motion (`cut_from_previous == false` at tick $t+1$):** position is lerped and the unit rotation quaternion slerped:
      $$\mathbf{P}_{\text{render}}(\alpha) = (1.0 - \alpha)\mathbf{P}_t + \alpha\mathbf{P}_{t+1}, \quad \mathbf{q}_{\text{render}}(\alpha) = \text{slerp}(\mathbf{q}_t, \mathbf{q}_{t+1}, \alpha)$$
    * **Camera Cuts & Instantaneous Teleports (`cut_from_previous == true` at tick $t+1$):** when `.FLM` switches camera rigs or the camera moves more than $50.0\text{ m}$ between ticks ($\left\|\mathbf{P}_{t+1} - \mathbf{P}_t\right\|_2 > 50.0\text{ m}$), $\alpha_{\text{eff}} = 0.0$: $\mathbf{P}_t$ and $\mathbf{q}_t$ hold until tick $t+1$, so the camera cuts instead of swooping.

#### [I5] Coplanar Decal Resolution

  * *Decoder:* A polygon coplanar with an earlier polygon of a shape's stream (runway markings, aircraft insignias, wing roundels) is a decal: matched by its front normal (the side `FrontFace::Cw` keeps) against the earlier polygons of the stream as decoded, flagged, and left where it lies.
    `SodModelIr` carries no decal offset ([ADR 0046](adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)).
  * *Phase 2 (`wgpu` Engine):* Decals draw after all base geometry, in stream order, with `GreaterEqual` (depth is reversed: nearer is larger), depth bias toward the viewer (`DepthBiasState { constant: 2, slope_scale: 2.0, clamp: 0.0 }`, [ADR 0054](adr/0054-depth-is-reversed-and-infinite.md)) and no depth write, so a later coplanar decal covers an earlier one.
    Outlines follow their fills per fan in a shape and per slice in the world; ungated world decals share one `WORLD_DECAL` node, whose outlines follow all the fills of each of its draw slices.
    The world's decal outlines are a line list, which wgpu cannot bias, so they compare `GreaterEqual` unbiased and can lose pixels to a base in their plane.
    An actor's ground shadow goes through the same pass, flattened 1 mm above the ground.
  * *glTF 2.0 export:* Core glTF 2.0 has no depth bias or draw order, so `stunt-gltf` alone moves decal vertices $\epsilon = 0.001\text{ m}$ toward their front normal: $\mathbf{v}' = \mathbf{v} + 0.001\hat{\mathbf{n}}$.
  * *Flat ground (`wgpu` Engine):* The ocean quad below the ground plane `y = base_y`, the `MAP.BIN` patches flat on that plane, and the prop triangles within 0.1 m of it, are drawn outside the depth-bias pass, first and in walk order (which follows `PLAYONE`'s painter order only in part), each slice replacing what is under it while writing depth ([ADR 0045](adr/0045-flat-ground-is-painted-in-walk-order.md)).

#### [I6] Visual Parity Acceptance Thresholds & VGA 1:1.2 Aspect Ratio Correction

  * VGA Mode 13h framebuffers are $320 \times 200$ pixels shown on a $4:3$ CRT, so pixels are stretched vertically by $1.2$: $\text{Aspect}_{\text{physical}} = \frac{320}{200 \times 1.2} = \frac{4}{3}$.
  * Parity gates normalize reference captures to $4:3$ ($320 \times 240$) before SSIM.
  * Off-screen renders (sky/horizon palette fills and static stage terrain included) must reach mean $\text{SSIM} \ge 0.88$ initially and $\ge 0.90$ at sign-off, both on the native `wgpu` engine.
    For the `stuntreel parity` comparator the thresholds apply to `mean_ssim_scored`, SSIM over scored frames ([`method.md`](../research/parity/method.md#1-the-loop)). glTF export, a convenience format, has no parity gate; the former Phase 1 glTF tier (G05) is retired.

### 2.3 Software Architecture Guardrails

#### [I2] Flat Arena Allocation (No Recursive Pointers)

  * Scene graphs and `.SOD` subobject hierarchies are stored in flat contiguous vectors (`Vec<SodNode>`) indexed by integer handles (`NodeId(pub u32)`).
  * Reference-counted pointers (`Rc<RefCell<T>>`, `Arc<Mutex<T>>`), raw pointers and self-referential lifetimes (`&'a SodNode`) are prohibited in `stunt-core`.

#### [I3] Authentic VGA Mode 13h Palette Indexing & Flat Shading

  * Geometry keeps the 8-bit VGA palette index (`0..=255`) in `SodVertex::palette_index`.
  * In Phase 2, the WGSL vertex-to-fragment stage passes palette and facet lighting indices with `@interpolate(flat)` and samples an uncompressed $256 \times 32$ RGBA lookup texture: 256 base colors across 32 discrete directional lighting and atmospheric haze levels.

#### [I7] Asset Isolation & Small Pure-Rust Core Dependencies

  * Retail binaries and data files (`corpus/`) are gitignored, never committed or downloaded in CI.
    Two small game-derived tables are committed as documented exceptions because `[I3]` rendering needs them: the 256-entry master palette and the 18-entry SOD scale table.
    Illustrative comparison images (a captured frame beside our render) that a research note cites are the third exception.
    All are credited and not relicensed ([`NOTICE.md`][notice]).
  * `crates/stunt-core` may depend on small, pure-Rust crates that do no I/O and touch no windowing, GPU, audio or emulator code, so unit and contract tests compile and run 100% offline in $< 2\text{ seconds}$.
    Each added crate is justified in the PR that adds it ([ADR 0002](adr/0002-stunt-core-may-take-small-dependencies.md)).

#### [I8] DOS 8.3 Uppercase Path Normalization

  * POSIX filesystems are case-sensitive and MS-DOS is not, so every virtual filesystem (`VfsArchive`) insertion and lookup, and the corpus extraction tools, normalize filenames to uppercase ASCII (`to_ascii_uppercase()`).

### 2.4 Evidentiary Tiers & Contract Anchor System

* **Evidentiary Confidence Tiers:** Each recovered struct, offset or opcode carries one tag.
  `EVIDENTIARY_TIERS` in [`catalog.py`](../python/scripts/formats_docs/catalog.py) owns the vocabulary; `mise run check` fails if any document uses another tag or this section stops defining one.
  In promotion order:
  * **`[Unknown]`**: Unmapped padding bytes or unencountered opcodes; parsers must fail loudly with explicit byte-offset context if encountered.
  * **`[Hypothesis]`**: Proposed from reasoning, community notes or an offline mock; not observed in the binary or a corpus file.
    Never cite as fact.
  * **`[Bounded Observation]`**: Observed empirically in a single film or fixture; behavior outside the observed value ranges is unverified.
  * **`[Supported Inference]`**: Confirmed by cross-file byte alignment and passing trajectory/visual parity gates across multiple corpus files.
  * **`[Established]`**: Proven by disassembled machine code in `PLAYONE.EXE` / `MAKEONE.EXE` or by a bit-exact runtime memory trap.
  * **`[Superseded]`**: Not a confidence level: a retired claim or label kept so old references still resolve, with a pointer to its replacement.

* **Immutable Contract Anchors:**
  * Permanent bracketed tokens (`[I1]`–`[I8]`, `# [FMT-*]`, `# [MEM-*]`) are cited from code, tests and documents.
    The registry in [`doc_anchors.py`](../python/stunt_reel/doc_anchors.py) lists every token and the one heading that defines it.
  * `tests/test_doc_invariants.py` (inside `mise run check`) fails if a registered anchor has no heading in its home file or a cited anchor is unregistered.

---

## 3. Format & Behaviour Reference

The specification does not carry binary-analysis findings.
They live in `research/`, each with its own evidence and tier, and [`research/MAP.md`](../research/MAP.md) summarizes every note: `PLAYONE.EXE` behaviour under [`research/playone-exe/`](../research/playone-exe/); `DGROUP` and work-segment offsets and the `# [MEM-*]` anchors in [`memory-map.md`](../research/playone-exe/memory-map.md) and the files it lists; file formats in [`research/formats/INDEX.md`](../research/formats/INDEX.md) and the `.ksy` schemas; parity findings in [`research/parity/`](../research/parity/).

---

## 4. Seam Contracts

The system integrates across four seams, defined by the types in `crates/stunt-core/src/contracts/` (the only definition of their fields):

* **Seam 1 (`VfsArchive`)**: `.RES` and `.ALL` extraction ([`vfs.rs`](../crates/stunt-core/src/contracts/vfs.rs)); layouts in [`res.md`](../research/formats/res.md) and [`all.md`](../research/formats/all.md).
* **Seam 2 (`TrajectoryRecord`, `FilmCapture`)**: per-tick film state on the cumulative 50 Hz clock, sampled through `FilmTimeline` ([`trajectory.rs`](../crates/stunt-core/src/contracts/trajectory.rs)); see `[I4]`.
* **Seam 3 (`SodModelIr`)**: the Shape IR, a flat-arena node graph of one shape, produced by the single `decode_sod` entry point in strict, lenient or census mode; a decoded shape carries its `DecodeRecord`, an authored shape none, and the shape owns its mesh slices and extent ([`shape/mod.rs`](../crates/stunt-core/src/contracts/shape/mod.rs)); see `[I2]`.
* **Seam 4 (`VisualParityGate`)**: capture-vs-render SSIM and the `[I6]` gate, reported by `stuntreel parity` ([`parity/`](../crates/stunt-score/src/parity/)); the seam has no core types ([`contracts/mod.rs`](../crates/stunt-core/src/contracts/mod.rs)).
  Its render, capture and report documents are typed by the pure [`stunt-parity`](../crates/stunt-parity/) port, one adapter per language ([ADR 0011](adr/0011-parity-artifacts-are-a-versioned-port.md)); see `[I6]`.

Which code path is governed by which seam, anchor and note: [`ARCHITECTURE.md`](ARCHITECTURE.md), and [`architecture-python.md`](architecture-python.md) for Python paths.

---

## 5. Master Verification Matrix

| Gate | Scope | Seam & Invariants | Command | Acceptance | Offline CI? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`G01`** | Formatting, lints, types & doc anchors | All crates, `python/stunt_reel`, `docs/` | `mise run check` | Exit `0`, no warnings; anchors (§ 2.4), doc tiers and links validate | **Yes** |
| **`G02`** | Asset-isolated VFS extraction | Seam 1, `[I7]`, `[I8]` | `cargo test -p stunt-core --test it -- vfs_spec:: vfs_fuzz::` | 100% byte match on `synthetic_minimal.res`; uppercase 8.3 lookup | **Yes** |
| **`G03`** | Arena scene graph & attribute welding | Seam 3, `[I1]`, `[I2]`, `[I3]` | `cargo test -p stunt-core --test it -- sod_spec:: sod_fuzz::` | `size_of::<SodVertex>() == 28`; flat `NodeId(u32)` arena; sharp facet normals preserved | **Yes** |
| **`G04`** | Synthetic `.FLM`, cut-aware `[I4]` & oracle trajectory | Seam 2, `[I1]`, `[I4]` | `cargo test -p stunt-core --all-features --test it -- flm_spec:: flm_fuzz::` | $\text{RMSE}_{\text{pos}} \le 0.01\text{ m}$ vs. `oracle_intro_trajectory.json`, `compute_position_rmse` sampling `FilmTimeline` at each oracle tick (50 Hz) of `build_synthetic_intro_flm` (test support); $\alpha = 0$ on cuts | **Yes** |
| **`G05`** | glTF export structure on synthetic fixtures; the Python exporter and its SSIM gate gave way to `crates/stunt-gltf` (`[I6]`) | Seam 3, `[I5]` | `cargo test -p stunt-gltf` | Exported `.glb` parses back with matching accessor bounds, decal offset and camera orientation | **Yes** |
| **`G07`** | Captured-vs-rendered parity loop | Seams 2 and 4, `[I3]`, `[I5]`, `[I6]` | `mise run capture-ref`, then render the film headless and score it with `stuntreel parity` ([Score a render change](howto/score-a-render-change.md)) | `report.json` carries `mean_ssim`, `min_ssim`, `mean_iou`, `sky_indices` for every sampled frame, and `i6_gate` (`initial` at $\text{mean\_ssim\_scored} \ge 0.88$, `sign_off` at $\ge 0.90$; the exit code is unchanged) | Local Corpus |
| **`G08`** | Headless interval capture & video export | Seams 2 and 4, `[I4]`, `[I6]`, `[I7]` | `cargo test -p stunt-render export` | A headless render of synthetic fixtures gives the exact interval frame count, valid PNG magic and dimensions; video export gives a valid container with ffmpeg, else an informative error | **Yes** |
