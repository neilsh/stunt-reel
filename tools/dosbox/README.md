# DOSBox-X configurations

Profiles for running the original *Stunt Island* programs under DOSBox-X. Each one mounts a
path **relative to the repository root**, so launch them from the root (the `mise` tasks and
`play_ctry.bat` do). None of them ship game files: `corpus/` comes from the shared data root
([`corpus/README.md`](../../corpus/README.md)).

| File | Used by | Purpose |
|---|---|---|
| `dosbox-playone.conf` | `mise run play`, `play_ctry.bat` | Interactive playback: mounts `corpus/stisldem`, starts `PLAYONE.EXE` and autotypes the `CTRY.FLM` selection |
| `dosbox-parity.conf` | `mise run capture-ref`, `probe-light` | Parity capture profile; the harness rewrites its mount and film literals into a staged copy ([`research/playone-exe/capture.md`](../../research/playone-exe/capture.md)) |
| `dosbox-mcp.conf` | `mise run ensure-dosbox`, `mcp` | Agent debugger with the MCP server on port `58991` |
| `dosbox-utils.conf` | by hand | Period utilities from `build/utils`, no MCP server ([`research/stunt-exe/sets.md`](../../research/stunt-exe/sets.md)) |
| `play_ctry.bat` | by hand | Windows shortcut for `mise run play` |
