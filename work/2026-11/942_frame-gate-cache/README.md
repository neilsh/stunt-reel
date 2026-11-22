---
title: "FilmScene::frame looks up every view-facing prop's shape and recomputes the camera's gate words on every frame"
started: 2026-11-22
issue: 942
outcome: "FilmScene::frame indexes the view-facing props that have a shape once per scene and tests every gate against one per-frame GateView: stores and scores are byte-identical on Windows lavapipe and the RTX 4070, scene_frame fell 20.2% to 51.2% in all nine cells, while the loop scattered under other agents' load: base first it moved -20.9% to +2.3% on Windows lavapipe (Span B up 2.3% with disjoint ranges) and -18.6% to -11.6% on the RTX 4070, and new first no lavapipe cell's ranges separated (+0.9%, -3.6%, -11.5%)."
---

# FilmScene::frame looks up every view-facing prop's shape and recomputes the camera's gate words on every frame

- Journal: [`journal.md`](journal.md); timing patch [`timer.patch`](timer.patch); raw runs [`runs_main.txt`](runs_main.txt), [`runs_swap.txt`](runs_swap.txt).
- Changed: `FilmScene::index_facing` and `GateView` in `crates/stunt-core/src/scene/` (`film.rs`, `projection.rs`).
- Not done: Ubuntu lavapipe figures (no cloud session); sharing a `LodBranch` chain's gate tests between props stays `#943`.
