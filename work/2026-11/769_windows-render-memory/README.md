---
title: "Add a committed way to measure a headless render's peak and stage RSS"
started: 2026-11-19
issue: 769
outcome: "`--report-memory` (#789) prints a headless render's stage memory and peak; its Windows reading ran unchanged on the RTX 4070 and on lavapipe, and LOCATION's figures there are in research/parity/evidence-limits.md section 3."
---

# Add a committed way to measure a headless render's peak and stage RSS

The flag landed in #789 and is documented in [`measure-a-renders-memory.md`](../../../docs/howto/measure-a-renders-memory.md).
This folder's [journal](journal.md) holds the Windows run.

## Handoff

Done: the Windows path ran on the RTX 4070 and on lavapipe with stores byte-identical, and the figures are in [`lavapipe-render-time.md` § 7](../../../research/parity/lavapipe-render-time.md#7-memory-per-worker).
Left: nothing for #769.
