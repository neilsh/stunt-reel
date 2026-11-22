---
title: "The castle's moat and its green surround tie in depth instead of painting in order"
started: 2026-11-22
issue: 966
outcome: "A flat prop lying on an earlier flat prop is drawn as its decal (ADR 0035 amended): LOCATION 3812-3968 GPU-lavapipe disagreement 132.08 to 12.64 pixels a tick, no tick over 500; Depth32Float re-measured on the fixed tree and rejected again (ADR 0054 stands)."
---

# The castle's moat and its green surround tie in depth instead of painting in order

[#966](https://github.com/neilsh/stunt-reel/issues/966): `LOCATION`'s castle green strip `0x0539` lies in the plane of its moat quad `0x04AC`, 75 m up, and the GPU and lavapipe settled the exact tie differently.
`PLAYONE` paints the moat, then the strip ([`journal.md`](journal.md), first entry); the fix draws a flat prop lying on an earlier flat prop as a decal of it (second entry), and `Depth32Float` still disagrees more than `Depth24Plus` on the fixed tree (third entry).

## Handoff

- Done: the rule (`prop_overlay_vertices`), both expected tables repinned on `crates` `bddf5daf`, [`world-scene-residuals.md`](../../../research/playone-exe/world-scene-residuals.md) section 6.9, ADR 0035 amended, ADR 0054 and [`lavapipe.md`](../../../research/parity/lavapipe.md) section 5 updated.
- Not run: the error readout (#901), and `mise run agreement -- pin`; the next agreement batch pins this tree.
- Open: the other 18 placements the rule picks on `LOCATION` were not traced, and the rule follows our placement order, not an eye-dependent `SP_XPLANE` or `SP_ZPLANE` order (`world-scene-residuals.md` open question 7).
