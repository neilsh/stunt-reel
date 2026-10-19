# SPEC: StuntReel (`stunt-reel`) — Stunt Island Cinematic Remaster & glTF Exporter

* **Project Name:** StuntReel
* **Repository Identifier:** `stunt-reel`
* **Binary CLI:** `stuntreel`
* **Status:** Phase 0 Complete (Scaffolding, Seams 1–4 Contracts, Cleanroom Fixtures, `PLAYONE.EXE` Disassembly); Entering Phase 1 (Capture Harness & glTF Exporter)
* **Strategy:** Two-Phase Delivery (Phase 1: Runtime Memory Capture to glTF 2.0; Phase 2: Native Cleanroom Rust Engine)
* **Methodology:** Cleanroom Reverse Engineering (Nanolathe), AI Hero Specification Architecture, & Offline Test-Driven Verification

---

## 1. Goal & Strategic Objectives

### 1.1 Executive Summary & Core Purpose

The objective of **StuntReel (`stunt-reel`)** is to build an authoritative, GPU-accelerated cinematic player and ahead-of-time (AOT) animation exporter capable of decoding and rendering Disney and The Assembly Line's 1992 *Stunt Island* standalone movie packages (`.ALL` scene containers and `.FLM` choreography scripts) at arbitrary modern resolutions (4K, Ultrawide) and unlocked framerates ($\ge 60\text{ FPS}$).

Rather than attempting a monolithic rewrite of the interactive flight simulator (`STUNT.EXE`)—which requires reverse-engineering real-time 6-DOF aerodynamic integrators, stall curves, and 16-bit authoring GUIs—**StuntReel** scopes exclusively to the standalone film playback runtime (`PLAYONE.EXE`) and its batch linker (`MAKEONE.EXE`). *Stunt Island* films are deterministic, pre-recorded choreographies: static stage setups, camera cuts, actor world trajectories, articulated subobject states, and sound triggers are baked into `.FLM` streams and paired `.ALL` archives.

Our engineering methodology is directly inspired by cleanroom reverse engineering principles:
1. **Strict Cleanroom Separation:** Retail executables and assets are treated solely as an external specification oracle and are never committed to version control or distributed with engine code.
2. **Evidentiary Confidence Tiering:** Every reverse-engineered struct, memory offset, and opcode carries a machine-checked evidentiary tag (`[Established]`, `[Supported Inference]`, `[Bounded Observation]`, or `[Unknown]`).
3. **Hierarchical Routing & Tokenized Contract Anchors:** Documentation is organized via 1-hop routing tables (`docs/ARCHITECTURE.md`) and permanent contract anchors (`# [MEM-...]`, `# [FMT-...]`, `[I1]`–`[I8]`) verified by automated tests so agents never suffer context bloat or citation drift.

### 1.2 Phased Delivery Architecture

To eliminate exploratory stalls and blind binary guesswork, project delivery is structured into sequential phases:

1. **Phase 0: Foundation, Cleanroom Scaffolding & Static Reverse Engineering *(Status: Complete)***
   * Established the Cargo workspace (`stunt-core`, `stunt-render`) and Python automation package (`stunt_reel`), managed reproducibly via `mise`.
   * Frozen the four core Rust data contracts (Seams 1–4: `VfsArchive`, `TrajectoryRecord`, `SodModelIr`, `VisualParityReport`) in `crates/stunt-core/src/contracts/`.
   * Built the 100% offline synthetic fixture suite (`tests/fixtures/synthetic_minimal.res`, `synthetic_minimal.flm`, `oracle_intro_trajectory.json`) and unified quality gate (`mise run check`).
   * Unpacked `PLAYONE.EXE` (LZEXE 0.91) and disassembled startup, memory allocation, command tail parser, and modal `VAULT\*.*` dialog routines (`research/playone-exe/`).

