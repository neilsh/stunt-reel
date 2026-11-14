# #489 prototype B: stencil-matched ordered decal pass

## 2026-11-13: decals drawn in stream order where their group's stencil holds

- **Question**: with no geometric `[I5]` offset, does an ordered decal pass that draws each
  decal only where its base's stencil id holds, with no depth test for the tie, match
  `PLAYONE` better than `main`'s 1 mm lift plus depth bias, and how bad is its worst target
  frame?
- **Method**: branch `proto/489-decal-stencil` from `main` at `3d680420`. Evidence track
  (the rule is `PLAYONE`'s painter order within a facet: a later coplanar polygon covers an
  earlier one, [`render-model.md`](../../../research/parity/render-model.md)). Baseline:
  `mise run parity` on `3d680420`, reports copied aside; candidate: `mise run parity` on the
  branch; judged with `mise run judge -- <base> <candidate> --track evidence --target
  bomb:2058-2179 --target location:4699-4819 --target land:518-573 --target
  traintnl:12-133`, gpu class (same adapter for both). Two rounds:
  1. **Round 1**, the variant committed here:
     - **Decoder.** `identify_coplanar_decals` no longer moves a decal. It matches on the
       front normal (from the winding, carried from #488) against the undisplaced
       polygons, and joins coplanar overlapping polygons into a decal group (union-find,
       so a decal over two bases merges them). A group of two or more is numbered `1..=255`
       per shape in order of its first polygon, wrapping past 255. The number rides in
       `SodVertex::decal_group` (the old `_padding` byte), is part of the weld key, and each
       base and decal batch is stably sorted by group so a group is one run.
     - **World.** `build_world_ir` offsets each placement's groups past the previous
       placement's, wrapping within `1..=255`. ADR 0045's `unlifted_height` step is gone,
       since there is no lift to remove.
     - **Renderer.** Depth format `Depth24PlusStencil8`, stencil cleared to 0. Upload cuts
       each mesh slice into runs of one group (`GpuMeshSlice::group`). Each draw takes the
       stencil values after the previous draw's (world first, then props, actors and
       sprites), so the reference is `(base + group - 1) % 255 + 1`.
       - *Base pass*: base slices with `Less` and depth write, stencil `Replace` with the
         slice's reference (0 for polygons in no group). Then every decal slice as *cover*:
         the old biased state (`LessEqual`, bias −2/−2, depth write), stencil `Replace`, so
         the group's stencil also covers decal area that reaches past its first polygon. A
         decal of group 0 (a ground decal snapped onto a hill, ADR 0035) is drawn only here.
       - *Decal pass*: each nonzero-group decal slice in stream order with depth `Always`,
         no depth write, no bias, stencil `Equal` to its reference; the world's decal
         outlines likewise, straight after their run. Shadows keep the old biased pipeline,
         after the world's decals.
     - **glTF.** The exporter alone moves decal triangles `EPSILON_DISPLACEMENT` toward
       their front.
  2. **Round 2**: also drew the world's nonzero-group decal outlines as cover (stencil
     `Replace`), after round 1 showed LOCATION's changed pixels on distant stripe edges.
     Reverted: see Result.
