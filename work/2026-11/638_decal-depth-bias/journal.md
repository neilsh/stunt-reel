# Journal: a decal losing to its own base polygon

## 2026-11-24: BOMB 1910 and every film after #636 and #637, both backends

- **Question**: whether, with #636's eye-relative transforms and #637's reversed, infinite `Depth24Plus` on `main`, a decal still loses to its own base polygon on one backend and not the other, at BOMB 1910 or any other tick, so that #638's stencil or larger-bias options are needed.
- **Method**: `main` `56f26269` (`crates` `d897adcc`) with a temporary `DBG_DECAL_BIAS` switch for the `[I5]` decal bias constant in `pipeline.rs` (committed value 2, slope 2.0 unchanged), on the RTX 4070 Laptop and on the canonical lavapipe (`llvmpipe (LLVM 20.1.2, 256 bits)`, Ubuntu `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` under WSL 2, the same tree and patch in a detached WSL worktree).
  BOMB 1910 alone: `mise run frame -- --film bomb --ticks 1910 --no-build --var DBG_DECAL_BIAS=<v>`, kept on the GPU for 2, 1000000 and `-100000000` (to show the switch reaches the pipeline), and with `--software-only` for 2, 64, 4096 and 1000000 on lavapipe.
  Every film: `DBG_DECAL_BIAS=<v> mise run parity -- --no-build` (lavapipe: `--software-only --workers 4`) for `v` 2 and 4096 on each backend, each `build/parity/ours` tree kept.
  Index and layer planes compared pixel by pixel over every tick by a one-off script over `RenderStore.frame`: GPU against lavapipe for each value, and 2 against 4096 on each backend, with the five largest (index A, index B, layer A, layer B) pairs and the worst ticks per film.
  A second one-off pass took, for each tick of the GPU-against-lavapipe comparison at 2, every (GPU index, lavapipe index) pair within one layer, and counted how many of its pixels have all four neighbours in that pair (interior pixels: a decal losing to its base draws a solid patch, a polygon edge does not).
  A decal draws in its base's layer (its shape's draw: prop 3 or the actor's; #966's flat prop on a flat prop is in the prop layer too); the same pass counted cross-layer pairs for scale.
  Figures: [`residue.txt`](residue.txt).
- **Result**:
  - BOMB 1910: the GPU and lavapipe draw identical index planes (0 differing pixels) at constant 2, at 4096 (each backend's whole-film run) and at 1,000,000.
    On the GPU, 4096 and 1,000,000 draw the same plane as 2, and `-100000000` changes 52,305 pixels, so the switch reached the pipeline; on lavapipe, 64, 4096 and 1,000,000 draw the same plane as 2.
    Before #636, against mesa-dist-win 25.2.8 (a different lavapipe build from the canonical one), the tick differed by 583 pixels on `3a7afb76`, and on `03356d6e` 506 of its differing pixels were the decal (index 7) failing against its base (35) on lavapipe.
  - Every film at constant 2, GPU against lavapipe, mean differing pixels per tick: CTRY 3.09, INTRO 2.21, LAND 5.22, BALLOON 4.12, TRAINTNL 3.66, BOMB 8.39, LOCATION 6.29.
    BOMB's worst tick is 2272 at 77 pixels, as in `expected/agreement.toml` (mean 8.40, `crates` `4d18e7a6`).
    CTRY and BALLOON match the pinned means.
    The pinned means for INTRO, LAND, TRAINTNL and LOCATION are 2.25, 5.23, 3.84 and 8.60, respectively.
    LOCATION moved with #966.
  - Same-layer swaps: of 67,645 (tick, same-layer pair) entries across all 20,621 ticks, two have interior pixels: LOCATION 3947 (layer 3, GPU 193 against lavapipe 148: 17 pixels, 4 interior) and 3836 (the same pair: 19 pixels, 2 interior).
    The largest same-layer pair in any tick covers 46 pixels (LOCATION 2971, layer 3, 14 against 56), 42 in an actor layer (BOMB 2264, layer 17, 160 against 62); every other film's pairs have 0 interior pixels.
    Across layers, one pair has more than 1 interior pixel: LOCATION 780, the GPU's terrain (layer 2, index 76) against lavapipe's actor (layer 16, index 0), 359 pixels, 112 interior, which is not a decal and its base.
  - A constant of 4096 in place of 2 raises the GPU-against-lavapipe mean on every film: CTRY 12.66, INTRO 11.99, LAND 73.37, BALLOON 5.12, TRAINTNL 33.70, BOMB 12.88, LOCATION 66.37.
    It changes every tick of LAND and TRAINTNL on each backend (GPU 248,555 and 173,966 pixels, lavapipe 172,610 and 138,195), and changes pixels on every film on each backend.
- **Verdict**: control.
  No same-layer pair the two backends swap has more than 4 interior pixels on any tick of the seven films.
  The two LOCATION swaps were not attributed to geometry.
  BOMB 1910's index planes now agree, so #638 keeps the current bias for backend agreement on the tested films.
  A constant of 4096 in place of 2 is ruled out: it raised the disagreement on every film.
  `[Supported Inference]`, not measured: in reversed, infinite depth a fixed number of 24-bit steps spans more eye distance the farther the polygon (depth is `near / w`, so a step `d` spans `d·w²/near`), so 4096 steps may push a decal through nearer geometry; which polygons moved was not looked at.
  Constants between 2 and 4096 were not run over whole films; 64 and 1,000,000 were run at BOMB 1910 only.
  Not measured: a decal that loses to its own base on both backends alike, which agreement cannot show, and a strip decal too thin to have interior pixels.
- **Lives in**: [`lavapipe.md`](../../../research/parity/lavapipe.md) section 5 and Ruled out.