2. **Phase 1: Capture Harness & AOT glTF 2.0 Exporter *(Status: Active — Tickets T01–T04)***
   * Treats `PLAYONE.EXE` as an authoritative black-box kinematics compiler running inside headless DOSBox-X (`2026.10.01`).
   * Drives the modal file selection dialog deterministically via BIOS Data Area (BDA) keystroke injection or DOSBox-X `autotype`, bypassing `PLAYONE.EXE`'s non-existent CLI file loading.
   * Uses `dosbox-x-mcp-server` (`v0.1.2`, port `58991`) for interactive real-mode memory inspection, locks a post-retrace execution breakpoint (`CS:IP`) following the hardware VGA vertical blank (V-Sync) loop on I/O port `0x03DA`, and gates snapshots on `PLAYONE.EXE`'s internal `.FLM` tick counter to extract resolved world-space stage, camera, and actor transforms without mid-frame tearing or $70\text{ Hz}$ duplicate frames.
   * Streams multi-hundred-frame trajectories via a headless local socket script (`python/stunt_reel/tac/`) and combines them with baseline static meshes extracted via historical `SODParse` logic (`RIPRES.C`, `DECODE.C`) to emit self-contained, animated glTF 2.0 (`.glb`) files and the golden trajectory oracle (`corpus/oracle/intro_trajectory.json`).

3. **Phase 2: Native Cleanroom Rust Engine *(Status: Planned — Tickets T05–T08)***
   * Implements a standalone, zero-emulator Rust runtime (`stunt-core` and `stunt-render`) targeting modern GPU backends via `wgpu`.
   * Parses `.ALL` and `.RES` archives natively (`VfsArchive`) using known-plaintext alignment against `MAKEONE.EXE`.
   * Transpiles procedural `.SOD` display-list bytecode into a flat arena-allocated Scene Graph Intermediate Representation (`SodModelIr`), preserving hard-edged flat-shaded normals, articulated subobjects (propellers, rudders, landing gear), procedural primitives (discs, spheres), and `IFVIS` conditional visibility gates.
   * Evaluates `.FLM` choreography streams natively (`TrajectoryRecord` & `FilmCapture`), asserting mathematical parity ($\text{RMSE} \le 0.01\text{ m}$) against Phase 1's golden oracle inside sub-second offline unit tests.
   * Renders with authentic 256-color VGA Mode 13h flat-shaded lighting ramps and distance haze via a $256 \times 32$ palette lookup texture (LUT) using `@interpolate(flat)` attributes, hardware depth biasing for coplanar decals, and detached Free-Cam inspection.

---

## 2. System Architectural Invariants & Guardrails

### 2.1 Explicit Scope Boundaries & Non-Goals

* **No Interactive Aerodynamics:** Real-time 6-DOF flight integration (Runge-Kutta/Euler), lift/drag polar lookup tables, stall physics, and joystick control loops (`STUNT.EXE`) are strictly excluded. The engine evaluates pre-recorded keyframe trajectories and discrete timeline events only.
* **No Authoring GUI Systems & Timeline Scrubbing:** The Set Designer, Prop Placement, Sound Stage, and Editing Room 16-bit DOS user interfaces are excluded. In Milestone 2, immediate-mode GUI chrome and timeline scrubbing sliders are deferred; playback is launched via CLI argument with basic keyboard controls (Space=Pause/Resume, Esc=Quit).
* **No CPU Software Rasterizer:** Software Mode 13h ($320 \times 200$) horizontal span filling, Sutherland-Hodgman CPU frustum clipping, and CPU-side Painter's Algorithm / BSP polygon sorting are superseded by modern GPU hardware rasterization and floating-point depth buffering.
* **No Direct Audio Hardware Output (Milestone 2 Deferral):** Sound output via hardware audio devices (WASAPI/CPAL/rodio) is deferred; `AudioCue` events are parsed and evaluated as data-only metadata in `TrajectoryRecord` (Seam 2).
* **No Analog CRT Post-Processing Shaders (Milestone 2 Deferral):** Scanline emulation, phosphor bloom, CRT barrel curvature, and temporal dithering passes are deferred; authentic visual reproduction is accomplished via the $256 \times 32$ palette LUT and `@interpolate(flat)`.

