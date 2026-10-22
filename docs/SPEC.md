# SPEC: StuntReel (`stunt-reel`) — Stunt Island Cinematic Remaster & glTF Exporter

* **Project Name:** StuntReel
* **Repository Identifier:** `stunt-reel`
* **Binary CLI:** `stuntreel`
* **Status:** Phases 0–2 delivered (Milestone 1 and 2 gates passed); Milestone 3 fidelity backlog open. Ticket-level status: [`TEAM_SHEET.md`](TEAM_SHEET.md)
* **Strategy:** Two-Phase Delivery (Phase 1: Runtime Memory Capture to glTF 2.0; Phase 2: Native Cleanroom Rust Engine)
* **Methodology:** Cleanroom Reverse Engineering (Nanolathe), AI Hero Specification Architecture, & Offline Test-Driven Verification

---

## 1. Goal & Strategic Objectives

### 1.1 Executive Summary & Core Purpose

The objective of **StuntReel (`stunt-reel`)** is to build an authoritative, GPU-accelerated cinematic player and ahead-of-time (AOT) animation exporter capable of decoding and rendering Disney and The Assembly Line's 1992 *Stunt Island* standalone movie packages (`.ALL` scene containers and `.FLM` choreography scripts) at arbitrary modern resolutions (4K, Ultrawide) and unlocked framerates ($\ge 60\text{ FPS}$).

Rather than attempting a monolithic rewrite of the interactive flight simulator (`STUNT.EXE`)—which requires reverse-engineering real-time 6-DOF aerodynamic integrators, stall curves, and 16-bit authoring GUIs—**StuntReel** scopes exclusively to the standalone film playback runtime (`PLAYONE.EXE`) and its batch linker (`MAKEONE.EXE`). *Stunt Island* films are deterministic, pre-recorded choreographies: static stage setups, camera cuts, actor world trajectories, articulated subobject states, and sound triggers are baked into `.FLM` streams and paired `.ALL` archives.

Our engineering methodology is directly inspired by cleanroom reverse engineering principles:
1. **Strict Cleanroom Separation:** Retail executables and assets are treated solely as an external specification oracle and are never committed to version control or distributed with engine code.
2. **Evidentiary Confidence Tiering:** Every reverse-engineered struct, memory offset, and opcode carries a machine-checked evidentiary tag (`[Established]`, `[Supported Inference]`, `[Bounded Observation]`, `[Hypothesis]`, or `[Unknown]`; `[Superseded]` marks retired claims).
3. **Hierarchical Routing & Tokenized Contract Anchors:** Documentation is organized via 1-hop routing tables (`docs/ARCHITECTURE.md`) and permanent contract anchors (`# [MEM-...]`, `# [FMT-...]`, `[I1]`–`[I8]`) verified by automated tests so agents never suffer context bloat or citation drift.

### 1.2 Phased Delivery Architecture

Delivery is sequential. This section records what each phase is for and whether it has shipped; per-ticket status, owners and milestone sign-offs live in [`TEAM_SHEET.md`](TEAM_SHEET.md).

1. **Phase 0: Foundation, Cleanroom Scaffolding & Static Reverse Engineering *(Status: Complete)***
   * Cargo workspace (`stunt-core`, `stunt-render`, `stunt-cli`) and Python package (`stunt_reel`), managed reproducibly via `mise`.
   * The four Seam contracts in `crates/stunt-core/src/contracts/` (§ 4), the 100% offline synthetic fixture suite, and the unified quality gate (`mise run check`).
   * `PLAYONE.EXE` unpacked and disassembled for startup, memory, navigation and the display-list VM ([`research/playone-exe/`](../research/playone-exe/)).

2. **Phase 1: Capture Harness & AOT glTF 2.0 Exporter *(Status: Complete; Milestone 1 gate passed)***
   * Treats `PLAYONE.EXE` as an authoritative black-box kinematics compiler running inside headless DOSBox-X, driven over its debugger socket, and gates snapshots on the film clock ([`capture.md`](../research/playone-exe/capture.md), [`MEMORY_MAP.md`](MEMORY_MAP.md)).
   * Emits the golden trajectory oracle and self-contained animated glTF 2.0 files (`python/stunt_reel/tac/`, `python/stunt_reel/gltf/`).

