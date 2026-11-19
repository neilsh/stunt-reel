# Journal: far props under the sub-pixel cull

## 2026-11-18: whether PLAYONE culls a whole scenery object by screen size

- **Question**: before its polygons reach the flat filler `0x7571`, does `PLAYONE` drop a whole scenery object because it is small on screen, as our `build_world` does with `MIN_PROP_PIXELS`?
- **Method**: static reading of the unpacked image with `mise run re-tool -- disasm 0x220B 0x2360` (the `SP_LEAF` handler), `disasm 0x2152 0x21B2` (the `SP_1NODE` far stand-in), `disasm 0x1B0C 0x1B75` (the cull both call) and `disasm 0x31CF 0x3240` (the normaliser that hands the cull its shift), on `main` at `4153a85`.
- **Result**: both draw paths normalise the eye-relative walk position at `0x31CF`, rotate it by `0x80C0` and call `0x1B0C` (`0x226A` for the leaf, `0x21A0` for the stand-in); carry set skips the object (`jb 0x2202` at `0x226E` and at `0x21A4`).
  `0x31CF` shifts the three 32-bit 16.16 components right by `s`, one more than the bit length of the high word of the largest, so each fits 16 bits (`0x31D5..0x3226`), and returns `CL = 16 - s` (`0x3228..0x322B`); the callers keep `CX` across the matrix call.
  `0x1B0C` takes the shape's `scale_index` `k` (`[es:8]`) and forms the gap `g = k - CL = k + s - 16` (`0x1B0C..0x1B13`).
  It sets carry in three places only.
  `0x1B28`: when `g` exceeds `[0x229E] + 7`; `s` grows with the largest coordinate, so this is a distance cull: the object is dropped once its largest eye-relative coordinate reaches `2^(22 + [0x229E] - k)` metres.
  When `g` is negative, `0x1B15..0x1B21` shifts the view point right by `-g` and the test sees 0.
  `0x1B3E`: when the depth plus `([es:4] >> g) >> ([0x229E] + 1)` is negative, an object behind the eye; `[es:4] >> g` is the radius word `R` in the view point's units.
  `0x1B55..0x1B67`: when either screen coordinate lies outside the frustum widened by that radius (`0x22A0`, `0x22A2`, `0x229C`).
  So the cull has no test of `R` over depth, but the `0x1B28` distance is keyed to the shape's scale: a shape's units are `2^-k` m, so its radius is under `2^(16 - k)` m, and at the cut, at the default lens (`[0x229E]` = 1, distance `2^(23 - k)` m), it spans at most about `R / 2^15` pixels.
  Over the seven reference archives' shapes (`scale_index` 3 to 16), `R / 2^15` is at most 0.68 pixels in six of them and 1.22 in `location`'s; the cut falls inside our 25 km far plane for `scale_index` 9 and above.
  Past the cull, the display-list run `0x9100` compares the point and the radius only to choose between two polygon-routine sets that both run the stream ([`sod-vm-frame.md` § 9.1](../../../research/playone-exe/sod-vm-frame.md#91-the-actor-shadow-draw)).
- **Verdict**: control (a reading, no score).
  `PLAYONE` does drop far scenery whole, by distance against `scale_index` rather than by projected radius; at the default lens the props it drops are under about a pixel, about the size our half-pixel cull drops.
  A first reading of this entry took `0x31CF`'s `CL` as `s` and so the gap as falling with distance; the fresh review of the commit found the `16 - s`.
  That the components are metres in 16.16 and relative to the eye is `[Supported Inference]` ([`sod-vm.md`](../../../research/playone-exe/sod-vm.md)); whether a polygon routine inside the stream drops a polygon under a pixel was not read.
- **Lives in**: [`world-scene-residuals.md` § 6.4](../../../research/playone-exe/world-scene-residuals.md#64-the-ground-decal-pass).

## 2026-11-18: how many placements the sub-pixel cull drops

- **Question**: per reference film, how many placements does `reaches_a_pixel` drop that project inside the raster on a scored tick, and so how much could lowering `MIN_PROP_PIXELS` gain?
- **Method**: a temporary `DBG_CULL_DUMP` switch (not committed) in `build_world` listed every placement the cull drops, with its radius and its `SP_1NODE` gates, and in `FilmScene::frame` projected each one through the tick's view camera (focal `100 / tan(fov / 2)` pixels, the 320 by 185 view, depth 0.5 to 25,000 m as our projection clips it) and tested its gates; a scratch script re-rendered each film's scored ticks on lavapipe with it set (`main` at `4153a85`) and kept the lines whose tick is scored (the scene is sampled at tick − 1, `capture_tick`).
  A run with the bound raised to 5 pixels checked the probe: `ctry` then drops 7 placements, all 7 on the raster on a scored tick, the largest 4.26 pixels in radius.
  A second pass rendered tick 1 of all 13 corpus films (the seven references' own archives, and `SUPERSET.ALL` for the ten in `stuntisl/VAULT` without one beside them) with the bound at 0.5 and at 0 and read the world's size.
- **Result**: at 0.5 the cull drops **no placement** on `ctry`, `intro`, `land`, `balloon`, `traintnl` or `bomb`, and **190** on `location` (182 of shape `0x0797`, 4 of `0x03F4`, 2 of `0x0729`, one each of `0x0451` and `0x0453`).
  All 190 lie inside the raster on some scored tick and 34 of them pass their gates there, but every one is a shape that decodes to no vertices (radius 0), so there is nothing to paint.
  The props `build_world` leaves out come from `place_props`' walk (the `SP_1NODE` reach and the de-duplication), not from this cull.
  Over the 13 corpus films, dropping the bound to 0 adds placements only on `BALLOON` with `SUPERSET.ALL` (35 placements, 258 vertices onto 1,832,571), `PLANES` and `TRAINTNL` with `SUPERSET.ALL` (2 each, no vertices) and `LOCATION` (the 190, no vertices); `INTRO.FLM`'s world is 819,169 vertices and 1,002,135 indices either way, so the 11 million vertices the comment on `MIN_PROP_PIXELS` cites no longer arise.
- **Verdict**: control (a count).
  Lowering the cull cannot change a pixel of the seven references: the props loss of `location`, `bomb`, `ctry` and `intro` is not far props the cull removes.
- **Lives in**: [`world-scene-residuals.md` § 6.4](../../../research/playone-exe/world-scene-residuals.md#64-the-ground-decal-pass).

## 2026-11-18: removing the size test from the cull

- **Question**: does dropping the size test (`MIN_PROP_PIXELS` 0, so every placement with a model is built) raise any reference film?
- **Method**: `mise run sweep -- --var DBG_MIN_PROP_PIXELS=0.5,0 --track evidence --record work/2026-11/777_far-prop-cull --topic "size cull" --jobs 4`, track **evidence** (on the first, backwards reading of `0x1B0C` above, which took it to have no size test), no `--target` (no frame shows a far prop the cull drops), on lavapipe (the only adapter here) at `main` `4153a85` with the temporary switch.
- **Result**: both variants score the same on every film to four decimals, the baseline's lavapipe scores (`ctry` 0.9184, `intro` 0.8612, `land` 0.8943, `balloon` 0.8172, `traintnl` 0.8627, `bomb` 0.8461, `location` 0.8320); no frame moves by more than 0.005.
  The sweep warns that the two variants scored identically and the switch may not be wired; it is wired (the count above shows `location` keeping its 190 extra placements at 0), but they draw nothing.
  Figures: [`sweeps/size-cull.toml`](sweeps/size-cull.toml).
  Winner line: `winner: none adopts (best DBG_MIN_PROP_PIXELS=0: no film rises)`.
  On the corrected reading the change has no `PLAYONE` rule behind it, so its track is heuristic: the recorded figures judged with `track = "heuristic"` (a scratch copy of the figures file, `mise run judge -- --recheck`) give `winner: none adopts (best DBG_MIN_PROP_PIXELS=0: film means short of +0.002 each or +0.004 on one)`.
- **Verdict**: rejected on either track, since no film moves; the cull stays at 0.5, and only its comment, which still cited the 11 million vertices, is corrected.
  No one-pixel stand-in was built: `INTRO.FLM` never nears the buffer limit, and there is no culled prop to stand in for.
- **Lives in**: [`world-scene-residuals.md` § Ruled out](../../../research/playone-exe/world-scene-residuals.md#ruled-out), [`attribution.md` § Ruled out](../../../research/parity/attribution.md#ruled-out).
