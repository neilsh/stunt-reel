---
title: "VisibleWalk recomputes camera LOD constants per node though GateView caches them per frame"
started: 2026-11-28
issue: 1088
outcome: "VisibleWalk's three camera gates read a per-walk FrameGates (lens words, view vector, its length and the depth divisor, computed once) in stunt-render's mesh.rs; an equivalence test over 4 cameras x 6 lenses x 289 points finds identical decisions, and the seven reference films' render stores are byte-identical to main's on the RTX 4070. The Span B loop median fell 2.2% on lavapipe and 3.2% on the GPU, each smaller than the old variant's spread (55.8 ms against 154.5 ms on lavapipe, 13.8 ms against 29.4 ms on the GPU) on a machine 10-17% busy, so no gain is claimed and the change is kept on maintainability grounds."
---

# VisibleWalk recomputes camera LOD constants per node though GateView caches them per frame

Issue `#1088` (split from `#1053`): `VisibleWalk` called `CameraTransform`'s three gate methods per node, each recomputing the lens words, the view vector and its `sqrt`.

- Changed: `FrameGates` in `crates/stunt-render/src/mesh.rs`, built once at the top of `VisibleWalk::walk`; no `stunt-core` API and none of `collect_world_meshes`, `plan_edges` or `place_sprites` (`#999`) changed.
- Timing: [`lavapipe.csv`](lavapipe.csv) and [`gpu.csv`](gpu.csv) with their summaries (`mise run ab`, Span B `3680..=3979`, 8 alternating rounds, `--max-load 0.25`; other load 10-17%, over the runner's default `0.10`, so a smoke check, not a measurement).
  Lavapipe medians 2561.8 ms (old) and 2506.0 ms (new), `-2.2%`, ranges `2506.9..2661.4` and `2466.6..2659`; GPU 433.6 ms and 419.8 ms, `-3.2%`, ranges `415.2..444.6` and `410.9..476.9`.
- Stores: `ctry`, `intro`, `land`, `balloon`, `traintnl`, `bomb` and `location` rendered over each film's captured ticks with the `main` and the branch binary on the RTX 4070, every output file but `render.json` equal by SHA-256 (31, 81, 27, 28, 29, 79 and 170 files).
  The captures were this machine's current ones, not the `references.toml` pins (four hashes differ), which only fixes the input, the same for both binaries.
- Not done: Ubuntu lavapipe figures; the instruction-count gate (`mise run icount` needs Linux).
