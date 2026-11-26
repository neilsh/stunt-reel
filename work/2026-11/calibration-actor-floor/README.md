---
title: "Calibrate the error readout only on actors a grader can see"
started: 2026-11-25
outcome: "Actors-removed calibration sheets need 64 actor pixels (a convention, MIN_ACTOR_PIXELS) and a calibration needs six of them to be conclusive; INTRO seed 1 stays a FAIL and INTRO then passed twice in a row under DSH on the same six removals. A Claude Sonnet pass graded the colour category's candidate sheets 1, 0 and 0, so it had no two-model example and was removed, leaving 19 categories at digest 5f8b01d6…; CTRY and both INTRO 19-category calibrations passed and seven readouts were scored (journal). DSH passes differed by 12 BOMB frames on background misregistration, exceeding min_change 4; repeatability remains open and the baseline refresh is pending review."
---

# Calibrate the error readout only on actors a grader can see

An `INTRO.FLM` calibration of the error readout failed on 2026-11-25 because two of its six actors-removed sheets had almost nothing to remove.
See the [journal](journal.md); the finding lives in [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.3.
