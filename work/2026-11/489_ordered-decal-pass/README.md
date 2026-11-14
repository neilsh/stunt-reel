---
title: "Coplanar decals should draw in an ordered pass, not by geometric offset"
started: 2026-11-13
issue: 489
outcome: "Adopted prototype A (ADR 0046, proposed): decals stay on their facet and draw in stream order with depth bias and no depth write; worst target frame LOCATION 4775 -0.0037 against the stencil prototype's -0.0071. Edge pixels between coplanar decals on LOCATION facades changed owner (3202 -0.0152), not yet attributed."
---

# Coplanar decals should draw in an ordered pass, not by geometric offset

How should the ordered decal pass that replaces `[I5]`'s geometric offset break a decal's tie with its base: a hardware depth bias (A) or a stencil id (B)?

- Prototype A, depth bias: [`depth-bias.md`](depth-bias.md).
- Prototype B, stencil: [`stencil.md`](stencil.md), copied from `proto/489-decal-stencil` at `e94c6095`.
- Comparison and verdict: [`comparison.md`](comparison.md).
- Decision: [ADR 0046](../../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md); rule and known gaps: [`render-model.md`](../../../research/parity/render-model.md) section 3.
