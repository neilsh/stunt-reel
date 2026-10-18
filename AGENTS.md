# AGENTS.md — Stunt Reel AI Agent Guide

Welcome to **stunt-reel**. This document defines the architectural principles, system contracts, repository conventions, quality gates, and standard operating procedures (SOPs) for AI agents collaborating on this codebase.

---

## 1. Project Overview & Mission

`stunt-reel` is a reverse engineering, analysis, modern reconstruction, and tooling environment for ***Stunt Island*** (1992, Walt Disney Computer Software / The Assembly Line).

The goals of the project are:
1. **File Format & Container Reverse Engineering**: Parse and extract proprietary assets, including resource containers (`.RES`, `.ALL`), 3D polygon models (`.SOD`), visual font tables (`.BIN`), and scripted film reels (`.FLM`).
2. **Deterministic Kinematic Playback**: Faithfully evaluate film timelines, actor placement, camera choreography, and sound events across discrete simulation ticks.
3. **Modern Real-Time Rendering & Parity**: Render extracted 3D scene graphs in modern graphics pipelines while validating visual equivalence against historical DOSBox-X output via automated visual parity gates.
4. **Agentic DOSBox-X Emulation & Dynamic Tracing**: Leverage DOSBox-X and `dosbox-x-mcp-server` to inspect real-mode DOS memory, hook into binary execution (`PLAYONE.EXE`), and capture runtime oracle traces.

---

## 2. Core Architectural Invariants & Seam Contracts

The system architecture is structured around four immutable boundaries ("seams") defined in [`crates/stunt-core/src/contracts/`](crates/stunt-core/src/contracts/):

```
┌────────────────────────────────────────────────────────────────────────┐
│ Seam 1: VfsArchive                                                     │
│ Container Ingest & Decompression (.RES, .ALL)                          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Unpacked .FLM / .SOD byte slices
                                    ▼
┌───────────────────────────────────┴────────────────────────────────────┐
│ Seam 2: TrajectoryRecord                  Seam 3: SodModelIr           │
│ Discrete Kinematic Timeline (20/30 Hz)    Procedural 3D Scene Graph    │
│ Camera & Actor transforms per tick        Flat arena & GPU-ready nodes │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Rendered Frames vs. DOSBox Grabs
                                    ▼
┌───────────────────────────────────┴────────────────────────────────────┐
│ Seam 4: VisualParityGate                                               │
│ Headless SSIM / perceptual comparison (Threshold: >= 0.88 / 0.90)      │
└────────────────────────────────────────────────────────────────────────┘
```

### The 4 Seam Contracts

| Seam | Type / Contract | Module | Responsibility |
|---|---|---|---|
| **Seam 1** | `VfsArchive`, `VfsEntry` | `contracts::vfs` | Ingests `.RES` and `.ALL` archives, extracts payloads, normalizes filenames. |
| **Seam 2** | `TrajectoryRecord`, `CameraTransform`, `ActorTransform`, `AudioCue` | `contracts::trajectory` | Discrete flight choreography, camera positions, entity poses, and audio events per tick. |
| **Seam 3** | `SodModelIr`, `SodNode`, `SodVertex`, `NodeId` | `contracts::scene` | Procedural 3D scene graph intermediate representation, flat arena storage, vertex packing. |
| **Seam 4** | `VisualParityReport` | `contracts::parity` | Automated headless visual regression gate comparing modern renders to DOSBox-X ground truth. |

### Architectural Invariants

All code, parsers, and transformers must adhere strictly to these invariants:

| ID | Invariant | Specification |
|---|---|---|
| `[I1]` | **Metric Coordinate Basis** | Right-handed 3D Cartesian coordinates: `+X` = Right, `+Y` = Up, `+Z` = Toward viewer / backward (`-Z` = Forward). Coordinates must be stored in meters. |
| `[I2]` | **Flat Arena Allocation** | Scene graphs must be flat contiguous vectors (`Vec<SodNode>`) indexed by `NodeId(u32)`. Self-referential smart pointer cycles (`Rc<RefCell<T>>`, `Arc<Mutex<T>>`) are strictly prohibited in core IR. |
| `[I3]` | **VGA Mode 13h Palette** | Surface materials and vertex color fields store authentic 8-bit VGA Mode 13h color indices (`0..=255`) mapped to standard game palette tables. |
| `[I4]` | **Decoupled Simulation Ticks** | Simulation evaluates at fixed discrete rates (20 Hz or 30 Hz ticks). Sub-tick rendering must use linear or spherical (`slerp`) transform interpolation. |
| `[I5]` | **Coplanar Decal Handling** | Decals and surface markings coplanar with parent geometry must carry decal bitflags and receive unit normal nudges to eliminate Z-fighting. |
| `[I6]` | **Visual Parity Gate** | Automated visual comparison requires Mean SSIM $\ge 0.88$ for early phases and $\ge 0.90$ for final sign-off against reference emulation captures. |
| `[I8]` | **DOS 8.3 Uppercase Normalization** | Virtual filesystem keys and asset references must always be normalized to uppercase ASCII 8.3 format (e.g. `PLANE.SOD`, not `plane.sod` or `Plane.Sod`). |

