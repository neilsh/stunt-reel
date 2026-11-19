# Journal: far props under the sub-pixel cull

## 2026-11-18: whether PLAYONE culls a whole scenery object by screen size

- **Question**: before its polygons reach the flat filler `0x7571`, does `PLAYONE` drop a whole scenery object because it is small on screen, as our `build_world` does with `MIN_PROP_PIXELS`?
- **Method**: static reading of the unpacked image with `mise run re-tool -- disasm 0x220B 0x2360` (the `SP_LEAF` handler), `disasm 0x2152 0x21B2` (the `SP_1NODE` far stand-in), `disasm 0x1B0C 0x1B75` (the cull both call) and `disasm 0x31CF 0x3240` (the normaliser that hands the cull its shift), on `main` at `4153a85`.
- **Result**: both draw paths rotate the walk position by `0x80C0`, normalise it at `0x31CF` (which returns 16-bit words and the right shift `CL` that fitted the largest of the three 32-bit components into 16 bits) and call `0x1B0C` (`0x226A` for the leaf, `0x21A0` for the stand-in); carry set skips the object (`jb 0x2202`, `0x21A4`).
  `0x1B0C` sets carry in three places only.
  `0x1B28`: when the shape's `scale_index` (`[es:8]`) less that shift exceeds `[0x229E] + 7`; a farther object has a larger shift, so this difference only falls with distance and the test cannot drop a far object (when the shift is the larger, `0x1B15..0x1B21` shifts the view point right by the difference instead and the test sees 0).
  `0x1B3E`: when the depth plus a fraction of the radius word `[es:4]` is negative, an object behind the eye.
  `0x1B55..0x1B67`: when either screen coordinate lies outside the frustum widened by the radius (`0x22A0`, `0x22A2`, `0x229C`).
  None of the three divides the radius by the depth or compares a projected size with a pixel: a small radius word only narrows the frustum margin, down to the object's centre.
  Past the cull, the display-list run `0x9100` compares the point and the radius only to choose between two polygon-routine sets that both run the stream ([`sod-vm-frame.md` § 9.1](../../../research/playone-exe/sod-vm-frame.md#91-the-actor-shadow-draw)).
- **Verdict**: control (a reading, no score).
  `PLAYONE` draws a scenery object whose centre lies in the frustum, however small; whether a polygon routine inside the stream drops a polygon under a pixel was not read.
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

- **Question**: does dropping the size test (`MIN_PROP_PIXELS` 0, so every placement with a model is built), which the reading of `0x1B0C` above licenses, raise any reference film?
- **Method**: `mise run sweep -- --var DBG_MIN_PROP_PIXELS=0.5,0 --track evidence --record work/2026-11/777_far-prop-cull --topic "size cull" --jobs 4`, track **evidence** (the rule is `0x1B0C`'s, image offsets `0x1B23..0x1B67`), no `--target` (no frame shows a far prop the cull drops), on lavapipe (the only adapter here) at `main` `4153a85` with the temporary switch.
- **Result**: both variants score the same on every film to four decimals, the baseline's lavapipe scores (`ctry` 0.9184, `intro` 0.8612, `land` 0.8943, `balloon` 0.8172, `traintnl` 0.8627, `bomb` 0.8461, `location` 0.8320); no frame moves by more than 0.005.
  The sweep warns that the two variants scored identically and the switch may not be wired; it is wired (the count above shows `location` keeping its 190 extra placements at 0), but they draw nothing.
  Figures: [`sweeps/size-cull.toml`](sweeps/size-cull.toml).
  Winner line: `winner: none adopts (best DBG_MIN_PROP_PIXELS=0: no film rises)`.
- **Verdict**: rejected by the evidence track's film-mean branch (no film rises); the cull stays at 0.5, and only its comment, which still cited the 11 million vertices, is corrected.
  No one-pixel stand-in was built: `INTRO.FLM` never nears the buffer limit, and there is no culled prop to stand in for.
- **Lives in**: [`world-scene-residuals.md` § Ruled out](../../../research/playone-exe/world-scene-residuals.md#ruled-out), [`attribution.md` § Ruled out](../../../research/parity/attribution.md#ruled-out).
