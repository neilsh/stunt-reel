---
title: "Which part of FilmScene::frame costs the 20 to 39% of the render loop it takes?"
started: 2026-11-22
issue: 934
outcome: "Collecting the world's view-facing props is 82-93% of FilmScene::frame (21-46% of the loop), most of it re-testing LOD gates for every prop on every frame; shadow_top is 7-15%, sampling and the rest of the per-actor work under 1%. Hoisting the shape lookup and camera words cut the collection 12-36% (#942); testing shared gates once (#943) and a collision-only shadow_top walk (#944) are filed."
---

# Which part of FilmScene::frame costs the 20 to 39% of the render loop it takes?

`#931` measured `scene_frame` (`FilmScene::frame`) at `19.7%..39.1%` of the headless loop after `#914`, as one block; this splits it on `#931`'s Spans A, B and C on Windows lavapipe and the RTX 4070.

- Probe patch: [`probe.patch`](probe.patch), applied on `origin/main` `9ccfd39c` with `git apply`; never committed under `crates/`.
- Journal: [`journal.md`](journal.md)
- Follow-ups: `#942` (hoist the shape lookup and the camera's gate words, `ready-for-agent`), `#943` (test each shared LOD gate once per frame, `needs-triage`), `#944` (walk only collision-bearing records in `shadow_top`, `ready-for-agent`).
- Not done: Ubuntu lavapipe figures (no cloud session in this run).
