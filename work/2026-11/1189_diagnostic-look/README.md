---
title: A viewer-only diagnostic look
started: 2026-11-27
issue: 1189
outcome: "`stuntreel --look diagnostic` colours each object by shape or layer, outlines it, hatches shadows, stripes decal ties and lays a 100 m and 1000 m world grid over ground, in the window, `--video` and `-o`; its index, layer and shape planes equal a Mode 13h render's."
---

# A viewer-only diagnostic look

[#1189](https://github.com/neilsh/stunt-reel/issues/1189) asked for a diagnostic render beside the Mode 13h and modern looks.
The plan is the issue's `## Implementation plan` comment; name labels, the depth and draw-order heat map and a look hotkey are follow-ups.

The look, its colour key and its command lines are in [Render a film](../../../docs/howto/render-a-film.md#see-what-each-pixel-is); the `[I3]` exemption is in [`docs/SPEC.md`](../../../docs/SPEC.md#2-system-architectural-invariants--guardrails).

[`images/ctry-300-700-1100-mode13h-vs-diagnostic.png`](images/ctry-300-700-1100-mode13h-vs-diagnostic.png) shows `CTRY.FLM` ticks 300, 700 and 1100 (Mode 13h left, diagnostic right), rendered with `-o --tick-range T..=T --software-only` on lavapipe: the plane is one pink actor with striped decal ties (a decal and the polygon under it) and a hatched shadow, the ground is one large prop mixed toward grey, the hillsides carry the grid, and each tree and building shape has its own colour.
