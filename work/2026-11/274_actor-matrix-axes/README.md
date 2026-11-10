---
title: "Which actor slot angle is roll and which is pitch in PLAYONE's matrix builder?"
started: 2026-11-09
issue: 274
outcome: "Answered: 0x04E5 builds Ry(-w2)·Rx(w1)·Rz(w0) on column vectors; rotation_quat_dos already matches and a test pins it; FreeFlight's axis assignment is ruled out; the actor light (R·L, not Rᵀ·L) is left open in terrain-shade.md."
---

# Which actor slot angle is roll and which is pitch in PLAYONE's matrix builder?

Findings: [`coordinates-and-units.md` § 3.4](../../../research/formats/concepts/coordinates-and-units.md#34-rotation-conventions--unit-quaternions-seam-2). Journal: [`journal.md`](journal.md).
