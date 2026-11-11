---
summary: "Records the camera and projection corrections tried against the capture: square 256 px projection (adopted) and the eye-height, pitch, FOV, framing-offset and tick-phase sweeps that were ruled out."
---

# Parity: Framing and Camera

`[Bounded Observation]`: `CTRY.FLM` (114 scored frames) and `INTRO.FLM` (209), `mean_ssim_scored`. Covers every camera, projection and actor-tick correction tried against the capture. The hero aircraft residual they point at is split by subject: [`hero-aircraft-placement.md`](hero-aircraft-placement.md) (position and body), [`hero-aircraft-orientation.md`](hero-aircraft-orientation.md) and [`hero-shadow.md`](hero-shadow.md). Method: [`method.md`](method.md); score history: journal entries, and before them the [parity log](../../work/2026-10/parity-log/log.md); where the rest of the loss sits: [`attribution.md`](attribution.md).

## 2. Projection: square raster pixels, focal length 256 (adopted)

`[Supported Inference]`, 2026-11-02. `PLAYONE.EXE` projects with square pixels on the 320 x 200 raster and a focal length of 256 raster pixels at the default lens, so horizontal and vertical focal lengths are equal; the CRT's 1.2x vertical stretch comes after projection. We had projected at 4:3 with a 45 degree vertical field of view: 241.4 px vertically and 289.7 px horizontally. The vertical field of view is now `2 * atan(100 / 256)` = 42.67 degrees ([`PLAYONE_FOV_Y_DEGREES`](../../crates/stunt-core/src/contracts/trajectory.rs)) at aspect 320 / 200 ([`MODE13H_PROJECTION_ASPECT`](../../crates/stunt-render/src/camera.rs)). 256 matches the `x 256` screen slopes `0x22A0`/`0x22A2` ([`lod.md`](../playone-exe/lod.md)), but the rule itself has not been read from the disassembly.

* **Horizon probe.** The sky/ground boundary was fitted column by column in every scored frame where it is visible: 49 CTRY and 23 INTRO frames. In the rest, mountains or framing hide it. The probe then compared that boundary with ours at the same tick. Capture minus ours at column 160 was -8.4 px (CTRY slot 3), -4.9 (CTRY slot 2), -5.0 (INTRO slot 2) and -10.8 (INTRO slot 4, eye at 500 m). It follows the camera's pitch (R² 0.94) and not its altitude (R² 0.10, coefficient about 0), heading or roll. The capture's horizon slope is -1.006 tan(roll) against our -0.833 tan(roll), which is the 4:3 pixel aspect. A projection fit to the capture's horizon gives `fy` 256 and centre row 91.9, against the live `0x41CA` = 92, with an rms error of 0.39 px. Composing the three angles in any other order fits worse (0.71 and 1.31 px), so our Euler order and roll sign stand. PLAYONE's horizon sits at infinity. Ours is the edge of finite ground, about 5 px low at a 500 m eye height, which is about half of the INTRO slot 4 offset and is still open.
* **Sweep** (`DBG_PROJ_X`, `DBG_PROJ_Y` scaling our focal lengths; `DBG_CAM_PITCH` in degrees). Square 256 px (x 0.884, y 1.0605) scored 0.8274 / 0.7155 against 0.7843 / 0.6902. Each scale alone gave about half the gain: x 0.884 alone 0.7986 / 0.7068, y 1.0605 alone 0.7934 / 0.6893. Moving either scale by about 3% scored lower on both films. The fit also suggested a -0.9 degree pitch offset, but every offset tried (-0.9, -0.4, +0.4, +0.9 degrees) cost 0.02 to 0.05, so none was adopted. Adopted at 0.8291 / 0.7154, IoU 0.9897 / 0.9712.

This is why the eye-height sweeps below found no consistent answer: a height offset was partly compensating for a projection error that changes with pitch, so its best value depended on the shot.

## Ruled out

All scores `mean_ssim_scored`, CTRY / INTRO unless a single film is named. Baselines moved between rounds (0.771 / 0.676 on 2026-10-22, 0.7708 / 0.6762 at `d90a047`, 0.7732 / 0.6799 after page timing); each sweep is read against its own baseline. Nothing below was adopted.

