---
title: "--game uploads all 2,516 stock shapes to GPU in SceneRenderer::new, doubling lavapipe film render time"
started: 2026-11-13
issue: 484
outcome: "The film path drops every shape no frame can draw before the device upload (FilmScene::drawn_only). CTRY and INTRO --game render stores are byte-identical; one-tick lavapipe renders fall from 0.90 to 0.60 s and 2.24 to 1.48 s. The per-frame effect was not resolved on a shared machine; see journal.md."
---

# --game uploads all 2,516 stock shapes to GPU in SceneRenderer::new, doubling lavapipe film render time

**Question.** `stuntreel --game` decoded all 2,516 stock shapes and uploaded every one to the device, against 127 or 250 from a film's archive. Does keeping only the shapes a film can draw leave its render unchanged and make it cheaper?

**Outcome.** The render stores' frames, layers and palettes are byte-identical, and one-tick renders are faster; whole-film timings on a shared machine did not resolve a per-frame change.

- Experiment and raw timings: [`journal.md`](journal.md).
- Finding: [`research/makeone-exe/linking.md` § 7.1](../../../research/makeone-exe/linking.md#71-rendering-straight-from-res) and its open question 7.
- Code: `FilmScene::drawn_only` in [`crates/stunt-core/src/scene.rs`](../../../crates/stunt-core/src/scene.rs), applied after the load report in [`crates/stunt-cli/src/scene.rs`](../../../crates/stunt-cli/src/scene.rs); tests in both and in [`crates/stunt-core/tests/it/scene_test.rs`](../../../crates/stunt-core/tests/it/scene_test.rs).