3. **Phase 2: Native Cleanroom Rust Engine *(Status: Complete; Milestone 2 gate passed)***
   * A standalone, zero-emulator Rust runtime (`stunt-core`, `stunt-render`, `stunt-cli`) on `wgpu`: native `.ALL`/`.RES` parsing, `.SOD` display-list transpilation into a flat arena IR, `.FLM` evaluation through `FilmTimeline`, and authentic Mode 13h flat-shaded rendering.
   * Asserts position parity ($\text{RMSE} \le 0.01\text{ m}$) against the Phase 1 oracle and visual parity against captured frames (gates `G04`–`G07`).

4. **Ongoing: Fidelity Backlog *(Status: Open; Milestone 3)***
   * Decode and timing gaps found by the `CTRY.FLM` export audit, such as `OP_ANIMATE` semantics. Findings: [`research/parity-findings.md`](../research/parity-findings.md); tickets: [`TEAM_SHEET.md`](TEAM_SHEET.md).

---

## 2. System Architectural Invariants & Guardrails

### 2.1 Explicit Scope Boundaries & Non-Goals

* **No Interactive Aerodynamics:** Real-time 6-DOF flight integration (Runge-Kutta/Euler), lift/drag polar lookup tables, stall physics, and joystick control loops (`STUNT.EXE`) are strictly excluded. The engine evaluates pre-recorded keyframe trajectories and discrete timeline events only.
* **No Authoring GUI Systems & Timeline Scrubbing:** The Set Designer, Prop Placement, Sound Stage, and Editing Room 16-bit DOS user interfaces are excluded. In Milestone 2, immediate-mode GUI chrome and timeline scrubbing sliders are deferred; playback is launched via CLI argument with basic keyboard controls (Space=Pause/Resume, Esc=Quit).
* **No CPU Software Rasterizer:** Software Mode 13h ($320 \times 200$) horizontal span filling, Sutherland-Hodgman CPU frustum clipping, and CPU-side Painter's Algorithm / BSP polygon sorting are superseded by modern GPU hardware rasterization and floating-point depth buffering.
* **No Direct Audio Hardware Output (Milestone 2 Deferral):** Sound output via hardware audio devices (WASAPI/CPAL/rodio) is deferred; `AudioCue` events are parsed and evaluated as data-only metadata in `TrajectoryRecord` (Seam 2).
* **No Analog CRT Post-Processing Shaders (Milestone 2 Deferral):** Scanline emulation, phosphor bloom, CRT barrel curvature, and temporal dithering passes are deferred; authentic visual reproduction is accomplished via the $256 \times 32$ palette LUT and `@interpolate(flat)`.

### 2.2 Mathematical & Spatial Invariants

