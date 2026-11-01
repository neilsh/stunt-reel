# Aircraft render errors: diagnose in parallel, fix serially

Status: spec, approved section by section 2026-11-01. Follows the error readout
([`error-readout-2026-11-01.md`](error-readout-2026-11-01.md); results in
`research/parity/log.md` 2026-11-01 and `research/parity/batch.md` § 4), which named the aircraft as
the render's most common error.

## Intent

Fix the two aircraft errors the readout grades most often, using subagents: the aircraft missing
parts or drawn broken (`CTRY.FLM`: parts missing on 11–12 of 12 frames) and the aircraft not drawn
at all (`INTRO.FLM`: absent on 7–10 of 12; `vault-land` 11 of 12, `vault-splanes` 8 of 12).

What was said: work in a new worktree from the latest `origin/main`; use subagents; this round covers
tracks A and B below only; a fix is adopted on the readout and the score together (user,
2026-11-01). Everything else below is this spec's proposal, approved section by section.

Out of scope this round: pink-cone tents and hangars, sea band, shadows, scenery, black blocks,
sun, blank frames (`batch.md` § 4), and the hero's 10 px placement residual
(`framing-and-actors.md` § 1), except where a diagnosis shows one shares a cause with A or B.

## What the evidence says

- **`CTRY.FLM` tick 48** (`research/parity/error-examples/ctry-0048.png`): we draw the lower wing
  and struts only; the fuselage, upper wing, wheels and cowl are missing. Shape `0x7F37` decodes to
  36 opcode polygons (20 `POLYZ`, 16 `GVPOLY`), 195 triangles in four nodes, one gated at
  `LodDistanceSq(1000)`; the body was a 4–6 px sliver before back-face culling was adopted and is
  still missing after it (`framing-and-actors.md` § 1, `attribution.md` § 6).
- **`INTRO.FLM` tick 1009** (`intro-1009.png`): the triplane draws as a flat black shape only, and
  the parked vehicle and figure beside it are missing too. Whether that shape is a shadow or the
  aircraft collapsed or recoloured is not known.
- Both look like geometry that never reaches the frame (decode, gating, culling, shape
  resolution), not shading, so they can be diagnosed offline from the committed references.

## Design

### 1. Setup and roles

- **Worktree:** `fix/aircraft-render` from `origin/main` at `514053c`, at
  `<repo>.wt/aircraft-render`; `mise run init` once, one release build.
- **Baseline:** `mise run parity` on `ctry` and `intro`, then the error readout on each (the
  `improving-render-parity` skill's "Error readout": `errors-make`, two Haiku graders,
  `errors-disputes`, a Sonnet tie-break if any sheet is disputed, `errors-score`). Each
  `readout.json` is copied to `build/scratch/<film>-readout-baseline.json`; every gate compares
  against these and the baseline scores.
- **Lead** (the orchestrating session): the only writer in the worktree between rounds. Runs every
  build, render, score and readout; reviews diagnoses; dispatches subagents; writes `log.md`.
- **Diagnosticians:** two Sonnet subagents at once, one per track; edit no source in the worktree.
- **Implementer:** one Sonnet subagent at a time, in the worktree; test first, then the fix, then
  `mise run check-rust`; does not commit. The lead reviews the diff and commits or reverts.
- **Graders:** Haiku and Sonnet subagents, dispatched exactly as the skill's "Error readout" says.

### 2. Diagnosis briefs

Each brief is the diagnostician's whole instruction, since a running subagent cannot be messaged.

- **Workspace:** a scratch worktree per track from the same commit (`<repo>.wt/aircraft-diag-a`,
  `-b`, `mise run init`), where it may add temporary instrumentation, since few `DBG_` switches
  remain and two agents building in one checkout would collide. It never commits there. Its
  proposed change goes to `build/scratch/<track>/fix.patch` in the main worktree. The lead reaps
  both scratch worktrees with `mise run reap` at the end.
