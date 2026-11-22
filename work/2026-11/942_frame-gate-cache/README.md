---
title: "FilmScene::frame looks up every view-facing prop's shape and recomputes the camera's gate words on every frame"
started: 2026-11-22
issue: 942
outcome: "FilmScene::frame indexes the view-facing props that have a shape once per scene and tests every gate against one per-frame GateView: stores and scores are byte-identical on Windows lavapipe and the RTX 4070, scene_frame fell 20.2% to 51.2% in all nine cells, and the loop fell where its runs' ranges do not overlap (5.3% to 20.9% in four of six first-set cells) but not on lavapipe Span B."
---

# FilmScene::frame looks up every view-facing prop's shape and recomputes the camera's gate words on every frame

- Journal: [`journal.md`](journal.md); timing patch [`timer.patch`](timer.patch); raw runs [`runs_main.log`](runs_main.log), [`runs_swap.log`](runs_swap.log).
- Changed: `FilmScene::index_facing` and `GateView` in `crates/stunt-core/src/scene/` (`film.rs`, `projection.rs`).
- Not done: Ubuntu lavapipe figures (no cloud session); sharing a `LodBranch` chain's gate tests between props stays `#943`.
