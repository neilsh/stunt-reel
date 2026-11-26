---
title: "Refresh the seven-film readout baseline to the 19-category taxonomy"
started: 2026-11-25
issue: 1086
outcome: "The seven 19-category readouts and baseline.toml were refreshed from the e09f8ff6 sheets of the dd7e76eb lavapipe render, with two DSH passes and a Sonnet tie-break; BOMB's background-misregistration is 3 of 12 by the tie-break alone (the DSH passes counted 12 and 0), so min_change 4 is not established for DSH and its repeatability remains open."
---

# Refresh the seven-film readout baseline to the 19-category taxonomy

Issue [#1086](https://github.com/neilsh/stunt-reel/issues/1086) added `propeller-solid`, removed `aircraft-colour-wrong` and calibrated the 19-category file in PR [#1085](https://github.com/neilsh/stunt-reel/pull/1085).
This follow-up replaces the seven committed readouts and [`baseline.toml`](../../../research/parity/readouts/baseline.toml) with the same 12 sheets per film graded under the 19-category taxonomy.

See the [journal](journal.md) for the counts, provenance and the BOMB disagreement.
