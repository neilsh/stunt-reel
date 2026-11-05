# Breakpoints run on DOSBox-X; capture stays on dosbox-automation

## Status

accepted 2026-11-04, for [#65](https://github.com/neilsh/stunt-reel/issues/65) and
[#66](https://github.com/neilsh/stunt-reel/issues/66): `mise run debug-x`
([`debug_x.py`](../../python/scripts/debug_x.py), [`dbx/`](../../python/scripts/dbx/)).

## Context

Both questions end in "which instruction does this": which code calls the light setup `0x9100`
and with what, and which code writes a ground record's colour byte. Capture runs on
dosbox-automation ([ADR 0025](0025-capture-runs-are-plans-not-sessions.md)), which has no
debugger: it has no breakpoints, pause or step, only memory reads and writes between frames
([`capture-dosbox-automation.md`](../../research/playone-exe/capture-dosbox-automation.md) § 1).
A memory write cannot be attributed to an instruction from there.

DOSBox-X v2026.10.01, which the retired capture harness used, has a debugger reachable over a
TCP link (`mcp_server`), with code, memory and interrupt breakpoints
([`dosbox-x-legacy.md`](../../research/playone-exe/dosbox-x-legacy.md) § 1–2). A 2026-11-04
spike hit `0x9100` and the film clock's writer through it.

## Decision

Breakpoint work runs on DOSBox-X's built-in debugger link: one-shot TOML plans
(`tools/dosbox-x/plans/`), one boot per plan, JSON lines per hit under
`<data root>/debug/<film>/`. Capture, per-frame sampling and parity stay on dosbox-automation.
Findings are recorded at image and file offsets only, never as emulator-specific linear
addresses, so they carry across the two emulators.

The controller speaks the link directly, not through `dosbox-x-mcp-server`: the link is the
same in every harness, a `mise run` task is pre-approved, and the plan file records exactly what
was asked. It lives in `python/scripts/` beside `build_pairing.py`, whose pairing maps plan
offsets onto Patch #3 and whose iced-x86 decoder names a watch stop's writer
([ADR 0033](0033-build-pairing-decodes-with-iced-x86.md)).

## Considered Options

- **A code hook on dosbox-automation** (a patched jump into a stub that logs registers to a
  ring buffer). Rejected: it rebuilds part of a debugger (stub assembler, ring, patch-safety
  rules, timing of the patch against the loader) and still cannot see memory writes, which #65's
  last step needs.
- **The MCP server for agents.** Rejected: tied to the harness that registers it, not scriptable
  through `mise run`, and it would hold a session where a plan suffices.
- **A held debugger session per question.** Rejected for the reason ADR 0025 gives for capture:
  a plan is reproducible and reviewable; a session is neither.

## Consequences

- DOSBox-X is pinned again in `mise.toml`, Windows only, for this tool alone.
- The debugger does not halt guest time while the controller reads a stop, so every hit records
  its own film tick and no finding rests on the order or spacing of hits.
- `BPM` fires on a changed value, so a watch sees every changing write, not every write.
- `BPM` arms with a stored value of `00`, so each watched byte that is not zero stops once,
  spuriously, right after arming. The runner's writer filter drops these, but they count in a
  probe's `spurious` total and its spurious records.
- The layout differs from dosbox-automation's (load paragraph `0x0824` against `0x01F5`); the
  tool reads it from `DOS MCBS` each run.
