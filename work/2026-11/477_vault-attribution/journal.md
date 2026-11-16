# Journal

## 2026-11-16: Loss by render layer on the seven VAULT references

**Question**: where does each pinned `VAULT` Patch #3 reference film lose SSIM on today's `main`, by render layer (#477, goal 1)?

**Method**: `mise run parity -- --jobs 1` on `main` at `76872e89` (`crates` tree `7aeabce`), RTX 4070. Every film matched its `[<film>.expected.gpu]` table to within 2e-7 SSIM (the tables were measured on `crates` `3449b7b`, so `parity` prints `not comparable: crates/ changed`). Shares are `mean_loss_by_class_scored` over `1 - mean_ssim_scored`, read from each `report.json`; classes under 0.00005 are left out.

**Result**:

| Film | SSIM | IoU | Index agreement | Scored | Largest classes (share of the loss) |
|---|---|---|---|---|---|
| `ctry` | 0.9185 | 0.9910 | 0.916 | 114 | props 0.0402 (49%), sky 0.0153 (19%), terrain 0.0117 (14%), actors 0.0074 (9%), reference-only 0.0064 (8%), ocean 0.0004 |
| `intro` | 0.8535 | 0.9863 | 0.853 | 209 | props 0.0503 (34%), actors 0.0350 (24%), terrain 0.0303 (21%), sky 0.0197 (13%), reference-only 0.0065 (4%), ocean 0.0041 (3%), props and actors render-only 0.0006 |
| `land` | 0.8932 | 0.9852 | 0.895 | 97 | terrain 0.0337 (32%), props 0.0319 (30%), sky 0.0147 (14%), actors 0.0147 (14%), reference-only 0.0093 (9%), ocean 0.0015, props and actors render-only 0.0006, terrain render-only 0.0003 |
| `balloon` | 0.8174 | 0.6409 | 0.499 | 107 | **reference-only 0.1014 (56%)**, actors 0.0376 (21%), terrain 0.0310 (17%), sky 0.0095 (5%), props 0.0015, ocean 0.0011, props and actors render-only 0.0005 |
| `traintnl` | 0.8599 | 0.9659 | 0.858 | 112 | terrain 0.0356 (25%), props 0.0343 (24%), actors 0.0224 (16%), sky 0.0223 (16%), reference-only 0.0215 (15%), ocean 0.0037 (3%), props and actors render-only 0.0004 |
| `bomb` | 0.8444 | 0.9118 | 0.780 | 316 | props 0.0741 (48%), sky 0.0248 (16%), terrain 0.0221 (14%), actors 0.0141 (9%), reference-only 0.0126 (8%), ocean 0.0075 (5%), props and actors render-only 0.0004 |
| `location` | 0.8292 | 0.9784 | 0.841 | 732 | props 0.0845 (49%), terrain 0.0363 (21%), sky 0.0171 (10%), ocean 0.0129 (8%), actors 0.0098 (6%), reference-only 0.0093 (5%), props and actors render-only 0.0009, terrain render-only 0.0001 |

Props are the largest class on `ctry`, `intro`, `bomb` and `location`, terrain on `land` and `traintnl` (props within 0.002 on `land` and 0.0013 on `traintnl`). `balloon` is the outlier: more than half its loss is reference-only, capture geometry where our render draws sky.

**Verdict**: control (a measurement; no change).

**Lives in**: [`attribution.md`](../../../research/parity/attribution.md) section 2.

## 2026-11-16: What drives BALLOON's mask IoU

**Question**: why is `balloon`'s `mean_iou_scored` 0.6409 when the other six score 0.91 to 0.99 (#477, goal 2)?

**Method**: the same render and report as the entry above. Per scored frame, the capture's non-sky mask (index outside 227..=238) against our layer plane, outside the UI overlay, as `mask_iou_planes` in `crates/stunt-cli/src/parity/mask.rs` computes it (reproduced in Python to the report's figure on every frame), with the capture indices on the reference-only pixels counted. Then the same IoU with the capture's sky widened to 224..=238 and to 224..=239, on all seven films. Pictures from `mise run frame -- --film balloon --ticks 155,606`; the render panels are `main` at `76872e89`. Scripts in `build/scratch/` (not committed).

**Result**:

* *Two runs of frames hold the loss.* 41 of 107 scored frames score IoU below 0.5; the median frame scores 0.980. They fall in two runs, and every other frame scores 0.965 or more.
  * **Ticks 12 to 254, 23 frames: a zenith sky the mask reads as geometry.** The camera looks up at the balloon. The capture paints the sky with index 224 (56,000 to 57,400 of the 59,200 viewport pixels at ticks 12 to 200), then 225 and 226 as the view comes down (ticks 210 to 254); our render paints it 228. 224 to 226 lie outside the scorer's sky band 227..=238, so the capture's whole sky counts as non-sky and IoU is 0.000 to 0.453 (mean 0.134) while SSIM stays 0.889 on average (0.93 to 0.95 at ticks 12 to 210). `PLAYONE` writes entries 224 to 238 as one sky gradient, zenith to horizon ([`palette-fade.md`](../../../research/playone-exe/palette-fade.md) section 3.1). Each of these frames also holds 1,746 capture pixels of index 239 at rows 135 to 180, columns 198 to 244: the sun disc, which our render does not draw ([picture](images/balloon-155-zenith-sky-and-sun.png)).
  * **Ticks 606 to 793, 18 frames: our render draws nothing.** The authored camera looks straight down: `render.json` gives `eye` (-2211.7, 159.9, 2073.1) and `target` (-2211.7, -840.1, 2073.1) at tick 606, the same x and z, so the view direction is exactly (0, -1, 0), with an 8.3 degree field of view. The capture shows the balloon from above over grass (index 195 on 35,400 of 59,200 pixels); our layer plane is empty and every pixel is sky index 238 ([picture](images/balloon-606-straight-down-camera.png)). IoU is 0 and SSIM 0.475 to 0.489 (mean 0.480) on all 18. `render.json` holds that camera from tick 601 to 796. `Camera::compute_view_matrix` (`crates/stunt-render/src/camera.rs`) passes the authored eye and target to glam 0.34's `look_at_mat4` with up `Vec3::Y` whenever roll is 0, and glam documents a view direction parallel to `up` as invalid: the side axis is the normalised cross product of two parallel vectors, a zero vector, so the matrix is not finite. That the matrix is NaN on these ticks is read from the code, not measured; an empty layer plane with every sky pixel at 238, the band for a ray that compares false against every edge, fits it.
