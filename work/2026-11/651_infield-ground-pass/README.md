---
title: "LOCATION's stadium infield loses its depth tie to the ground it lies on"
started: 2026-11-20
issue: 651
outcome: "Adopted: a prop face whose corners lie within 0.1 m of the ground plane is painted in the walk-order ground pass, so LOCATION's infield shows over the plaza at 2586 to 2872; LOCATION, LAND and BOMB rise on the GPU."
---

# LOCATION's stadium infield loses its depth tie to the ground it lies on

The infield lies 7.8125 mm below the ground plane, under the plaza, which the snap moves onto the plane ([#701](https://github.com/neilsh/stunt-reel/issues/701)); this item draws it in the ground pass after the plaza, as `PLAYONE`'s walk paints it.
See [`journal.md`](journal.md).

## Handoff

Done; nothing is left on #651.
Two side effects were not traced: which `LAND` face is the runway the change restores at tick 221, and what costs `LOCATION` 3268 its 0.0044.
