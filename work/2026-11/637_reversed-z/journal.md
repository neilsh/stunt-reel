# Journal

## 2026-11-16: The decal bias constant on single ticks

- **Question**: which constant the `[I5]` decal bias needs once depth is reversed `near / w` in `Depth32Float`, where the constant counts units of `2^(e - 23)` of the triangle's largest depth instead of `2^-24` of depth.
- **Method**: branch `neilsh/637-reversed-z` on PR #650's head `8783a168` (the code later committed as `feat(render): draw with reversed, infinite depth in Depth32Float`), with a temporary `DBG_DECAL_BIAS` switch for the constant and `slope_scale: 2.0`. `mise run frame -- --film <film> --ticks <ticks> --var DBG_DECAL_BIAS=<values>` on the RTX 4070, then the same with `--software-only --no-build` and `VK_DRIVER_FILES` naming the mesa-dist-win 25.2.8 ICD (`llvmpipe (LLVM 21.1.7, 256 bits)` in each store). Index planes compared pixel by pixel between the variants on each backend, and between the backends for each variant, by a one-off script over `RenderStore.frame(tick).indices`. Ticks: LAND 227 and 415; BOMB 1500, 1910, 2113, 2971 and 3000; CTRY 300, 700 and 1102. The `stunt-render` GPU tests (`mise run test-gpu`'s binary) were also run with constants 0, 1, 2 and 16 on both backends.
- **Result**:
  - Constants 2, 16 and 64 (LAND, BOMB 1910, 2113, 2971) and 0 and 16 (BOMB 1500, 1910, 2113, 2971, 3000; CTRY 300, 700, 1102) drew identical index planes on each backend. A constant of -100,000,000 changed 1,668 (GPU) and 1,666 (lavapipe) pixels at BOMB 2971 and 1,781 and 1,785 at 3000, so the switch reached the pipeline.
  - Lavapipe against the GPU, every constant alike: LAND 227 14 pixels, LAND 415 1,903; BOMB 1500 3, 1910 1, 2113 7, 2971 115, 3000 37; CTRY 300 4, 700 36, 1102 17. On #650's tree the PR reported LAND 227 17 and BOMB 1910 1, and LAND 415 2,084 in its full-film stores.
  - Every GPU test passed with every constant on both backends, the 2-degree grazing ground decals of `a_ground_decal_a_kilometre_and_a_half_away_still_shows` included.
- **Verdict**: control. No sampled frame separates the constants, so the slope term and the compare's equality settle these ties; the constant was set to 32 from the worst-case rounding bound in that draft of ADR 0054, not by score.
- **Lives in**: the `Depth32Float` draft of ADR 0054 (commit `96ce4ad6`), superseded by the entries below.

## 2026-11-21: Reversed depth in Depth32Float over every tick, both backends

