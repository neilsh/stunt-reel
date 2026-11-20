---
title: "Trace PLAYONE's back-face cull of shape polygons and their outlines"
started: 2026-11-20
issue: 850
outcome: "[Established] static: none of the polygon routines read computes a facing; the fillers skip a row whose right end (forward walk from the top vertex) is left of its left (backward walk), so an anticlockwise polygon loses fill and outline together except the rows of a lone apex vertex and rows narrower than its edges' runs. One-row, collinear and two-vertex polygons draw as lines whatever their order. No renderer change."
---

# Trace PLAYONE's back-face cull of shape polygons and their outlines

Research only, for [#850](https://github.com/neilsh/stunt-reel/issues/850): where `PLAYONE.EXE` culls a back-facing shape polygon, and what that does to its outline and to degenerate polygons.
The finding is in [`sod-vm-lines-spans.md` § 8.12](../../../research/playone-exe/sod-vm-lines-spans.md#812-back-faces-the-span-test); the read is in [`journal.md`](journal.md).

## Handoff

The cull is the fillers' row test, not a facing test, read statically and not traced live.
Left for #730 and #717: whether to draw a back face's apex rows and thin rows as `PLAYONE` does, and the open questions in § 8.12.
