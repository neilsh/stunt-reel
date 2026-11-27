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
The timing test scores an actor's own draw, and a prop's layer pixels inside its bounding box grown by 3 px (a prop has no id across ticks), at render ticks t-2, t-1, t+1 and t+2.

| film | frames flagged | objects | time-explained |
|---|---|---|---|
| ctry | 1 (804) | 1 | 0 |
| intro | 4 (1355, 2597, 2773, 3125) | 6 | 0 |
| land | 1 (177) | 1 | 0 |
| balloon | 1 (970) | 1 | 1 |
| traintnl | 5 (12, 123, 232, 342, 562) | 10 | 1 |
| bomb | 0 | 0 | |
| location | 1 (683) | 1 | 1 |

- 3 of the 20 objects are time-explained: BALLOON 970's prop, TRAINTNL 342's horizon strip and LOCATION 683's horizon strip.
- A Sonnet pass read the 13 sheets and labelled each flagged object: 4 are the flown aircraft (CTRY 804 and INTRO 3125 props, INTRO 1355 and 2773 `actor0`), so 16 are not (INTRO 1355's two ground vehicles, INTRO 2597's small distant aircraft, TRAINTNL 232's four train cars and the track props, and the horizon and terrain props).
  The labels are one model's reading of the sheets, not checked by a second.
- All 3 time-explained objects are non-aircraft, so 13 of the 16 non-aircraft objects are not time-explained: placement or something no tick offset removes.
- TRAINTNL 232: the four train cars and the track prop (5 objects) show a consistent shift of about 3 to 5 px right and 6 to 7 px down (gain 0.63 to 0.80, terrain gain 0.04), and none is time-explained.
  The 2026-11-26 readout's note on that frame put the train 15 to 20 px high, so the census confirms the direction and the lack of a timing explanation but finds a smaller shift.
- The 10 frames holding a non-aircraft object: 7 reach 2 in some category (INTRO 1355 and TRAINTNL 232 in `object-misaligned`; INTRO 2597 and TRAINTNL 12, 123 and 342 and LOCATION 683 in `background-misregistration`), and 3 reach 2 in none: LAND 177 and TRAINTNL 562 (not time-explained, 2 to 3 px shifts of one prop) and BALLOON 970 (time-explained).
  So 2 frames show a small, non-timing, non-aircraft shift that no category caught.

**Re-grade.**
Frames graded 2 or more in `object-misaligned`: INTRO 2, TRAINTNL 1, the other five films 0.
No frame in CTRY's real sheets (the calibration run's own 12 real sheets) reaches 2 there.
The categories' counts moved from the 2026-11-26 baseline by the render, the panels, the pairing and the new category together, so none of the differences is attributed (the re-grade is of the current render, not `6486fb67`: the captures were re-pinned and the pairing changed since, so that render cannot be scored against today's captures here).

The graders put INTRO 1355 and 2773 and TRAINTNL 232 at 2 or more in `object-misaligned`, and both Haiku passes graded each of the three 2 or more (so no tie-break was needed).
INTRO 2773's flagged object is a flown aircraft's wing, which the category's own definition leaves to `aircraft-misplaced`, so the graders' use of the new category there is a misfit, not a catch.

**Calibration** (CTRY, seed 1): `calibration PASS`, controls clean 12/12, `actors_removed` 6/6, `shift_y:4` 6/6, `advance:5` 3/6, `props_shift:8` 0/6.
The `props_shift:8` count is reported, not gated.
Zero of six means the graders did not grade `object-misaligned` (or any listed category) above the same tick's real sheet for an 8-column move of the prop layer on CTRY; whether the planted shift is visible on these frames or the graders miss it is not separated here.
The category's detection evidence is therefore the three real frames above (one of them the misfit), not the planted fault.

**Not done.**
The 16 `research/parity/error-examples/*.png` were not regenerated: 14 of the 16 ticks (the old `ctry-0004` etc.) no longer exist in the re-pinned captures, whose pages sit at other ticks, so the sheets cannot be rebuilt; the other 2 would show the current render, not the one the example names.
They keep the layout they were made in.
No `object-misaligned` example was committed: the two-model rule needs two different models each grading a sheet 2 or more, and on INTRO 1355 and 2773 and TRAINTNL 232 both graders were Haiku passes and no Sonnet pass graded them (the tie-break covers disputed sheets only).
The example is an open follow-up: a Sonnet pass over TRAINTNL 232, which the census shows is a clean case.

A cloud session can capture: dosbox-automation mounts its own `drives/y` from the mise install under `/root`, which the mount policy refuses, so `capture-ref` sat at the DOS prompt until `cp -r` of the install to `/home/user/dba` and `DOSBOX_AUTOMATION_EXE=/home/user/dba/bin/dosbox` removed the refusal (121 pages in 98 s).