#### [I1] Metric Right-Handed Coordinates, Attribute-Preserving Vertex Welding & Angle/FOV Normalization

  * Spatial coordinates use the standard glTF 2.0 right-handed metric basis: $+X$ right, $+Y$ up, $+Z$ backward (toward viewer), and $-Z$ forward.
  * Signed 16-bit fixed-point coordinates ($12.4$ and $8.8$ formats) are converted at ingest into IEEE 754 32-bit floating-point meters ($1.0 = 1.0\text{ m}$).
  * **Attribute-Preserving Vertex Welding:** Near-coincident vertex positions within $\epsilon_{\text{weld}} = 10^{-4}\text{ m}$ are snapped to identical floating-point coordinates to eliminate fixed-point T-junction cracks. However, to preserve *Stunt Island*'s flat-shaded facet boundaries and prevent normal/color bleeding across hard edges, index deduplication in `SodModelIr` keys on the full vertex attribute tuple rather than position alone:
    $$\text{WeldKey} = \left(\text{quantize}(\mathbf{position}, 10^{-4}),\; \text{quantize}(\mathbf{normal}, 10^{-3}),\; \text{palette\_index},\; \text{flags}\right)$$
  * **Binary Angular Measurement (BAM):** 16-bit integer BAM angles ($\text{raw\_u16} \in [0, 65535]$) are converted to floating-point radians via:
    $$\theta_{\text{rad}} = \left(\frac{\text{raw\_u16}}{65536.0}\right) \times 2\pi$$
  * **Vertical Field of View ($\text{FOV}_y$) Convention:** `CameraTransform::fov_degrees` is strictly defined as **vertical field of view ($\text{FOV}_y$)** in degrees. The DOS engine's integer focal-length zoom scalar (`focal_dist`) converts to vertical $\text{FOV}_y$ against the aspect-corrected half-height ($H_{\text{half}} = 120.0$) via:
    $$\text{FOV}_y = 2 \arctan\left(\frac{H_{\text{half}}}{\text{focal\_dist}}\right) \times \frac{180}{\pi}$$

#### Real-Mode Physical Address Translation

  * All 16-bit MS-DOS `Segment:Offset` pointers inspected via `dosbox-x-mcp-server`, GDB, or static disassembly must be normalized to 20-bit linear physical addresses within the $1\text{ MB}$ conventional memory space (`0x00000`–`0xFFFFF`):
    $$\text{Address}_{\text{linear}} = (\text{Segment} \ll 4) + \text{Offset} = (\text{Segment} \times 16) + \text{Offset}$$

#### [I4] Discrete Simulation Ticks & Cut-Aware Sub-Tick Interpolation

  * `.FLM` choreography logic advances at the runtime's fixed $50\text{ Hz}$ tick rate ($20.0\text{ ms}$ per tick; `PLAYONE.EXE` PIT divisor `0x5D38`). Each slice's `tick_duration` is the number of ticks elapsed since the previous slice, so slice $i$'s timestamp is $\sum_{k \le i}\text{tick\_duration}_k$.
  * **Record tick semantics:** `TrajectoryRecord.tick` is always this cumulative 50 Hz authored tick, never a slice ordinal; a slice's ordinal is only its index in the timeline. Oracle ticks, `AudioCue.tick`, and parity sample points all use the same clock.
  * **Single sampling interface:** `FilmTimeline` (`crates/stunt-core/src/flm/timeline.rs`) is the only public path from a `.FLM` film to trajectory records (`from_bytes`, `sample(tick)`, `sample_at_seconds`, `cues_between`, `total_ticks`, `duration_seconds`, `slices()`, `truncated_to_ticks`, `warnings`, `stop_reason`). The per-slice-ordinal evaluators (`FlmPlayer::step_tick`, `evaluate_all`, `evaluate_film`, `evaluate_sub_tick`) are removed; `FlmPlayer` and the interpolation helpers are crate-private.
  * **Partial films:** a slice that fails to decode does not discard the film. Slices decoded before the failure are kept and `stop_reason()` reports why decoding stopped, mirroring the Partial SOD convention (see [`GLOSSARY.md`](../GLOSSARY.md)). Only an invalid header is an error.
  * The presentation loop runs unlocked ($\ge 60\text{ FPS}$). For fractional sub-tick factor $\alpha \in [0.0, 1.0)$ between consecutive slices at $T_t$ and $T_{t+1} = T_t + 20\text{ ms} \times \text{tick\_duration}_{t+1}$:
    * **Continuous Motion (`cut_from_previous == false` at tick $t+1$):** World position $\mathbf{P}$ and unit quaternion rotation $\mathbf{q}$ are evaluated via linear and spherical-linear interpolation:
      $$\mathbf{P}_{\text{render}}(\alpha) = (1.0 - \alpha)\mathbf{P}_t + \alpha\mathbf{P}_{t+1}$$
      $$\mathbf{q}_{\text{render}}(\alpha) = \text{slerp}(\mathbf{q}_t, \mathbf{q}_{t+1}, \alpha)$$
    * **Camera Cuts & Instantaneous Teleports (`cut_from_previous == true` at tick $t+1$):** When `.FLM` switches camera rigs or when inter-tick camera displacement exceeds the continuity threshold ($\left\|\mathbf{P}_{t+1} - \mathbf{P}_t\right\|_2 > 50.0\text{ m}$), sub-tick interpolation is suppressed ($\alpha_{\text{eff}} = 0.0$, holding $\mathbf{P}_t$ and $\mathbf{q}_t$ until tick $t+1$ arrives) so the camera cuts instantaneously without swooping across the island.

