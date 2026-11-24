# Journal: is background misregistration a time offset or a page shift?

## 2026-11-23: time offset against page shift on the readout ticks

`[Bounded Observation]`

- **Question**: On the error readout's ticks, does a render-tick offset or a whole-page shift best close the gap between our backdrop and the capture's, and is the answer the same across films?
- **Method**:
  - **Render.** `mise run parity` on `main` at `3e53f767`, every reference film, on the GPU (`NVIDIA GeForce RTX 4070 Laptop GPU`, class `hardware`); scores equal the `gpu` expected rows (ctry 0.9385, intro 0.8833, land 0.9245, balloon 0.9059, traintnl 0.9107, bomb 0.8949, location 0.8727).
    The question is geometric, so the adapter class does not bear on it.
  - **Ticks.** The twelve ticks of each film's readout (`research/parity/readouts/<film>.json`), 84 in all; they include every grade 2+ tick of `background-misregistration` (BOMB 2850, INTRO 1355 and 2597, LAND 419, LOCATION 5611, TRAINTNL 123 and 1013).
  - **Probe.** `parity_probe.py register` (added on this branch), driven by [`run_register.py`](run_register.py) with `--time-reach 4 --shift-reach 6 --pad 8`.
    It compares our backdrop pixels (layers sky, ocean and terrain, more than 8 px from any prop, actor or credit pixel) that lie within one pixel of an index edge in our page, by palette index, with the capture's.
    Flat sky and ground agree under any small move, so only edge pixels carry registration.
    Per tick it reports the agreement as rendered (`base`), the best render tick `t + k` for `k` in -4..+4 with no shift (`time`), the best page shift `dx`, `dy` in -6..+6 at `k = 0` (`page`, our pixel at `(x, y)` against the capture's at `(x + dx, y + dy)`), and the best of both together (`joint`).
    `--with-props` adds the prop layer.
  - **Classification** ([`classify.py`](classify.py)), thresholds chosen for this entry, not measured: a tick with fewer than 500 compared pixels is `few`; one with none is `none` (the page is all props, actors or credits); otherwise `neither` when both gains are under 0.02, `time` when the time gain beats the page gain by 0.02 or more, `page` the converse, `either` when both reach 0.02 within 0.02 of each other.
    `joint` is not used: an offset and a shift compensating each other overfit it (CTRY 540 joins `k = -2` to `dx = -6`, `dy = -1` for +0.003).
  - **Time profiles** ([`time_profile.py`](time_profile.py)): agreement at `k` from -6 to +12 with no shift, on the ticks where time won or tied.
- **Result**:
  Raw output: [`register-backdrop.txt`](register-backdrop.txt), [`register-with-props.txt`](register-with-props.txt), [`time-profiles.txt`](time-profiles.txt).

  | Film | time | page | either | neither | few | none |
  |---|---|---|---|---|---|---|
  | ctry | 1 | 3 | 0 | 7 | 1 | 0 |
  | intro | 2 | 2 | 1 | 4 | 1 | 2 |
  | land | 3 | 1 | 1 | 4 | 3 | 0 |
  | balloon | 0 | 5 | 0 | 5 | 0 | 2 |
  | traintnl | 0 | 2 | 3 | 3 | 2 | 2 |
  | bomb | 0 | 3 | 1 | 7 | 0 | 1 |
  | location | 0 | 1 | 0 | 10 | 0 | 1 |
  | all | 6 | 17 | 6 | 40 | 7 | 8 |

  - **Neither is the commonest class.** 40 of the 69 ticks with enough pixels gain less than 0.02 under any single time offset or page shift tried; LOCATION 10 of 11, CTRY and BOMB 7 of 11.
    By agreement as rendered, 16 of the 40 are at 0.95 or more (nothing a single offset or shift improves by 0.02), 10 between 0.90 and 0.95, and 14 below 0.90 (0.826 to 0.889), where no single time offset or page shift gains 0.02 or more (only the `joint` search, set aside as overfitting, gains 0.02 or more on two of them: BALLOON 331 +0.044, TRAINTNL 793 +0.020).
  - **Page shifts are small and mostly one row.** Over the 23 `page` and `either` ticks, `dy` is -1 on 13, 0 on 6, +1 on 3 and -3 on 1: where the backdrop is off, the capture's edges most often sit one row above ours.
    `dx` has no common sign (0 on 7, -1 on 4, from -6 to +3 on the rest; the three -6, BOMB 12 and 1904 and TRAINTNL 562, sit at the edge of the search).
  - **Time offsets have no common sign across films.** The best `k` on the 12 `time` and `either` ticks: CTRY 980 -4; INTRO 1178 -3, 3125 +4, 3477 -3; LAND 177 +2, 254 +1, 419 +4, 661 +3; TRAINTNL 12 +4, 123 -1, 452 -3; BOMB 2212 +1.
    Only LAND's four agree in sign (the capture ahead of our render).
    The profiles show what lies behind three of them: LAND 419 is a cut (0.437 to 0.438 for every `k` up to 0, then 0.963 to 0.965 from `k = +1` on: the capture already shows the next shot, which we cut to at 420); LAND 177 is a slow pan whose profile climbs in steps to 0.975 at +7; TRAINTNL 452 is 1.000 from -5 to -3 and on a one-row page shift alike, a backdrop that is one horizon line.
  - **The grade 2+ ticks.**
    BOMB 2850: neither (base 0.988, time +0.000, page +0.005).
    INTRO 1355: no backdrop edge (the page is props and actors); with props, neither (+0.013 page).
    INTRO 2597: page, `dx` -2 (+0.039; time +0.002).
    LAND 419: time, the cut above (+0.527).
    LOCATION 5611: neither (base 0.997, time +0.001, page +0.000).
    TRAINTNL 123: either (time `k` -1 +0.141, page `dy` +1 +0.134).
    TRAINTNL 1013: few (102 pixels); with props, page `dy` -1 (+0.044).
- **Verdict**: control (no render change).
  Background misregistration is neither one time offset nor one page shift in any film.
  The one recurring component is a one-row vertical shift of the backdrop (ours low), filed as #1027 on the projection side; the time side shows only per-tick offsets of mixed sign and one cut a tick late (LAND 419), next to the open BOMB 3302 cut a frame early (`attribution.md` open question 7) and the varying page lag of #826.
- **Lives in**: [`framing-and-actors.md` § 4](../../../research/parity/framing-and-actors.md#4-background-misregistration-is-neither-one-time-offset-nor-one-page-shift).