- **Result**, round 1 (`mean_ssim_scored`, baseline → candidate, unrounded differences
  from the judge):

  | Film | Before | After | Δ |
  |---|---|---|---|
  | CTRY | 0.9162 | 0.9179 | +0.0018 |
  | INTRO | 0.8535 | 0.8531 | −0.0004 |
  | LAND | 0.8929 | 0.8926 | −0.0003 |
  | BALLOON | 0.8174 | 0.8173 | −0.0000 |
  | TRAINTNL | 0.8566 | 0.8601 | +0.0035 |
  | BOMB | 0.8394 | 0.8443 | +0.0049 |
  | LOCATION | 0.8288 | 0.8289 | +0.0001 |

  Target frames (whole-frame SSIM before → after):

  - BOMB 2058–2179, mean Δ +0.0205: 2058 0.7962 → 0.8236, 2070 0.8527 → 0.8686,
    2080 0.8225 → 0.8267, 2091 0.8176 → 0.8595, 2102 0.8762 → 0.8882,
    2113 0.8282 → 0.8496, 2124 0.8065 → 0.8434, 2135 0.8139 → 0.8238,
    2146 0.8261 → 0.8446, 2157 0.8314 → 0.8591, 2168 0.8448 → 0.8543,
    2179 0.8496 → 0.8701.
  - LOCATION 4699–4819, mean Δ −0.0024: 4709 0.8346 → 0.8283, 4720 0.8067 → 0.8018,
    4732 0.8267 → 0.8223, 4742 0.8085 → 0.8045, 4753 0.8211 → 0.8237,
    4764 0.8419 → 0.8399, 4775 0.8435 → 0.8405, 4786 0.8341 → 0.8348,
    4797 0.8309 → 0.8314, 4809 0.8542 → 0.8471, 4819 0.8487 → 0.8500.
  - LAND 518–573, mean Δ −0.0021: 518 0.7598 → 0.7585, 529 0.7155 → 0.7133,
    540 0.7639 → 0.7613, 551 0.9196 → 0.9156, 562 0.7580 → 0.7536, 573 0.8357 → 0.8376.
  - TRAINTNL 12–133, mean Δ −0.0007: 12 0.8221 → 0.8204, 23 0.8485 → 0.8475,
    34 0.8125 → 0.8121, 45 0.8594 → 0.8586, 56 0.8288 → 0.8278, 67 0.8549 → 0.8557,
    78 0.8610 → 0.8608, 89 0.8756 → 0.8748, 100 0.8991 → 0.8991, 111 0.8949 → 0.8944,
    123 0.9147 → 0.9135, 133 0.9250 → 0.9241.

  Worst target frame: LOCATION 4809, −0.0071 (4709, the known bad frame: −0.0063; #488's
  per-level lift had −0.0205 there). LAND 573, where #488 buried an actor shadow (−0.0110),
  rises +0.0019. Judge winner line, round 1:

  > `winner: run=candidate adopts (evidence, film means; target idx +0.0036 attribution; worst target frame -0.0071 location:4809; 65 frames down >0.005, listed)`

  The 65 frames down by more than 0.005 are mostly LOCATION's (largest −0.0179 at 2993),
  plus CTRY 826–980 (≤ −0.0084) and INTRO 2795–3378 (≤ −0.0081). At LOCATION 4709 the
  render changes on 287 pixels, all thin edge pixels of distant stand stripes and a fence
  line (rows 14–61). Outlines of a group's decals draw only where the stencil holds the
  group, and an outline pixel just outside the fill holds the neighbouring surface's value,
  so the stripes lose edge pixels the capture has.

  Round 2 restored those outline pixels. Film means rose a little further (CTRY 0.9184,
  TRAINTNL 0.8604, BOMB 0.8447, LOCATION 0.8289), but it painted 164 more pixels at 4709 in
  outline index 150 over indices 134, 195, 148, 133 and 11, and the LOCATION target mean fell
  to −0.0057. Judge winner line, round 2:

  > `winner: run=candidate adopts (evidence, film means; target idx +0.0036 attribution; worst target frame -0.0080 location:4809; 52 frames down >0.005, listed)`

- **Verdict**: round 1 adopts on the evidence track (CTRY, TRAINTNL, BOMB and LOCATION rise;
  no film falls by more than 0.002) with worst target frame −0.0071 at LOCATION 4809. Round
  2 also adopts but has the worse worst target frame (−0.0080), the figure the #489
  comparison ranks by, so it is reverted and round 1 is the variant on this branch. Two of
  three rounds used.

  **Stencil id choice.** Ids are per decal group, not per draw. A shape numbers its groups
  `1..=255`, wrapping. The world offsets each placement's groups past the previous
  placement's. Each frame's draws take consecutive ranges after the world's. Every value
  wraps within `1..=255`, and 0 means no group. With more than 255 groups in a frame, two
  groups 255 apart in draw order share a value. Where one group's visible area lies under
  the other's decal footprint, the other's decal (no depth test) paints over it. The number
  of groups in each film's world was not counted, so how often that happens is not
  measured. The alternative is to draw each group's base and decals and then clear its
  stencil before the next group: exact with one id, but three draws per group.
- **Lives in**: this journal; the comparison with prototype A and the `[I5]` ADR follow in
  #489's PR.
