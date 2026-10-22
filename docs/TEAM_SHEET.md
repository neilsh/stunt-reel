# Team Sheet & Ticket Status

Process only: who owns which files, and where each ticket stands. It is **not** a source of truth for the system. Requirements, invariants and gates are in [`SPEC.md`](SPEC.md); layouts and evidence are in `research/`; decisions are recorded in [`adr/`](adr/). Each ticket row below is a status plus links to where its substance lives; findings are never recorded in this file.

---

## 1. Roles & File Blast Radii

| Role | Domain | Allowed file blast radius |
|---|---|---|
| **`sentinel`** | Orchestration: dispatches tickets, enforces branch isolation, reviews handoffs | `docs/TEAM_SHEET.md`, PR reviews |
| **`re-harness-worker`** | DOSBox-X harness and memory reverse engineering | `python/stunt_reel/tac/`, `docs/MEMORY_MAP.md`, `research/playone-exe/`, `tests/test_harness.py` |
| **`gltf-exporter-worker`** | Baseline `.SOD` mesh ingest and glTF export | `python/stunt_reel/gltf/`, `tests/test_gltf.py` |
| **`rust-engine-worker`** | Cleanroom Rust engine | `crates/stunt-core/`, `crates/stunt-render/`, `crates/stunt-cli/` |
| **`parity-auditor`** | Quality gate and cleanroom verification | Read-only across all code; runs `mise run check` and the gates in [`SPEC.md` § 5](SPEC.md#5-master-verification-matrix) |

---

## 2. Milestones & Tickets

### Milestone 1: Runtime Capture Harness & glTF Exporter *(Gate 1 passed)*

Playbook (historical): [`playbooks/m1-runtime-capture.md`](playbooks/m1-runtime-capture.md).

| Ticket | Title | Owner | Status | Links |
|---|---|---|---|---|
| `T00` | Cleanroom scaffolding, contracts and fixtures | `rust-engine-worker` | Done | [`contracts/`](../crates/stunt-core/src/contracts/mod.rs), [`tests/fixtures/README.md`](../tests/fixtures/README.md) |
| `T01` | DOSBox-X harness and navigation | `re-harness-worker` | Done | [`client.py`](../python/stunt_reel/tac/client.py), [`bda.py`](../python/stunt_reel/tac/bda.py), [`navigation.md`](../research/playone-exe/navigation.md) |
| `T02` | Real-mode memory map and V-Sync trap | `re-harness-worker` | Done (address conflict open) | [`MEMORY_MAP.md`](MEMORY_MAP.md), [`vsync.py`](../python/stunt_reel/tac/vsync.py) |
| `T03` | Trajectory streamer and oracle export | `re-harness-worker` | Done (camera/actor layouts unverified live) | [`streamer.py`](../python/stunt_reel/tac/streamer.py), [`MEMORY_MAP.md`](MEMORY_MAP.md) |
| `T04` | Baseline mesh ingest and glTF exporter | `gltf-exporter-worker` | Done | [`gltf/`](../python/stunt_reel/gltf/), [`sod.md`](../research/formats/sod.md) |

### Milestone 2: Native Cleanroom Rust Engine *(Gate 2 passed)*

| Ticket | Title | Owner | Status | Links |
|---|---|---|---|---|
| `T05` | Native VFS (`.ALL` / `.RES` parsers) | `rust-engine-worker` | Done | [`vfs/`](../crates/stunt-core/src/vfs/), [`res.md`](../research/formats/res.md), [`all.md`](../research/formats/all.md) |
| `T06` | Procedural `.SOD` bytecode transpiler | `rust-engine-worker` | Done | [`sod/`](../crates/stunt-core/src/sod/), [`sod.md`](../research/formats/sod.md) |
| `T07` | Native `.FLM` player and parity suite | `rust-engine-worker` | Done | [`flm/`](../crates/stunt-core/src/flm/), [`flm.md`](../research/formats/flm.md) |
| `T08` | `wgpu` presentation engine | `rust-engine-worker` | Done | [`stunt-render/`](../crates/stunt-render/), [`stunt-cli/`](../crates/stunt-cli/) |

### Milestone 3: Fidelity Backlog *(Open)*

Origin: the `CTRY.FLM` + `CTRY.ALL` export audit. Each ticket is independent. Findings: [`parity-findings.md`](../research/parity-findings.md).

| Ticket | Title | Owner | Status | Links |
|---|---|---|---|---|
| `T09` | `OP_TAP` (`0x022E`) semantics | `rust-engine-worker` | Done | [`sod-vm.md`](../research/playone-exe/sod-vm.md), [`sod.md` `# [FMT-SOD-TAP]`](../research/formats/sod.md#314a-terrain-anchor-load-op_tap-0x022e--fmt-sod-tap), [ADR 0001](adr/0001-sod-tap-anchor-table.md) |
| `T10` | `OP_ANIMATE` (`0x01F8`) semantics | `rust-engine-worker` | **Open** | [`sod-animate.md`](../research/playone-exe/sod-animate.md), [`sod.md` `# [FMT-SOD-ANIMATE]`](../research/formats/sod.md#314b-animation-resource-draw-op_animate-0x01f8--fmt-sod-animate) |
| `T11` | Consume `tick_duration` in playback and export | `rust-engine-worker` | Done | [`timeline-and-ticks.md`](../research/formats/concepts/timeline-and-ticks.md), [`flm.md` § 2.1.1](../research/formats/flm.md#211-tick_duration-semantics--corpus-distribution), [`memory.md` § 3.2](../research/playone-exe/memory.md#32-tick-counter-evidence) |

---

## 3. Documentation Revision Protocol

1. **Findings** (any worker): record new offsets, opcodes and observations in the document that owns them ([`MEMORY_MAP.md`](MEMORY_MAP.md) for offsets, `research/` for evidence and formats), with a tier from [`SPEC.md` § 2.4](SPEC.md#24-evidentiary-tiers--contract-anchor-system). Promote a tier only with a cited address, disassembly or live read.
2. **Ticket status** (`sentinel`): edit the status column above.
3. **Contracts and invariants** (`parity-auditor`-gated): changes under `crates/stunt-core/src/contracts/` stay backward compatible (`serde(default)`), update `tests/fixtures/` and tests in the same change, and must leave `mise run check` green.
