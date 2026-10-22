# AGENTS.md — Stunt Reel AI Developer Guide

`stunt-reel` is a reverse engineering, analysis, modern reconstruction, and tooling environment for ***Stunt Island*** (1992, Walt Disney Computer Software / The Assembly Line).

---

## 1. Non-Negotiable Directives

1. **Cleanroom Asset Isolation**: **NEVER** commit proprietary assets, executables, or original binary disks into Git (`corpus/` and `target_bin/` are strictly gitignored). All tests must run 100% offline using synthetic cleanroom fixtures in [`tests/fixtures/`](tests/fixtures/README.md).
2. **Quality Gate Requirement**: Before concluding any task or presenting code, **always verify that `mise run check` passes** (format check, lint, typecheck, test across both Rust and Python). See [`README.md`](README.md#development--quality-assurance) and [`mise.toml`](mise.toml).
3. **Architectural Invariants**: All code must conform to system invariants `[I1]`–`[I8]` documented in [`crates/stunt-core/src/contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs):
   - `[I1]` Right-handed metric coordinates (`+X` Right, `+Y` Up, `+Z` Backward, `-Z` Forward).
   - `[I2]` Flat arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`; no `Rc<RefCell<T>>`).
   - `[I3]` Authentic 8-bit VGA Mode 13h palette index color mapping (`0..=255`).
   - `[I4]` Discrete 50 Hz authored simulation ticks with sub-tick interpolation.
   - `[I5]` Coplanar decal identification and normal displacement nudging.
   - `[I6]` Visual parity thresholds (SSIM $\ge 0.88$ initial / $\ge 0.90$ sign-off).
   - `[I8]` DOS 8.3 uppercase path normalization in virtual filesystems.

---

## 2. Documentation Directory & Single Sources of Truth

Refer directly to authoritative documents rather than duplicating definitions:

| Domain | Source of Truth | Summary |
|---|---|---|
|**Domain Glossary**|[`GLOSSARY.md`](GLOSSARY.md)|Canonical project vocabulary: film, slice, tick, trajectory record, epilogue, shape, slot, partial SOD.|
|**System Specification**|[`docs/SPEC.md`](docs/SPEC.md)|Authoritative master specification, mathematical invariants (`[I1]`–`[I8]`), reverse engineering findings, and master verification matrix.|
| **Architecture & 1-Hop Routing** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Routing table connecting code modules to specifications, format anchors (`# [FMT-*]`), and research notes. |
| **Teamwork Blueprint & Milestones** | [`docs/TEAM_SHEET.md`](docs/TEAM_SHEET.md) | Multi-agent team roles (`sentinel`, `re-harness-worker`, `gltf-exporter-worker`, `rust-engine-worker`, `parity-auditor`), file blast radii, and milestone gates. |
| **Runtime Memory Map** | [`docs/MEMORY_MAP.md`](docs/MEMORY_MAP.md) | `DGROUP` (`0x0D51`) offset reference tables, real-mode linear translation, and memory anchors (`# [MEM-*]`). |
| **Seam Contracts** | [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs) | Contract boundaries: [`vfs`](crates/stunt-core/src/contracts/vfs.rs) (Seam 1), [`trajectory`](crates/stunt-core/src/contracts/trajectory.rs) (Seam 2), [`scene`](crates/stunt-core/src/contracts/scene.rs) (Seam 3), and [`parity`](crates/stunt-core/src/contracts/parity.rs) (Seam 4). |
| **Project Setup & Tasks** | [`README.md`](README.md) & [`mise.toml`](mise.toml) | Environment prerequisites, task runner definitions (`check`, `lint`, `fmt`, `typecheck`, `test`, `play`, `mcp`), and manual command fallbacks. |
| **Repository Layout** | [`README.md#project-structure`](README.md#project-structure) | Workspace crate locations, tooling directories, and asset storage rules. |
| **Synthetic Fixtures** | [`tests/fixtures/README.md`](tests/fixtures/README.md) | Cleanroom synthetic mock files (`.res`, `.flm`, `.json`) and binary specifications. |
| **Reference Corpus** | [`corpus/README.md`](corpus/README.md) | Upstream demo archive and community developer package structure (`stisldem/`, `si_archive/`). |
| **Binary Disassembly (Lab Notebook)** | [`research/playone-exe/`](research/playone-exe/) | Reverse engineering notes for `PLAYONE.EXE`: [`startup.md`](research/playone-exe/startup.md), [`navigation.md`](research/playone-exe/navigation.md), and [`memory.md`](research/playone-exe/memory.md). |
| **Coding & Format Rules** | [`Cargo.toml`](Cargo.toml), [`pyproject.toml`](pyproject.toml), [`.editorconfig`](.editorconfig) | Clippy workspace lints, Ruff & Mypy configurations, LF line endings, and 4-space indentation. |

---

## 3. Standard Operating Procedures (SOPs)

### SOP 1: Adding or Modifying File Parsers / Contracts
1. Implement or modify types in [`crates/stunt-core/src/contracts/`](crates/stunt-core/src/contracts/) and re-export in [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs).
2. Synthesize cleanroom test bytes in [`tests/fixtures/`](tests/fixtures/) and document in [`tests/fixtures/README.md`](tests/fixtures/README.md).
3. Add unit and roundtrip tests in `crates/stunt-core/tests/` (verifying with `--all-features`).
4. Run `mise run check` to verify formatting, linter, typechecker, and test pass.

### SOP 2: Documenting Binary Analysis
1. Place research notes under [`research/<binary-name>/`](research/) following the structure of [`research/playone-exe/startup.md`](research/playone-exe/startup.md).
2. Document segment:offset addresses, register states, Mermaid flowcharts, and DGROUP tables.

### SOP 3: Verification & Handoff
1. Run `git status` to ensure no files from `corpus/` or `target_bin/` are staged.
2. Run `mise run check` to ensure all checks pass with zero warnings or errors.
3. Link modified code symbols and files using markdown links.
4. Use Conventional Commit subjects, e.g. `feat(core): add a parser`.

### SOP 4: Living Specification Updates & Evidentiary Promotion
1. When reverse engineering uncovers new runtime offsets, opcodes, or binary realities:
   - Update [`docs/SPEC.md`](docs/SPEC.md) or [`docs/MEMORY_MAP.md`](docs/MEMORY_MAP.md) immediately with verified discoveries.
   - Promote evidentiary tiers (`[Unknown]` $\rightarrow$ `[Bounded Observation]` $\rightarrow$ `[Supported Inference]` $\rightarrow$ `[Established]`) and cite the linear address or research note.
2. If extending Seam contracts in [`crates/stunt-core/src/contracts/`](crates/stunt-core/src/contracts/):
   - Add fields using backward-compatible defaults (`#[cfg_attr(feature = "serde", serde(default))]`).
   - Update synthetic test fixtures in [`tests/fixtures/`](tests/fixtures/) and contract unit tests.
   - Verify `mise run check` exits code `0` before marking any ticket complete.
