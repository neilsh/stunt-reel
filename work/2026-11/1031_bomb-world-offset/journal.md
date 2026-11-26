# Journal: BOMB's world offset per shot

## 2026-11-24: the offset per shot, against the camera

- **Question**: on every scored `bomb` frame, how far does our whole frame sit off the capture's, and does it follow the view slot, the eye or the lens (#1031 step 1)?
  On `location` ticks 2201 to 2322, does the crater 1150's near rim move against the far shore (a camera difference) or differ in outline at a fixed offset?
- **Method**: GPU render of `bc166452` (`mise run parity -- --films bomb,location`: `bomb` 0.8949, `location` 0.8727, both equal to their `gpu` pins).
  `mise run parity-probe -- register --with-props --time-reach 4 --shift-reach 6` on all 316 scored `bomb` ticks ([`probes.md` § 11](../../../research/parity/probes.md#11-backdrop-registration-register)), each row joined to the camera `stuntreel film-slots` samples at that tick, with a scratch `roll`, `lens` and `cut` added to its output: [`register-bomb.csv`](register-bomb.csv).
  `register`'s `dx`, `dy` compare our pixel `(x, y)` with the capture's `(x + dx, y + dy)`, so `dy` -1 is ours a row low.
  [`bands.py`](bands.py) repeats the page search per row band, on the edge pixels of one layer at a time with no pad: [`bands.txt`](bands.txt).
  A shot is a run of ticks whose eye moves under 5 m between scored frames.
- **Result**:
  - Every `bomb` frame has the default lens (8192) and zero roll, so the lens takes no part.

    | Ticks | Eye height | Pitch | Yaw | Page shift (frames) | Time offset gaining 0.02 or more (frames) |
    |---|---|---|---|---|---|
    | 12–210 | 0.2 m | +13° | 50° | `dy` -1 (19 of 19), +0.138 | none |
    | 221–420 | 0.2 m | +17° | -87° | `dy` -1 (19 of 19), +0.080 | none |
    | 430–595 | 1.8 m | -1° | -90° | none | none |
    | 606–1904 | 16 to 18 m, 0.7 m from slot 0 | -15° to +22° | 3° to 167° | `dx` -3 on 42 frames, mean +0.052 | +1 or +2 ticks on 22 |
    | 1915–2740 | 0.2 to 1 m | -3° | -177° to -92° | 7 above +0.01, mean +0.003 | -1 or -2 ticks on 10 |
    | 2751–3290 | 18 m, slot 0 | -66° to -17° | all | mixed, mean +0.029 | -1 or -2 on 14, +1 on 2 |
    | 3302–3477 | 0.6 m | -8° to -3° | 13° to 31° | 4 above +0.01 | -1 or -2 on 4 |

  - The frames #989 named split in two.
    On the two static opening shots no render tick moves anything, and the shift is a row: by layer ([`bands.txt`](bands.txt)), the props below the projection centre sit a row low (tick 155 +0.146, 320 +0.161) while those above it sit level (155: `dx` +1, `dy` 0) or a row high (320, +0.008), opposite signs about the centre.
    The sky's band edges sit a row low on both halves at tick 155 and on the upper half at 320; the lower half at 320 is level.
    The frames #989 found 2 to 4 px off (2961, 3191, 3268) and ticks 1013 to 1200 are frames where the camera turns or moves fast, and a render tick or two either way gains about as much as the page shift: 2961 gains 0.266 at one tick back against 0.197 for the best shift, 3191 0.209 at one tick on against 0.129, 1024 0.305 at one tick on against 0.343, and the neighbouring frames of each shot gain nothing from either.
    At 3191 the eye looks 57° down from 19 m and moves 0.2 m a tick with its angles fixed; its prop edges sit 0 to 1 rows off above the centre and 5 columns and 3 rows off below it, the parallax a moving eye gives, not one shift.
  - Ticks 606 to 1002 hold a `dx` -3 shift on the lower half (+0.013); it is too small a gain to separate from shading.
  - **`location` 2201 to 2212**: ours draws the same page at 2201 and 2212 (13,160 compared pixels at both, the same in every band) while the capture's agreement with it falls from 0.713 to 0.496, and no page shift or render tick within 3 raises 2212 by more than 0.008.
    `film-slots` holds the eye at (5133.96, 249.2, -4699.66) from 2201 to 2212 and then moves it 84 m by 2218: slices end at 2198 and 2215, the eye moves more than 50 m between them, so our player flags the 2215 record as a cut and holds the 2198 pose for the whole slice.
    So the near rim's outline differs because our camera stands still while the capture's moves: a camera-position difference, not a shape or cover order.
- **Verdict**: control (diagnosis).
  No `bomb` offset follows the view slot, the eye or the lens as a per-shot rule: the static shots' row is the truncation toward the centre that [#1064](https://github.com/neilsh/stunt-reel/issues/1064) tracks plus the sky's band edges, and the larger offsets are pages drawn a tick or two off ours while the camera moves, the per-page lag of [`framing-and-actors.md` § 4](../../../research/parity/framing-and-actors.md#4-background-misregistration-is-neither-one-time-offset-nor-one-page-shift).
  `location`'s held camera is tested in the next entry.
- **Lives in**: [`framing-and-actors.md` § 4](../../../research/parity/framing-and-actors.md#4-background-misregistration-is-neither-one-time-offset-nor-one-page-shift).

## 2026-11-24: PLAYONE interpolates a slot across any distance

- **Question**: does `PLAYONE` hold a camera that moves more than 50 m in a slice, as our player's displacement cut does ([`[I4]`](../../../docs/SPEC.md#i4-discrete-simulation-ticks--cut-aware-sub-tick-interpolation)), and does interpolating it raise the films?
- **Method**: `mise run re-tool -- disasm 0x3E63 0x3F20`, the per-frame slot interpolation.
  Then a temporary switch, `DBG_NO_DISP_CUT=1`, makes `detect_camera_cut` skip its distance test and keep the `view_obj` switch.
  Evidence-backed track, image `0x3E7A..0x3ECA`; target frames `--target location:2199-2214`, the held slice's two scored frames, reported as attribution:
  `mise run sweep -- --var DBG_NO_DISP_CUT=0,1 --track evidence --target location:2199-2214 --record work/2026-11/1031_bomb-world-offset --topic displacement-cut`.
- **Result**:
  - `0x3E6C` lerps each 16.16 position coordinate as `start + (end − start) · frac` (`0x3E7A..0x3ECA`, through `0x131B`) and each angle word as `start + ((end − start) · (frac >> 1)) >> 15` on the signed 16-bit difference (`0x3ED4..0x3EF5`); nothing in it measures a distance, so `PLAYONE` moves a slot smoothly across a slice however far it goes.
  - The sweep ([`sweeps/displacement-cut.toml`](sweeps/displacement-cut.toml), GPU, `bc166452` plus the switch) raises `intro` from 0.8833 to 0.8937 and `location` from 0.8727 to 0.8863; `ctry`, `land`, `balloon`, `traintnl` and `bomb` do not move.
    The canonical lavapipe under WSL on the committed fix (`crates/` `1140027`) gives the same: `intro` 0.8937, `location` 0.8864.
  - The target frames rise: 2201 from 0.8308 to 0.8828, 2212 from 0.6201 to 0.8698 (index agreement +0.1388 pooled) ([picture](images/location-2201-displacement-cut.png): capture, baseline, candidate).
    INTRO 936 rises from 0.7200 to 0.9758 ([before](images/intro-936-before.png), [after](images/intro-936-after.png): capture beside render).
  - Every other moved frame lies in a slice where the eye moves more than 50 m: `intro` 26 frames on six runs (783 to 936 and 2058 to 2223), all up; `location` 89, of which 87 up, on 1277 to 1289, 3972 to 4137, 4500, the canyon run 6722 to 7635 and 7844.
    The canyon run's eye moves about 59 m per 10-tick slice, so our player flagged every slice a cut and held it: the stepping of [`prop-shape-loss.md` § 2.1](../../../research/parity/prop-shape-loss.md#21-the-camera-held-through-far-moving-slices-fixed) ([#1029](https://github.com/neilsh/stunt-reel/issues/1029)).
    Its 64 scored frames from 6700 to 7400 rise from 0.8312 to 0.9421; 7030 from 0.7409 to 0.9641, 7184 from 0.7226 to 0.8972.
  - Two frames fall by more than 0.005.
    `location` 6942 falls from 0.9653 to 0.8993: with the switch, `register` matches its capture page to our tick 6941 (agreement 0.862, against 0.673 at 6942), a page drawn a tick early, which the held pose happened to resemble ([picture](images/location-6942-displacement-cut-guard.png)).
    `location` 7844 falls by 0.0063; neither render registers it (0.783 with the switch, 0.798 without), its best page shifts pointing opposite ways (4 columns each), so the capture lies between the held and the moving pose.
- **Verdict**: adopted, evidence-backed (image `0x3E7A..0x3ECA`): the winner line adopts on the film means, `intro` +0.0104 and `location` +0.0136 with no film down.
  The angle words' per-word lerp differs from our slerp only within a slice that turns far; it is left to a follow-up issue.
- **Lives in**: [`timeline-and-ticks.md` § 3.2](../../../research/formats/concepts/timeline-and-ticks.md#32-director-cut-suppression), [`[I4]`](../../../docs/SPEC.md#i4-discrete-simulation-ticks--cut-aware-sub-tick-interpolation).
