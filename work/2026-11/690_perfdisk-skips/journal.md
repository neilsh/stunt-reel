# Journal: OP_PERFDISK skips

## 2026-11-20: OP_PERFDISK shadow-mode skip (0xA045)

- **Question**: Does skipping `OP_PERFDISK` (`VERTEX_FLAG_DISC`) during the actor shadow draw (`work:0x806C` set, `0xA040..0xA05A`) raise parity on the seven reference films ([#690](https://github.com/neilsh/stunt-reel/issues/690))?
- **Method**: On `5fbfe844` (RTX 4070 Laptop GPU), with a temporary `DBG_PERFDISK_SHADOW` switch (`0` off, `1` on) in [`scene_renderer.rs`](../../../crates/stunt-render/src/scene_renderer.rs) and [`mode13h.wgsl`](../../../crates/stunt-render/src/shaders/mode13h.wgsl) (saved as [`switches/DBG_PERFDISK_SHADOW.diff`](switches/DBG_PERFDISK_SHADOW.diff)).
  When set, `vs_main` collapses any vertex carrying `FLAG_DISC` (`0x40`, both filled disc triangles and their `outline.rs` rim quads) to `(0, 0, 0, 1)` during shadow draws (`model.layer.y != 0`).
  Evidence-backed track (`0xA045`, `[Established]` static in [`sod-vm-generators.md` § 8.8](../../../research/playone-exe/sod-vm-generators.md#88-model-frame-the-other-generators)), scored with `mise run sweep -- --var DBG_PERFDISK_SHADOW=0,1 --track evidence --record work/2026-11/690_perfdisk-skips --topic "perfdisk shadow mode"`.
  Frames rendered with `mise run frame -- --var DBG_PERFDISK_SHADOW=0,1 --no-build` at the top moved ticks (`intro` 2388, `location` 320).
- **Result**: `winner: DBG_PERFDISK_SHADOW=1 adopts (evidence, film means)`.
  `mean_ssim_scored` before to after: `ctry` 0.9376100 → 0.9376100 (0 frames moved), `intro` 0.8824190 → 0.8824226 (+0.0000035, 63 frames moved, top +0.001067 at tick 2388, worst −0.000616 at tick 1046), `land` 0.9235107 → 0.9235103 (−0.0000004, 3 frames moved), `balloon` 0.9056862 → 0.9056862 (0 frames moved), `traintnl` 0.9066300 → 0.9066296 (−0.0000004, 1 frame moved), `bomb` 0.8774968 → 0.8774970 (+0.0000002, 4 frames moved), `location` 0.8719112 → 0.8719160 (+0.0000048, 18 frames moved, top +0.001179 at tick 320).
  `mean_iou_scored` was unchanged on every film to seven decimals, and no frame fell by more than 0.005.
  Pictures (capture, `DBG_PERFDISK_SHADOW=0`, `DBG_PERFDISK_SHADOW=1` on `5fbfe844`): [INTRO 2388](images/intro-2388-perfdisk-shadow-mode.png) (the triplane's wheel-disc shadows disappear from the ground shadow, matching the capture) and [LOCATION 320](images/location-320-perfdisk-shadow-mode.png) (the helicopter's nose-wheel disc shadow disappears).
  Figures: [`sweeps/perfdisk-shadow-mode.toml`](sweeps/perfdisk-shadow-mode.toml).
- **Verdict**: adopted, evidence-backed (`0xA045`): `intro`, `bomb` and `location` rise and no film falls by more than 0.002 (all deltas are under the 0.002 floor).
- **Lives in**: [`sod-vm-generators.md` § 8.8](../../../research/playone-exe/sod-vm-generators.md#88-model-frame-the-other-generators).

## 2026-11-20: OP_PERFDISK centre-depth skip (below 0x80 signed, 0xA09A)

- **Question**: Does dropping `OP_PERFDISK` discs whose centre's zoomed view depth `z + work:0x8088` is below `0x80` signed (`0xA09A`) change parity on the seven reference films ([#690](https://github.com/neilsh/stunt-reel/issues/690))?
- **Method**: On `5fbfe844` plus Case 1 (RTX 4070 Laptop GPU), with a temporary `DBG_PERFDISK_ZMIN` switch (`0` off, `1` on) in [`camera.rs`](../../../crates/stunt-render/src/camera.rs) and [`mode13h.wgsl`](../../../crates/stunt-render/src/shaders/mode13h.wgsl) (saved as [`switches/DBG_PERFDISK_ZMIN.diff`](switches/DBG_PERFDISK_ZMIN.diff); the diff also shows Case 1's four lines in `mode13h.wgsl`).
  In perspective projections, `CameraUniform._pad1` carries `2^c` (`c = work:0x810C`, `clamp(ceil(log2(disc_depth_scale)), 0, 3)`), `0x31CF`'s normalising shift `s` is computed from `model_matrix[3].xyz` for actors and view-facing props (`model.layer.x != 0`) or `centre_eye` for world meshes, and `vs_main` collapses `FLAG_DISC` vertices when `centre.w < 2^(s + c - 8)`.
  Evidence-backed track (`0xA09A`, `[Established]` static in [`sod-vm-generators.md` § 8.8](../../../research/playone-exe/sod-vm-generators.md#88-model-frame-the-other-generators)), scored with `mise run sweep -- --var DBG_PERFDISK_ZMIN=0,1 --track evidence --record work/2026-11/690_perfdisk-skips --topic "perfdisk centre depth"`.
- **Result**: `winner: none adopts (best DBG_PERFDISK_ZMIN=1: no film rises)`.
  Every reference film scored identically to seven decimal places (`ctry` 0.9376100, `intro` 0.8824226, `land` 0.9235103, `balloon` 0.9056862, `traintnl` 0.9066296, `bomb` 0.8774970, `location` 0.8719160; 0 frames moved in SSIM or index agreement).
  Figures: [`sweeps/perfdisk-centre-depth.toml`](sweeps/perfdisk-centre-depth.toml).
- **Verdict**: rejected / ruled out for the seven reference films (`no film rises`, zero frames changed; no disc in the seven films triggers the `< 0x80` centre-depth threshold on screen).
- **Lives in**: [`sod-vm-generators.md` § Ruled out](../../../research/playone-exe/sod-vm-generators.md#ruled-out).

## 2026-11-20: OP_PERFDISK eye-plane skip (0xA156)

- **Question**: Does dropping whole `OP_PERFDISK` discs any part of whose squeezed rim reaches the eye plane (`0xA156`, `[Supported Inference]`) change parity on the seven reference films ([#690](https://github.com/neilsh/stunt-reel/issues/690))?
- **Method**: On `5fbfe844` plus Case 1 (RTX 4070 Laptop GPU), with a temporary `DBG_PERFDISK_EYEPLANE` switch (`0` off, `1` on) across [`camera.rs`](../../../crates/stunt-render/src/camera.rs), [`mesh.rs`](../../../crates/stunt-render/src/mesh.rs) and [`mode13h.wgsl`](../../../crates/stunt-render/src/shaders/mode13h.wgsl) (saved as [`switches/DBG_PERFDISK_EYEPLANE.diff`](switches/DBG_PERFDISK_EYEPLANE.diff); the diff also shows Case 1's four lines in `mode13h.wgsl`).
  `GpuModel::upload` and `GpuModel::rewrite_vertices` store each filled disc's unit normal in `apex` at `FLAG_DISC && !FLAG_LINE` vertices; `vs_main` finds the disc's view-normal tilt `sin_tilt = sqrt(max(0, 1 - nz^2))` and radius `r = length(in.normal)` and skips the disc when `centre.w <= disc_depth_scale * r * sin_tilt` (`z - zoom * r * sqrt(nx^2 + ny^2) / |n| <= 0`, matching `D <= 0` at `0xA156`).
  Evidence-backed track (`0xA156`, `[Supported Inference]` in [`sod-vm-generators.md` § 8.8](../../../research/playone-exe/sod-vm-generators.md#88-model-frame-the-other-generators)), scored with `mise run sweep -- --var DBG_PERFDISK_EYEPLANE=0,1 --track evidence --record work/2026-11/690_perfdisk-skips --topic "perfdisk eye plane"`.
- **Result**: `winner: none adopts (best DBG_PERFDISK_EYEPLANE=1: no film rises)`.
  Every reference film scored identically to seven decimal places (`ctry` 0.9376100, `intro` 0.8824226, `land` 0.9235103, `balloon` 0.9056862, `traintnl` 0.9066296, `bomb` 0.8774970, `location` 0.8719160; 0 frames moved in SSIM or index agreement).
  Figures: [`sweeps/perfdisk-eye-plane.toml`](sweeps/perfdisk-eye-plane.toml).
- **Verdict**: rejected / ruled out for the seven reference films (`no film rises`, zero frames changed; no disc in the seven films reaches the eye plane on a scored frame).
- **Lives in**: [`sod-vm-generators.md` § Ruled out](../../../research/playone-exe/sod-vm-generators.md#ruled-out).
