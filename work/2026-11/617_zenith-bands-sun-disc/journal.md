# Journal: zenith bands and the sun disc (#617)

## 2026-11-20: the sky drawer, the sun disc and the var-13 light read live on BALLOON

- **Question**: what band law `PLAYONE` draws above 23.4 degrees (224 to 227), and where and how large it draws the sun disc of index 239, so the renderer can draw both.
- **Method**: static reads with `mise run re-tool -- disasm` of the var-13 handler `0x196C`, its trig `0x8812` (`0824:05D2`) and sine table (`work:0x19AA`), the sky drawer `0x8C45..0x8E01` with its edge step `0x8E02`, band fill `0x8E6C` and segment clip `0xBBF3`, the disc drawer `0x908E` and the circle builder `0xCF39`.
  Then two DOSBox-X runs on `BALLOON.FLM` (Patch #3, the build the `vault-balloon` capture ran; the film's `.FLM` from the corpus beside the capture's `BALLOON.ALL`, `all_sha256` `e8d852fa...`): the committed plan `tools/dosbox-x/plans/sun-disc.toml` (breaks at the handler's entry and `ret`, the disc drawer after its transform and before its fill, every band edge `0x8D64` and band fill `0x8E86` from tick 205), and `tools/dosbox-x/plans/sky-bands.toml` with the same edge and fill breaks plus the view matrix and band state (`work:0x80C0`, `work:0x41B0..0x41CB`) at the loop start `0x8D36`, from tick 200 (`E:/git/stunt-reel.data/debug/BALLOON/sun-disc-patch3-20261120T094334Z.jsonl`, `sky-bands-patch3-20261120T094650Z.jsonl`).
  A Python model of the band loop and of the span generator was run against those hits and against the capture's pixels.
- **Result**:
  - The handler stores `L = (cos a cos b, -sin a, -cos a sin b)` with `a = var 13 - 0x4000` and `b = 0x71C`, both taken to 12 bits, products floored in Q15.
    Live: variable 13 = `0xF02D` gives `L = (-12259, 30310, 2147)`, which the formula reproduces exactly with the image's table; it also reproduces `CTRY.FLM`'s `(99, 32766, -17)`.
    The table is `round(32767 sin)` over its first half and one more than that half's negation over its second (all 4096 entries checked against the image).
  - The disc: at tick 53 `0x90EF` held centre `(220, 158)`, radius 23, depth word 8054, with the lens mantissa `0x8108` = 31127 and shift `0x810C` = 1; radius `= ((0x600 · 0x8108) >> 8) / DI`, so `12 · zoom / cos` pixels.
    The span generator's rows are `cy - r` to `cy + r - 1`, row `i` spanning `round(sqrt(r² - i²))` either side (checked for every radius below 400); it reproduces the capture's 1,746-pixel disc with no pixel different on all 18 frames from tick 12 to 200, at the centres the live run gives.
    Its direction is 3.75 degrees off the earlier probe's `(sin a, cos a, 0)`: the second angle `b` turns it out of the `x`-`y` plane, which at zoom 1.9 is the probe's 31 px miss.
  - The bands: 15 edges through `j · 1024` along the view's horizontal heading and `2048 - 128 j` up, each a straight screen line parallel to the horizon; the walk starts at the first edge on screen (colour `224 + j` above it), stops at the first off screen (its colour fills the rest), and ends with `0xD0` below edge 14.
    With no edge on screen the view is one fill: 224 looking up (and the sun), `0xD0` looking down.
    The model reproduced the edge rows and the fill colours of all 17 frames the second run logged in full (ticks 223 to 267; the run stopped inside the 18th, 270), to the pixel.
    So ticks 12 to 200 of the capture are all 224 because the camera (76.6 degrees up, zoom 1.9) has the zenith edge above the screen and edge 1 below it, and ticks 276 to 298 are all 208 because the view looks down with no edge on screen.
  - Our evaluated camera agrees with the live matrix: the view direction within 0.002 at ticks 53 and 257.
- **Verdict**: control; the rules are recorded below and implemented in `crates/stunt-render/src/sky.rs`.
- **Lives in**: [`palette-and-shading.md`](../../../research/formats/concepts/palette-and-shading.md#sky-bands) (Sky Bands), [`palette-fade.md`](../../../research/playone-exe/palette-fade.md#32-other-readers-of-the-live-variables) § 3.2, [`terrain-shade.md`](../../../research/playone-exe/terrain-shade.md) § 4.2.

## 2026-11-20: draw the read sky, disc and light, scored on the GPU

- **Question**: does drawing the sky as `0x8C45` does, with the disc of `0x908E` and the var-13 light of `0x196C`, raise the reference films' scores.
- **Method**: evidence-backed track (image offsets `0x8C45`, `0x908E`, `0xCF39`, `0x196C`).
  Variants of a temporary switch `DBG_617`: 0 the measured elevation table (baseline), 1 the read bands, 2 the bands and the disc, 3 those and the var-13 light for shading.
  Target frames, quoted before the sweep: `--target balloon:12-254`.
  `mise run sweep -- --var DBG_617=0,1,2,3 --track evidence --record work/2026-11/617_zenith-bands-sun-disc --topic sky drawer --target balloon:12-254 --images work/2026-11/617_zenith-bands-sun-disc/images`, on the GPU.
- **Result**: `DBG_617=3` adopts on the evidence track, every reference film rising ([figures](sweeps/sky-drawer.toml), recheck with `mise run judge -- --recheck`).

  | Film | Baseline SSIM | Bands (1) | And disc (2) | And light (3) | IoU (all variants) |
  |---|---|---|---|---|---|
  | `ctry` | 0.9190 | 0.9376 | 0.9376 | 0.9376 | 0.9910 |
  | `intro` | 0.8629 | 0.8824 | 0.8824 | 0.8824 | 0.9865 |
  | `land` | 0.8945 | 0.9213 | 0.9213 | 0.9213 | 0.9852 |
  | `balloon` | 0.8842 | 0.8924 | 0.8972 | 0.9057 | 0.8978 |
  | `traintnl` | 0.8635 | 0.9066 | 0.9066 | 0.9066 | 0.9659 |
  | `bomb` | 0.8463 | 0.8770 | 0.8770 | 0.8770 | 0.9626 |
  | `location` | 0.8395 | 0.8680 | 0.8680 | 0.8680 | 0.9796 |

  Winner line: `winner: DBG_617=3 adopts (evidence, film means; target idx +0.8677 attribution; worst target frame +0.0041 balloon:243; 7 frames down >0.005, listed) (noise floor +/-0.002; winner is ~within noise)`; the noise note is the winner's lead over variant 2 in the mean over films (0.8998 against 0.8986), which only `balloon` separates.
  The bands move every film because they replace the measured elevation table everywhere: straight edges and the `0xD0` strip below 1.0 degree.
  The disc and the light move `balloon` alone at four decimals, the film whose variable 13 (`0xF02D`) turns the light off the zenith and whose camera looks up into it.
  IoU does not move: our sky plane is sky whatever its index, and the scorer counts the capture's disc (239) as geometry and ours as sky, filed as [#844](https://github.com/neilsh/stunt-reel/issues/844).
  The seven frames down by more than 0.005: `land:419` -0.0447, where the capture shows another shot than ours (a runway against our F-16), so a sky change lands on unmatched content ([picture](images/land-419-sky-drawer-guard.png)); `location:529` -0.0121, `location:496`, `7097`, `518`, `485` (-0.0094 to -0.0064) and `traintnl:573` -0.0099, where the read bands' straight edges land a few rows off the capture's band edges and the baseline's curved ones happened to sit closer; this entry does not attribute the offset ([picture](images/location-529-sky-drawer-guard.png), [picture](images/traintnl-573-sky-drawer-guard.png)).
  Target pictures, capture | baseline | winner, rendered at this branch's uncommitted tree on `f951d770`: [12](images/balloon-12-sky-drawer.png), [78](images/balloon-78-sky-drawer.png), [144](images/balloon-144-sky-drawer.png), [188](images/balloon-188-sky-drawer.png), [243](images/balloon-243-sky-drawer.png).
- **Verdict**: adopted (evidence track, every film rises); the switch is removed and the read sky, disc and light are the renderer's only path.
- **Lives in**: [`palette-and-shading.md`](../../../research/formats/concepts/palette-and-shading.md#sky-bands) (Sky Bands), [`attribution.md` § 7](../../../research/parity/attribution.md#7-balloons-mask-iou-two-runs-of-frames).
