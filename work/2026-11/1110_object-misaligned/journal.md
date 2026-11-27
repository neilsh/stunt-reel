# Journal

## 2026-11-27: census, calibration and the seven-film re-grade

`[Bounded Observation]`, 2026-11-27, the branch at `6d511d1`, lavapipe (`llvmpipe (LLVM 20.1.2, 256 bits)`, no drift on any film against `expected/lavapipe.toml`), cloud session.

**Method.**
1. `mise run parity -- --software-only`, then `errors-make --film <f>` for the seven films (seed 1, 12 sheets each, 20 categories, pairing `render_tick`).
2. Two Haiku passes per film, `errors-disputes`, one Sonnet tie-break per film (disputed sheets: CTRY 8, INTRO 3, LAND 2, BALLOON 4, TRAINTNL 3, BOMB 2, LOCATION 3), `errors-score`.
   The readouts replace `research/parity/readouts/*.json` and `baseline.toml`; `errors-score --against` on CTRY and TRAINTNL then prints `changes since …: none`.
3. [`census.py`](census.py) over the 84 readout frames, with the plan's criterion (objects of at least 64 unmasked pixels, shift reach 24, gain 0.25, terrain gain under 0.10, timing test over render ticks t-2 to t+2 with slack 0.05).
4. CTRY recapture (`capture-ref --film corpus/stuntisl/VAULT/CTRY.FLM --out <data root>/bench/vault-ctry/recapture`, 121 pages), then `errors-make --film ctry --calibrate --recapture …` (48 sheets), two Haiku passes, 19 disputed sheets to one Sonnet tie-break, `errors-score`.

**Census.**
20 objects on 13 of the 84 frames pass the criterion; none passes on the 12 recapture-as-render control frames (the control swaps CTRY's recapture indices in for the render's, so it tests only that census does not flag a page-identical recapture).

| film | frames flagged | objects | time-explained |
|---|---|---|---|
| ctry | 1 (804) | 1 | 1 |
| intro | 4 (1355, 2597, 2773, 3125) | 6 | 1 |
| land | 1 (177) | 1 | 1 |
| balloon | 1 (970) | 1 | 0 |
| traintnl | 5 (12, 123, 232, 342, 562) | 9 | 1 |
| bomb | 0 | 0 | |
| location | 1 (683) | 1 | 1 |

- 5 of the 20 objects are time-explained (a render tick within 2 of the paired one lines up as well as the best shift).
- TRAINTNL 232: the four carriages and the track prop (5 objects) show a consistent shift of about 3 to 5 px right and 6 to 7 px down (gain 0.63 to 0.80, terrain gain 0.04), and none is time-explained.
  The grader's note put the train 15 to 20 px high, so the census confirms the direction and the lack of a timing explanation but finds a smaller shift.
- The layer plane does not say which actor draw is the flown aircraft, and the aircraft/non-aircraft labelling (plan step 5) was not done by a second reader: INTRO 1355's `actor0` (3288 px) is the large foreground aircraft on the one sheet read, and it and INTRO 2773's `actor0` are probably aircraft; the other 18 objects are probably not, which is unverified.
- Of the 13 flagged frames, 3 are graded 2 or more in `object-misaligned` (INTRO 1355 and 2773, TRAINTNL 232), 5 are graded 2 or more in `background-misregistration`, and 5 reach 2 in no category (CTRY 804, INTRO 3125 and LAND 177, all time-explained props; BALLOON 970 and TRAINTNL 562, not time-explained).
  So at least 2 frames, BALLOON 970 and TRAINTNL 562, show a small non-timing prop shift that no category catches; both are 2 to 3 px shifts of one prop.

**Re-grade.**
Frames graded 2 or more in `object-misaligned`: INTRO 2, TRAINTNL 1, the other five films 0.
No frame in CTRY's real sheets (the calibration run's own 12 real sheets) reaches 2 there.
The categories' counts moved from the 2026-11-26 baseline by the render, the panels, the pairing and the new category together, so none of the differences is attributed (the re-grade is of the current render, not `6486fb67`: the captures were re-pinned and the pairing changed since, so that render cannot be scored against today's captures here).

**Calibration** (CTRY, seed 1): `calibration PASS`, controls clean 12/12, `actors_removed` 6/6, `shift_y:4` 6/6, `advance:5` 3/6, `props_shift:8` 0/6.
The `props_shift:8` count is reported, not gated.
Zero of six means the graders did not grade `object-misaligned` (or any listed category) above the same tick's real sheet for an 8-column move of the prop layer on CTRY; whether the planted shift is visible on these frames or the graders miss it is not separated here.
The category's detection evidence is therefore the three real frames above, not the planted fault.

**Not done.**
The 16 `research/parity/error-examples/*.png` were not regenerated: 14 of the 16 ticks (the old `ctry-0004` etc.) no longer exist in the re-pinned captures, whose pages sit at other ticks, so the sheets cannot be rebuilt; the other 2 would show the current render, not the one the example names.
They keep the layout they were made in.
No `object-misaligned` example was committed (the two-model rule needs two different models each grading a sheet 2 or more; INTRO 1355 and TRAINTNL 232 qualify only if a Sonnet grade and a Haiku grade both reach 2, which was not checked).

A cloud session can capture: dosbox-automation mounts its own `drives/y` from the mise install under `/root`, which the mount policy refuses, so `capture-ref` sat at the DOS prompt until `cp -r` of the install to `/home/user/dba` and `DOSBOX_AUTOMATION_EXE=/home/user/dba/bin/dosbox` removed the refusal (121 pages in 98 s).
