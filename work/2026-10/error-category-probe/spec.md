# Probe: can a vision model name and grade our render errors?

Status: done 2026-10-31; result in `research/parity/method.md` § 2.3, categories in
`research/parity/error-categories.toml`. Haiku grades. The run added a second discovery pass on
`INTRO.FLM` (ticks from 1000, 15 categories in all) and graded both films; detection compares each
matching category rather than the highest grade. Follows the metric bench
([`parity-scoring-2026-10-31.md`](parity-scoring-2026-10-31.md), result in `research/parity/method.md`
§ 2.2), where no numeric metric passed and the Haiku forced-choice judge failed its control.

## Question

Shown a captured frame beside our render, can a model (a) name the kinds of error the render makes,
consistently, with example frames, and (b) grade each kind's presence and severity per frame well
enough to steer the next render fix? The output is an answer and a recommendation; the scripts are
throwaway.

## Why this setup and not the judge's

The judge saw three 320-wide panels and chose which of two near-identical renders was closer; it
scored 0.67 on its easiest control and one subagent declined to guess. Here the model describes
differences that are large (SSIM 0.78; our actors match the capture worse than the ground behind
them), and each image is built for looking:

- capture and render side by side, each stretched to 320x240 and enlarged 2x (nearest), labelled
  `CAPTURE` and `RENDER`;
- below them, the absolute luma difference at the same scale;
- a close-up strip: the bounding boxes of the render's actor (layer 16 and up) and prop (layer 3)
  pixels, padded by 16 pixels, enlarged 4x, capture crop beside render crop.

## Inputs

- `CTRY.FLM`: reference `vault-ctry/frames/004`, recapture `005`, render `build/parity/ours/ctry_current`
  (rendered at `2461289`; this branch changes scoring only).
- 12 frames spread evenly over the scored ticks both captures hold below the fade (tick 990): ticks 4,
  48, 92, 136, 180, 224, 279, 323, 367, 411, 455 and 499, all with aircraft on screen. The button bar
  (rows 185 and below) is painted grey in every panel, since it is not part of the 3D view.
- Faults from `stunt_reel.bench.faults.plant`, applied in memory.

## Steps

1. **Build the sheets** (controller, a script in the session scratchpad). Each sheet gets a random
   12-character id; the key (id to frame, kind, fault) stays in the scratchpad, outside the folder the
   models read.
2. **Discover** (one Haiku, one Sonnet and one Opus subagent, independently, same brief, on the 12 real
   sheets). Per sheet: every difference seen, as `what | where | render vs capture`. Then a list of 5
   to 10 error categories, each with a one-line definition and the sheet ids that show it.
3. **Compare and decide the taxonomy** (controller drafts, the user decides). A side-by-side of the
   three models' categories: which each found, which only one found, and which descriptions disagree
   on the same sheet. From that, a proposed `taxonomy.md` with definitions, example ids and an `other`
   category. The probe stops here until the user settles the categories.
4. **Grade** (one Haiku and one Sonnet subagent, independently, same 42 sheets in the same shuffled
   order):
   - 12 real: render against capture `004`;
   - 12 controls: capture `005` in the `RENDER` panel against `004` at the same tick, which should
     grade as no error;
   - 18 planted: the 12 frames' renders with `actors_removed` (6 frames that have actors), `shift_y:4`
     (6) and `advance:5` (6).

   Per sheet one line: `<id> <category>=<0-3> ... | other: <free text>`, where 0 is absent, 1 minor
   (seen only on a close look), 2 clear, 3 dominates the frame.
5. **Score** each grader (controller script) against the key:
   - **Controls:** at least 10 of 12 have every grade at 1 or below.
   - **Planted:** the grade of the matching category (or an `other` note naming it) rises over the
     same frame's unplanted grade in at least 5 of 6 `actors_removed` and 4 of 6 for each of the two
     others.
   - **Agreement** (reported, not a pass bar): Haiku and Sonnet within one grade per
     (sheet, category) cell, overall and on the real frames.
6. **Report:** send 3 or 4 example sheets with the taxonomy for a human look, and record the result in
   `research/parity/method.md` (a short section after § 2.2) and a `log.md` row.

## Outcomes

- **Haiku passes:** propose a spec for a graded error readout per film (the spec's part 4 by another
  route), cheap enough to run on every render change.
- **Only Sonnet passes:** the same, priced per run; decide whether it runs on every change or on
  demand.
- **Neither passes:** record it and keep to the numeric readouts (spec part 4: offset search, actor
  match).

Discovery also says how much the categories depend on the model: if Haiku finds what Opus finds,
discovery can be rerun cheaply on new films. The real-frame grades are useful whichever way it goes:
a ranked list of error kinds with example frames is the input the next render fix needs.

## Cost

12 image reads each for Haiku, Sonnet and Opus in discovery, then 42 each for Haiku and Sonnet in
grading: 120 image reads over five subagents, within SOP 5's limit.

## Open questions

- Is 12 frames enough to find the categories, or should discovery also see `INTRO.FLM`?
- Should the controls also include the render against itself, to check the grader does not invent
  errors when the two panels are identical?
