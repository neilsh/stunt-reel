# Journal: the Gouraud ground test's one-index allowance on lavapipe

## 2026-11-26: one index of difference in the Gouraud ground test on lavapipe

`[Bounded Observation]`

- **Question**: The shader now draws a vertex on the pixel `PLAYONE`'s projectors truncate it to, which `a_gouraud_ground_polygon_under_a_low_eye_keeps_its_gradient` (a 120 m ground square, index 40 to 100, under a 3 m eye) did not model, and CI's lavapipe failed it; what does the test have to allow, and does it still reject a perspective-correct gradient?
- **Builds**: `mode13h.wgsl` as committed in `e5e4d689` throughout; the test of `ac98edbf` is in `crates` trees `a7acdb14`, `2c5a4012` and `bd8f452f`, which differ only in that test's comment, so its count holds for each.
  Windows: mesa-dist-win 25.2.8 (`lvp_icd.x86_64.json` in `VK_DRIVER_FILES`; the adapter string was not read), `STUNT_REQUIRE_GPU=1`.
  The canonical lavapipe is Ubuntu 24.04's Mesa 25.2.8 under WSL and CI.
  The test is `software_only` (`gpu_or_skip_software`), so it cannot run on the RTX 4070.
- **Command** (Windows runs): `cargo test -p stunt-render --test gpu -- a_gouraud_ground_polygon_under --nocapture`.
- **Results** (each figure's source in brackets):
  - The test before the change, `7121a185`'s, fails with `11588 of 47040 ground pixels are not screen-linear` [a committed test and the committed shader, rerun on 2026-11-26 on Windows; CI's lavapipe gave the same count, per the commit body of `ac98edbf`].
  - After the model snaps the front corners to the truncated pixels (`playone_pixel_ndc`), 2,951 pixels differ, counted with the old allowance for a rounding boundary [the previous session's uncommitted variant, quoted from `ac98edbf`'s message; not rerun].
  - With the test of `ac98edbf` (its code is unchanged in `c790e3e1`; it asserts no pixel beyond one index off and at most 4,500 one index off) plus a temporary `eprintln!` of its counters, `checked=47040 one_off=3167 beyond_one=0 apart=46457`, and the gap at pixel (319, 139) is 74.61 indices [uncommitted instrumented copy of the committed test, run on Windows on 2026-11-26].
    The same 3,167 on the canonical lavapipe was reported by the previous session [not rerun here; a pass there shows at most 4,500 one-off pixels, not the count].
  - With the slide disabled, 0 of 47,040 pixels are one index off or more, so every pixel is equal [uncommitted variant on Windows on 2026-11-26: the final `return` of `playone_vertex` replaced by `vec4<f32>(ndc * clip.w, clip.z, clip.w)`, which keeps the truncated pixel and the vertex's own depth; the previous session's variant, which `ac98edbf`'s message also reports as "none off", was not recorded].
  - The 46,457 pixels are those where the world-X-linear perspective index differs from the unrounded screen-linear model by 3 or more; rounding is monotone, so a perspective-correct render lands 2 or more indices away at each of them, and the committed test's `MIN_APART_PIXELS` is 40,000.
  - An RTX 4070 render of this scene with the slide on, every pixel equal, was reported by the previous session [an unrecorded observation of an uncommitted variant, pointed at the GPU by hand; not rerun, and the committed test cannot reproduce it].
  - "Up to about 0.7 index" of difference, quoted in `ac98edbf`'s message, was not recomputed and is no longer claimed by the test or the PR.
- **Reason**: observed, with the slide on, 3,167 of 47,040 pixels are one index off and none beyond; with the slide disabled, none; the slide-disabled run shows the one-index difference needs the slide.
  `[Hypothesis]` for the cause: the slide changes the two front corners' depths (the polygon reaches behind the eye, so the clipper cuts it), the clipper's fallback then bends the gradient, and rounding turns the bend into one-index flips.
  The run did not isolate the clipper, the ratio's f32 arithmetic or the rasteriser as the cause, and `lavapipe.md` § 3 says the `shade·w / w` ratio is exact at a vertex the clipper makes, which does not fit the hypothesis; the two are not reconciled.
- **Pass without `VK_DRIVER_FILES`**: on Windows with the variable unset the test prints `Skipping software-only GPU test: no software fallback adapter with clip distances (WARP lacks them; ADR 0054)` and passes, with or without `STUNT_REQUIRE_GPU=1`, so a green run there that did not name the lavapipe manifest checked nothing.
- **Pin**: the lavapipe pins end on `crates` tree `1728739f` (the tree after this item's edit to the test's comment, which moved the hash again), from `mise run parity -- --software-only` then `mise run parity-repin -- --class lavapipe` on the parent of the repin commit with `crates/` clean, in Ubuntu 24.04 under WSL (`llvmpipe (LLVM 20.1.2, 256 bits)`), 2026-11-26.
  - Earlier hashes in this change were superseded: `a160e577` (`git rev-parse e5e4d689:crates`, repinned in `b60aba3a`), `a7acdb14` (the tree of the comment before the cut; the pins on `main` after #1099) and `bd8f452f` (`git rev-parse 60d7b49e:crates`, the hedged comment); the file carries none of them now.
  - Every film's SSIM, IoU and `sha256` equal the pins on `2c5a4012` (`git rev-parse c790e3e1:crates`, the tree that cut the comment to its contract) and on `bd8f452f`, so only the `crates` field moved.
- **Verdict**: adopted: the test allows one index, not zero, on lavapipe, guarded by `ONE_OFF_GUARD` (a guard, not a measured bound) and `MIN_APART_PIXELS`; the cause stays a hypothesis.
- **Lives in**: [`lavapipe.md` § 3](../../../research/parity/lavapipe.md#3-the-fix-a-guard-then-the-screen-linear-ratio), the test's comment in `crates/stunt-render/tests/gpu/scene_renderer.rs`.
