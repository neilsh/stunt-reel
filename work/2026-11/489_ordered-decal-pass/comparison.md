# Ordered decal pass: depth bias against stencil

## 2026-11-13: prototype A (depth bias) wins the comparison

- **Question**: of the two ways #489 named to break the tie inside an ordered decal pass, which one ships: **A**, a hardware depth bias on a decal pipeline that writes no depth, or **B**, a stencil id written by each base and matched by its decals with no depth test?
- **Method**: both prototypes branched from `main` at `3d680420`, were scored with `mise run parity` on the same adapter (gpu class) and judged against `main`'s reports with `mise run judge -- <main> <candidate> --track evidence --target bomb:2058-2179 --target location:4699-4819 --target land:518-573 --target traintnl:12-133`. The rule, fixed in #489 before either ran (both runs widened its single LOCATION 4709 and LAND 573 targets to `4699-4819` and `518-573`; on the issue's own targets A's worst frame is LAND 573, −0.0017, and B's LOCATION 4709, −0.0063, so the verdict holds either way): the winner must pass the adoption rule; of two that pass, the better worst target frame wins; within 0.001, A wins as the simpler one. A's record is [`depth-bias.md`](depth-bias.md) (branch `proto/489-decal-bias`, `8da45a4e`); B's is [`stencil.md`](stencil.md), copied from `proto/489-decal-stencil` at `e94c6095` so it outlives that branch.
- **Result** (whole-frame SSIM differences from `main`; target means over each range's scored frames):

  | | A, depth bias (`8da45a4e`) | B, stencil (`e94c6095`) |
  |---|---|---|
  | Judge verdict | adopts (evidence, film means) | adopts (evidence, film means) |
  | Worst target frame | LOCATION 4775, −0.0037 | LOCATION 4809, −0.0071 |
  | Frames down > 0.005 | 31 | 65 |
  | BOMB 2058–2179 (SSIM) | +0.0190 | +0.0205 |
  | LOCATION 4699–4819 | −0.0013 (4709: −0.0012) | −0.0024 (4709: −0.0063) |
  | LAND 518–573 | −0.0011 (573: −0.0017) | −0.0021 (573: +0.0019) |
  | TRAINTNL 12–133 | −0.0004 | −0.0007 |
  | Film means rising > 0.002 | CTRY, TRAINTNL, BOMB | TRAINTNL, BOMB |
  | Film means falling | none | INTRO −0.0004, LAND −0.0003, BALLOON −0.0000 (rounded to four places, `stencil.md`) |

  A's 31 frames down by more than 0.005, as its judge listed them, worst first: LOCATION 3202 −0.0152, 4610 −0.0144, LAND 628 −0.0124, LOCATION 3785 −0.0105, 3433 −0.0097, 3279 −0.0096, 3235 −0.0091, 5644 −0.0088, 3213 −0.0087, 3158 −0.0076, 5633 −0.0074, 3125 −0.0073, 3169 −0.0073, 3191 −0.0073, 5622 −0.0072, 3224 −0.0071, 3323 −0.0068, 5655 −0.0063, BOMB 2718 −0.0063, LOCATION 3312 −0.0060, BOMB 2696 −0.0059, LOCATION 5589 −0.0059, 3114 −0.0058, BOMB 2675 −0.0056, LOCATION 3180 −0.0056, INTRO 2982 −0.0055, BOMB 2685 −0.0054, LOCATION 4577 −0.0053, 4599 −0.0053, 3246 −0.0051, BOMB 2708 −0.0051.

  Judge lines:

  - A: `winner: run=candidate adopts (evidence, film means; target idx +0.0041 attribution; worst target frame -0.0037 location:4775; 31 frames down >0.005, listed)`
  - B: `winner: run=candidate adopts (evidence, film means; target idx +0.0036 attribution; worst target frame -0.0071 location:4809; 65 frames down >0.005, listed)`

- **Verdict**: A wins. Both adopt, and A's worst target frame (−0.0037) beats B's (−0.0071) by 0.0034, more than the 0.001 margin. B is ahead on BOMB's targets (+0.0015 over A), on the TRAINTNL film mean (0.8601 against 0.8599) and on LAND 573, the frame where #488 buried a shadow: A loses 0.0017 there, with the shadow drawn.

  **Cost and risk, A.** The pipeline change is one flag, no depth write on the decal state that the shadow and decal-edge pipelines share, with `main`'s bias (`-2, -2.0`); the constant made no difference from −1 to −8, and the slope trades a target frame (−0.5) against bleed-through (−8). A pass without depth writes needs outlines drawn in stream order, which A does per fan in shapes and per slice in the world; inside one world decal slice the outlines still follow all of its fills, and on LOCATION's facades edge pixels between coplanar polygons changed owner (tick 3202, −0.0152, the worst frame of the judge's list), not attributed to either order. The bias is in depth-buffer units, so it does not fall below the depth step with distance (inferred), at the cost that a decal also beats any surface within a few depth steps of it (two steps are about 24 cm at 1 km by arithmetic, more at grazing angles).

  **Cost and risk, B.** A new seam-contract field (`SodVertex::decal_group`), union-find grouping, per-group draws, `Depth24PlusStencil8` and three new pipelines. Ids wrap at 255 per frame; how often two groups 255 apart overlap was not counted. Its decal pass has no depth test, so a decal's outline is clipped to its group's stencil and loses the edge pixels the capture has (LOCATION 4709); restoring them (B's round 2) made the worst target frame worse (−0.0080).
- **Lives in**: [ADR 0046](../../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md) for the decision, [`render-model.md`](../../../research/parity/render-model.md) section 3 for the rule and its known gaps.
