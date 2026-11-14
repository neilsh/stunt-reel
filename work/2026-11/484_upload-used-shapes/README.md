---
title: "--game uploads all 2,516 stock shapes to GPU in SceneRenderer::new, doubling lavapipe film render time"
started: 2026-11-13
issue: 484
outcome: "The film path drops every shape no frame can draw before the device upload (FilmScene::drawn_only). CTRY and INTRO --game render stores are byte-identical; one-tick lavapipe renders fall from 0.90 to 0.60 s and 2.24 to 1.48 s. The per-frame effect was not resolved on a shared machine; see journal.md."
---

# --game uploads all 2,516 stock shapes to GPU in SceneRenderer::new, doubling lavapipe film render time