#### [I5] Coplanar Decal Resolution

  * *Phase 1 (glTF 2.0 Export):* Because core glTF 2.0 lacks pipeline depth-bias states, coplanar decal polygons (runway markings, aircraft insignias, wing roundels) are geometrically displaced along their outward surface normal $\hat{\mathbf{n}}$ by $\epsilon = 0.001\text{ m}$ at export:
    $$\mathbf{v}' = \mathbf{v} + 0.001\hat{\mathbf{n}}$$
  * *Phase 2 (`wgpu` Engine):* Coplanar decal batches are rendered in a dedicated pipeline pass using hardware depth biasing (`DepthBiasState { constant: 2, slope_scale: 2.0, clamp: 0.0 }`).

#### [I6] Visual Parity Acceptance Thresholds & VGA 1:1.2 Aspect Ratio Correction

  * Original VGA Mode 13h framebuffers render at $320 \times 200$ pixels displayed on a physical $4:3$ CRT, resulting in non-square pixels stretched vertically by $1.2$:
    $$\text{Aspect}_{\text{physical}} = \frac{320}{200 \times 1.2} = \frac{320}{240} = \frac{4}{3} \approx 1.3333$$
  * All visual parity gates normalize reference DOSBox-X captures to $4:3$ ($320 \times 240$) prior to Structural Similarity (SSIM) evaluation.
  * Off-screen renders (including background sky/horizon palette fills and static stage terrain) must achieve mean $\text{SSIM} \ge 0.88$ for Phase 1 glTF exports and mean $\text{SSIM} \ge 0.90$ for Phase 2 native `wgpu` engine sign-off.

### 2.3 Software Architecture Guardrails

#### [I2] Flat Arena Allocation (No Recursive Pointers)

  * Scene graphs and `.SOD` subobject hierarchies must be stored in flat contiguous vectors (`Vec<SodNode>`) indexed via lightweight integer handles (`NodeId(pub u32)`).
  * Reference-counted pointers (`Rc<RefCell<T>>`, `Arc<Mutex<T>>`), raw pointers, and self-referential lifetimes (`&'a SodNode`) are strictly prohibited in `stunt-core`.

#### [I3] Authentic VGA Mode 13h Palette Indexing & Flat Shading

  * Geometry preserves original 8-bit VGA palette indices (`0..=255`) inside `SodVertex::palette_index`.
  * In Phase 2, the WGSL vertex-to-fragment stage passes palette and facet lighting indices using `@interpolate(flat)` (disabling bilinear attribute interpolation across triangle interiors) and samples an uncompressed $256 \times 32$ RGBA lookup texture (LUT) representing 256 base colors across 32 discrete directional lighting and atmospheric haze levels.

#### [I7] Cleanroom Asset Isolation & Zero-Dependency Core

  * Proprietary game binaries and retail data files (`corpus/`, `target_bin/`) are strictly gitignored and never checked into Git or downloaded during CI.
  * `crates/stunt-core` maintains zero OS windowing, GPU, audio, or emulator dependencies so unit and contract tests compile and run 100% offline in $< 2\text{ seconds}$.

#### [I8] DOS 8.3 Uppercase Path Normalization

  * Because POSIX filesystems are case-sensitive while MS-DOS is case-insensitive, all virtual filesystem (`VfsArchive`) insertions, lookups, and corpus extraction tools normalize filenames to uppercase ASCII (`to_ascii_uppercase()`).

