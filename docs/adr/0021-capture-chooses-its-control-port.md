# Capture chooses its own control port

## Status

accepted 2026-10-29; supersedes the machine-wide capture lock of
[ADR 0008](0008-worktrees-share-one-read-only-data-root.md).

A capture session binds port 0 — the OS picks — and launches DOSBox-X with
`-set "dosbox mcp_server=<port>"`, so the port DOSBox-X dials is the port the
controller actually holds. `capture-ref` had instead hardcoded `58991` in one
constant, two transport defaults and four profiles, and on 2026-10-28 a smoke capture
failed with `WinError 10013` because Windows had put that number inside a Hyper-V/WSL
excluded range (58949–59048). Those ranges are carved out of the dynamic range and
move across reboots, so the failure was never a single bad port: it is a week of
failures that only someone reading `netsh interface ipv4 show excludedportrange` can
explain. Binding port 0 removes the class of failure instead of retrying past it.

The machine-wide lock goes with it. "One capture at a time" was never a requirement;
it was a side effect of the fixed port. A second capture now owns a second port, a
second DOSBox-X and a stage mount of its own, so neither session can damage the other's
run. The guest's emulated work per tick is fixed (`core = normal`, `cycles = 8000`), but
the sampling loop asks for one retrace hit at a time, so load can shift which retrace a
frame is taken at; see Consequences. No lock file replaces it: this
codebase already keeps per-process scratch (`stunt_tac_read_<pid>.bin` in
[`transport.py`](../../python/stunt_reel/tac/transport.py)) rather than global locks.

## What enforces this

- **The bind.** [`ListenTransport.listen()`](../../python/stunt_reel/tac/transport.py)
  binds `self.port` (0 by default) and returns the port the OS gave it.
  [`DosboxX.start()`](../../python/stunt_reel/tac/emulator.py) passes that value to
  DOSBox-X through `launch_argv()` — the one construction `ensure_dosbox.py` also
  uses — and announces it as
  `WaitingForGuest(port)`, so the `[capture] waiting for DOSBox-X on 127.0.0.1:<port>`
  line prints the real port. `CONTROL_PORT` is gone.
- **The tests.** [`test_tac_capture_session.py`](../../tests/test_tac_capture_session.py)
  covers two sessions binding distinct advertised ports, the argv DOSBox-X is launched
  with (`-set dosbox mcp_server=…` alone; a launch that set only `-set debugger
  mcp_server=…` never dialled, so the profiles' duplicate `[debugger]` lines did
  nothing), and port 0 reporting what it bound. The "two sessions cannot hold one port" test is deleted with the rule
  it encoded.
- **The stage mount.** [`stage_film()`](../../python/stunt_reel/tac/staging.py)
  builds a mount named after the capture process ([`stage_dir`](../../python/stunt_reel/parity_layout.py))
  and [`run_session`](../../python/stunt_reel/tac/session.py) removes it after the
  emulator stops. The fixed port had hidden this: one shared
  `build/parity/stage/<film>` meant a second capture of the same film deleted the tree
  the first was emulating from, and the machine-wide lock was what kept that from
  happening.
- **The interactive launch.** `dosbox-mcp.conf` carries no port either:
  [`ensure_dosbox.py`](../../python/scripts/ensure_dosbox.py) takes the port the MCP
  server reports through `dosbox_mcp_port` and passes it through the same
  `launch_argv()`. That
  server prefers `58991` and falls back to another free port on **any** bind error,
  including an excluded range, reporting whichever it chose — which is why a conf pin
  would leave DOSBox-X dialling a port nothing holds.

## Considered Options

- **Keep the fixed port and retry the bind.** `WinError 10013` is not transient within
  a boot: the same number cannot succeed until `winnat` restarts, so a retry loop would
  turn a one-line error into a hang.
- **Pick a fixed port below 49152 instead.** 47991 is outside the dynamic range, so it
  cannot be excluded — but it is still one number for the machine, which serialises
  again, and still a claim the OS can contradict.
- **Move the interactive profiles below 49152 too.** Rejected: `dosbox-x-mcp-server`
  compiles `DEFAULT_CONTROL_PORT = 58991` in and takes no port argument, so a profile
  pinning 47991 would dial a port nothing listens on. Asking the server for its port is
  the same mechanism this ADR introduces, applied to the other direction of the wire.
- **A lock file in place of the port.** Rejected: it would preserve a serialisation
  nobody asked for, and add a second thing to clean up after a crashed session.

## Consequences

Two captures still contend for the machine's cores. `LAUNCH_TIMEOUT_SECONDS` and the
dialog-settle budgets are wall-clock, so a second session can spend them; a timeout is
then a scheduling measurement, not a reason to bring the lock back. 

Frames are not interchangeable between runs, and this change did not make them so: a
solo capture and the shared reference disagree at three of the four film ticks they
share (32, 54 and 65 differ; 43 matches), and the same raster appears at tick 54 in one
run and tick 55 in another. The trap samples whichever retrace it stops on, so a
frame's declared film tick can sit beside a raster that belongs to its neighbour. Two
simultaneous captures inherit that, so a concurrent pair is a workflow convenience, not
a way to produce interchangeable reference sets.

Two sessions writing the same shared capture directory under `STUNT_DATA_WRITE=1` are
the operator's business: the write guard is a consent gate, not a concurrency gate.

The interactive debugger still depends on `58991` being bindable in one narrow sense —
the MCP server tries it first — but nothing on this side pins it any more, so an
excluded range costs one extra tool call, not a broken session.
