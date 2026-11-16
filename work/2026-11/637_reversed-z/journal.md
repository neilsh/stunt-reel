# Journal

## 2026-11-16: The decal bias constant on single ticks

- **Question**: which constant the `[I5]` decal bias needs once depth is reversed `near / w` in `Depth32Float`, where the constant counts units of `2^(e - 23)` of the triangle's largest depth instead of `2^-24` of depth.
- **Method**: branch `neilsh/637-reversed-z` on PR #650's head `8783a168` (the code later committed as `feat(render): draw with reversed, infinite depth in Depth32Float`), with a temporary `DBG_DECAL_BIAS` switch for the constant and `slope_scale: 2.0`. `mise run frame -- --film <film> --ticks <ticks> --var DBG_DECAL_BIAS=<values>` on the RTX 4070, then the same with `--software-only --no-build` and `VK_DRIVER_FILES` naming the mesa-dist-win 25.2.8 ICD (`llvmpipe (LLVM 21.1.7, 256 bits)` in each store). Index planes compared pixel by pixel between the variants on each backend, and between the backends for each variant, by a one-off script over `RenderStore.frame(tick).indices`. Ticks: LAND 227 and 415; BOMB 1500, 1910, 2113, 2971 and 3000; CTRY 300, 700 and 1102. The `stunt-render` GPU tests (`mise run test-gpu`'s binary) were also run with constants 0, 1, 2 and 16 on both backends.
- **Result**:
  - Constants 2, 16 and 64 (LAND, BOMB 1910, 2113, 2971) and 0 and 16 (BOMB 1500, 1910, 2113, 2971, 3000; CTRY 300, 700, 1102) drew identical index planes on each backend. A constant of -100,000,000 changed 1,668 (GPU) and 1,666 (lavapipe) pixels at BOMB 2971 and 1,781 and 1,785 at 3000, so the switch reached the pipeline.
  - Lavapipe against the GPU, every constant alike: LAND 227 14 pixels, LAND 415 1,903; BOMB 1500 3, 1910 1, 2113 7, 2971 115, 3000 37; CTRY 300 4, 700 36, 1102 17. On #650's tree the PR reported LAND 227 17 and BOMB 1910 1, and LAND 415 2,084 in its full-film stores.
  - Every GPU test passed with every constant on both backends, the 2-degree grazing ground decals of `a_ground_decal_a_kilometre_and_a_half_away_still_shows` included.
- **Verdict**: control. No sampled frame separates the constants, so the slope term and the compare's equality settle these ties; the constant was set to 32 from the worst-case rounding bound in [ADR 0054](../../../docs/adr/0054-depth-is-reversed-and-infinite-in-float.md), not by score.
- **Lives in**: [ADR 0054](../../../docs/adr/0054-depth-is-reversed-and-infinite-in-float.md), "The decal bias".