### 2.4 Evidentiary Tiers & Contract Anchor System

* **Evidentiary Confidence Tiers:** Every reverse-engineered binary struct, memory offset, or opcode carries one explicit evidentiary tag. The vocabulary is owned by `EVIDENTIARY_TIERS` in [`python/scripts/verify_formats_docs.py`](../python/scripts/verify_formats_docs.py), which fails `mise run check` if any document uses another tag or if this section stops defining one. In promotion order:
  * **`[Unknown]`**: Unmapped padding bytes or unencountered opcodes; parsers must fail loudly with explicit byte-offset context if encountered.
  * **`[Hypothesis]`**: Proposed from reasoning, community notes, or an offline mock; not observed in the binary or a corpus file. Never cite as fact.
  * **`[Bounded Observation]`**: Observed empirically in a single film or fixture; behavior outside observed value ranges remains unverified.
  * **`[Supported Inference]`**: Confirmed via cross-file byte alignment and passing trajectory/visual parity gates across multiple corpus files.
  * **`[Established]`**: Proven directly via disassembled machine code in `PLAYONE.EXE` / `MAKEONE.EXE` or verified via bit-exact runtime memory trap.
  * **`[Superseded]`**: Not a confidence level: a retired claim or label kept so old references still resolve, with a pointer to its replacement.

* **Immutable Contract Anchors:**
  * Permanent bracketed tokens (`[I1]`–`[I8]`, `# [FMT-*]`, `# [MEM-*]`) are cited from code, tests and documents. The list of tokens and the one heading that defines each is the registry in [`python/stunt_reel/doc_anchors.py`](../python/stunt_reel/doc_anchors.py); this document does not duplicate it.
  * `tests/test_doc_invariants.py` (inside `mise run check`) fails if a registered anchor has no heading in its home file or if any cited anchor is unregistered.

---

## 3. Reverse-Engineering Reference

The specification does not carry binary-analysis findings. They live in `research/` and in the memory map, each with its own evidence and tier:

| Topic | Home |
|---|---|
| `PLAYONE.EXE` image, entry point, LZEXE packing, command tail (only a leading `?` is read, everything else is ignored), memory and disk gates | [`research/playone-exe/startup.md`](../research/playone-exe/startup.md) |
| Modal `LOAD FILM` dialog, prefix search, BIOS Data Area keystroke injection, `.FLM` + `.ALL` pairing rule | [`research/playone-exe/navigation.md`](../research/playone-exe/navigation.md) |
| `DGROUP` offsets, work-segment offsets, `# [MEM-*]` anchors | [`docs/MEMORY_MAP.md`](MEMORY_MAP.md) (evidence: [`memory.md`](../research/playone-exe/memory.md)) |
| DOSBox-X capture harness and protocol | [`research/playone-exe/capture.md`](../research/playone-exe/capture.md) |
| Display-list VM, `OP_TAP`, `OP_ANIMATE` | [`sod-vm.md`](../research/playone-exe/sod-vm.md), [`sod-animate.md`](../research/playone-exe/sod-animate.md) |
| File formats and byte layouts | [`research/formats/INDEX.md`](../research/formats/INDEX.md) and the `.ksy` schemas |
| `CTRY.FLM` parity findings: comparator, camera look direction, partial model fidelity, scenery | [`research/parity-findings.md`](../research/parity-findings.md) |

---

## 4. Seam Contracts

The system integrates across four seams, defined by the types in `crates/stunt-core/src/contracts/` (the only definition of their fields):