* *Their share of the IoU.* Mean IoU over the 107 frames: 0.6409 as scored; 0.7705 with the 18 blank frames left out; 0.7303 with the capture's sky widened to 224..=238; 0.8780 with both; 0.9418 with both and 239 (the sun) counted as sky too.
* *Their share of the SSIM.* The 18 blank frames average 0.4803 against 0.8856 for the other 89. Had they scored like the rest, the film mean would be 0.8856 instead of 0.8174; this is a bound on what a camera fix could recover, not a prediction.
* *Their share of the reference-only loss.* Of `balloon`'s 0.1014 reference-only class, 0.0874 (86%) is on the straight-down run and 0.0119 (12%) on the zenith-sky run, from each frame's `loss_by_class`.
* *Other films.* Scanning every tick's camera in the seven films' `render.json` for a view direction whose vertical component is above 0.9999 of its length finds only `balloon` and `intro`. `intro`'s points straight down on ticks 12 to 760, 1520 to 2055 and 3642 to 3818, but none of its scored frames falls in them (all fade to black there, authored fade 0). Widening the capture sky to 224..=238 moves `balloon` 0.6409 -> 0.7303 and `bomb` 0.9118 -> 0.9540, but lowers `traintnl` 0.9659 -> 0.9608, where all 19,850 of its 224-226 capture pixels fall on our non-sky; `ctry`, `intro`, `land` and `location` move by 0.0001 or less. Which shapes paint 224 to 226 on `traintnl` is not known.

**Verdict**: control (attribution; nothing changed). Three follow-ups, filed: the straight-down camera (#615, renderer), the scorer's sky band (#616, scorer) and the zenith bands and the sun disc (#617, renderer).

**Lives in**: [`attribution.md`](../../../research/parity/attribution.md) section 7.

## 2026-11-16: Error readout on the Patch 3 references

**Question**: which kinds of error does a vision-model readout see on the current renders of the pinned references, against the 2026-11-01 readout of [`batch-vault-films.md`](../../../research/parity/batch-vault-films.md) section 4 (its open question 4)?

**Method**: the renders of the first entry (`76872e89`), `mise run parity-bench -- errors-make --film <film>` (12 sheets per film, seed 1), two Haiku passes per film, `errors-disputes`, a Sonnet tie-break on the disputed sheets (intro 4, land 8, balloon 1, traintnl 3, bomb 1, location 4), then `errors-score` with no `--against` (no earlier `readout.json` exists in this checkout). `ctry` got one Haiku pass only: the session's permission check refused the second grader, so `ctry` has no readout here.

**Result**: frames graded 2 or more of 12, per category (all categories with any):

| Film | Ticks | Categories graded 2+ (frames) | `other` notes |
|---|---|---|---|
| `intro` | 1002–3477 | `background-misregistration` 2, `sea-band-wrong` 1 | 5 |
| `land` | 12–903 | `sea-band-wrong` 3, `scenery-missing` 3, `terrain-type-wrong` 1, `shadow-shape-wrong` 1, `ground-shade-edges` 1, `aircraft-misplaced` 1 | 3 |
| `balloon` | 12–1178 | `sun-missing` 3 (12, 122, 221), `frame-blank` 2 (650, 749), `aircraft-absent` 2 (650, 749) | 8 |
| `traintnl` | 12–1233 | `sea-band-wrong` 6 | 7 |
| `bomb` | 12–3477 | `sea-band-wrong` 4, `background-misregistration` 1 | 3 |
| `location` | 134–6161 | `sea-band-wrong` 2, `ground-shade-edges` 2, `terrain-type-wrong` 1, `background-misregistration` 1 | 1 |

`balloon`'s graded frames fall on the two runs of the entry above: `sun-missing` on the zenith-sky run, `frame-blank` and `aircraft-absent` at 650 and 749 in the straight-down run. Its `other` notes are all small edge and shading offsets on the balloon. `bomb`'s three `other` notes (1277, 1585, 1904) say the sky above the horizon is pale grey where the capture shows light blue. `traintnl`'s seven name the railway drawn without sleepers, propellers drawn as dark bars, and train cars a few pixels off. No aircraft category reaches 3 frames on any of the six films, On 2026-11-01 the top aircraft category reached 5 to 11 frames on each of the four films both readouts graded (`balloon` 6, `bomb` 7, `land` 11, `traintnl` 5). Those readouts graded older renders of the pre-stub captures, so the counts are not paired.

**Verdict**: control (a measurement).

**Lives in**: [`batch-vault-films.md`](../../../research/parity/batch-vault-films.md) section 7.