### 2.2 Mathematical & Spatial Invariants

* **`[I1]` Metric Right-Handed Coordinates, Attribute-Preserving Vertex Welding & Angle/FOV Normalization:**
  * Spatial coordinates use the standard glTF 2.0 right-handed metric basis: $+X$ right, $+Y$ up, $+Z$ backward (toward viewer), and $-Z$ forward.
  * Signed 16-bit fixed-point coordinates ($12.4$ and $8.8$ formats) are converted at ingest into IEEE 754 32-bit floating-point meters ($1.0 = 1.0\text{ m}$).
  * **Attribute-Preserving Vertex Welding:** Near-coincident vertex positions within $\epsilon_{\text{weld}} = 10^{-4}\text{ m}$ are snapped to identical floating-point coordinates to eliminate fixed-point T-junction cracks. However, to preserve *Stunt Island*'s flat-shaded facet boundaries and prevent normal/color bleeding across hard edges, index deduplication in `SodModelIr` keys on the full vertex attribute tuple rather than position alone:
    $$\text{WeldKey} = \left(\text{quantize}(\mathbf{position}, 10^{-4}),\; \text{quantize}(\mathbf{normal}, 10^{-3}),\; \text{palette\_index},\; \text{flags}\right)$$
  * **Binary Angular Measurement (BAM):** 16-bit integer BAM angles ($\text{raw\_u16} \in [0, 65535]$) are converted to floating-point radians via:
    $$\theta_{\text{rad}} = \left(\frac{\text{raw\_u16}}{65536.0}\right) \times 2\pi$$
  * **Vertical Field of View ($\text{FOV}_y$) Convention:** `CameraTransform::fov_degrees` is strictly defined as **vertical field of view ($\text{FOV}_y$)** in degrees. The DOS engine's integer focal-length zoom scalar (`focal_dist`) converts to vertical $\text{FOV}_y$ against the aspect-corrected half-height ($H_{\text{half}} = 120.0$) via:
    $$\text{FOV}_y = 2 \arctan\left(\frac{H_{\text{half}}}{\text{focal\_dist}}\right) \times \frac{180}{\pi}$$

* **Real-Mode Physical Address Translation:**
  * All 16-bit MS-DOS `Segment:Offset` pointers inspected via `dosbox-x-mcp-server`, GDB, or static disassembly must be normalized to 20-bit linear physical addresses within the $1\text{ MB}$ conventional memory space (`0x00000`–`0xFFFFF`):
    $$\text{Address}_{\text{linear}} = (\text{Segment} \ll 4) + \text{Offset} = (\text{Segment} \times 16) + \text{Offset}$$

* **`[I4]` Discrete Simulation Ticks & Cut-Aware Sub-Tick Interpolation:**
  * `.FLM` choreography logic advances at its authored fixed tick rate ($20\text{ Hz}$ or $30\text{ Hz}$).
  * The presentation loop runs unlocked ($\ge 60\text{ FPS}$). For fractional sub-tick factor $\alpha \in [0.0, 1.0)$ between tick $t$ and tick $t+1$:
    * **Continuous Motion (`cut_from_previous == false` at tick $t+1$):** World position $\mathbf{P}$ and unit quaternion rotation $\mathbf{q}$ are evaluated via linear and spherical-linear interpolation:
      $$\mathbf{P}_{\text{render}}(\alpha) = (1.0 - \alpha)\mathbf{P}_t + \alpha\mathbf{P}_{t+1}$$
      $$\mathbf{q}_{\text{render}}(\alpha) = \text{slerp}(\mathbf{q}_t, \mathbf{q}_{t+1}, \alpha)$$
    * **Camera Cuts & Instantaneous Teleports (`cut_from_previous == true` at tick $t+1$):** When `.FLM` switches camera rigs or when inter-tick camera displacement exceeds the continuity threshold ($\left\|\mathbf{P}_{t+1} - \mathbf{P}_t\right\|_2 > 50.0\text{ m}$), sub-tick interpolation is suppressed ($\alpha_{\text{eff}} = 0.0$, holding $\mathbf{P}_t$ and $\mathbf{q}_t$ until tick $t+1$ arrives) so the camera cuts instantaneously without swooping across the island.

