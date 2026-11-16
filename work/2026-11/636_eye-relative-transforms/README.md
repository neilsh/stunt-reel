---
title: "Large world coordinates make the vertex transform round differently on lavapipe and the GPU"
started: 2026-11-16
issue: 636
outcome: "Eye-relative transforms cut the lavapipe/GPU index-plane residue by 46% to 84% per film and leave 17 pixels or fewer at each of the four near-coplanar tie residues; GPU parity within the 0.002 guard on every film (LOCATION -0.0005, the stadium infield now losing its tie to the ground), GPU repinned, lavapipe repin left to the owner."
---

# Large world coordinates make the vertex transform round differently on lavapipe and the GPU

**Question.** Whether eye-relative transforms make lavapipe and the GPU agree on the near-coplanar depth ties of [`lavapipe.md`](../../../research/parity/lavapipe.md) section 5 ([#636](https://github.com/neilsh/stunt-reel/issues/636), Lane A step 1 of #639).

## Status

- 2026-11-16: implemented and measured in [journal.md](journal.md); finding in `lavapipe.md` section 5 and open question 1. Left: the stadium infield at LOCATION 2586-2872 (a world prop lying on the ground, which PLAYONE paints and the depth test now hides), the ties at LOCATION 3815 and LAND 415, and #637 (reversed-Z) next.
