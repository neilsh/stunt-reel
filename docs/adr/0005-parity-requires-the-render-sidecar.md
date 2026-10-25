# Parity requires the render sidecar

## Status

accepted; implemented

## Context

Parity scores a frame's brightness against the film's fade. Today the fade can come from two places. The first is the authored brightness the film sets in palette control 14, read from a palette sidecar written next to the render. The second is the fade measured from the captured palette. The scorer uses `authored.unwrap_or(measured)`, so a render directory without a sidecar silently falls back to the measurement, and the score changes meaning without any warning.

The sidecar is currently named `palette_controls.json` ([`headless.rs`](../../crates/stunt-cli/src/headless.rs)). Its loader returns an empty map when the file is absent ([`parity/frames.rs`](../../crates/stunt-cli/src/parity/frames.rs)). The probe script also hard-codes the render size.

## Decision

Parity requires the sidecar. A render directory without it is an error, and `authored.unwrap_or(measured)` is removed. The measured fade stays in the report as a cross-check only and no longer decides `scored`. The sidecar is renamed `render.json`, and the old name is still read. It becomes a typed serde struct shared by the writer and parity, and it records width, height and viewport rows so that `parity_probe.py` can drop its constants. The film clock is one inclusive range, `0..=total_ticks`.

## Considered Options

- **Keep the measured fallback.** Rejected. It lets a missing file change what a score means.
- **Keep the untyped JSON and add the fields by convention.** Rejected. The writer and the reader would drift apart without a type that both use.

## Consequences

Renders made before the sidecar existed can no longer be scored. Re-rendering is the fix, and the error should say so. Current state, for reference: `score.rs` still has the `unwrap_or(fade)` fallback, `render.json` is not written or read, the sidecar is still `palette_controls.json`, and `parity_probe.py` still hard-codes 320, 185 and 16 ([`python/scripts/parity_probe.py`](../../python/scripts/parity_probe.py)). The work is tickets `T13` and `T14` in [`TEAM_SHEET.md`](../process/TEAM_SHEET.md).

## Implementation note

Landings 1-2 of the architecture deepening programme implemented this decision.
`render.json` is typed, written last beside the legacy `palette_controls.json`,
and parity requires one of the two documents, refusing a directory with neither
and naming the re-render action. The measured fade is a cross-check only:
`scored` comes from the authored brightness, and a tick with no authored entry is
not excluded. The documents are defined by the versioned port in
[ADR 0011](0011-parity-artifacts-are-a-versioned-port.md). `T13` is complete;
`T14` (the film-clock range) remains a separate ticket.