* **`[I5]` Coplanar Decal Resolution:**
  * *Phase 1 (glTF 2.0 Export):* Because core glTF 2.0 lacks pipeline depth-bias states, coplanar decal polygons (runway markings, aircraft insignias, wing roundels) are geometrically displaced along their outward surface normal $\hat{\mathbf{n}}$ by $\epsilon = 0.001\text{ m}$ at export:
    $$\mathbf{v}' = \mathbf{v} + 0.001\hat{\mathbf{n}}$$
  * *Phase 2 (`wgpu` Engine):* Coplanar decal batches are rendered in a dedicated pipeline pass using hardware depth biasing (`DepthBiasState { constant: 2, slope_scale: 2.0, clamp: 0.0 }`).

* **`[I6]` Visual Parity Acceptance Thresholds & VGA $1:1.2$ Aspect Ratio Correction:**
  * Original VGA Mode 13h framebuffers render at $320 \times 200$ pixels displayed on a physical $4:3$ CRT, resulting in non-square pixels stretched vertically by $1.2$:
    $$\text{Aspect}_{\text{physical}} = \frac{320}{200 \times 1.2} = \frac{320}{240} = \frac{4}{3} \approx 1.3333$$
  * All visual parity gates normalize reference DOSBox-X captures to $4:3$ ($320 \times 240$) prior to Structural Similarity (SSIM) evaluation.
  * Off-screen renders (including background sky/horizon palette fills and static stage terrain) must achieve mean $\text{SSIM} \ge 0.88$ for Phase 1 glTF exports and mean $\text{SSIM} \ge 0.90$ for Phase 2 native `wgpu` engine sign-off.

### 2.3 Software Architecture Guardrails

* **`[I2]` Flat Arena Allocation (No Recursive Pointers):**
  * Scene graphs and `.SOD` subobject hierarchies must be stored in flat contiguous vectors (`Vec<SodNode>`) indexed via lightweight integer handles (`NodeId(pub u32)`).
  * Reference-counted pointers (`Rc<RefCell<T>>`, `Arc<Mutex<T>>`), raw pointers, and self-referential lifetimes (`&'a SodNode`) are strictly prohibited in `stunt-core`.

* **`[I3]` Authentic VGA Mode 13h Palette Indexing & Flat Shading:**
  * Geometry preserves original 8-bit VGA palette indices (`0..=255`) inside `SodVertex::palette_index`.
  * In Phase 2, the WGSL vertex-to-fragment stage passes palette and facet lighting indices using `@interpolate(flat)` (disabling bilinear attribute interpolation across triangle interiors) and samples an uncompressed $256 \times 32$ RGBA lookup texture (LUT) representing 256 base colors across 32 discrete directional lighting and atmospheric haze levels.

* **`[I7]` Cleanroom Asset Isolation & Zero-Dependency Core:**
  * Proprietary game binaries and retail data files (`corpus/`, `target_bin/`) are strictly gitignored and never checked into Git or downloaded during CI.
  * `crates/stunt-core` maintains zero OS windowing, GPU, audio, or emulator dependencies so unit and contract tests compile and run 100% offline in $< 2\text{ seconds}$.

* **`[I8]` DOS 8.3 Uppercase Path Normalization:**
  * Because POSIX filesystems are case-sensitive while MS-DOS is case-insensitive, all virtual filesystem (`VfsArchive`) insertions, lookups, and corpus extraction tools normalize filenames to uppercase ASCII (`to_ascii_uppercase()`).

### 2.4 Evidentiary Tiers & Contract Anchor System

