---
summary: "Records the camera and projection corrections tried against the capture: square 256 px projection (adopted) and the eye-height, pitch, FOV, framing-offset and tick-phase sweeps that were ruled out; the `location` rotor drawn with its solid blades on every tick (#504, #624); and background misregistration, which is neither one time offset nor one page shift on the readout ticks, with a one-row vertical shift recurring that `PLAYONE`'s truncated projection fits (#990, #1027); BOMB's per-shot offsets are that row and pages a tick off while the camera moves, not a camera rule (#1031)."
---

# Parity: Framing and Camera

`[Bounded Observation]`: `CTRY.FLM` (114 scored frames) and `INTRO.FLM` (209), `mean_ssim_scored`.
Covers every camera, projection and actor-tick correction tried against the capture.
The hero aircraft residual they point at is split by subject: [`hero-aircraft-placement.md`](hero-aircraft-placement.md) (position and body), [`hero-aircraft-orientation.md`](hero-aircraft-orientation.md) and [`hero-shadow.md`](hero-shadow.md).
Method: [`method.md`](method.md); score history: journal entries, and before them the [parity log](../../work/2026-10/parity-log/log.md); where the rest of the loss sits: [`attribution.md`](attribution.md).

## 2. Projection: square raster pixels, focal length 256 (adopted)

`[Supported Inference]`, 2026-11-02.
`PLAYONE.EXE` projects with square pixels on the 320 x 200 raster and a focal length of 256 raster pixels at the default lens, so horizontal and vertical focal lengths are equal; the CRT's 1.2x vertical stretch comes after projection.
We had projected at 4:3 with a 45 degree vertical field of view: 241.4 px vertically and 289.7 px horizontally.
The vertical field of view is now `2 * atan(100 / 256)` = 42.67 degrees ([`PLAYONE_FOV_Y_DEGREES`](../../crates/stunt-core/src/contracts/trajectory.rs)) at aspect 320 / 200 ([`MODE13H_PROJECTION_ASPECT`](../../crates/stunt-render/src/camera.rs)). 256 matches the `x 256` screen slopes `0x22A0`/`0x22A2` ([`lod.md`](../playone-exe/lod.md)), but the rule itself has not been read from the disassembly.

* **Horizon probe.**
  The sky/ground boundary was fitted column by column in every scored frame where it is visible: 49 CTRY and 23 INTRO frames.
  In the rest, mountains or framing hide it.
  The probe then compared that boundary with ours at the same tick.
  Capture minus ours at column 160 was -8.4 px (CTRY slot 3), -4.9 (CTRY slot 2), -5.0 (INTRO slot 2) and -10.8 (INTRO slot 4, eye at 500 m).
  It follows the camera's pitch (R² 0.94) and not its altitude (R² 0.10, coefficient about 0), heading or roll.
  The capture's horizon slope is -1.006 tan(roll) against our -0.833 tan(roll), which is the 4:3 pixel aspect.
  A projection fit to the capture's horizon gives `fy` 256 and centre row 91.9, against the live `0x41CA` = 92, with an rms error of 0.39 px.
  Composing the three angles in any other order fits worse (0.71 and 1.31 px), so our Euler order and roll sign stand.
  PLAYONE's horizon sits at infinity.
  Ours is the edge of finite ground, about 5 px low at a 500 m eye height, which is about half of the INTRO slot 4 offset and is still open.
* **Sweep** (`DBG_PROJ_X`, `DBG_PROJ_Y` scaling our focal lengths; `DBG_CAM_PITCH` in degrees).
  Square 256 px (x 0.884, y 1.0605) scored 0.8274 / 0.7155 against 0.7843 / 0.6902.
  Each scale alone gave about half the gain: x 0.884 alone 0.7986 / 0.7068, y 1.0605 alone 0.7934 / 0.6893.
  Moving either scale by about 3% scored lower on both films.
  The fit also suggested a -0.9 degree pitch offset, but every offset tried (-0.9, -0.4, +0.4, +0.9 degrees) cost 0.02 to 0.05, so none was adopted.
  Adopted at 0.8291 / 0.7154, IoU 0.9897 / 0.9712.

This is why the eye-height sweeps below found no consistent answer: a height offset was partly compensating for a projection error that changes with pitch, so its best value depended on the shot.

## 3. `location`: the rotor's solid blades on every tick