---

## 3. Cleanroom & Asset Isolation Policy

> [!CAUTION]
> **Proprietary Asset Isolation Rule**:
> Do NOT commit proprietary game assets, executables, or original binary disks into git.

- **`corpus/`** and **`target_bin/`** are explicitly ignored by `.gitignore`. They contain original demo files, central archive dumps, and extracted binaries for local reverse engineering.
- **Continuous Integration is 100% Offline & Synthetic**:
  - Tests running in CI (GitHub Actions) must **only** depend on synthetic cleanroom fixtures stored in [`tests/fixtures/`](tests/fixtures/).
  - If a test requires specific container structures or opcodes, synthesize a minimal binary fixture using cleanroom knowledge (e.g. [`tests/fixtures/synthetic_minimal.res`](tests/fixtures/synthetic_minimal.res)).

---

## 4. Repository Layout & File Ownership

```
stunt-reel/
├── .github/workflows/          # Continuous integration definitions (ci.yml)
├── capture/                    # Emulation dumps, frame captures, debug logs (gitignored)
├── corpus/                     # Historical demo archives & developer materials (gitignored)
├── crates/
│   ├── stunt-core/             # Rust workspace crate: core data models, contracts, math, parsers
│   │   ├── src/contracts/      # Seam contract specifications (vfs, trajectory, scene, parity)
│   │   └── tests/              # Contract and synthetic fixture integration tests
│   └── stunt-render/           # Rust workspace crate: modern renderer & display pipeline
├── python/
│   └── stunt_reel/             # Python package: tooling, CLI helpers, analysis scripts
├── research/
│   └── playone-exe/            # Disassembly analysis, memory maps, navigation mechanics
├── target_bin/                 # Extracted binary files for analysis (gitignored)
├── tests/
│   ├── fixtures/               # Committed cleanroom synthetic fixtures & JSON oracles
│   ├── test_fixtures.py        # Python fixture verification tests
│   └── test_smoke.py           # Smoke test suite
├── dosbox-mcp.conf             # DOSBox-X configuration with remote debugger control enabled
├── dosbox-playone.conf         # DOSBox-X configuration configured for film reel autotype playback
├── mise.toml                   # Toolchain pins & centralized task runner definitions
├── pyproject.toml              # Python build setup, Ruff linter/formatter, and Mypy rules
└── Cargo.toml                  # Workspace Rust manifest and clippy lint rules
```

---

## 5. Toolchain & Quality Assurance Commands

