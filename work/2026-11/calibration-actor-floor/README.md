---
title: "Calibrate the error readout only on actors a grader can see"
started: 2026-11-25
outcome: "Actors-removed calibration sheets need 64 actor pixels (a convention, MIN_ACTOR_PIXELS) and a calibration needs six of them to be conclusive; INTRO seed 1 stays a FAIL and INTRO then passed twice in a row under DSH on the same six removals. A Claude Sonnet pass graded the colour category's candidate sheets 1, 0 and 0, so it had no two-model example and was removed, leaving 19 categories at digest 5f8b01d6…; fresh CTRY and INTRO calibration inputs and seven-film readout inputs are prepared but ungraded (journal, prepared-inputs.txt). The seven 20-category readouts are DSH's; its two passes move a category count by at most 1, so min_change 4 stands. The baseline refresh still waits on grading the new inputs."
---

# Calibrate the error readout only on actors a grader can see

An `INTRO.FLM` calibration of the error readout failed on 2026-11-25 because two of its six actors-removed sheets had almost nothing to remove.
See the [journal](journal.md); the finding lives in [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3.