* **Seam 1 (`VfsArchive`)**: `.RES` and `.ALL` extraction ([`vfs.rs`](../crates/stunt-core/src/contracts/vfs.rs)); layouts in [`res.md`](../research/formats/res.md) and [`all.md`](../research/formats/all.md).
* **Seam 2 (`TrajectoryRecord`, `FilmCapture`)**: per-tick film state on the cumulative 50 Hz clock, sampled through `FilmTimeline` ([`trajectory.rs`](../crates/stunt-core/src/contracts/trajectory.rs)); see `[I4]`.
* **Seam 3 (`SodModelIr`)**: the flat-arena scene graph built by `transpile_sod` (strict) or `transpile_sod_lenient` ([`scene.rs`](../crates/stunt-core/src/contracts/scene.rs)); see `[I2]`.
* **Seam 4 (`VisualParityGate`)**: SSIM evaluation against aspect-corrected frames ([`parity.rs`](../crates/stunt-core/src/contracts/parity.rs)); see `[I6]`.

Which code path is governed by which seam, anchor and note: [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 5. Master Verification Matrix

| Gate ID | Verification Scope | Target Seam & Invariants | Execution Command | Required Acceptance Threshold | Runs in Offline CI? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`G01`** | Formatting, Lints, Types & Doc Anchors | All Crates, `python/stunt_reel`, `docs/` | `mise run check` | Exit code `0`; $0$ warnings; every registered anchor has its heading and every cited anchor is registered (`stunt_reel.doc_anchors`); doc tiers and links validate | **Yes** |
| **`G02`** | Cleanroom VFS Extraction | Seam 1 (`VfsArchive`), `[I7]`, `[I8]` | `cargo test -p stunt-core vfs` | 100% byte match on `synthetic_minimal.res`; uppercase 8.3 lookup | **Yes** |
| **`G03`** | Arena Scene Graph & Attribute Welding | Seam 3 (`SodModelIr`), `[I1]`, `[I2]`, `[I3]` | `cargo test -p stunt-core scene` | `size_of::<SodVertex>() == 28`; flat `NodeId(u32)` arena; sharp facet normals preserved | **Yes** |
| **`G04`** | Synthetic `.FLM`, Cut-Aware `[I4]` & Oracle Parity | Seam 2 (`TrajectoryRecord`), `[I1]`, `[I4]` | `cargo test -p stunt-core trajectory` | $\text{RMSE}_{\text{pos}} \le 0.01\text{ m}$ vs. `oracle_intro_trajectory.json`, with `compute_position_rmse` sampling `FilmTimeline` at each oracle tick (50 Hz ticks) of `build_synthetic_intro_flm` (test support); $\alpha = 0$ on cuts | **Yes** |
| **`G05`** | Phase 1 glTF 2.0 Visual Parity | Seam 4 (`VisualParityReport`), `[I5]`, `[I6]` | `uv run pytest -m phase1_oracle` | `VisualParityReport::is_passing() == true` ($\text{Mean SSIM} \ge 0.88$) | Local Corpus |
| **`G06`** | Phase 2 Native `wgpu` Visual Parity | Seam 4 (`VisualParityReport`), `[I3]`, `[I5]`, `[I6]` | `cargo test --workspace -- --ignored oracle_parity` | $\text{RMSE}_{\text{pos}} \le 0.01\text{ m}$ and $\text{Mean SSIM} \ge 0.90$ across 600 ticks | Local Corpus |
| **`G07`** | Captured-vs-rendered parity loop | Seam 2 + Seam 4, `[I6]` | `mise run capture-ref`, then `cargo run -p stunt-cli -- --headless <film.flm> --all <film.all> --frames 1..<total_ticks+1> --out-dir build/parity/ours/ctry`, then `cargo run -p stunt-cli -- parity --reference build/parity/reference/ctry --test build/parity/ours/ctry --output build/parity/report/ctry --clear-index 233` | `report.json` carries `mean_ssim`, `min_ssim`, `mean_iou`, `sky_index` for every sampled frame | Local Corpus |
| **`G08`** | Headless Interval Capture & Video Export | Seam 2, Seam 4, `[I4]`, `[I6]`, `[I7]` | `cargo test -p stunt-render export` | Headless render of cleanroom synthetic fixtures produces exact interval frame count with valid PNG magic/dimensions; video export produces valid container when ffmpeg is present, or fails gracefully with informative error when absent | **Yes** |
