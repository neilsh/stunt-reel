# Team Sheet & Ticket Status

Process only: who owns which files, and where each ticket stands. It is **not** a source of truth for the system. Requirements, invariants and gates are in [`SPEC.md`](../SPEC.md); layouts and evidence are in `research/`; decisions are recorded in [`adr/`](../adr/). Each ticket row below is a status plus links to where its substance lives; findings are never recorded in this file.

---

## 1. Roles & File Blast Radii

The roles below are automation personas used by the development workflow, not people.

| Role | Domain | Allowed file blast radius |
|---|---|---|
| **`sentinel`** | Orchestration: dispatches tickets, enforces branch isolation, reviews handoffs | `docs/process/TEAM_SHEET.md`, PR reviews |
| **`re-harness-worker`** | DOSBox-X harness and memory analysis | `python/stunt_reel/tac/`, `research/playone-exe/memory-map.md`, `research/playone-exe/`, `tests/test_harness.py` |
| **`gltf-exporter-worker`** *(retired; the exporter is now `crates/stunt-gltf/`, owned by `rust-engine-worker`)* | Baseline `.SOD` mesh ingest and glTF export | `crates/stunt-gltf/` (formerly `python/stunt_reel/gltf/`, `tests/test_gltf.py`) |
| **`rust-engine-worker`** | Rust engine | `crates/stunt-core/`, `crates/stunt-render/`, `crates/stunt-cli/` |
| **`parity-auditor`** | Quality gate and asset-isolation verification | Read-only across all code; runs `mise run check` and the gates in [`SPEC.md` § 5](../SPEC.md#5-master-verification-matrix) |
| **`tooling-worker`** | Repository tooling and harness policy | `mise.toml`, `python/scripts/`, `tests/conftest.py`, `tests/test_formats_catalog.py`, `docs/harness.md`, `docs/harness-setup.md`, `docs/process/plans/` |

---

## 2. Milestones & Tickets

### Milestone 1: Runtime Capture Harness & glTF Exporter *(Gate 1 passed)*

| Ticket | Title | Owner | Status | Links |
|---|---|---|---|---|
| `T00` | Scaffolding, contracts and fixtures | `rust-engine-worker` | Done | [`contracts/`](../../crates/stunt-core/src/contracts/mod.rs), [`tests/fixtures/README.md`](../../tests/fixtures/README.md) |
| `T01` | DOSBox-X harness and navigation | `re-harness-worker` | Done | [`client.py`](../../python/stunt_reel/tac/client.py), [`bda.py`](../../python/stunt_reel/tac/bda.py), [`navigation.md`](../../research/playone-exe/navigation.md) |
| `T02` | Real-mode memory map and V-Sync trap | `re-harness-worker` | Done (address conflict open) | [`memory-map.md`](../../research/playone-exe/memory-map.md), [`vsync.py`](../../python/stunt_reel/tac/vsync.py) |
| `T03` | Trajectory streamer and oracle export | `re-harness-worker` | Done (camera/actor layouts unverified live) | [`streamer.py`](../../python/stunt_reel/tac/streamer.py), [`memory-map.md`](../../research/playone-exe/memory-map.md) |
| `T04` | Baseline mesh ingest and glTF exporter | `gltf-exporter-worker` | Done | [`stunt-gltf/`](../../crates/stunt-gltf/), [`sod.md`](../../research/formats/sod.md) |

### Milestone 2: Native Rust Engine *(Gate 2 passed)*

| Ticket | Title | Owner | Status | Links |
|---|---|---|---|---|
| `T05` | Native VFS (`.ALL` / `.RES` parsers) | `rust-engine-worker` | Done | [`vfs/`](../../crates/stunt-core/src/vfs/), [`res.md`](../../research/formats/res.md), [`all.md`](../../research/formats/all.md) |
| `T06` | Procedural `.SOD` bytecode transpiler | `rust-engine-worker` | Done | [`sod/`](../../crates/stunt-core/src/sod/), [`sod.md`](../../research/formats/sod.md) |
| `T07` | Native `.FLM` player and parity suite | `rust-engine-worker` | Done | [`flm/`](../../crates/stunt-core/src/flm/), [`flm.md`](../../research/formats/flm.md) |
| `T08` | `wgpu` presentation engine | `rust-engine-worker` | Done | [`stunt-render/`](../../crates/stunt-render/), [`stunt-cli/`](../../crates/stunt-cli/) |

### Milestone 3: Fidelity Backlog *(Open)*

Origin: the `CTRY.FLM` + `CTRY.ALL` export audit. Each ticket is independent. Findings: [`research/parity/`](../../research/parity/).

| Ticket | Title | Owner | Status | Links |
|---|---|---|---|---|
| `T09` | `OP_TAP` (`0x022E`) semantics | `rust-engine-worker` | Done | [`sod-vm.md`](../../research/playone-exe/sod-vm.md), [`sod.md` `# [FMT-SOD-TAP]`](../../research/formats/sod-opcodes.md#23-terrain-anchor-load-op_tap-0x022e--fmt-sod-tap), [ADR 0001](../adr/0001-sod-tap-anchor-table.md) |
| `T10` | `OP_ANIMATE` (`0x01F8`) semantics | `rust-engine-worker` | **Open** | [`sod-animate.md`](../../research/playone-exe/sod-animate.md), [`sod.md` `# [FMT-SOD-ANIMATE]`](../../research/formats/sod-opcodes.md#24-animation-resource-draw-op_animate-0x01f8--fmt-sod-animate) |
| `T11` | Consume `tick_duration` in playback and export | `rust-engine-worker` | Done | [`timeline-and-ticks.md`](../../research/formats/concepts/timeline-and-ticks.md), [`flm.md` § 2.1.1](../../research/formats/flm.md#211-tick_duration-semantics--corpus-distribution), [`memory.md` § 3.2](../../research/playone-exe/memory.md#32-tick-counter-evidence) |
| `T12` | `--tick-range A..=B` (0-based, inclusive) replaces `--frames`; `--frames` becomes an error that names it | `rust-engine-worker` | **Open** | [`config.rs`](../../crates/stunt-cli/src/config.rs), [`headless.rs`](../../crates/stunt-cli/src/headless.rs) |
| `T13` | Typed serde render sidecar `render.json` (still reads `palette_controls.json`; records width, height, viewport_rows), required by parity; `parity_probe.py` drops its hard-coded 320/185/16 | `rust-engine-worker` | **Done** (landings 1-4) | [ADR 0005](../adr/0005-parity-requires-the-render-sidecar.md), [`parity/`](../../crates/stunt-cli/src/parity/), [`parity_probe.py`](../../python/scripts/parity_probe.py) |
| `T14` | One film clock range `0..=total_ticks`; the window wraps at `% (total_ticks + 1)` | `rust-engine-worker` | **Open** | [`config.rs`](../../crates/stunt-cli/src/config.rs) |
| `T15` | Typed parity report, once `T12`–`T14` show what `FrameScore` and the per-film summary need | `rust-engine-worker` | **Open** (deferred) | [`score.rs`](../../crates/stunt-cli/src/parity/score.rs) |

### Milestone 4: Architecture Deepening *(Complete)*

Four design units from the architecture review, worked in order A-D. Each unit's brief lives in [`docs/process/plans/architecture-deepening/`](plans/architecture-deepening/README.md) and records the interface, migration, test survival and kill criteria. Implementation is one PR per unit, each requiring `mise run check` green and an unchanged local parity baseline. Owners are assigned when implementation starts.

| Ticket | Title | Owner | Status | Links |
|---|---|---|---|---|
| `A01` | Render artifact seam: typed render/capture port, one adapter per language, report-aggregation rider | - | **Done** (landings 1-4 merged) | [brief](plans/architecture-deepening/A-render-artifact.md), [ADR 0005](../adr/0005-parity-requires-the-render-sidecar.md) |
| `A02` | Decoded shape seam: one stop decision, a shape IR that owns its invariants, partial SOD as a value | - | **Done** (merged 2026-10-25) | [brief](plans/architecture-deepening/B-decoded-shape.md) |
| `A03` | Renderer entry point: one renderer interface for headless and window | - | **Done** (all stages merged) | [brief](plans/architecture-deepening/C-renderer-entry.md) |
| `A04` | Capture session: one emulator session with an injectable transport; transport at operation altitude | - | **Done** (merged; live capture and probe verified 2026-10-25) | [brief](plans/architecture-deepening/D-capture-session.md) |

### Milestone 5: Retro Hardening *(Implementation in progress)*

Source: [retro-hardening plan](plans/retro-hardening-2026-10-25.md), agreed 2026-10-25. One branch/PR; commits per ticket; the full `mise run check` runs once at the tip.

| Ticket | Title | Owner | Status | Links |
|---|---|---|---|---|
| `T16` | Verify the fresh-worktree `pytest` cache assumption | `tooling-worker` | **Done** (verified; no change) | [plan](plans/retro-hardening-2026-10-25.md), [salvage note](plans/review-dsh-friction-salvage.md) |
| `T17` | Tier checker ignores nested bracket expressions | `tooling-worker` | **Done** | [plan](plans/retro-hardening-2026-10-25.md), [`verify_formats_docs.py`](../../python/scripts/verify_formats_docs.py) |
| `T18` | Writer policy for Agent Teams | `tooling-worker` | **Done** | [plan](plans/retro-hardening-2026-10-25.md), [harness.md](../../docs/harness.md) |
| `T19` | `mise run build-at` for a previous revision | `tooling-worker` | **Done** | [plan](plans/retro-hardening-2026-10-25.md), [mise.toml](../../mise.toml) |
| `T20` | Commit-reference convention and programme pointer | `sentinel` | **Done** | [plan](plans/retro-hardening-2026-10-25.md), [ARCHITECTURE.md](../../docs/ARCHITECTURE.md) |


---

## 3. Documentation Revision Protocol

1. **Findings** (any worker): record new offsets, opcodes and observations in the document that owns them (see [`research/README.md`](../../research/README.md) for where each kind of finding goes), with a tier from [`SPEC.md` § 2.4](../SPEC.md#24-evidentiary-tiers--contract-anchor-system). Promote a tier only with a cited address, disassembly or live read.
2. **Ticket status** (`sentinel`): edit the status column above.
3. **Contracts and invariants** (`parity-auditor`-gated): changes under `crates/stunt-core/src/contracts/` stay backward compatible (`serde(default)`), update `tests/fixtures/` and tests in the same change, and must leave `mise run check` green.