* **Evidentiary Confidence Tiers:** Every reverse-engineered binary struct, memory offset, or opcode carries one of four explicit evidentiary tags:
  * **`[Established]`**: Proven directly via disassembled machine code in `PLAYONE.EXE` / `MAKEONE.EXE` or verified via bit-exact runtime memory trap.
  * **`[Supported Inference]`**: Confirmed via cross-file byte alignment and passing trajectory/visual parity gates across multiple corpus files.
  * **`[Bounded Observation]`**: Observed empirically in a single film or fixture; behavior outside observed value ranges remains unverified.
  * **`[Unknown]`**: Unmapped padding bytes or unencountered opcodes; parsers must fail loudly with explicit byte-offset context if encountered.

* **Immutable Contract Anchors:**
  * Permanent bracketed anchor tokens remain invariant:
    * **System Invariants:** `[I1]` through `[I8]`
    * **Format Anchors:** `# [FMT-RES-HEADER]`, `# [FMT-ALL-CHUNKS]`, `# [FMT-SOD-OPCODES]`, `# [FMT-SOD-IFVIS]`, `# [FMT-FLM-OPCODES]`
    * **Runtime Memory Anchors:** `# [MEM-VSYNC-03DA]`, `# [MEM-FLM-TICK]`, `# [MEM-CAMERA-RIG]`, `# [MEM-ACTOR-TABLE]`
  * Verified automatically via `tests/test_doc_invariants.py` inside `mise run check`.

---

## 3. Reverse-Engineering Discoveries & Runtime Mechanics

### 3.1 `PLAYONE.EXE` Binary Structure & MZ/LZEXE Specifications

| Attribute | Ground-Truth Value | Evidentiary Tier | Reference Note |
| :--- | :--- | :--- | :--- |
| **Executable Format** | 16-bit MS-DOS MZ Executable, compressed with **LZEXE 0.91** | `[Established]` | `research/playone-exe/startup.md` |
| **Packed File Size** | $102{,}703\text{ bytes}$ | `[Established]` | `research/playone-exe/startup.md` |
| **Unpacked Image Size** | $201{,}548\text{ bytes}$ | `[Established]` | `research/playone-exe/startup.md` |
| **Unpacked Entry Point** | `CS:IP = 0000:0C5Eh` (relative to load segment) | `[Established]` | `research/playone-exe/startup.md` |
| **Data Segment (`DGROUP`)** | Segment `0x0D51` (unpacked binary file offset `0xD910`) | `[Established]` | `research/playone-exe/memory.md` |

### 3.2 Command Tail Parsing Realities (`0x0C7C`–`0x0CBD`)

Disassembly of `0x0C7C`–`0x0CBD` established:
1. `PLAYONE.EXE` reads the PSP command tail at `PSP:0080h` and inspects **only the first non-whitespace character**.
2. If that character is `'?'` (`0x3F`), it spawns `INSTALL.EXE` via `INT 21h, AH=4Bh`.
3. **All other arguments (such as `playone.exe INTRO.ALL`) are completely ignored.**
See `research/playone-exe/startup.md` for full disassembly.

### 3.3 Modal Navigation, Prefix Searching & BDA Input Injection

Because CLI arguments are ignored, automated capture harnesses must navigate the built-in modal file picker (`0x0787`):
* **Vault Pattern (`DS:0A58`):** Enumerates `VAULT\*.*`.
* **Single-Character Prefix Jumping (`0x5EC6`–`0x5F15`):** The keyboard handler does not buffer words; pressing an alphanumeric key jumps directly to the first file starting with that character.
* **Deterministic Selection Protocol:** Stage only the target film pair (e.g. `VAULT\CTRY.FLM` + `VAULT\CTRY.ALL`) or inject keystrokes via:
  * DOSBox-X `autotype` (`autotype -w 2 -p 0.5 enter c enter`).
  * BIOS Data Area (BDA) circular buffer writes at `0040:001Eh`–`0040:003Dh` (`head: 0040:001A`, `tail: 0040:001C`).
See `research/playone-exe/navigation.md`.

### 3.4 Conventional Memory Partitioning & MCB Layout