- **Question**: whether reversed, infinite depth in `Depth32Float` (commit `96ce4ad6`, `crates` tree `4da7d78`) lowers the index-plane pixels per tick on which lavapipe and the GPU differ, against `main` `5fbfe844` (`crates` `bf72b96`), and what it does to GPU parity.
- **Method**: track heuristic, no target frames. `main`'s binary built by `mise run build-at -- 5fbfe844`; on each tree `mise run parity` on the RTX 4070, then `mise run parity -- --software-only --no-build` with `VK_DRIVER_FILES` naming only the mesa-dist-win 25.2.8 ICD (`llvmpipe (LLVM 21.1.7, 256 bits)` in every store). Residue: `mise run parity-residue -- <gpu root> <lavapipe root>` on each tree. Scores: `mise run judge -- <main gpu reports> <branch gpu reports> --track heuristic`. A one-off script tallied each residue pixel's layers on both backends and which backend's index plane moved from `main`.
- **Result**:
  - Mean differing pixels per tick, `main` then branch: CTRY 12.2 → 12.0, INTRO 12.8 → 12.1, LAND 35.7 → 46.5, BALLOON 19.9 → 44.6, TRAINTNL 20.7 → 30.9, BOMB 14.7 → 26.6, LOCATION 62.0 → 92.7.
  - The new differences are mostly between polygons of one layer, and mostly lavapipe's: per tick, lavapipe's own index plane moved from `main` on 47.6 pixels on BALLOON (the GPU's on 3.2), 24.7 on BOMB (6.6), 29.0 on LAND (10.9) and 39.0 on TRAINTNL (19.7). On BALLOON the same-layer residue is the balloon's actor layer 17 (14.8 → 40.1 per tick), on index pairs such as 168 against 48 both ways.
  - GPU judge: no film falls by 0.002; 3 frames fall by more than 0.005 (LOCATION 4203 −0.0162, 4214 −0.0123, 3895 −0.0071); winner line `none adopts (best run=candidate: film means short of +0.002 each or +0.004 on one)`.
- **Verdict**: rejected. Reversed depth in `Depth32Float` makes the backends disagree more on five of seven films.
- **Lives in**: [ADR 0054](../../../docs/adr/0054-depth-is-reversed-and-infinite.md), Considered Options; [`lavapipe.md`](../../../research/parity/lavapipe.md) section 5 and Ruled out.

## 2026-11-21: Bias or format at 13 ticks

- **Question**: whether the decal bias, whose unit changes with a float format, or the depth format itself, drives the extra disagreement of the entry above.
- **Method**: a temporary `DBG_DEPTH` switch (not committed) on `96ce4ad6`: `a` `Depth32Float` with `constant: 32, slope_scale: 2.0`; `b` constant 0; `c` slope 0; `d` both 0; `e` `Depth24Plus` with `constant: 2, slope_scale: 2.0`, the same reversed, infinite projection; `f` constant 1,024; `g` slope 8. `mise run frame -- --film <film> --ticks <ticks> --no-build --var DBG_DEPTH=a,b,c,d,e,f,g` on the GPU, then with `--software-only` and lavapipe, at BALLOON 851, 1017, 1130; TRAINTNL 218, 922, 1127; BOMB 2113, 2372, 2971; LAND 227, 416; LOCATION 2599, 3820 (the ticks with the most residue in the entry above, plus four from `lavapipe.md` section 5). Differing pixels between the two backends' stores per variant per tick by a one-off script.
- **Result**: GPU against lavapipe, variant `a` then `e`: BALLOON 176 → 31, 170 → 22, 191 → 37; TRAINTNL 203 → 13, 265 → 35, 217 → 25; BOMB 7 → 8, 183 → 93, 115 → 36; LAND 12 → 6, 2,176 → 2,075; LOCATION 147 → 8, 2,856 → 182. `b` and `f` matched `a` within 2 pixels at every tick and `g` within 7; `c` and `d` raised it (LOCATION 3820 4,603 and 4,961, BOMB 2372 326 and 462). `main` at the same ticks: BALLOON 85, 30, 45; TRAINTNL 23, 50, 127; BOMB 9, 73, 76; LAND 13, 2,096; LOCATION 15, 2,120.
- **Verdict**: the format, not the bias. Reversed depth in `Depth24Plus` disagrees less than `Depth32Float` at 12 of the 13 ticks, and less than `main` at 12 of them, so it went to a whole-film measurement.
- **Lives in**: [ADR 0054](../../../docs/adr/0054-depth-is-reversed-and-infinite.md), Considered Options.

## 2026-11-21: Reversed depth in Depth24Plus over every tick, both backends

- **Question**: whether reversed, infinite depth in `Depth24Plus`, with the decal bias at `constant: 2, slope_scale: 2.0` toward the viewer, lowers the residue against `main` on every film and keeps GPU parity.
- **Method**: track heuristic, no target frames. Variant `e` of the entry above, rendered and scored as in the first entry of this date, against the same `main` stores. The committed code is the same variant without the switch; its runs are in the next entry.
- **Result**:
  - Mean differing pixels per tick, `main` then `e`: CTRY 12.2 → 6.3, INTRO 12.8 → 8.9, LAND 35.7 → 26.2, BALLOON 19.9 → 8.9, TRAINTNL 20.7 → 5.2, BOMB 14.7 → 11.6, LOCATION 62.0 → 29.8. Ticks with any difference fell on six films (LOCATION 7,786 → 7,535, TRAINTNL 1,208 → 1,124) and rose on BOMB (3,431 → 3,433).
  - The ties named in `lavapipe.md` section 5, `main` then `e`: LAND 227 13 → 6, LAND 415 1,867 → 1,858, LAND 416 2,096 → 2,075, BOMB 1910 1 → 1, LOCATION 2599 15 → 8, 2859 5 → 6, 3815 3,131 → 1,490, 3830 2,603 → 2,470.
  - GPU judge: no film falls by 0.002 and no frame by more than 0.005 (worst −0.0049); 7 frames move by more than 0.005, all up (LAND 1, LOCATION 6); winner line `none adopts (best run=candidate: film means short of +0.002 each or +0.004 on one)`. `mean_ssim_scored` per film is unchanged to four decimals but LAND 0.9235 → 0.9236 and LOCATION 0.8719 → 0.8720.
  - The `stunt-render` GPU tests (`STUNT_REQUIRE_GPU=1 mise run test-gpu`) pass on the RTX 4070, the ground-decal tests at 1 to 8 km included.
- **Verdict**: adopted on #637's criterion, backend agreement, with every guard passing; the score branch does not adopt. LAND 415 and 416 barely move, so the terrain against prop tie there is not depth rounding of this kind.
- **Lives in**: [ADR 0054](../../../docs/adr/0054-depth-is-reversed-and-infinite.md); [`lavapipe.md`](../../../research/parity/lavapipe.md) section 5.
