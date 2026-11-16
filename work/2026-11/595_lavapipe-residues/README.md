---
title: "Lavapipe clipper residues: polygons drawn over others and Gouraud polygons drawn flat"
started: 2026-11-16
issue: 595
outcome: "The four depth residues are near-coplanar ties that lavapipe's vertex-stage rounding flips (LAND 227 included: a flat ground polygon, not a Gouraud one drawn flat); a perspective copy of the shade keeps Gouraud polygons the clipper breaks from drawing flat, GPU stores byte-identical."
---

# Lavapipe clipper residues: polygons drawn over others and Gouraud polygons drawn flat

**Question.** The four solid residues in [`lavapipe.md`](../../../research/parity/lavapipe.md) section 5, and the flat-Gouraud fix ([#595](https://github.com/neilsh/stunt-reel/issues/595)).

## Status

- 2026-11-16: attribution and the fix in [journal.md](journal.md); findings in `lavapipe.md` sections 3 and 5. Left open: why the vertex stage rounds differently, and whether the clipper adds to a broken polygon's depth error (`lavapipe.md` Open questions 1 and 2).
