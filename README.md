# stunt-reel

Tooling, automation, and analysis environment for *Stunt Island* (1992) film reels (`.FLM`), demos, and game executables using DOSBox-X and agentic debugging workflows.

---

## Requirements

- **[mise](https://mise.jdx.dev/)** (recommended environment & tool manager)
- **[Rust](https://www.rust-lang.org/)** (managed via `mise` or `rustup`, 2024 edition)
- **[uv](https://docs.astral.sh/uv/)** & **Python 3.11+** (managed via `mise` or standalone)
- **[DOSBox-X](https://dosbox-x.com/) `2026.10.01`** (managed automatically via `mise`)
- **[`dosbox-x-mcp-server`](https://github.com/caiiiycuk/dosbox-x-mcp-server)** (managed automatically via `mise`)

---

## Setup

### 1. Automatic Setup with mise (Recommended)

Run:

```powershell
mise install
```

This automatically downloads and configures:
- **Rust Toolchain** (`rustc`, `cargo`, `rustfmt`, `clippy`)
- **Python 3.11** & **uv**
- **DOSBox-X `2026.10.01`** (64-bit portable build)
- **`dosbox-x-mcp-server` `v0.1.2`** (Windows x86_64 binary)

Initialize the Python virtual environment and developer tools:

```powershell
uv sync --all-groups
```

### 2. Antigravity MCP Configuration

Register the MCP server in your global configuration file (`~/.gemini/config/mcp_config.json`) using `dosbox-x-mcp-server`, which must be available on `PATH`:

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
> When Antigravity starts the MCP server over stdio, the server listens locally on TCP port `58991` (or WebSocket `58992`). DOSBox-X can connect to this control port to enable remote debugger execution (`debug_exec`), memory queries, and breakpoint hooks.

### 3. Alternative / Manual Installation

If not using `mise`:
- **DOSBox-X**: Install **DOSBox-X `2026.10.01`** and make its binaries, including `dosbox-x.exe`, available on `PATH`.
- **`dosbox-x-mcp-server`**: Download `dosbox-x-mcp-server-v0.1.2-x86_64-pc-windows-msvc.exe` from [GitHub Releases](https://github.com/caiiiycuk/dosbox-x-mcp-server/releases), install it, and make it available on `PATH`.

---

## Project Structure

- `docs/` — Living specification (`SPEC.md`), 1-hop architecture (`ARCHITECTURE.md`), Antigravity Teamwork blueprint (`TEAM_SHEET.md`), and runtime memory maps (`MEMORY_MAP.md`).
- `crates/` — Rust workspace crates (`stunt-core`, `stunt-render`).
- `python/` — Python tooling and automation modules (`stunt_reel`).
- `tests/` — Test suites for Rust and Python components.
- `research/` — Reverse engineering documentation and binary analysis lab notebook (e.g., `research/playone-exe/`).
- `corpus/` — Reference data, demo files, and film vaults (e.g., `corpus/stisldem/VAULT/`).
- `target_bin/` — Full target game binaries, sound drivers, and resource files.
- `capture/` — Output captures, logs, and traces.
- `dosbox-playone.conf` — DOSBox-X configuration file tailored for running `PLAYONE.EXE` film playback with auto-type sequences.
- `play_ctry.bat` — Convenience runner launching DOSBox-X via `mise`.
- `mise.toml` — Tool versions and task definitions.

---

## Development & Quality Assurance

Run the complete verification pipeline (formatting, linting, typechecking, tests):

```powershell
mise run check
```

Or individual tasks via `mise`:

| Command | Description | Underlying Tooling |
|---|---|---|
| `mise run check` | Run entire CI verification suite | All linters, formatters, tests |
| `mise run lint` | Lint both Rust and Python | `cargo clippy` & `uv run ruff check` |
| `mise run fmt` | Format all code | `cargo fmt` & `uv run ruff format` |
| `mise run fmt-check` | Check code formatting | `cargo fmt --check` & `uv run ruff format --check` |
| `mise run typecheck` | Static type checking | `uv run mypy` |
| `mise run test` | Run Rust & Python test suites | `cargo test` & `uv run pytest` |

You can also run tool commands directly:

```powershell
# Rust
cargo check --workspace
cargo clippy --workspace --all-targets --all-features
cargo fmt --check
cargo test --workspace

# Python (uv)
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

---

## Quick Start

Launch a film reel playback test:

```powershell
mise run play
```

Or via the batch runner:

```powershell
.\play_ctry.bat
```
