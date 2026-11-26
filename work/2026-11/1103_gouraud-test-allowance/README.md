---
title: "Record the Gouraud ground test's one-index allowance on lavapipe"
started: 2026-11-26
issue: 1103
outcome: "The Gouraud ground test allows one index, not zero, on lavapipe: 3,167 of 47,040 pixels are one index off with the vertex slide on and none with it disabled, and the cause is a hypothesis, not isolated. The record is `journal.md`; `research/parity/lavapipe.md` § 3 and the test's comment point to it."
---

# Record the Gouraud ground test's one-index allowance on lavapipe

#1064's vertex slide made `a_gouraud_ground_polygon_under_a_low_eye_keeps_its_gradient` fail on CI's lavapipe, and #1099 relaxed it to one index.
Its work folder was frozen when #1099 landed, so the measurement and the repins that followed are recorded here.

- [`journal.md`](journal.md): the observation, its counts and the repin.
- Part of [#1064](../1064_projector-vertex-truncation/README.md).
