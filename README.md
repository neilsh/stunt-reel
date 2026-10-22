# stunt-reel

Reverse-engineering, analysis, and reconstruction workspace for *Stunt Island* (1992, Walt Disney Computer Software / The Assembly Line): a DOSBox-X harness for the original `PLAYONE.EXE`, cleanroom Rust and Python parsers, a native `wgpu` renderer (`stuntreel`), and a parity loop that scores rendered frames against frames captured from the original player.

The living specification is [`docs/SPEC.md`](docs/SPEC.md) — goals, invariants `[I1]`–`[I8]`, evidentiary tiers, and the verification matrix. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) routes each module to its specification anchor and research note; [`AGENTS.md`](AGENTS.md) holds the contributor and agent rules.

---

## Requirements

- **[mise](https://mise.jdx.dev/)** (recommended environment and tool manager)
- **[Rust](https://www.rust-lang.org/)** 2024 edition (rustc ≥ 1.88), managed via `mise` or `rustup`
- **[uv](https://docs.astral.sh/uv/)** and **Python ≥ 3.11**, managed via `mise` or standalone
- **[DOSBox-X](https://dosbox-x.com/) `2026.10.01`** (Windows x64 portable SDL2 build, installed by `mise`)
- **[`dosbox-x-mcp-server`](https://github.com/caiiiycuk/dosbox-x-mcp-server) `0.1.2`** (managed via `mise`)
- **Java 21 (Temurin)** and **Kaitai Struct Compiler `0.11`** (managed via `mise`; needed only for the `.ksy` corpus checks)

---

## Setup

### 1. mise

```powershell
mise install          # pinned toolchains, DOSBox-X, Kaitai compiler
uv sync --all-groups  # Python virtualenv plus dev tools (ruff, mypy, pytest, kaitaistruct)
```

Pinned versions live in [`mise.toml`](mise.toml); the `kaitaistruct==0.11` runtime is installed by `uv sync` for the schema checks.

### 2. Agent / MCP integration

```powershell
mise run ensure-dosbox   # start DOSBox-X with the MCP debugger enabled (no-op if already running)
mise run mcp             # launch dosbox-x-mcp-server over stdio
```

Register the server in the agent's MCP configuration file (`~/.gemini/config/mcp_config.json`) and make sure `dosbox-x-mcp-server` is on `PATH`:

```json
{
  "mcpServers": {
    "dosbox-x": {
      "command": "dosbox-x-mcp-server",
      "args": []
    }
  }
}
```

> [!NOTE]
> DOSBox-X profiles connect *out* to the control port via `[dosbox] mcp_server = 58991`. `mise run capture-ref` binds that port itself, so stop the MCP server and any other DOSBox-X instance before capturing.

---

## Project Structure

| Path | Contents |
| --- | --- |
| `crates/stunt-core/` | Seam contracts, `.RES`/`.ALL`/`.SOD`/`.FLM` parsers, and the `.SOD` bytecode VM |
| `crates/stunt-render/` | `wgpu` pipelines, Mode 13h palette LUT, headless renderer, SSIM/IoU comparator |
| `crates/stunt-cli/` | `stuntreel` binary: interactive/headless presentation plus the `parity` subcommand |
| `python/stunt_reel/tac/` | DOSBox-X TAC harness: control transport, BIOS Data Area input, frame capture — [`research/playone-exe/capture.md`](research/playone-exe/capture.md) |
| `python/stunt_reel/gltf/` | `.SOD`/`.FLM` glTF 2.0 exporter |
| `python/scripts/` | Entry points: `capture_playone_reference.py`, `verify_schemas_corpus.py`, `verify_formats_docs.py`, `adversarial_formats_challenge.py` |
| `tests/` | Python suite and cleanroom fixtures — [`tests/fixtures/README.md`](tests/fixtures/README.md); Rust integration tests live in `crates/*/tests/` |
| `docs/` | Living spec, architecture routing, memory map, team blueprint, and milestone playbooks |
| `research/` | Format specifications beside their `.ksy` layouts plus `PLAYONE.EXE` analysis notes — [`research/formats/INDEX.md`](research/formats/INDEX.md) |
| `corpus/` | Gitignored demo and archive data — [`corpus/README.md`](corpus/README.md) |
| `target_bin/` | Gitignored original game binaries |
| `build/` | Gitignored outputs: `build/parity/{reference,ours,report}/` and `build/gltf_output/` |
| `dosbox-*.conf` | `dosbox-playone.conf` (interactive play), `dosbox-parity.conf` (capture), `dosbox-mcp.conf` (agent debugger), `test_mcp.conf` |
| `play_ctry.bat` | Convenience launcher for `mise run play` |

---

## Workflows

### Play a film in the original player

```powershell
mise run play        # or: .\play_ctry.bat
```

`dosbox-playone.conf` mounts `corpus/stisldem`, launches `PLAYONE.EXE`, and queues the autotype sequence that selects `CTRY.FLM`.

### Capture reference frames and score a render

```bash
mise run capture-ref
cargo run -p stunt-cli -- --headless corpus/stisldem/VAULT/CTRY.FLM \
    --all corpus/stisldem/VAULT/CTRY.ALL --frames 1..1344 \
    --sidata corpus/si_archive/Developer/FreeFlight/SIDATA \
    --out-dir build/parity/ours/ctry --width 320 --height 200
cargo run -p stunt-cli -- parity --reference build/parity/reference/ctry \
    --test build/parity/ours/ctry --output build/parity/report/ctry --clear-index 233
```

`capture-ref` stores 140 reference frames, each tagged in `meta.json` with the film clock (`film_tick`) it was captured at. `--frames 1..1344` (also the default range) renders ticks 0 through 1,342, the film's last tick included, as `tick_00000.png`–`tick_01342.png`, named by 0-based 50 Hz tick (the end-hold captures sit at tick 1,342), and the comparator pairs each capture with the render at its `film_tick` (captures made before film-clock tagging must be recaptured). The comparator writes `report.json` (per-frame `ssim`/`iou`, `mean_ssim`, `min_ssim`, `mean_iou`, `sky_index`, `unmatched`) and `contact_NNNN.png` sheets under `build/parity/report/ctry/`.

Prerequisites: `corpus/stisldem/VAULT/CTRY.FLM` and `CTRY.ALL`, and a free port `58991`. How the dialog is driven (BIOS Data Area keystrokes) and how frames are sampled (post-retrace breakpoint at `0D51:0C5E`) is recorded in [`docs/SPEC.md § 3.6`](docs/SPEC.md#36-visual-parity-capture-loop-playoneexe-vs-stuntreel) and [`research/playone-exe/capture.md`](research/playone-exe/capture.md).

### Render in the native engine

```powershell
cargo run -p stunt-cli -- corpus/stisldem/VAULT/CTRY.FLM --all corpus/stisldem/VAULT/CTRY.ALL
```

Opens the interactive presentation (Space pauses, C toggles authored/free camera, WASD/QE fly the free camera, Esc exits). Interactive playback follows the authored 50 Hz timeline and interpolates between slices. `--help` lists the headless flags, `--frames <A..B>` (half-open, 1-based 50 Hz tick ordinals), `--ticks`, and the `parity` subcommand. `ANCHORPT.DAT`, `MAP.BIN`, and `SCENERY.scn` are searched for in `--sidata <dir>` first, then the archive's directory, its parent and grandparent, then `sidata/` or `SIDATA/` inside the parent (filename case ignored); the demo's `corpus/si_archive/Developer/FreeFlight/SIDATA` needs an explicit `--sidata`.

### Export a film to video container

```powershell
# Export film sequence to an MP4 video sampled at 30 fps
cargo run -p stunt-cli -- --headless corpus/stisldem/VAULT/CTRY.FLM \
    --all corpus/stisldem/VAULT/CTRY.ALL --video build/ctry.mp4
```

Headless video export samples the authored 50 Hz timeline at `--fps` (default 30), interpolates between slices, and encodes directly into a standard video container (`.mp4`, `.webm`, `.mkv`, or `.avi`) via `ffmpeg`, with physical $4:3$ aspect ratio correction ($320 \times 240$, `[I6]`). `--frames <A..B>` limits the export to a half-open range of 1-based tick ordinals. `CTRY.FLM` spans 1,342 ticks (26.84 s), producing 806 sampled frames at 30 fps; the container is trimmed to the authored span, so ffmpeg encodes 805 frames and ffprobe reports 26.833 s (nearest whole frame; 26.84 s exactly at `--fps 50`). Requires `ffmpeg` on `PATH`.

### Interval-based frame capture for rapid audits

```powershell
# Capture one frame every 25 ticks (0.5 s) across the full 1,342-tick film
cargo run -p stunt-cli -- --headless corpus/stisldem/VAULT/CTRY.FLM \
    --all corpus/stisldem/VAULT/CTRY.ALL --frames 1..1343 --frame-step 25 \
    --out-dir build/parity/ours/ctry_sparse
```

`--frames` uses 1-based 50 Hz tick ordinals; `--frame-step <N>` extracts every Nth tick, saving frames named by 0-based tick (`tick_00000.png`, `tick_00025.png`, etc.) without redundant disk consumption. `--sample-count <N>` writes `sample_0001.png`… (1-based sample index) instead; those are not parity inputs.

### Validate the format catalog against a local corpus

```powershell
mise run verify-corpus              # report anomalies
mise run verify-corpus -- --strict  # fail on them
```

Compiles `research/formats/**/*.ksy` and checks documented headers, offsets, and opcodes against `corpus/`. Local-only: `corpus/` is gitignored and absent in CI.

---

## Development & Quality Assurance

The gate is `mise run check`, which chains formatting, linting, strict typing, and both test suites. Individual tasks:

| Task | Runs |
| --- | --- |
| `check` | `fmt-check` + `lint` + `typecheck` + `test` + `doc` + `check-rust-matrix` |
| `fmt-check` / `fmt` | `cargo fmt` and `ruff format` check/apply |
| `lint` | `cargo clippy -- -D warnings` and `ruff check .` |
| `typecheck` | `uv run mypy` (strict) |
| `doc` | rustdoc with `RUSTDOCFLAGS=-D warnings` |
| `check-rust-matrix` | `stunt-core` without the `serde`/`bytemuck` features |
| `test` | `cargo test --workspace --all-features` and `uv run pytest` |
| `fmt-rust`, `fmt-py`, `fmt-check-rust`, `fmt-check-py`, `lint-rust`, `lint-py`, `test-rust`, `test-py` | single-language halves of the tasks above |
| `cov-py` | `pytest` with `--cov=stunt_reel` term-missing report (no fail-under) |
| `deny` | `cargo deny check` — advisories, license allow-list, wildcard bans, and registry sources |
| `capture-ref` | reference capture into `build/parity/reference/ctry` (`--max-frames` defaults to 140) |
| `verify-corpus` | `.ksy` catalog check against `corpus/` |
| `play` | launch `dosbox-playone.conf` |
| `ensure-dosbox`, `mcp` | agent debugger plumbing |

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) invokes the mise tasks instead of restating them: Ubuntu runs the full `mise run check` gate, Windows runs the non-GPU subset (`fmt-check lint typecheck test-py`), a separate job checks the declared MSRV (`1.88`), and a `cargo deny` job enforces the dependency policy. Corpus- and DOSBox-X-dependent tasks stay local. Optional git hooks mirror the gate; see [`.pre-commit-config.yaml`](.pre-commit-config.yaml).

Equivalent direct commands:

```powershell
cargo check --workspace
cargo clippy --workspace --all-targets --all-features
cargo fmt --check
cargo test --workspace --all-features
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

---

## Documentation Map

| Document | Covers |
| --- | --- |
| [`docs/SPEC.md`](docs/SPEC.md) | Master specification, invariants `[I1]`–`[I8]`, evidentiary tiers, verification matrix |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 1-hop module routing to specification anchors and research notes |
| [`docs/MEMORY_MAP.md`](docs/MEMORY_MAP.md) | `DGROUP` map and runtime anchors (`# [MEM-*]`) |
| [`docs/TEAM_SHEET.md`](docs/TEAM_SHEET.md) | Multi-agent roles and file blast radii |
| [`docs/playbooks/`](docs/playbooks/) | Milestone playbooks |
| [`research/formats/INDEX.md`](research/formats/INDEX.md) | Format catalog and Kaitai layouts |
| [`research/playone-exe/`](research/playone-exe/) | Startup, navigation, memory map, and capture harness notes |
| [`corpus/README.md`](corpus/README.md) | How to populate the demo and archive data |
| [`tests/fixtures/README.md`](tests/fixtures/README.md) | Cleanroom fixture specifications |
| [`AGENTS.md`](AGENTS.md) | Contributor directives and standard operating procedures |
