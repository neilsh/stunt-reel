# Playbook: Milestone 1 — Runtime Capture Harness & glTF Exporter

> **Historical.** Milestone 1 shipped; this plan is kept for context and is not a source of truth. Current status: [`TEAM_SHEET.md`](../TEAM_SHEET.md); specification: [`SPEC.md`](../SPEC.md).

* **Milestone**: Milestone 1 (`T01`–`T04`)
* **Integrity Mode**: `development`
* **Assigned Team**:
  - `Sentinel` (Coordinator / PR Gatekeeper)
  - `re-harness-worker` (DOSBox-X MCP & Memory Reverse Engineering: `python/stunt_reel/tac/`, `docs/MEMORY_MAP.md`)
  - `gltf-exporter-worker` (3D Exporter & Asset Pipeline: `python/stunt_reel/gltf/`)
  - `parity-auditor` (Quality Gate & Cleanroom Verification)
* **Working Directory**: `repository root`

---

## 1. Context & Objective

Treat `PLAYONE.EXE` as an authoritative black-box kinematics compiler running inside headless DOSBox-X. Stream 600 continuous simulation ticks of trajectory data, package self-contained animated `.glb` assets, and emit the golden trajectory oracle (`corpus/oracle/intro_trajectory.json`) and visual parity sign-off for Phase 1.

### Reference Specifications
- System Specification: [`docs/SPEC.md`](../SPEC.md)
- Team Blueprint: [`docs/TEAM_SHEET.md`](../TEAM_SHEET.md)
- Runtime Memory Map: [`docs/MEMORY_MAP.md`](../MEMORY_MAP.md)
- Seam Contracts: [`crates/stunt-core/src/contracts/`](../../crates/stunt-core/src/contracts/mod.rs)
- Synthetic Fixtures: [`tests/fixtures/`](../../tests/fixtures/README.md)

---

## 2. Requirements

### R1. Dual-Mode DOSBox-X Capture Harness & BDA Input Injection (T01)
Implement a capture harness under `python/stunt_reel/tac/` supporting dual operation: a live TCP socket client connecting to `dosbox-x-mcp-server` (default `localhost:58991`) and an offline synthetic mock/replay interface for automated offline test suites. Automate navigation through `PLAYONE.EXE`'s modal film selection dialog (`0x0787`) via BIOS Data Area (BDA) keystroke buffer injection or autotype, navigating directly to the target film without CLI parameters.

### R2. Post-Retrace Port 0x03DA V-Sync Trap & Memory Map Promotion (T02)
Isolate vertical blank polling on VGA I/O port `0x03DA` (`BPIO 03DA`) and set an execution breakpoint immediately after the vertical retrace loop completes. Gate frame snapshots on increments of `PLAYONE.EXE`'s internal `.FLM` simulation tick counter (`[MEM-FLM-TICK]`) to eliminate mid-frame tearing and discard duplicate 70 Hz display frames. As memory layouts for camera rigs (`[MEM-CAMERA-RIG]`) and actor tables (`[MEM-ACTOR-TABLE]`) are verified, update `docs/MEMORY_MAP.md` promoting evidentiary tags to `[Established]` per SOP 4.

### R3. Trajectory Streamer & Golden Oracle Export (T03)
Stream 600 continuous simulation ticks into `corpus/oracle/intro_trajectory.json` conforming strictly to Seam 2 (`TrajectoryRecord`) contracts, unit quaternions, and right-handed metric coordinates `[I1]`. Extract camera eye, target, focal distance / FOV, and actor world transforms with zero matrix tearing.

### R4. Baseline SOD Mesh Ingest & glTF 2.0 Exporter (T04)
Ingest baseline `.SOD` geometries in `python/stunt_reel/gltf/` based on historical `RIPRES.C` / `DECODE.C` specifications. Apply coplanar decal normal displacement ($\epsilon = 0.001\text{ m}$) along outward normals per invariant `[I5]`. Sample streamed trajectories into glTF node hierarchies and skeletal/rigid animations to emit valid, self-contained `.glb` files (`build/gltf_output/INTRO.glb`).

### R5. Offline Test Coverage & Dependency Management
Provide comprehensive unit and integration tests in `tests/test_harness.py` and `tests/test_gltf.py` that execute against offline synthetic fixtures without requiring a running DOSBox-X process. Minimal runtime dependencies (e.g. for glTF serialization or numerical operations) may be added to `pyproject.toml` provided they maintain strict type safety under `mypy` and pass `mise run check`.

### R6. Cleanroom Verification, Licensing Attribution & Gate 1 Sign-Off
Enforce cleanroom asset isolation `[I7]`: all proprietary files and capture dumps remain in gitignored paths (`corpus/` or `target_bin/`), while CI relies purely on synthetic fixtures in `tests/fixtures/`. Any open-source reference logic must contain clear licensing attribution. The final delivery must satisfy Gate 1 acceptance and achieve exit code 0 on `mise run check`.

---

## 3. Acceptance Checklist

### Capture Harness & V-Sync Trap (T01, T02)
- [ ] Harness connects to live `dosbox-x-mcp-server` over TCP port 58991 when active.
- [ ] Offline synthetic mock/replay runner executes in pytest without external process requirements.
- [ ] Modal file picker navigation successfully injects filename keystrokes into the BIOS keyboard buffer.
- [ ] Breakpoint triggers post-VGA retrace on port `0x03DA` with tick deduplication ($70\text{ Hz}$ presentation → $50\text{ Hz}$ simulation).
- [ ] `docs/MEMORY_MAP.md` updated with verified offsets and promoted to `[Established]` where confirmed.

### Trajectory Streamer & Golden Oracle (T03)
- [ ] `corpus/oracle/intro_trajectory.json` records 600 simulation ticks validated against `TrajectoryRecord` schema (`crates/stunt-core/src/contracts/trajectory.rs`).
- [ ] Zero quaternion normalization errors ($|\|\mathbf{q}\| - 1.0| < 10^{-4}$) and zero matrix tearing across all ticks.
- [ ] Position root-mean-square error satisfies $\text{RMSE}_{\text{pos}} \le 0.01\text{ m}$ against baseline fixture.

### glTF 2.0 Exporter & Visual Parity (T04, Gate 1)
- [ ] `build/gltf_output/INTRO.glb` passes standard glTF 2.0 validation with valid node hierarchy and animation samplers.
- [ ] Coplanar decals are displaced along surface normals by $\epsilon = 0.001\text{ m}$ (`[I5]`).
- [ ] Off-screen render achieves mean $\text{SSIM} \ge 0.88$ (`[I6]`) against reference Mode 13h frames normalized to 4:3 ($320 \times 240$).

### Repository Integrity & Quality Gate
- [ ] `mise run check` exits code 0 with zero warnings across Ruff, Mypy, Clippy, Rust tests, and Python tests.
- [ ] `git status` verifies no proprietary binaries or dumps from `corpus/` or `target_bin/` are staged (`[I7]`).
- [ ] All new Python tests (`tests/test_harness.py`, `tests/test_gltf.py`) pass offline in CI.
- [ ] Any open-source reference code included contains appropriate attribution notices.
