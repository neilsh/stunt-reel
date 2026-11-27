# Journal

## 2026-11-27: the census and the threshold

`[Bounded Observation]`, 2026-11-27, the lavapipe render of `main` at `332acbc` (`llvmpipe (LLVM 20.1.2, 256 bits)`), whose planes digest equals each film's `run.json` `render_digest` from the 2026-11-27 baseline (made at `6d511d1`), so the sheets measured are the ones graded; cloud session.

**Method.**
1. `mise run parity -- --software-only` for the seven films.
2. [`census.py`](census.py) over the baseline's 84 real sheets (12 per film, seed 1, pairing `render_tick`): each sheet's `mismatch_fraction(index_mismatch(capture.idx, render.idx), readout_mask(capture.idx, credits_drawn=…))` at the sheet's `render_tick`, joined to the two Haiku passes' `grades.txt` and `grades-2.txt` kept from the baseline's re-grade (not committed; the committed readouts hold merged counts only).
3. Each sheet is `disputed` (what `errors-disputes` sends to the tie-break), `quiet` (undisputed, neither pass grades any category 2 or more) or `clear` (undisputed, both passes grade some category 2 or more), and noted when either pass wrote an `other` note.
   The census's disputed counts per film (CTRY 8, INTRO 3, LAND 2, BALLOON 4, TRAINTNL 3, BOMB 2, LOCATION 3) equal the baseline's, which checks the join.
   Figures: [`census.txt`](census.txt) (sorted by fraction) and [`census.json`](census.json).

**Spread** (fraction of unmasked pixels whose palette index differs; min, 25th percentile, median, 75th percentile, max):

| Class | Sheets | With a note | Min | P25 | Median | P75 | Max |
|---|---|---|---|---|---|---|---|
| quiet | 38 | 28 | 0.0061 | 0.0289 | 0.0353 | 0.0572 | 0.1271 |
| disputed | 25 | 9 | 0.0194 | 0.0284 | 0.0407 | 0.0525 | 0.0794 |
| clear | 21 | 6 | 0.0251 | 0.0388 | 0.0643 | 0.0820 | 0.1896 |

The classes overlap across most of the range: quiet sheets sit lower on the whole, but a quarter of them are above 0.057, and the highest quiet sheet (BALLOON 749, 0.127) is above every clear sheet but three.
The fraction is driven by the film as much as by the error: BALLOON's median sheet is 0.071, CTRY's 0.033.
All 9 quiet sheets above 0.06 carry an `other` note, and 6 of the notes name a palette or shading difference on the aircraft or balloon (for example BALLOON 749, "balloon envelope facet shading differs, geometry aligned"), so on those the graders saw the difference and judged it shading rather than missing it.
The other 3 name a 1-pixel facet-edge offset (BALLOON 441), a propeller blade angle (INTRO 3125) and cockpit and strut detail drawn over the fuselage (TRAINTNL 1233).

**Threshold.**
The candidates for routing are the 44 undisputed sheets that are quiet or noted (38 quiet, 6 clear with a note).
D4's rule, the lowest fraction above the 25th percentile of sheets with some category clear (0.0329) routing at most 2 candidates per film, gives 0.1232 and routes 2 sheets, both BALLOON, because BALLOON's whole film sits high.
That would leave the route nearly inert, so the threshold follows D4's budget of about 2 per film (about 14 for the seven) instead: `ROUTE_MISMATCH = 0.06` routes 13.

| Threshold | Routed | Per film |
|---|---|---|
| 0.0329 | 29 | BOMB 8, BALLOON 7, LAND 6, INTRO 3, LOCATION 3, CTRY 1, TRAINTNL 1 |
| 0.05 | 19 | BALLOON 7, BOMB 4, INTRO 3, LAND 3, LOCATION 1, TRAINTNL 1 |
| **0.06** | **13** | BALLOON 7, INTRO 2, BOMB 2, LAND 1, TRAINTNL 1 |
| 0.07 | 8 | BALLOON 5, BOMB 2, INTRO 1 |
| 0.1232 | 2 | BALLOON 2 |

At 0.06 the 13 are BALLOON 441, 540, 650, 749, 970, 1068 and 1178; INTRO 2421 and 3125; BOMB 1904 and 2850; LAND 584; TRAINTNL 1233.
Four of them (BALLOON 540, 1068 and 1178, INTRO 2421) are clear with a note; the rest are quiet.
TRAINTNL 232 (0.190), the sheet that prompted the issue, is now clear in both passes (`object-misaligned`), so it is not routed.

The sample is 84 sheets, 12 per film, graded once; the threshold is a budget choice read off this spread, not a boundary the fraction draws between examined and unexamined sheets.
