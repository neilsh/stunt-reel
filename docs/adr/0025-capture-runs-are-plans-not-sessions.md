# Capture runs are plans, not sessions

## Status

accepted 2026-10-30; supersedes [ADR 0021](0021-capture-chooses-its-control-port.md).

## Context

Capture, the lighting probe, `make-all` and `play` drove DOSBox-X through its debugger socket:
the controller listened, the emulator dialled in, and the guest was halted at the post-retrace
trap so Python could read a frame, its palette and the film clock one at a time. dosbox-automation
(0.85.1) exposes a REST and Lua API instead. Lua runs on the emulation thread under an
instruction limit, cannot pause or step the guest, and returns strings through a bounded output
store. There is no halted guest to read from.

## Decision

A run is a **plan**. The first pass is a Lua trace that records, for each emulated frame, the film
clock, the global tick and whether the page changed. Python picks the frames worth keeping from
that trace. The second pass replays the same boot and dumps the picked pages, the working palette
(`DS:0x2768`) and any extra memory ranges, at most `MAX_DUMPS` pages per pass because a pass of 90
ran out of Lua memory. The dump pass's own trace is compared with the first; a mismatch is
`PlanDivergence`, so frames are never filed under another run's ticks.

Each run stages its conf and mount together under `<data root>/stage/<film>-<label>/` (the emulator
refuses a mount under the checkout), picks a free port at launch, and gets a fresh random bearer
token through the environment only. `play` and `make-all` use the same staging; `make-all` presses
its keys with a script and polls `GET /video/text` for the return to a text mode.

## Consequences

- `session.py`, the DOSBox-X process and debugger transports, `ensure-dosbox`, the `mcp` task and the
  checked-in DOSBox-X confs are gone. The offline streamer model stays, because the Rust oracle
  cites `streamer.py` as its kinematic reference.
- Pages are read between emulated frames without a retrace wait, so a page can tear; the rule for
  judging one is in [`method.md`](../../research/parity/method.md) § 3.1 and is not yet applied in `pick`.
- Existing references (`references.toml`) were captured on DOSBox-X; promoting a new-path capture
  is a separate reviewed edit after a rescore.
- A run costs a replay of the boot per dump pass, so a long film takes several passes instead of
  one halted session.
