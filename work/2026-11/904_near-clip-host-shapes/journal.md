# Journal

## 2026-11-21: what CTRY shape 926 and BOMB shape 1756 are, and where their loss sits

- **Question**: why do shape 926 (`ctry`, `mean_loss_by_shape_scored` 0.01266, a third of the film's props loss) and shape 1756 (`bomb`, 0.01587, a fifth) lose so much?
- **Method**: `main` at `581453ed`, `mise run parity` on the RTX 4070 (every film matched its `gpu` pin).
  A temporary scorer print (`DBG_SHAPE_DUMP`, saved as [`switches/DBG_SHAPE_DUMP.diff`](switches/DBG_SHAPE_DUMP.diff)) wrote each frame's per-shape props loss from `attribute_shape_loss`; a scratch script decoded `shapes.zst` to compare each shape's pixels with the capture's indices; `mise run frame` drew the worst ticks.
- **Result**:
  - **926 is `SCENERY2.RES` #157 (`0x039E`), the airfield grass tile in colour `0xC4` (196)** ([`world-scene.md` § 3](../../../research/playone-exe/world-scene.md#3-scenery-shapes-drawn-over-the-ground)).
    It covers 94 of 114 scored frames, up to 43,000 of the 59,200 view pixels, and its loss is spread evenly: no frame holds more than 3% of it (0.028 to 0.038 on the worst 25 frames).
    Its own pixels agree with the capture's index on 98.8 to 99.2% at ticks 397, 485, 716 and 771; 88 to 91% of the disagreeing pixels lie within 3 px of its edge, around the hero aircraft and its shadow (picture `build/scratch/ctry-485-shape926-diff.png`, not committed).
    The rest is the capture's clock text at rows 178 to 184 (about 45 px a frame) and, at tick 804, a brown near object at the left edge that our render lacks (1,312 interior pixels).
  - **1756 is drawn in colour 14 on `bomb`, the street surface** under the police-car shots.
    47% of its loss falls on 13 scored frames, ticks 1915 to 2048 (SSIM 0.44 to 0.59, index agreement in the shape 0.00), and 3% more on tick 3302 (SSIM 0.52).
    At 1915 to 2048 the camera rides beside the police car: the capture shows the car's white door with the `SIPD` badge filling most of the view, our render shows the street behind it, with only the wheel disc drawn; from tick 2058 on both draw the door (SSIM 0.83).
    At 3302 the capture still shows the top-down shot of ticks 3280 to 3290 while ours has already cut to the street shot of 3312, one captured frame early.
- **Verdict**: control (diagnosis).
  926's loss is not the tile's: it is the host of the windows around the hero aircraft and its shadow (next entry).
  1756's loss is not the street's: it is the police car's body missing at close range (the near-clip entry below) and one camera cut one frame early.
- **Lives in**: [`attribution.md` § 2](../../../research/parity/attribution.md#2-current-breakdown).

## 2026-11-21: how much of shape 926's loss lies around the actors

- **Question**: if the hero aircraft and both shadows matched exactly, how much of 926's loss would remain?
- **Method**: a capture-side oracle ([`probes.md` § 7](../../../research/parity/probes.md#7-no-rebuild-experiments-on-the-capture)): in a copy of the `vault-ctry` capture, our render's index replaced the capture's within 4 px of every pixel where our layer is an actor (16 and up) or either side shows index 0 (the shadows), 4.7% of the frame on average; `stuntreel parity` rescored the `581453ed` render against it with the per-shape print.
- **Result**: 926 falls 0.01266 -> 0.00354 (-72%), 917 0.00517 -> 0.00253, and the film 0.9376 -> 0.9592 (props 0.0371 -> 0.0235, actors 0.0073 -> 0).
  An oracle, not a realisable gain.
- **Verdict**: control.
  Most of 926's loss is the windows it shares with the hero aircraft and the shadows, so it belongs to their placement and outline ([`hero-aircraft-placement.md`](../../../research/parity/hero-aircraft-placement.md), [`hero-shadow.md`](../../../research/parity/hero-shadow.md)), not to the tile.
- **Lives in**: [`attribution.md` § 2](../../../research/parity/attribution.md#2-current-breakdown).

## 2026-11-21: the near clip plane at 0.5 m against the police car

- **Question**: at `bomb` 1915 to 2048 the police car's door is missing from our render; is our 0.5 m near plane cutting it away?
  `mise run frame -- --film bomb --ticks 1915,1970,2048 --var DBG_NEAR=0.5,0.1,0.02` drew the door at 0.1 and 0.02 and not at 0.5.
- **Method**: a temporary switch `DBG_NEAR` replacing `near_clip` in `compute_proj_matrix` ([`switches/DBG_NEAR.diff`](switches/DBG_NEAR.diff)), on `581453ed`.
  Track: heuristic.
  PLAYONE's clipping projector flags a register when its depth `z + work:0x8088` is at most 0 (`0x1AFA`, image `0x9D3A`; [`sod-animate.md`](../../../research/playone-exe/sod-animate.md)), but the plane its polygon clipper cuts at is not read, so no value is cited.
  Targets, quoted before the sweep: `--target bomb:1915-2048`.
  `mise run sweep -- --var DBG_NEAR=0.5,0.1,0.05,0.02 --track heuristic --record work/2026-11/904_near-clip-host-shapes --topic near clip --target bomb:1915-2048 --images work/2026-11/904_near-clip-host-shapes/images`
- **Result**: the figures are [`sweeps/near-clip.toml`](sweeps/near-clip.toml); `mise run judge -- --recheck` on it prints the same winner line.
  Against 0.5 m, 0.1 m scores `bomb` 0.8775 -> 0.8945 (+0.0170) and `traintnl` 0.9066 -> 0.9103 (+0.0037); `balloon` +0.0002, `land` and `location` +0.0001, `ctry` and `intro` unchanged; `bomb` IoU 0.9648 -> 0.9660, `traintnl` 0.9690 -> 0.9716.
  The 13 target frames rise by 0.317 to 0.465 in SSIM (target index agreement +0.7349); no frame falls by more than 0.005 (the worst, -0.0023).
  Outside the target, `traintnl` 1013 to 1101 rise by 0.037 to 0.065: the camera passes close to the tunnel wall there, and at 0.5 m our render drew a tan wall and the sky through it where the capture shows the green wall (the error readout's note at 1013); `location` 837, 881 and 3829 to 3906 rise by 0.007 to 0.018; `bomb` 2058 and 2762 to 2905 by 0.005 to 0.014.
  0.05 m ties 0.1 m on the target and is 0.0001 lower on four films; 0.02 m scores `location` 0.0003 below 0.1 m and 0.5 m (`worst frame` -0.0078, 6 frames down by more than 0.005), so a nearer plane is not better.
  Pictures: [`bomb-1937-near-clip.png`](images/bomb-1937-near-clip.png), [`bomb-1992-near-clip.png`](images/bomb-1992-near-clip.png), [`bomb-2048-near-clip.png`](images/bomb-2048-near-clip.png) (capture, 0.5 m, 0.1 m; render panels from `581453ed` with the switch).
- **Verdict**: `DBG_NEAR=0.1` adopts on the heuristic track ("winner: DBG_NEAR=0.1 adopts (heuristic, film means; target idx +0.7349; worst target frame +0.3168 bomb:1992)"; its lead over 0.05 m is within the noise floor).
  Not landed in this entry: the switch stays a patch until a PR sets `DEFAULT_NEAR_CLIP` and repins `expected/gpu.toml`.
  The value is a heuristic pick between 0.05 and 0.1; reading the plane PLAYONE's polygon clipper cuts at would make it evidence-backed.
- **Lives in**: [`attribution.md` § 2](../../../research/parity/attribution.md#2-current-breakdown).

## 2026-11-21: the 0.1 m near plane as the default

- **Question**: does `DEFAULT_NEAR_CLIP = 0.1` on a committed tree reproduce the sweep's 0.1 m row?
- **Method**: `a0476c9b` (`crates/` tree `81b0b41`), `mise run parity` on the RTX 4070, then `mise run parity-repin` for `gpu`.
  The `lavapipe` pins measure the cloud's llvmpipe (LLVM 20.1.2), which this machine does not have; they stay on their older tree until the catch-up repin of [#830](https://github.com/neilsh/stunt-reel/issues/830).
- **Result**: `ctry` 0.9376, `intro` 0.8824, `land` 0.9237, `balloon` 0.9059, `traintnl` 0.9103, `bomb` 0.8945, `location` 0.8721, each the sweep's 0.1 m figure to four decimals; IoU `traintnl` 0.9716, `bomb` 0.9660, the rest unchanged to four decimals.
  `bomb` shape 1756 falls 0.01587 -> 0.00836.
  Depth resolution at 1 km coarsens from about 12 cm to 60 cm (`z² / (near × 2²⁴)`); no film fell by more than 0.0001 (`ctry` 0.9376329 -> 0.9375648, `intro` 0.8824304 -> 0.8823589).
- **Verdict**: adopted (the sweep's verdict above); 0.1 m is a heuristic pick, not a value read from `PLAYONE`.
- **Lives in**: [`attribution.md` § 2](../../../research/parity/attribution.md#2-current-breakdown), [`render-model.md`](../../../research/parity/render-model.md).
