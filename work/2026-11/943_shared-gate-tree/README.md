---
title: "FilmScene::frame re-tests LOD branches that many view-facing props share, once per prop"
started: 2026-11-22
issue: 943
outcome: "World holds the view-facing props' SP_1NODE gates as a parent-before-child tree and FilmScene::frame tests each node once, only when its parent is open (at most 48,604 on LOCATION and 36,584 on INTRO, 27,719 and 20,985 SP_1NODE branches plus one distance gate for each prop that carries one, against 65,606 to 116,791 tests a tick): the four stores on Spans A, B and C are byte-identical on Windows lavapipe and the RTX 4070, scene_frame fell 39.2% to 73.6% in all nine cells, and the loop medians fell 0.7% to 23.0% with ranges disjoint in six of nine, so no loop saving is claimed."
---

# FilmScene::frame re-tests LOD branches that many view-facing props share, once per prop

Issue `#943` (from `#934`): `FilmScene::frame` re-tested every `SP_1NODE` gate once per view-facing prop under it.

- Journal: [`journal.md`](journal.md); raw runs [`runs_main.txt`](runs_main.txt), [`runs_swap.txt`](runs_swap.txt); the timing patch is `#942`'s [`timer.patch`](../942_frame-gate-cache/timer.patch).
- Changed: `World::gate_nodes` (`GateNode`) and `FacingProp::{node, reach}` in `crates/stunt-core/src/world/assemble.rs`, the per-frame `OpenGates` pass in `scene/projection.rs`, read by `FilmScene::frame`.
- Not done: Ubuntu lavapipe figures (no cloud session); the seven reference films' scores (not re-run); skipping nodes whose props the shape table drops; the world mesh's gated nodes (`#920`).