The environment is managed via **[mise](https://mise.jdx.dev/)**. Agents should prefer using `mise run <task>` to ensure identical execution between local environments and CI.

### Primary Verification Task

Before completing any task or presenting code changes, **always run the full check suite**:

```powershell
mise run check
```

This runs formatting checks, linting, typechecking, and unit tests across both Rust and Python in parallel.

### Individual Task Reference

| Task | Command | Underlying Action |
|---|---|---|
| **Full CI Suite** | `mise run check` | Runs `fmt-check`, `lint`, `typecheck`, `test` |
| **Lint All** | `mise run lint` | `cargo clippy --workspace --all-targets --all-features` & `uv run ruff check .` |
| **Format All** | `mise run fmt` | `cargo fmt` & `uv run ruff format` |
| **Format Check** | `mise run fmt-check` | `cargo fmt --check` & `uv run ruff format --check .` |
| **Type Check** | `mise run typecheck` | `uv run mypy` (strict mode) |
| **Run All Tests** | `mise run test` | `cargo test --workspace --all-features` & `uv run pytest` |
| **Run Rust Tests** | `mise run test-rust` | `cargo test --workspace --all-features` |
| **Run Python Tests** | `mise run test-py` | `uv run pytest` |
| **Launch Playback** | `mise run play` | Runs `dosbox-x -conf dosbox-playone.conf` |
| **Launch MCP Server**| `mise run mcp` | Starts `dosbox-x-mcp-server` (TCP `58991`) |

### Direct Command Fallbacks

If running commands outside `mise`:

```powershell
# Rust checks
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo fmt --check
cargo test --workspace --all-features

# Python checks (via uv)
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

---

## 6. Coding Standards & Conventions

### Rust Standards

1. **Edition & Version**: Rust 2024 edition, MSRV 1.85+.
2. **Clippy Rules**: Deny `unused_must_use`. Warnings treated as errors in CI. Never suppress warnings with blanket `#[allow(...)]` without documenting justification.
3. **Feature Hygiene**: Features like `serde` and `bytemuck` are optional in `stunt-core`. Always verify tests compile and pass both with and without features enabled (use `--all-features` for full contract suites).
4. **Memory & Types**:
   - Pack GPU vertex types with `#[repr(C)]` and maintain 4-byte alignment (`SodVertex`).
   - Use `NodeId(u32)` indices rather than heap pointers or nested references.
   - Use `std::path::Path` / `PathBuf` for all filesystem paths (cross-platform Windows/Linux compatibility).
5. **Errors & Panics**: Library code must return `Result<T, E>`. Avoid `unwrap()` and `expect()` outside of test code.

### Python Standards

1. **Python Version**: Python 3.11+.
2. **Type Annotations**: Enforce strict typing (`tool.mypy` with `strict = true`). All new functions, parameters, and return types must be fully annotated.
3. **Formatting & Linting**: Managed by Ruff (line length 100). Run `mise run fmt-py` and `mise run lint-py`.
4. **Path Handling**: Always use `pathlib.Path`, never raw string path concatenation.

### File Endings & Formatting

Per [`.editorconfig`](.editorconfig):
- Text files use **LF** line endings.
- Always insert a trailing newline at the end of files.
- Indentation: 4 spaces for Rust and Python, 2 spaces for YAML, JSON, and TOML.

---

## 7. Emulation & DOSBox-X Automation

For runtime reverse engineering and trajectory capture:
- **Port Assignment**: `dosbox-x-mcp-server` communicates with DOSBox-X over local TCP port `58991`.
- **Playback Autotype**: `dosbox-playone.conf` automates `PLAYONE.EXE` by typing commands directly into the keyboard buffer (`autotype -w 2 -p 0.5 enter c enter`).
- **Research Documentation**: Findings from static disassembly or runtime hooks must be recorded in [`research/`](research/) with memory addresses, register expectations, and behavior flowcharts (see [`research/playone-exe/startup.md`](research/playone-exe/startup.md) as the gold standard).

---

## 8. Agent Standard Operating Procedures (SOPs)

### SOP 1: Introducing or Updating File Format Parsers
1. Identify the specification rules and invariants (e.g. `[fmt res]`, `[fmt flm]`, `[fmt sod]`).
2. If modifying or adding contracts, update [`crates/stunt-core/src/contracts/`](crates/stunt-core/src/contracts/) and re-export in [`crates/stunt-core/src/contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs).
3. If new fixtures are needed, synthesize cleanroom minimal binary bytes in [`tests/fixtures/`](tests/fixtures/) and document their layout in [`tests/fixtures/README.md`](tests/fixtures/README.md).
4. Add unit tests verifying both roundtrip parsing and edge cases (e.g., malformed magic headers, truncated entries, bounds checking).
5. Run `mise run check` to ensure all linters, typecheckers, and test suites pass.

### SOP 2: Documenting Binary Reverse-Engineering Findings
1. Place research notes under [`research/<binary-name>/`](research/).
2. Maintain structured documentation:
   - Executable specifications (entry point, header paragraphs, relocation entries).
   - Low-level disassembly snippets (with segment:offset addresses and annotated opcodes).
   - Flowcharts / state diagrams using Mermaid where appropriate.
   - DGROUP data tables and memory maps.

### SOP 3: Finalizing Changes
Before concluding any task or reporting completion:
1. Verify no unintended files or binaries in `corpus/` or `target_bin/` are staged in git (`git status`).
2. Run `mise run check`. All stages (`fmt-check`, `lint`, `typecheck`, `test`) must pass with zero errors and zero warnings.
3. Link referenced files using clickable markdown links with file schemes.