* **A montage tick-skipping rule** (2026-11-05, `[Bounded Observation]`, [#73](https://github.com/neilsh/stunt-reel/issues/73)). Offset search over -200..+10 on `captures/vault-intro`: the best-matching render tick follows the capture tick at slope 0.99 (largest deviation 7 ticks), so the 0.9-lag reading was a search saturating at -180. See [`film-segments.md`](film-segments.md#23-montage-frames).

**Vertical placement, CTRY-only gains** (2026-10-22, [log row](../../work/2026-10/parity-log/log.md)). Each helps CTRY and costs INTRO, so no global rule:
* Camera eye height `dy` (CTRY): -0.2 m 0.778, **-0.3 m 0.784**, -0.4 m 0.781, -0.6 m 0.777, -0.8 m 0.772, -2 m 0.767, +0.4 m 0.760. INTRO (baseline 0.676): -0.3 m 0.668, +0.3 m 0.667, -0.6 m 0.654.
* Camera pitch (CTRY): -2 degrees 0.760 (IoU 0.883 from 0.856), +2 degrees 0.727. Finer `DBG_CAM_PITCH` (2026-10-23): -2 0.7598 / 0.6542, -1.5 0.7696 / 0.6601, -1 0.7746 / 0.6620, -0.5 0.7784 / 0.6672, 0 0.7718 / 0.6754, +0.5 0.7566 / 0.6682, +1 0.7475 / 0.6618. CTRY peaks at -0.5 degrees (+0.007), INTRO at 0. Pitch -0.5 to -4 degrees with a hero ground-offset multiplier of -2 to 4 gave no consistent gain (offset 0 +0.005, pitch -2 +0.002).
* Terrain `base_y` (CTRY): +0.3 m 0.774, +0.6 m 0.773, -0.3 m 0.767. `DBG_TERRAIN_BASE` lifting terrain and props together: 0 0.7713 / 0.6775, +0.3 m 0.7733 / 0.6673, +0.6 m 0.7728 / 0.6446, +1.0 m 0.7731 / 0.6575.
* Hero lift (CTRY): +0.3 m **0.780**, +0.6 m 0.775, +1.0 m 0.768, -0.3 m 0.766; by `k * ground_y_offset` k = 1 0.780, k = 2 0.774. INTRO, every actor lifted one extra `ground_y_offset` 0.668, two 0.656.
* Second `ground_y_offset` per shape, `DBG_GROUND_LIFT` k times (2026-10-23): 1 **0.7732 / 0.6799**, 1.5 0.7652 / 0.6799, 2 0.7623 / 0.6789, 2.5 0.7576 / 0.6775. Only k = 1 is near the peak; the CTRY hero's ~0.3 m is per-actor, not a shape-wide convention.

**Eye height per view slot** (2026-11-01, `fix/gvpoly-colour` at 0.7843 / 0.5189, [log row](../../work/2026-10/parity-log/log.md)). The hypothesis: each camera is a prop slot, so the eye might sit at a per-prop lens point, which would explain why one global `dy` helped CTRY and cost INTRO. Every view slot in both films is an undrawn rig (no shape, [`flm.md` § 3.5](../formats/flm.md#35-camera-channel-architecture--director-cuts-i4)), so a lens point could only be keyed by slot. `DBG_EYE_DY_SLOT`/`DBG_EYE_DY` moved the eye (aim unchanged) for one slot at a time, -1.0 to +1.0 m, scored as the mean SSIM over that slot's frames only:
* CTRY slot 3 (70 frames) and slot 2 (51): best at 0; -0.3 m costs 0.012 and 0.005. The 2026-10-22 -0.3 m gain is gone since the aircraft fixes.
* INTRO slot 2 (132 frames): +0.022 at both -1.0 and +0.6 m, -0.006 at -0.3 m: not monotonic, and against CTRY's slot 2 optimum of 0. The crop at tick 899 moves the horizon 2-4 px; the ground below it differs more.
* INTRO slot 4 (45): +0.004 at +0.3 m, within its noise; slot 1 (35): +0.018 at +0.3 m, few frames. INTRO slot 3 (134): no change at any height; it is the title card (film-segments.md § 2.4).

No offset is shared by one slot across films or by the slots of one film: neither a per-slot nor a global eye offset.

**Field of view** (`DBG_FOV_SCALE`, 2026-10-23): 0.9 0.7638 / 0.6641, 0.95 0.7716 / 0.6708, 1.0 0.7713 / **0.6775**, 1.05 0.7627 / 0.6748, 1.1 0.7541 / 0.6689. Flat between 0.95 and 1.0 on CTRY, peak at 1.0 on INTRO: not the residual. (The per-frame lens zoom adopted later is in [`lod.md` § 2.2](../playone-exe/lod.md#22-how-the-lens-scales-the-projection), and its score in § 4.2.)

**Single framing offset.** Normalised cross-correlation over 23 sample frames peaks at median dy -4 px, dx 0, but spread -10 to +5 px and peak correlation only 0.28 to 0.83: geometry error that varies with the camera, not a rigid shift. Capture-shift scores are in [`attribution.md`](attribution.md#ruled-out).

**Tick phase** (not a lag):
* Camera, capture at `film_tick` t against render at t+d, d -20..+4: 0.762 to 0.774 (baseline 0.771, best d = -4 at 0.774); no consistent lag.
* Actors only, `DBG_ACTOR_TICKS` (camera fixed): -6 0.7645 / 0.6777, -4 0.7677 / 0.6750, -2 0.7705 / 0.6751, 0 **0.7708 / 0.6762**, +2 0.7685 / 0.6753, +4 0.7652 / 0.6747, +6 0.7617 / 0.6744. The 0 to 18 px horizontal shift is not a wrong sample tick.
* Actors only on the page-timed baseline: -1 0.7732 / 0.6791, -0.5 0.7733 / 0.6795, 0 **0.7732 / 0.6799**, +0.5 0.7728 / 0.6798. The +10 px horizontal residual is not a tick offset.

_Found 2026-10-22 and 2026-10-23 at `d90a047`; see the [parity log](../../work/2026-10/parity-log/log.md)._

## Open questions

1. Closed 2026-11-05: the montage needs no tick-skipping rule; see Ruled out. ([#73](https://github.com/neilsh/stunt-reel/issues/73))
2. The coastline band (capture sand where we draw airfield green) remains; see [`attribution.md`](attribution.md#5-coastline-and-sea). ([#71](https://github.com/neilsh/stunt-reel/issues/71))
3. Two things the projection change of § 2 leaves open. First, the projection centre: our 185-row viewport centres it at row 92.5, while the horizon fit gives 91.9 and `0x41CA` reads 92; half a row has not been swept. Second, the finite ground: at a 500 m eye height our sea edge sits about 5 px below PLAYONE's horizon, which is at infinity. That accounts for about half of the INTRO slot 4 offset.
