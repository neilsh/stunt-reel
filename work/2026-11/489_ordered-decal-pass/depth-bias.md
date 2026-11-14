# Prototype A: ordered decal pass, tie broken by depth bias

Issue [#489](https://github.com/neilsh/stunt-reel/issues/489), prototype A of two (B is the stencil variant). Branch `proto/489-decal-bias`, from `main` at `3d680420`.

## 2026-11-13: decals in stream order, no depth write, hardware depth bias

- **Question**: with the `[I5]` geometric offset removed (decals flagged in place, PR #488's front-normal matching carried over), does an ordered decal pass (after the base, stream order, `LessEqual`, no depth write) with a hardware depth bias on the decal pipeline beat `main` on the targets, and which `(constant, slope_scale)` works best?
- **Method**: track **evidence** (the painter rule PR #488 cites: a later coplanar polygon covers an earlier one, `POLYZ` `0x9B78`, filler `0x7571` without a depth test, [`render-model.md`](../../../research/parity/render-model.md) section 3). Targets, quoted before the sweep runs:

  `--track evidence --target bomb:2058-2179 --target location:4699-4819 --target land:518-573 --target traintnl:12-133`

  Code: `SodModelIr` carries no decal offset (`identify_coplanar_decals` only flags), `ground_decal_vertices` and `push_prop_mesh` no longer subtract a lift (ADR 0045's `unlifted_height` step is gone), the decal, decal-edge and shadow pipelines keep `LessEqual` but stop writing depth, and `stunt-gltf` alone lifts decal vertices 1 mm toward their front. Outlines needed reordering too: with no depth write, an outline drawn after every fill of its node or slice lands on the later decals (a GPU test showed the earlier decal's outline ring, 100 pixels, on the later one). A shape's decal node now emits each fan's outline right after the fan (`outline.rs`), and the world draws each decal slice's outline right after that slice (`scene_renderer.rs`); inside one world decal slice the outlines still follow all its fills. The actor shadow keeps its 1 mm `flatten_matrix` lift. Round 1 sweeps the bias with `DBG_DECAL_BIAS_C` and `DBG_DECAL_BIAS_S` (first values `-2`, `-2.0`, `main`'s pipeline bias); the winner, made the default, is then judged against `main`'s `mise run parity` reports with `mise run judge`.

  The switches are kept as [`switches/DBG_DECAL_BIAS.diff`](switches/DBG_DECAL_BIAS.diff) and [`switches/DBG_DECAL_OUTLINE.diff`](switches/DBG_DECAL_OUTLINE.diff), reconstructed after the rounds as diffs against `c1e6f444`.

  Round 2 (one switch, same track and targets): `DBG_DECAL_OUTLINE=1,0` at the round-1 bias, `1` the fan- and slice-interleaved outlines above, `0` `main`'s order (every outline after its node's or slice's fills), to attribute the non-target falls of round 1.

- **Result**: round 1 (`9` variants, base `3d680420` plus the switch): the constant does nothing from `-1` to `-8` (identical scores at each slope); the slope decides. Against the in-sweep baseline `(-2, -2.0)`, slope `-0.5` raises film means by up to +0.0005 (CTRY 0.9190, LOCATION 0.8296) but drops one target frame by 0.0160 (4 frames down >0.005), and `-8.0` lets decals through nearby base surfaces (LAND 0.8917, LOCATION 0.8275, 109 frames down >0.005). The sweep picked `C=-8, S=-2.0`, scoring identically to `(-2, -2.0)`, which the branch keeps (`main`'s pipeline values). Round 2 (`DBG_DECAL_OUTLINE=1,0`): `main`'s outline order loses CTRY 0.0002, TRAINTNL 0.0006 and LOCATION 0.0006, with 29 frames down >0.005, so the interleaved outlines stay.

  Final `mise run parity` on `8335afbb` (`crates` tree `9de93cb`, RTX 4070 Laptop GPU) against `main` at `3d680420`:

  | Film | main | A (bias) | Δ |
  |---|---|---|---|
  | CTRY | 0.9162 | 0.9185 | +0.0023 |
  | INTRO | 0.8535 | 0.8535 | +0.0000 |
  | LAND | 0.8929 | 0.8932 | +0.0003 |
  | BALLOON | 0.8174 | 0.8174 | +0.0001 |
  | TRAINTNL | 0.8566 | 0.8599 | +0.0033 |
  | BOMB | 0.8394 | 0.8444 | +0.0050 |
  | LOCATION | 0.8288 | 0.8292 | +0.0004 |

  `mise run judge -- <main reports> <A reports> --track evidence` with the four targets:

  `winner: run=candidate adopts (evidence, film means; target idx +0.0041 attribution; worst target frame -0.0037 location:4775; 31 frames down >0.005, listed)`

  Worst target frame: LOCATION 4775, -0.0037 (117 pixels on the stands' tiers change from palette 132-135 to 150). LOCATION 4709 moves -0.0012 (57 pixels on the stands; the field and its border are unchanged, and both renders lack the capture's yard lines). LAND 573 moves -0.0017: the aircraft's shadow is not buried as under PR #488 (-0.0110), since shadows draw after the world's decals and write no depth. The 31 frames down >0.005 are 25 LOCATION frames (worst 3202, -0.0152), LAND 628, INTRO 2982 and four BOMB frames after the targets (2675-2718). LOCATION 3202 changes 343 pixels: one-pixel rows where coplanar facade bands and the roof edge meet now take the later polygon's fill instead of the earlier one's outline; in the two rows looked at (roof edge, one band boundary) the capture matches `main`.

  Target frames, whole-frame SSIM and index agreement, `main` then A:

  #### bomb 2058-2179: 12 scored frames; mean dSSIM +0.0190, mean dIdx +0.0141
  | tick | SSIM main | SSIM A | dSSIM | idx main | idx A |
  |---|---|---|---|---|---|
  | 2058 | 0.7962 | 0.8178 | +0.0216 | 0.8448 | 0.8737 |
  | 2070 | 0.8527 | 0.8675 | +0.0148 | 0.8889 | 0.8940 |
  | 2080 | 0.8225 | 0.8271 | +0.0046 | 0.8833 | 0.8885 |
  | 2091 | 0.8176 | 0.8563 | +0.0387 | 0.8638 | 0.8937 |
  | 2102 | 0.8762 | 0.8853 | +0.0092 | 0.8895 | 0.8935 |
  | 2113 | 0.8282 | 0.8496 | +0.0214 | 0.8718 | 0.8804 |
  | 2124 | 0.8065 | 0.8371 | +0.0305 | 0.8513 | 0.8748 |
  | 2135 | 0.8139 | 0.8239 | +0.0100 | 0.8680 | 0.8770 |
  | 2146 | 0.8261 | 0.8440 | +0.0179 | 0.8723 | 0.8802 |
  | 2157 | 0.8314 | 0.8576 | +0.0262 | 0.8673 | 0.8837 |
  | 2168 | 0.8448 | 0.8568 | +0.0120 | 0.8685 | 0.8849 |
  | 2179 | 0.8496 | 0.8713 | +0.0218 | 0.8795 | 0.8934 |

  #### location 4699-4819: 11 scored frames; mean dSSIM -0.0013, mean dIdx +0.0000
  | tick | SSIM main | SSIM A | dSSIM | idx main | idx A |
  |---|---|---|---|---|---|
  | 4709 | 0.8346 | 0.8333 | -0.0012 | 0.9493 | 0.9488 |
  | 4720 | 0.8067 | 0.8047 | -0.0020 | 0.9445 | 0.9445 |
  | 4732 | 0.8267 | 0.8247 | -0.0020 | 0.9463 | 0.9460 |
  | 4742 | 0.8085 | 0.8081 | -0.0004 | 0.9416 | 0.9421 |
  | 4753 | 0.8211 | 0.8228 | +0.0017 | 0.9476 | 0.9485 |
  | 4764 | 0.8419 | 0.8422 | +0.0004 | 0.9532 | 0.9533 |
  | 4775 | 0.8435 | 0.8398 | -0.0037 | 0.9518 | 0.9517 |
  | 4786 | 0.8341 | 0.8340 | -0.0001 | 0.9500 | 0.9498 |
  | 4797 | 0.8309 | 0.8292 | -0.0017 | 0.9516 | 0.9515 |
  | 4809 | 0.8542 | 0.8514 | -0.0029 | 0.9580 | 0.9579 |
  | 4819 | 0.8487 | 0.8468 | -0.0020 | 0.9555 | 0.9553 |

  #### land 518-573: 6 scored frames; mean dSSIM -0.0011, mean dIdx -0.0002
  | tick | SSIM main | SSIM A | dSSIM | idx main | idx A |
  |---|---|---|---|---|---|
  | 518 | 0.7598 | 0.7593 | -0.0005 | 0.7099 | 0.7099 |
  | 529 | 0.7155 | 0.7146 | -0.0009 | 0.7066 | 0.7064 |
  | 540 | 0.7639 | 0.7624 | -0.0015 | 0.7951 | 0.7948 |
  | 551 | 0.9196 | 0.9182 | -0.0014 | 0.9417 | 0.9411 |
  | 562 | 0.7580 | 0.7578 | -0.0002 | 0.8319 | 0.8318 |
  | 573 | 0.8357 | 0.8340 | -0.0017 | 0.8758 | 0.8756 |

  #### traintnl 12-133: 12 scored frames; mean dSSIM -0.0004, mean dIdx +0.0001
  | tick | SSIM main | SSIM A | dSSIM | idx main | idx A |
  |---|---|---|---|---|---|
  | 12 | 0.8221 | 0.8209 | -0.0013 | 0.8871 | 0.8871 |
  | 23 | 0.8485 | 0.8478 | -0.0008 | 0.8859 | 0.8861 |
  | 34 | 0.8125 | 0.8123 | -0.0002 | 0.9025 | 0.9029 |
  | 45 | 0.8594 | 0.8586 | -0.0008 | 0.9078 | 0.9077 |
  | 56 | 0.8288 | 0.8283 | -0.0005 | 0.9189 | 0.9188 |
  | 67 | 0.8549 | 0.8558 | +0.0009 | 0.9083 | 0.9086 |
  | 78 | 0.8610 | 0.8607 | -0.0003 | 0.9083 | 0.9083 |
  | 89 | 0.8756 | 0.8754 | -0.0003 | 0.9256 | 0.9254 |
  | 100 | 0.8991 | 0.8990 | -0.0001 | 0.9529 | 0.9530 |
  | 111 | 0.8949 | 0.8943 | -0.0005 | 0.9614 | 0.9614 |
  | 123 | 0.9147 | 0.9136 | -0.0011 | 0.9561 | 0.9562 |
  | 133 | 0.9250 | 0.9248 | -0.0003 | 0.9731 | 0.9735 |

- **Verdict**: adopted against `main` on the evidence track by the film-mean branch (CTRY, TRAINTNL and BOMB rise by more than 0.002; no film falls). BOMB's targets carry it (+0.0190 SSIM, +0.0141 index agreement); LOCATION, LAND and TRAINTNL's targets each fall by 0.0004 to 0.0013 on average, none by more than 0.004. Two rounds used of three.
- **Cost and risk**: the pipeline change is one flag (`depth_write_enabled: false` on the decal depth state, which the shadow and decal-edge pipelines share; the bias is `main`'s); the rest is `[I5]` plumbing either prototype needs (no offset, flag-only matching, no `unlifted_height`, exporter-only lift) plus outline order, which a no-write pass needs whatever breaks the tie. A world decal slice still draws its outlines after all its fills, so an earlier decal's outline can show on a later one inside one slice (per-polygon draws would fix it). Precision at distance: the bias is in depth-buffer units, so it shrinks with the depth step instead of failing past ~100 m as 1 mm levels did; the price is that a decal also wins against any other surface within 2 units plus 2 slopes of its own depth, about 24 cm at 1 km for the constant term ([`render-model.md`](../../../research/parity/render-model.md) section 3 gives 12 cm a step there) and more at grazing angles through the slope term (slope `-8` showed it). Shadows: they go through the same no-write biased pass, after the world's decals and before the actor, so they lie over runway markings as `PLAYONE` paints them.
- **Lives in**: this journal until the comparison picks a winner; the winner's PR carries the `[I5]` ADR and the `render-model.md` update.