- **Inputs:** the film's reference capture and baseline render, the example sheets,
  `framing-and-actors.md` § 1, `research/playone-exe/sod-vm.md`, `research/formats/sod-opcodes.md`,
  `stuntreel export-gltf`, `mise run parity-probe`.
- **Track A, aircraft absent** (`INTRO.FLM` ticks 1009 and 1108; check against `vault-land` and
  `vault-splanes`): which actor slot and shape is the aircraft at 1009? Is the shape in
  `INTRO.ALL`, and does `decode_sod` reach `RETURN` or stop on a blocking opcode? How many
  triangles reach the renderer at that tick after LOD, `IFVIS` and culling? What is the flat black
  shape we draw? Are the missing vehicle and figure the same cause?
- **Track B, parts missing** (`CTRY.FLM` ticks 48 and 92, shape `0x7F37`): do all 36 opcode
  polygons reach the mesh? Which faces does the back-face cull remove (culling off)? Is the
  `LodDistanceSq(1000)` node ever drawn? Is the fuselage behind an `IFVIS`/BSP branch we take
  wrongly, or the undecoded two-sided flag (`SodVertex::flags` bit 1)?
- **Output:** `build/scratch/<track>/diagnosis.md` with the headings **Claim**, **Evidence**
  (counts, offsets, at most 3 images cited), **Proposed change** (files, plus `fix.patch`),
  **Predicted effect** per film, **Ruled out**, **Open**; a final reply of five lines or fewer
  pointing to it.
- **Stop rule:** a claim with evidence, or about 60 tool calls or 10 images read; then the best lead
  and what was ruled out. Never capture, never edit `references.toml`, never touch the main
  worktree's source.

### 3. Fix, gate and recording

Per diagnosis:

1. **Review.** The lead reads `diagnosis.md` and reruns its key command. If both tracks name the
   same root cause, they become one fix.
2. **Implement.** One implementer subagent writes a failing test on a synthetic fixture
   (`tests/fixtures/`, no game bytes, [I7]), applies the fix (adapting `fix.patch` to what has
   landed), runs `mise run check-rust`, and reports the diff and test names.
3. **Gate.** One release build; `mise run parity` on both films; the regression verdict against the
   baseline render; the readout on both films `--against` the baseline readouts.
4. **Adopt** (Conventional Commit, body with the evidence) **or revert.** Either way a
   `research/parity/log.md` row, and the finding in its owning note (`framing-and-actors.md`,
   `sod-vm.md`, …).

**Adoption bar.** The bench showed that removing our actors raises SSIM, because they match the
capture worse than the ground (`method.md` § 2.2), so a correct fuselage drawn at the hero's known
10 px offset can lower SSIM. A fix is adopted when:

- **Readout:** on the target film, frames graded 2+ in `aircraft-absent`, `aircraft-parts-missing`
  and `aircraft-shape-broken` together fall by 4 or more (`min_change`), and no other category
  rises by 4 or more on either film.
- **Score:** the regression verdict shows no frame outside the aircraft's windows moving away from
  the capture. Inside them SSIM may fall only if aircraft overlap rises: the render's actor pixels
  (layer plane) against the capture's object pixels, as measured in `framing-and-actors.md` § 1
  (410 of 2,603 at `CTRY.FLM` tick 273). Any SSIM fall is recorded in the log row.

**Rounds:** at most two per track; a round-2 diagnostician gets round 1's gate result in its brief.
A track stops after two rounds with nothing adopted.

**End:** full `mise run check`, push the branch; a PR only when the user asks.

## Risks

- A diagnosis may find the missing geometry depends on a `PLAYONE.EXE` rule not yet decoded (the
  two-sided flag has no known writer). Then the track ends with the finding recorded, not a fix.
- The readout's per-category noise is up to 3 frames; a real fix touching fewer than 4 frames of 12
  cannot pass the readout bar, and is recorded as a lead.
