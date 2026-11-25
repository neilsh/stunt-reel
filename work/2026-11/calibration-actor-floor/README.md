---
title: "Calibrate the error readout only on actors a grader can see"
started: 2026-11-25
outcome: "Actors-removed calibration sheets need 64 actor pixels (a convention, MIN_ACTOR_PIXELS) and a calibration needs six of them to be conclusive; INTRO seed 1 stays a FAIL and INTRO then passed twice in a row under DSH on the same six removals. The seven 20-category readouts are DSH's; its two passes move a category count by at most 1, so min_change 4 stands. A baseline refresh waits: aircraft-colour-wrong has no two-model example and the CTRY calibration is Hydrogen's, not DSH's (journal)."
---

# Calibrate the error readout only on actors a grader can see

An `INTRO.FLM` calibration of the error readout failed on 2026-11-25 because two of its six actors-removed sheets had almost nothing to remove.
See the [journal](journal.md); the finding lives in [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3.
