---
title: "World slices outside the camera's view are still drawn"
started: 2026-11-16
issue: 644
outcome: "Adopted in PR #652: the world walk skips a node whose subtree box lies wholly outside the view frustum. LOCATION's median frame falls from 127,910 draw_indexed calls to 6,791, its ticks 12-300 take 83% less wall-clock time on mesa-dist-win lavapipe and 68% less on the RTX 4070 (one run each), and the render stores stay byte-identical over the films' captured ticks; research/parity/lavapipe.md section 6 holds the figures."
---

# World slices outside the camera's view are still drawn

Issue #644; built in PR #652. The counts, timings and byte checks are in [`journal.md`](journal.md)
and [`research/parity/lavapipe.md` § 6](../../../research/parity/lavapipe.md#6-render-time).

Follow-ups #622 asks for (contiguous runs measured on top of culling) and a cull for props, actors
and sprites (6,762 draws a LOCATION frame, untouched) are not started.
