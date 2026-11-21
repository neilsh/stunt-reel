# Journal: PLAYONE's scale_index distance cut on scenery props

## 2026-11-20: how many drawn placements lie past their 0x1B28 cut

- **Question**: per reference film, how many placements that the world builder keeps and draws lie past `PLAYONE`'s `0x1B28` distance cut on a scored tick?
- **Method**: static reading first, on `main` at `111970fa`: `mise run re-tool -- disasm 0x31CF 0x3240` and `disasm 0x1B0C 0x1B40`.
  `0x31CF` takes the absolute values of the three 32-bit components (`0x31D5..0x31F3`), keeps the largest (`0x31F6..0x3208`), and looks the bit length of its high word up in the table at `0x323A`, whose entry for `x` is one more than the bit length of `x` (`0x320A..0x3217`); so `s` is one more than the bit length of the high word, and `CL = 16 - s`.
  `0x1B0C..0x1B13` forms `g = [es:8] - CL`, `0x1B15..0x1B21` sets a negative `g` to 0, and `0x1B28` jumps to the carry exit when `g > [0x229E] + 7` (`ja`, unsigned).
  So an object is dropped when the integer part of its largest eye-relative coordinate is at least `2^(22 + [0x229E] - k)` metres, `k` its `scale_index`, taking the walk position as 16.16 metres from the eye (`[Supported Inference]`, as in [#777](../777_far-prop-cull/journal.md#2026-11-18-whether-playone-culls-a-whole-scenery-object-by-screen-size)).
  `[0x229E]` is 0 at the default lens 8192, not 1: `CameraTransform::lod_lens_words` gives `(0xFFFD, 0)` there (`crates/stunt-core/tests/it/contracts_trajectory_test.rs`), and [`lod.md`](../../../research/playone-exe/lod.md) section 2.2 keeps a subtree to about `2 × splitdist` at that lens, `2^(0x229E + 1)` with `0x229E = 0`.
  A temporary `DBG_SCALE_CUT_DUMP` switch (not committed) in `FilmScene::frame` wrote, for each placement record the world draws whose `SP_1NODE` gates hold on the frame, whether it lies past that cut with the frame camera's own `0x229E`, and whether it lies in front of the eye (depth 0.5 to 25,000 m) and inside the half-diagonal of the 320 by 185 view widened by its radius in pixels, roll ignored, a superset of the frame.
  `mise run parity -- --no-build --films <film>` rendered each film's captured ticks on the RTX 4070 with the switch set, and a scratch script kept the lines of scored ticks (the scene is sampled at tick − 1, `capture_tick`).
- **Result**: per film, the placements past their cut on at least one scored tick, then those inside the frame on one:

  | Film | Past the cut | In the frame | Scored ticks with one in the frame |
  |---|---|---|---|
  | `ctry` | 0 | 0 | 0 |
  | `intro` | 12,750 | 0 | 0 |
  | `land` | 48 | 0 | 0 |
  | `balloon` | 0 | 0 | 0 |
  | `traintnl` | 0 | 0 | 0 |
  | `bomb` | 0 | 0 | 0 |
  | `location` | 46,987 | 14 | 9 |

  `location`'s 14 are `SP_1NODE` stand-ins of `scale_index` 14 (`0x071C` to `0x0735`, bounding radius 3.9 to 4.1 m), at 300 to 470 m with the cut at 256 m, 2.1 to 3.6 pixels in radius, on ticks 3642 to 3697 and 6678 to 6700.
  The cut lies inside the 25 km far plane for `scale_index` 8 and above at `0x229E` 0, and 9 and above at 1.
- **Verdict**: control (a count).
  The count is non-zero on `location`, so the cut is swept (next entry).
  [#777](../777_far-prop-cull/journal.md#2026-11-18-whether-playone-culls-a-whole-scenery-object-by-screen-size) took `[0x229E]` as 1 at the default lens; with 0 the cut there falls at `2^(22 - k)` metres, half the distance it gave, and its bound on the radius in pixels at the cut, `R / 2^15`, becomes `R / 2^14`, twice its figures.
  The 14 stand-ins' radii above are of their decoded vertices about the origin, not the header word `R` that bound uses.
- **Lives in**: [`world-scene-residuals.md` § 6.4](../../../research/playone-exe/world-scene-residuals.md#64-the-ground-decal-pass).

## 2026-11-20: applying the 0x1B28 cut per frame

- **Question**: does dropping a scenery placement on each frame where `PLAYONE`'s `0x1B28` cut drops it raise any reference film?
- **Method**: a temporary `DBG_SCALE_CUT` switch (not committed) gives every placement that some camera eye puts past its cut at `0x229E` 0 one more gate on its `SP_1NODE` chain, a `VisibilityCondition` that `CameraTransform` tests per frame with the frame camera's own `0x229E`, as `0x1B28` does (view-facing props get the same gate).
  Positive control: `mise run frame -- --film location --ticks 3642,3697,6700 --var DBG_SCALE_CUT=0,1` changes 25 pixels at tick 6700, 22 of which then match the capture and none did before; at 3642 and 3697 it changes none.
  Sweep: `mise run sweep -- --var DBG_SCALE_CUT=0,1 --track evidence --record work/2026-11/811_scale-index-cut --topic "scale index cut" --target location:3642-3697 --target location:6678-6700 --no-build`, track **evidence** (the rule at image `0x1B28`), on the RTX 4070 at `111970fa` with the temporary switch.
- **Result**: the winner line, `winner: DBG_SCALE_CUT=1 adopts (evidence, film means; target idx +0.0001 attribution; worst target frame +0.0000 location:3642)`; `mise run judge -- --recheck` on the figures gives the same line.
  `location` rises by 0.0000049 in unrounded `mean_ssim_scored` (0.8719 at four decimals either way): ticks 6678, 6689 and 6700 rise by 0.0009, 0.0013 and 0.0014 SSIM and every other frame scores the same.
  The other six films score the same on every frame; no frame of any film falls.
  The target ticks 3642 to 3697 do not move: the stand-ins there change no pixel; whether nearer buildings hide them or they lie outside the frame, which the count's in-frame test (a superset) does not tell apart, was not checked.
  Figures: [`sweeps/scale-index-cut.toml`](sweeps/scale-index-cut.toml); switch: [`switches/DBG_SCALE_CUT.diff`](switches/DBG_SCALE_CUT.diff).
  The committed form (`VisibilityCondition::ScaleReach`, `CameraTransform::scale_reach_keeps`, `Placement::reach`) scored by `mise run parity` gives the `DBG_SCALE_CUT=1` score on every frame of all seven films.
- **Verdict**: adopted, on the evidence track's film-mean branch: `location` rises and no film or frame falls.
  The margin is under the 0.002 noise floor, so the score does not attribute anything to the change; the rule read at `0x1B28` is what adopts it.
- **Lives in**: [`world-scene-residuals.md` § 6.4](../../../research/playone-exe/world-scene-residuals.md#64-the-ground-decal-pass).
