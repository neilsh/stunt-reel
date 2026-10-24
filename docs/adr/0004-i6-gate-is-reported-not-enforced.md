# The `[I6]` SSIM gate is reported, not enforced

## Status

accepted; implemented

## Context

`[I6]` in [`AGENTS.md`](../../AGENTS.md) sets two visual parity thresholds on SSIM: 0.88 for initial acceptance and 0.90 for sign-off. Parity work is iterative. Most candidate changes land below the thresholds for a long time, and the sweep tools score many candidates in a row.

The thresholds were previously spread across render tests and the spec. They belong to the parity report, which already computes the mean SSIM the gate reads.

## Decision

The thresholds are constants in the stunt-cli parity module: `I6_INITIAL_SSIM` and `I6_SIGN_OFF_SSIM` in [`parity/mod.rs`](../../crates/stunt-cli/src/parity/mod.rs). The report carries `"i6_gate": {"initial": bool, "sign_off": bool}`, computed from the scored mean SSIM by `i6_gate()`. Neither a failed threshold nor a missing score changes the exit code. A run with no comparable frames still fails, but for the separate reason that it has nothing to score.

## Considered Options

- **Exit non-zero when a gate fails.** Rejected. Every candidate below the threshold would then count as a command failure, which breaks sweeps and scripts that are meant to record negative results.
- **Keep the thresholds in the render tests.** Rejected. The gate is a property of a scored report, and the render tests should not own it.

## Consequences

Callers who need enforcement must read `i6_gate` from `report.json` and decide for themselves. The spec's gate entry should point at the report, not at a test. The thresholds are defined in one place, so changing one requires updating `[I6]` in `AGENTS.md` and `python/stunt_reel/doc_anchors.py` together.
