# stunt-reel

Tooling, automation, and analysis environment for *Stunt Island* (1992) film reels (`.FLM`), demos, and game executables using DOSBox-X and agentic debugging workflows.

---

## Requirements

- **[DOSBox-X](https://dosbox-x.com/) `2026.10.01`** (recommended build with debugger support enabled)
- **[`dosbox-x-mcp-server`](https://github.com/caiiiycuk/dosbox-x-mcp-server)** (MCP server for controlling the DOSBox-X debugger via AI agents)

---

## Setup

### 1. DOSBox-X Installation
1. Install **DOSBox-X `2026.10.01`** on your system and make `dosbox-x.exe` available on `PATH`.
2. Ensure configuration batch scripts (e.g., `play_ctry.bat`) can resolve `dosbox-x.exe` from `PATH`.

### 2. DOSBox-X MCP Server Installation
Download the server binary or build from source:

- **Pre-built binary**: Download `dosbox-x-mcp-server-v0.1.2-x86_64-pc-windows-msvc.exe` from the [GitHub Releases](https://github.com/caiiiycuk/dosbox-x-mcp-server/releases), install it, and make it available on `PATH`.
- **Build with Cargo**:
  ```powershell
  git clone https://github.com/caiiiycuk/dosbox-x-mcp-server.git
  cd dosbox-x-mcp-server
  cargo build --release
  ```

### 3. Antigravity MCP Configuration
To allow Antigravity agents to control and inspect DOSBox-X during sessions, register the MCP server in your global configuration file (`~/.gemini/config/mcp_config.json`):

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

---

## Project Structure

- `corpus/` — Reference data, demo files, and film vaults (e.g., `corpus/stisldem/VAULT/`).
- `target_bin/` — Full target game binaries, sound drivers, and resource files.
- `capture/` — Output captures, logs, and traces.
- `dosbox-playone.conf` — DOSBox-X configuration file tailored for running `PLAYONE.EXE` film playback with auto-type sequences.
- `play_ctry.bat` — Convenience runner launching DOSBox-X with `dosbox-playone.conf`.

---

## Quick Start

Launch a film reel playback test:

```powershell
.\play_ctry.bat
```
