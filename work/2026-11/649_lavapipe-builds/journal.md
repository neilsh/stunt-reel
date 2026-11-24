# Journal

## 2026-11-24: Three lavapipe builds and the GPU pixel by pixel on one crates tree

- **Question**: how far mesa-dist-win 26.2.6 draws from 25.2.8, from the canonical lavapipe and from the GPU, pixel by pixel and by score, on all seven reference films, and what the largest differing regions are ([#649](https://github.com/neilsh/stunt-reel/issues/649), spike steps 1 to 3; `lavapipe.md` open question 3).
- **Method**: commit `37587968` (`main`), `crates` tree `d897adcc`, clean, all seven reference films, every tick, on the RTX 4070 laptop (AMD Ryzen 7 7745HX).
  - **GPU**: `mise run parity` (`NVIDIA GeForce RTX 4070 Laptop GPU`).
  - **25.2.8** and **26.2.6**: `mise run parity -- --software-only --no-build` on the same binary, with `VK_DRIVER_FILES` naming only the lavapipe ICD of `mesa3d-25.2.8-release-msvc.7z` (`llvmpipe (LLVM 21.1.7, 256 bits)`) or `mesa3d-26.2.6-release-msvc.7z` (`llvmpipe (LLVM 23.1.4, 256 bits)`), downloaded again and matching the SHA-256 `render-on-lavapipe.md` gives for each; the render stores and reports were copied aside after each run.
  - **Canonical**: the same machine under WSL 2, Ubuntu 24.04's `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`), a fresh release build of the same commit in its own WSL worktree, `mise run parity -- --software-only --no-build`, data root on the Linux filesystem; its stores were copied to Windows.
    Each of its seven films scored its `expected/lavapipe.toml` row to the seven decimals the run prints (delta `+0.0000000` or `-0.0000000`).
  - The four runs went one at a time.
  - Pixels: `mise run parity-residue` between every pair of stores.
    For 25.2.8 against 26.2.6, scratch scripts (not committed) read each differing pixel's index and layer from both stores and the GPU's index: per tick, the 4-connected components of the differing pixels, how many are edge pixels (a 4-neighbour of another index in either build), how many keep one layer on both builds, and which build the GPU agrees with; and, at BALLOON 144 and over BOMB 3446 to 3730, each differing pixel's coordinates, indices and layers.
  - Clipper: one sentinel build, `fragment_index` returning 250 when `shade` is not finite (before the ratio fallback; never committed, reverted and rebuilt after), rendered BALLOON 143 to 145, LOCATION 722, 780 and 2107, BOMB 3600 and INTRO 3044 on both mesa-dist-win builds with `mise run frame -- --software-only --no-build`.
    Off the 250 pixels each sentinel tick matched its build's full-run plane exactly.
  - Raw figures: [`figures.txt`](figures.txt).
- **Result**:
  - **Pixels, all ticks of each film** (ticks differing of all ticks, mean differing pixels per tick, the largest on one tick at its tick):

    | Film | Ticks | 25.2.8 vs 26.2.6 | canonical vs 25.2.8 | canonical vs 26.2.6 | GPU vs canonical | GPU vs 25.2.8 | GPU vs 26.2.6 |
    |---|---|---|---|---|---|---|---|
    | CTRY | 1,320 | 114, 0.1, 11 at 808 | 10, 0.0, 2 at 49 | 118, 0.1, 11 at 808 | 1,218, 3.1, 14 at 861 | 1,216, 3.1, 14 at 861 | 1,215, 3.1, 13 at 811 |
    | INTRO | 3,807 | 558, 0.5, 44 at 3044 | 24, 0.0, 4 at 3275 | 562, 0.5, 44 at 3044 | 2,064, 2.2, 25 at 3044 | 2,064, 2.2, 25 at 3044 | 2,136, 2.5, 53 at 3044 |
    | LAND | 1,123 | 150, 0.2, 8 at 503 | 1, 0.0, 1 at 660 | 150, 0.2, 8 at 503 | 1,042, 5.2, 31 at 589 | 1,042, 5.2, 31 at 589 | 1,043, 5.2, 31 at 589 |
    | BALLOON | 1,179 | 608, 1.5, 81 at 144 | 32, 0.1, 7 at 453 | 613, 1.6, 81 at 144 | 1,114, 4.1, 17 at 1163 | 1,112, 4.1, 17 at 1163 | 1,119, 4.2, 83 at 144 |
    | TRAINTNL | 1,222 | 345, 0.4, 5 at 1132 | 10, 0.0, 3 at 49 | 347, 0.4, 5 at 1132 | 1,149, 3.7, 20 at 1135 | 1,149, 3.7, 20 at 1135 | 1,147, 3.7, 19 at 1135 |
    | BOMB | 3,719 | 1,406, 2.7, 74 at 2274 | 23, 0.0, 5 at 1354 | 1,407, 2.7, 74 at 2274 | 3,288, 8.4, 77 at 2272 | 3,286, 8.4, 77 at 2272 | 3,287, 7.5, 82 at 2272 |
    | LOCATION | 8,251 | 1,367, 0.3, 359 at 780 | 108, 0.0, 8 at 4918 | 1,406, 0.3, 359 at 780 | 7,548, 6.3, 359 at 780 | 7,548, 6.3, 359 at 780 | 7,549, 6.3, 321 at 722 |

  - **Scores** (`mean_ssim_scored`, GPU / canonical / 25.2.8 / 26.2.6): CTRY 0.9384875 / 0.9384853 / 0.9384853 / 0.9384865, INTRO 0.8832691 / 0.8832587 / 0.8832591 / 0.8832712, LAND 0.9245423 / 0.9245296 / 0.9245296 / 0.9245330, BALLOON 0.9059092 / 0.9058907 / 0.9058892 / 0.9058823, TRAINTNL 0.9107161 / 0.9107178 / 0.9107178 / 0.9107221, BOMB 0.8948900 / 0.8948693 / 0.8948696 / 0.8948723, LOCATION 0.8727428 / 0.8727596 / 0.8727587 / 0.8727595.
    As differences of these seven-decimal scores, 26.2.6 lies within 0.0000125 of the canonical lavapipe on every film (INTRO +0.0000125 the largest), within 0.0000121 of 25.2.8 (INTRO), and within 0.0000269 of the GPU (BALLOON); 25.2.8 within 0.0000015 of the canonical (BALLOON, which its run's delta, from unrounded scores, prints as -0.0000016).
    Against the `lavapipe` rows, which hold the canonical scores, both mesa-dist-win runs read `not comparable: other adapter` on all seven films (14 rows); the canonical run read `not comparable` on the crates tree, awaiting a repin.
  - **What differs between 25.2.8 and 26.2.6**: 17,001 pixels over the seven films; 16,750 (98.5%) are edge pixels, 11,648 (68.5%) keep one layer on both builds, and 10,039 (59.0%) are components of a single pixel.
    Components of 10 or more pixels occur on BOMB (286 ticks), LOCATION (4) and BALLOON (1, tick 144) only.
    The largest regions:
    - **LOCATION 780** (359 pixels) and **722** (321): a band of actor layer 16 at index 0 against the terrain at index 76, rows 85 to 91 and 80 to 91, reaching the right edge.
      At 780 25.2.8 draws the actor and 26.2.6 the terrain, and the GPU agrees with 26.2.6 on all 359; at 722 26.2.6 draws the actor, and the GPU agrees with 25.2.8 on all 321.
      The canonical lavapipe differs from 25.2.8 by at most 8 pixels on any LOCATION tick, and from the GPU by 359 at 780.
      No pixel of either is one the sentinel marks: none at 780 on either build, and at 722 the 198 marked pixels on each build lie off the band.
      Not traced further; neither build sides with the GPU at both ticks.
    - **BALLOON 144** (81): 78 pixels in one component of actor layer 17, index 168 on 25.2.8 and the GPU against 169 on 26.2.6, and 3 pixels 168 against 48.
      Compared by coordinate in the saved stores, all 78 are pixels the sentinel marks on 25.2.8 (1,827 marked there) and none are on 26.2.6 (1,318 marked, elsewhere); none of the other 3 is marked on 25.2.8.
      `[Supported Inference]` 25.2.8 reaches them through the clipper's NaN and the ratio `shade·w / w`, which gives the GPU's 168, and 26.2.6 interpolates `shade` there, finite, and rounds to 169; no `shade` was read out.
      Which pixels the clipper breaks moves with the build: BALLOON 145 has 4,043 marked pixels on 25.2.8 and none on 26.2.6, and the two draw it identically; BOMB 3600 14,990 against 10,521, 15 differing pixels, none marked.
    - **BOMB 3446 to 3730** (15 pixels on each of 285 ticks, 4,275 in all, of BOMB's 10,029): on every one of the 285 ticks the same row (y 137, x 272 to 286), the actor layer 17 at index 56 on 25.2.8 against a prop (layer 3) at index 14 on 26.2.6, and the GPU agrees with 26.2.6 on 13 of the 15.
      An edge row between an actor and a prop; of these ticks the sentinel rendered BOMB 3600 only; not traced further.
    - **BOMB 2274** (74) and **INTRO 3044** (44): 36 and 42 components of 7 pixels or fewer, all edge pixels, all within one actor layer (pairs such as 21 and 43, or 2 and 3, swapped both ways); the GPU agrees with 25.2.8 on 55 of 74 and 36 of 44.
      Consistent with edge pixels the two builds give to different polygons of one actor; no pixel at INTRO 3044 is one the sentinel marks.
    - **CTRY 808** (11), **LAND 503** (8) and **TRAINTNL 1132** (5): edge pixels within one layer, single pixels at CTRY 808 and TRAINTNL 1132, and at LAND 503 in 6 components of at most 3.
  - **Wall time** for seven films, as each run printed it: GPU 70.35 s with its build, 25.2.8 54.77 s, 26.2.6 67.91 s, canonical 50.55 s.
- **Verdict**: control (a measurement, no renderer change, no repin).
  On this tree the canonical lavapipe and mesa-dist-win 25.2.8 nearly coincide (1 to 108 ticks a film, at most 8 pixels a tick), 26.2.6 differs from both on 114 to 1,407 ticks a film and by at most 359 pixels on a tick (LOCATION 780, an actor-against-terrain band the GPU draws as 26.2.6 does), and all three differ from the GPU on most ticks (2.2 to 8.4 pixels a tick on average); every score lies within 0.00003 of the others'.
  Most differing pixels are single edge pixels; BALLOON 144's region (78 pixels) lies on the clipper's NaN path on 25.2.8, and no differing pixel of the other ticks the sentinel rendered (LOCATION 722 and 780, BOMB 3600, INTRO 3044) does.
- **Lives in**: [`lavapipe.md` § 7](../../../research/parity/lavapipe.md#7-three-lavapipe-builds-on-one-tree).