`PLAYONE.EXE` enforces three strict startup preconditions (`[Established]`):
1. **`game.cfg` Check (`DS:05AC`):** Validates hardware configuration.
2. **Conventional RAM Gate (`570,000 bytes`):** Requires $\ge 570{,}000\text{ bytes}$ free RAM (`PSP:0002h`). Do not use `loadfix -64` if it drops free RAM below this threshold.
3. **Disk Free Space Gate (`70,000 bytes`):** Calls `INT 21h, AH=36h` ($\ge 70\text{ KB}$ free on mounted drive).

### 3.5 Asset Pairing Dependencies (`.FLM` + `.ALL`)

`PLAYONE.EXE` requires **both** `<NAME>.FLM` and `<NAME>.ALL` in `VAULT\`. If `<NAME>.ALL` is absent, execution halts with `"That film does not have a matching .ALL file"`.

---

## 4. Seam Contracts & Format Anchors

The system integrates strictly across four immutable seams in `crates/stunt-core/src/contracts/`:
* **Seam 1 (`VfsArchive`)**: Unpacks `.RES` (`# [FMT-RES-HEADER]`) and `.ALL` (`# [FMT-ALL-CHUNKS]`) containers.
* **Seam 2 (`TrajectoryRecord` & `FilmCapture`)**: Discrete timeline ticks with cut-awareness (`cut_from_previous`), static stage header, and audio cues (`# [FMT-FLM-OPCODES]`).
* **Seam 3 (`SodModelIr`)**: Flat arena vector of `SodNode` indexed by `NodeId(u32)` (`# [FMT-SOD-OPCODES]`, `# [FMT-SOD-IFVIS]`).
* **Seam 4 (`VisualParityGate`)**: Quantitative SSIM evaluation against aspect-corrected $4:3$ frames (`[I6]`).

---

## 5. Master Verification Matrix

| Gate ID | Verification Scope | Target Seam & Invariants | Execution Command | Required Acceptance Threshold | Runs in Offline CI? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`G01`** | Formatting, Lints, Types & Doc Anchors | All Crates, `python/stunt_reel`, `docs/` | `mise run check` | Exit code `0`; $0$ warnings; all `[I*]`, `# [MEM-*]`, `# [FMT-*]` anchors resolve | **Yes** |
| **`G02`** | Cleanroom VFS Extraction | Seam 1 (`VfsArchive`), `[I7]`, `[I8]` | `cargo test -p stunt-core vfs` | 100% byte match on `synthetic_minimal.res`; uppercase 8.3 lookup | **Yes** |
| **`G03`** | Arena Scene Graph & Attribute Welding | Seam 3 (`SodModelIr`), `[I1]`, `[I2]`, `[I3]` | `cargo test -p stunt-core scene` | `size_of::<SodVertex>() == 28`; flat `NodeId(u32)` arena; sharp facet normals preserved | **Yes** |
| **`G04`** | Synthetic `.FLM`, Cut-Aware `[I4]` & Oracle Parity | Seam 2 (`TrajectoryRecord`), `[I1]`, `[I4]` | `cargo test -p stunt-core trajectory` | $\text{RMSE}_{\text{pos}} \le 0.01\text{ m}$ vs. `oracle_intro_trajectory.json`; $\alpha = 0$ on cuts | **Yes** |
| **`G05`** | Phase 1 glTF 2.0 Visual Parity | Seam 4 (`VisualParityReport`), `[I5]`, `[I6]` | `uv run pytest -m phase1_oracle` | `VisualParityReport::is_passing() == true` ($\text{Mean SSIM} \ge 0.88$) | Local Corpus |
| **`G06`** | Phase 2 Native `wgpu` Visual Parity | Seam 4 (`VisualParityReport`), `[I3]`, `[I5]`, `[I6]` | `cargo test --workspace -- --ignored oracle_parity` | $\text{RMSE}_{\text{pos}} \le 0.01\text{ m}$ and $\text{Mean SSIM} \ge 0.90$ across 600 ticks | Local Corpus |