`[Established]` that the black trapezoid over `location`'s foreground at ticks 717 to 903 is the solid-blade arm of shape `0x3E57`'s main rotor in its rest pose, by the shape's stream and a render that takes the other arm; the live bank read behind the `PLAYONE` rule below is `[Bounded Observation]`, one film, run with a `.ALL` that differs from the reference capture's ([#504](https://github.com/neilsh/stunt-reel/issues/504)).
The rotor's angle (`ROTY` on bank `0x14`) and its arm (`BVGT` on bank `0x12`) both come from the angle bank ([`angle-bank.md`](../playone-exe/angle-bank.md) § 4), whose words our VM read as 0 for both until [#271](https://github.com/neilsh/stunt-reel/issues/271): the angle stayed at 0, the blades pointing at the camera.
The rotor now turns by bank `0x14` ([`sod-vm-execution.md`](../playone-exe/sod-vm-execution.md) § 8.7), and `BVGT` reads the bank word and records its operand in `DecodeRecord::bank_operands` ([#624](https://github.com/neilsh/stunt-reel/issues/624)), while `PREVIOUS_FRAME_TICKS = 0` keeps word `0x12` at 0 so the solid blades still draw on every tick.
`PLAYONE` spins the rotor and draws line blades whenever var 10 moved by 16 or more since its previous frame.
The trapezoid persists after #495 (`location` at its expected score).

The capture agrees: rows 100 to 184 hold 63 to 69 index-0 pixels at ticks 826, 848, 859, 870 and 892, and large index-0 and index-23 shapes at 837 (7,454 pixels of index 0, 197 of 23) and 881 (4,785 and 201), whose counts differ from each other and, in the capture-beside-render panels of `mise run frame` at those ticks (journal), whose silhouettes differ from our trapezoid.
`[Hypothesis]` that they are the solid blades at two angles other than our rest pose.
Not wrong geometry: with `BVGT` forced to branch, our render draws short lines and no trapezoid.

`[Hypothesis]` that 837 and 881 are frames in which var 10 moved by less than 16 since the previous one.
Under DOSBox-X every frame from 836 to 901 took the line arm, but under the capture harness drawn frames there are 0 ticks apart in 81% of the measured frames with var 10 moving and 1 tick in the rest ([`angle-bank.md`](../playone-exe/angle-bank.md) § 2), so most frames see no change of var 10.
Since #693 our render takes word `0x14` from this frame's var 10 (`PREVIOUS_FRAME_TICKS` = 0), which turned the blades at 881 near the capture's shape.
Choosing the line arm on spun frames now awaits a non-constant frame-spacing rule for word `0x12`.

_Source: [the trapezoid is the rotor's slow arm at rest](../../work/2026-11/504_rotor-trapezoid/journal.md#2026-11-16-the-trapezoid-is-the-rotors-slow-arm-at-rest); [OP_BVGT reads the angle bank](../../work/2026-11/624_sod-bvgt-angle-bank/journal.md#2026-11-19-op_bvgt-reads-bankwordvar-at-draw-time-and-location-rescores-unchanged)._

## 4. Background misregistration is neither one time offset nor one page shift

`[Bounded Observation]`, 2026-11-23, the twelve readout ticks of each of the seven reference films (84), GPU render of `3e53f767`, `parity_probe.py register` ([`probes.md` § 11](probes.md#11-backdrop-registration-register)) ([#990](https://github.com/neilsh/stunt-reel/issues/990)).
The error readout's `background-misregistration` grade rises under both a planted frame advance and a planted page shift, so the grade alone cannot say which one our render has.
Searching render ticks `t - 4` to `t + 4` and page shifts up to 6 px on our backdrop's edge pixels (sky, ocean and terrain away from props and actors) gives, per film:

| Film | Ticks compared | Neither (both gains under 0.02) | Time wins | Page wins | Tie | Grade 2+ ticks |
|---|---|---|---|---|---|---|
| ctry | 11 | 7 | 1 | 3 | 0 | none |
| intro | 9 | 4 | 2 | 2 | 1 | 1355 no backdrop edge; 2597 page, `dx` -2 |
| land | 9 | 4 | 3 | 1 | 1 | 419 time: a cut |
| balloon | 10 | 5 | 0 | 5 | 0 | none |
| traintnl | 8 | 3 | 0 | 2 | 3 | 123 tie; 1013 too few pixels |
| bomb | 11 | 7 | 0 | 3 | 1 | 2850 neither |
| location | 11 | 10 | 0 | 1 | 0 | 5611 neither |

No film's backdrop error is one time offset or one page shift: where one wins, its size and sign change from tick to tick.
`neither` mixes two cases the table does not separate: 16 of its 40 ticks already agree at 0.95 or more as rendered, and 14 sit below 0.90 where no single time offset or page shift gains 0.02 or more (only the `joint` search, set aside as overfitting, gains 0.02 or more on two of them: BALLOON 331 +0.044, TRAINTNL 793 +0.020), an error this probe does not account for.
The two `neither` grade 2+ ticks, BOMB 2850 and LOCATION 5611, agree at 0.988 and 0.997 as rendered, so the probe sees almost no backdrop misregistration there and does not explain their grade.
Two parts recur:

* **A one-row vertical shift, ours low.**
  On 13 of the 23 ticks a page shift helps, the capture's edges sit one row above ours; 3 sit one row below, and the horizontal shift has no common sign.
  That is what truncating projected coordinates toward the projection centre gives, which `PLAYONE`'s register projectors and its anchor transform `0xAE67` do for every vertex of a SOD VM polygon or a ground leaf that is not clipped (a clipped crossing was not read) ([`sod-vm-lines-spans.md` § 8.14](../playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)); drawing vertices so raised every reference film, but no form that keeps the renderer's depth ties has adopted yet ([#1064](https://github.com/neilsh/stunt-reel/issues/1064)).
  _Source: [the register projectors truncate toward the centre](../../work/2026-11/1027_projection-truncation/journal.md#2026-11-24-the-register-projectors-truncate-toward-the-centre)._
* **Per-tick time offsets of either sign.**
  The best render tick on the 12 ticks where time wins or ties lies before the captured tick on 5 and after it on 7, up to the search's reach of 4 either way (LAND 177's wider profile peaks 7 after); only LAND's four all fall after.
  LAND 419 is a cut: the capture already shows the next shot, which our render reaches at 420 (agreement 0.437 to 0.438 for every earlier tick, 0.963 to 0.965 from one tick later).
  BOMB cuts the other way at 3302 ([`attribution.md`](attribution.md#open-questions) open question 7), and #826 asks why CTRY's pages are drawn at a varying tick, so the time side is a per-page lag, not a film-wide one.
  On LOCATION, where a capture with other settings holds a page differing by over 100 pixels at the same tag, a frame's best offset in -2..+2 recurs on few such frames outside the canyon run (4 of 32, 4 of 61, 4 of 53), so those offsets follow the capture's settings ([`capture.md` § 4](../playone-exe/capture.md#4-observed-results)).

_Source: [time offset against page shift on the readout ticks](../../work/2026-11/990_bg-misregistration/journal.md#2026-11-23-time-offset-against-page-shift-on-the-readout-ticks)._

**Every BOMB frame, by shot** (`[Bounded Observation]`, 2026-11-24, all 316 scored `bomb` ticks, GPU render of `bc166452`, `register --with-props`, [#1031](https://github.com/neilsh/stunt-reel/issues/1031)).
Joined to the camera at each tick, the best page shift follows no camera input as a per-shot rule: every frame has the default lens and no roll, and shots with the same eye height (0.2 m on ticks 12 to 420, 0.2 to 1 m on 1915 to 2740) take different shifts.
* **The two static opening shots** (ticks 12 to 420, eye 0.2 m above the ground, pitched 13° and 17° up) shift a row on all 38 frames and gain nothing from any render tick.
  Searched per layer and per half of the frame, the props below the projection centre sit a row low while those above it sit level or a row high, the sign flip that truncation toward the centre gives (open question 5).
  The sky's band edges sit a row low on both halves at tick 155 and on the upper half at 320; the lower half at 320 is level.
* **The larger offsets** (2961, 3191, 3268, and 1013 to 1200, from 2 to 4 px) fall on frames where the camera turns or moves fast, and a render tick or two either way gains about as much as the page shift (2961: +0.266 at one tick back against +0.197; 3191: +0.209 at one tick on against +0.129), while the shot's neighbouring frames gain from neither: the per-page lag above, not the camera.

_Source: [the offset per shot, against the camera](../../work/2026-11/1031_bomb-world-offset/journal.md#2026-11-24-the-offset-per-shot-against-the-camera)._

## Ruled out

All scores `mean_ssim_scored`, CTRY / INTRO unless a single film is named.
Baselines moved between rounds (0.771 / 0.676 on 2026-10-22, 0.7708 / 0.6762 at `d90a047`, 0.7732 / 0.6799 after page timing); each sweep is read against its own baseline.
Nothing below was adopted.

* **Wrong geometry for the `location` trapezoid** (2026-11-16, [#504](https://github.com/neilsh/stunt-reel/issues/504)): the other `BVGT` arm of the same shape draws the capture's line blades; see § 3. [Journal](../../work/2026-11/504_rotor-trapezoid/journal.md#2026-11-16-the-trapezoid-is-the-rotors-slow-arm-at-rest).
* **A per-shot camera offset on BOMB** (2026-11-24, [#1031](https://github.com/neilsh/stunt-reel/issues/1031)): no shot's page shift follows the view slot, the eye or the lens; see § 4. [Journal](../../work/2026-11/1031_bomb-world-offset/journal.md#2026-11-24-the-offset-per-shot-against-the-camera).
* **One time offset or one page shift per film behind `background-misregistration`** (2026-11-23, [#990](https://github.com/neilsh/stunt-reel/issues/990)): on 84 readout ticks, 40 of the 69 with enough edge pixels move under neither (16 of them already agree at 0.95 or more, 14 sit below 0.90), and the best time offsets change sign within INTRO and TRAINTNL; see § 4. [Journal](../../work/2026-11/990_bg-misregistration/journal.md#2026-11-23-time-offset-against-page-shift-on-the-readout-ticks).
* **A montage tick-skipping rule** (2026-11-05, `[Bounded Observation]`, [#73](https://github.com/neilsh/stunt-reel/issues/73)).
  Offset search over -200..+10 on `captures/vault-intro`: the best-matching render tick follows the capture tick at slope 0.99 (largest deviation 7 ticks), so the 0.9-lag reading was a search saturating at -180.
  See [`film-segments.md`](film-segments.md#23-montage-frames).

**Vertical placement, CTRY-only gains** (2026-10-22, [log row](../../work/2026-10/parity-log/log.md)).
Each helps CTRY and costs INTRO, so no global rule:
* Camera eye height `dy` (CTRY): -0.2 m 0.778, **-0.3 m 0.784**, -0.4 m 0.781, -0.6 m 0.777, -0.8 m 0.772, -2 m 0.767, +0.4 m 0.760.
  INTRO (baseline 0.676): -0.3 m 0.668, +0.3 m 0.667, -0.6 m 0.654.
* Camera pitch (CTRY): -2 degrees 0.760 (IoU 0.883 from 0.856), +2 degrees 0.727.
  Finer `DBG_CAM_PITCH` (2026-10-23): -2 0.7598 / 0.6542, -1.5 0.7696 / 0.6601, -1 0.7746 / 0.6620, -0.5 0.7784 / 0.6672, 0 0.7718 / 0.6754, +0.5 0.7566 / 0.6682, +1 0.7475 / 0.6618.
  CTRY peaks at -0.5 degrees (+0.007), INTRO at 0.
  Pitch -0.5 to -4 degrees with a hero ground-offset multiplier of -2 to 4 gave no consistent gain (offset 0 +0.005, pitch -2 +0.002).
* Terrain `base_y` (CTRY): +0.3 m 0.774, +0.6 m 0.773, -0.3 m 0.767.
  `DBG_TERRAIN_BASE` lifting terrain and props together: 0 0.7713 / 0.6775, +0.3 m 0.7733 / 0.6673, +0.6 m 0.7728 / 0.6446, +1.0 m 0.7731 / 0.6575.
* Hero lift (CTRY): +0.3 m **0.780**, +0.6 m 0.775, +1.0 m 0.768, -0.3 m 0.766; by `k * ground_y_offset` k = 1 0.780, k = 2 0.774.
  INTRO, every actor lifted one extra `ground_y_offset` 0.668, two 0.656.
* Second `ground_y_offset` per shape, `DBG_GROUND_LIFT` k times (2026-10-23): 1 **0.7732 / 0.6799**, 1.5 0.7652 / 0.6799, 2 0.7623 / 0.6789, 2.5 0.7576 / 0.6775.
  Only k = 1 is near the peak; the CTRY hero's ~0.3 m is per-actor, not a shape-wide convention.

**Eye height per view slot** (2026-11-01, `fix/gvpoly-colour` at 0.7843 / 0.5189, [log row](../../work/2026-10/parity-log/log.md)).
The hypothesis: each camera is a prop slot, so the eye might sit at a per-prop lens point, which would explain why one global `dy` helped CTRY and cost INTRO.
Every view slot in both films is an undrawn rig (no shape, [`flm.md` § 3.5](../formats/flm.md#35-camera-channel-architecture--director-cuts-i4)), so a lens point could only be keyed by slot.
`DBG_EYE_DY_SLOT`/`DBG_EYE_DY` moved the eye (aim unchanged) for one slot at a time, -1.0 to +1.0 m, scored as the mean SSIM over that slot's frames only:
* CTRY slot 3 (70 frames) and slot 2 (51): best at 0; -0.3 m costs 0.012 and 0.005.
  The 2026-10-22 -0.3 m gain is gone since the aircraft fixes.
* INTRO slot 2 (132 frames): +0.022 at both -1.0 and +0.6 m, -0.006 at -0.3 m: not monotonic, and against CTRY's slot 2 optimum of 0.
  The crop at tick 899 moves the horizon 2-4 px; the ground below it differs more.
* INTRO slot 4 (45): +0.004 at +0.3 m, within its noise; slot 1 (35): +0.018 at +0.3 m, few frames.
  INTRO slot 3 (134): no change at any height; it is the title card (film-segments.md § 2.4).

No offset is shared by one slot across films or by the slots of one film: neither a per-slot nor a global eye offset.

**Field of view** (`DBG_FOV_SCALE`, 2026-10-23): 0.9 0.7638 / 0.6641, 0.95 0.7716 / 0.6708, 1.0 0.7713 / **0.6775**, 1.05 0.7627 / 0.6748, 1.1 0.7541 / 0.6689.
Flat between 0.95 and 1.0 on CTRY, peak at 1.0 on INTRO: not the residual.
(The per-frame lens zoom adopted later is in [`lod.md` § 2.2](../playone-exe/lod.md#22-how-the-lens-scales-the-projection), and its score in [`lod.md` § 4.3](../playone-exe/lod.md#43-the-lens-sets-the-field-of-view-adopted).)

**Single framing offset.**
Normalised cross-correlation over 23 sample frames peaks at median dy -4 px, dx 0, but spread -10 to +5 px and peak correlation only 0.28 to 0.83: geometry error that varies with the camera, not a rigid shift.
Capture-shift scores are in [`attribution.md`](attribution.md#ruled-out).

**Tick phase** (not a lag):
* Camera, capture at `film_tick` t against render at t+d, d -20..+4: 0.762 to 0.774 (baseline 0.771, best d = -4 at 0.774); no consistent lag.
* Actors only, `DBG_ACTOR_TICKS` (camera fixed): -6 0.7645 / 0.6777, -4 0.7677 / 0.6750, -2 0.7705 / 0.6751, 0 **0.7708 / 0.6762**, +2 0.7685 / 0.6753, +4 0.7652 / 0.6747, +6 0.7617 / 0.6744.
  The 0 to 18 px horizontal shift is not a wrong sample tick.
* Actors only on the page-timed baseline: -1 0.7732 / 0.6791, -0.5 0.7733 / 0.6795, 0 **0.7732 / 0.6799**, +0.5 0.7728 / 0.6798.
  The +10 px horizontal residual is not a tick offset.

_Found 2026-10-22 and 2026-10-23 at `d90a047`; see the [parity log](../../work/2026-10/parity-log/log.md)._

## Open questions

1. Closed 2026-11-05: the montage needs no tick-skipping rule; see Ruled out. ([#73](https://github.com/neilsh/stunt-reel/issues/73))
2. The coastline band (capture sand where we draw airfield green) remains; see [`attribution.md`](attribution.md#5-coastline-and-sea). ([#71](https://github.com/neilsh/stunt-reel/issues/71))
3. Two things the projection change of § 2 leaves open.
   First, the projection centre: our 185-row viewport centres it at row 92.5, while the horizon fit gives 91.9 and `0x41CA` reads 92; row 92's centre is our 92.5, so the centre alone moves nothing vertically, and moving our axis half a column right, to column 160's centre, lowered six films ([`sod-vm-lines-spans.md` § 8.14](../playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)).
   Second, the finite ground: at a 500 m eye height our sea edge sits about 5 px below PLAYONE's horizon, which is at infinity.
   That accounts for about half of the INTRO slot 4 offset.
4. Whether `PLAYONE` under dosbox-automation draws some `location` frames less than 16 var-10 units after the previous one, which § 3 hypothesises for ticks 837 and 881; a bank read in the capture harness would show it. ([#624](https://github.com/neilsh/stunt-reel/issues/624))
5. How to draw polygon vertices on the pixels `PLAYONE` truncates them to, toward the projection centre ([`sod-vm-lines-spans.md` § 8.14](../playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)), without breaking the renderer's depth ties, and whether that removes § 4's one-row backdrop shift. ([#1064](https://github.com/neilsh/stunt-reel/issues/1064))
6. Why LAND's capture cuts at tick 419, one tick before our render (§ 4), when BOMB's cuts one captured frame after ours at 3302 ([`attribution.md`](attribution.md#open-questions) open question 7).
