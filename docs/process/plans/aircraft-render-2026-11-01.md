# Aircraft render errors: diagnose in parallel, fix serially

Status: closed 2026-11-01. Both tracks proved to share one cause (`run_vm` skipped `SORTON` and
stopped at the first `RETURN`); round 1 (the walk alone) and round 2 (plus the centre stack and
`SHADE` colour) both failed the score gate on three 2–7 px props-only `INTRO.FLM` frames. Round 2
was adopted as `cddd583` on the user's call that a drawn but miscoloured body beats a missing one,
and on the readout (`INTRO` aircraft absent 9 -> 0 of 12, `CTRY` shape broken 10 -> 3). Findings:
`research/parity/framing-and-actors.md` § 1 and `research/playone-exe/sod-vm.md` § 8.5; open: the
`GVPOLY16` colour path (the fuselage is drawn blue, not white) and the `SHADE` light vector.

Follows the error readout
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
- **Baseline:** `mise run parity` on `ctry` and `intro`, each film's render and `report.json` kept
  under `build/scratch/baseline/<film>/`, its actor overlap (`mise run parity-probe -- iou`) per film, and
  the error readout on both films (the `improving-render-parity` skill's "Error readout":
  `errors-make` per film, two Haiku graders, `errors-disputes`, a Sonnet tie-break if any sheet is
  disputed, `errors-score`). Each grader takes both films' briefs in one prompt, as the `VAULT`
  readout did with one grader per two films. Each `readout.json` is copied to
  `build/scratch/<film>-readout-baseline.json`; every gate compares against these.
- **Lead** (the orchestrating session): the only writer in the worktree. Creates and reaps the
  scratch worktrees, runs every build, render, score and readout, reviews each diagnosis, applies
  the fix, dispatches subagents, writes `log.md`.
- **Diagnosticians:** two Sonnet subagents at once, one per track, each in its own scratch worktree
  (§ 2). Sonnet, not Haiku first: the work is open-ended diagnosis, not a survey.
- **Implementer:** the lead applies a reviewed `fix.patch` itself, test first, since the patch is
  already written and a subagent would start cold only to apply it. One Sonnet implementer
  subagent is dispatched only when the change outgrows the patch (more than about 100 lines, or a
  second crate); it does not commit, and the lead reviews its diff.
- **Graders:** Haiku and Sonnet subagents, dispatched exactly as the skill's "Error readout" says.
- **Subagent budget:** round 1 is 2 diagnosticians, 3 baseline graders and 3 graders per fix that
  passes the score gate: 8 to 11, about SOP 5's cap of 8. A round 2 adds 2 to 5. The graders are
  small, fixed-prompt runs the skill requires.

### 2. Diagnosis briefs

Each brief is the diagnostician's whole instruction, since a running subagent cannot be messaged.

- **Workspace:** a scratch worktree per track (`<repo>.wt/aircraft-diag-a`, `-b`), which the lead
  creates from `origin/main` at `514053c` and runs `mise run init` in before dispatch. Not from this
  branch: the plan commit changes no code, and `mise run reap` only removes worktrees whose branch
  `main` already holds. There the
  diagnostician may add temporary instrumentation, since the code keeps almost no `DBG_` switches
  and two agents building in one checkout would collide. It never commits there, and it writes
  nothing outside that worktree. Before finishing, it saves its instrumentation as
  `build/scratch/<track>/instrumentation.patch` and its proposed change as
  `build/scratch/<track>/fix.patch`, then restores tracked files (`git checkout -- .`), so the
  worktree is clean for reaping.
- **Inputs:** the film's reference capture (`references.toml`) and the baseline render at
  `<main worktree>/build/scratch/baseline/<film>/`, read-only; the example sheets;
  `framing-and-actors.md` § 1, `research/playone-exe/sod-vm.md`, `research/formats/sod-opcodes.md`,
  `stuntreel export-gltf`, `mise run parity-probe`.
- **Track A, aircraft absent** (`INTRO.FLM` ticks 1009 and 1108; the `VAULT` films `vault-land`
  and `vault-splanes` only if a claim needs a second film, since they have no kept render and each
  costs a `batch-parity` render): which actor slot and shape is the aircraft at 1009? Is the shape in
  `INTRO.ALL`, and does `decode_sod` reach `RETURN` or stop on a blocking opcode? How many
  triangles reach the renderer at that tick after LOD, `IFVIS` and culling? What is the flat black
  shape we draw? Are the missing vehicle and figure the same cause?
- **Track B, parts missing** (`CTRY.FLM` ticks 48 and 92, shape `0x7F37`): do all 36 opcode
  polygons reach the mesh? Which faces does the back-face cull remove (culling off)? Is the
  `LodDistanceSq(1000)` node ever drawn? Is the fuselage behind an `IFVIS`/BSP branch we take
  wrongly, or the undecoded two-sided flag (`SodVertex::flags` bit 1)?
- **Output:** in its own worktree, `build/scratch/<track>/diagnosis.md` with the headings **Claim**, **Evidence**
  (counts, offsets, at most 3 images cited), **Proposed change** (files, plus `fix.patch`),
  **Predicted effect** per film, **Ruled out**, **Open**; a final reply of five lines or fewer
  pointing to it.
- **Stop rule:** a claim with evidence, or about 60 tool calls or 10 images read; then the best lead
  and what was ruled out. Never capture, never edit `references.toml`, never touch the main
  worktree's source.

### 3. Fix, gate and recording

Per diagnosis:

1. **Review.** The lead copies the track's `build/scratch/<track>/` into the main worktree, reads
   `diagnosis.md` and reruns its key command. If both tracks name the same root cause, they become
   one fix.
2. **Implement.** The lead (or, past the size in § 1, one implementer subagent) writes a failing
   test on a synthetic fixture (`tests/fixtures/`, no game bytes, [I7]), applies the fix (adapting
   `fix.patch` to what has landed), and runs `mise run check-rust`.
3. **Score gate** (no subagents). One release build; `mise run parity` on both films; the
   regression verdict on both films (`stuntreel parity … --compare build/scratch/baseline/<film>/report.json
   --compare-test build/scratch/baseline/<film>/<render> --noise-sigma 0.000303 --build-floor 0`,
   `method.md` § 1 step 5); actor overlap (`parity-probe iou`) on both films. A fix that fails here is reverted without a readout.
4. **Readout gate.** The readout on both films `--against` the baseline readouts.
5. **Adopt** (Conventional Commit, body with the evidence) **or revert.** Either way a
   `research/parity/log.md` row, and the finding in its owning note (`framing-and-actors.md`,
   `sod-vm.md`, …). After an adoption, the adopted render and readouts become the baseline for the
   next fix.

**Adoption bar.** The bench showed that removing our actors raises SSIM, because they match the
capture worse than the ground (`method.md` § 2.2), so a correct fuselage drawn at the hero's known
10 px offset can lower SSIM. A fix is adopted when both gates pass:

- **Score:** in the regression verdict, no frame whose changed pixels lie outside the `actors`
  layer (`changed_by_layer`) is `Further`. Frames whose changes are in the `actors` layer may be
  `Further` only if the film's actor overlap (`parity-probe iou`, render actor layer against the
  capture's object pixels) rises. The noise floor is σ = 0.000303 on both films: `CTRY.FLM`'s `noise_sigma` from `references.toml`, used for `INTRO.FLM` too because its
  two captures agree so closely that its own σ is inflated (`method.md` § 2.2). Any fall in mean
  SSIM is recorded in the log row.
- **Readout,** read from `compare`'s report against the baseline:
  - Track A: `aircraft-absent` falls by 4 or more frames on `INTRO.FLM`. `aircraft-parts-missing`
    and `aircraft-shape-broken` may rise, since an aircraft that is drawn but imperfect moves from
    absent to those.
  - Track B: `aircraft-parts-missing` or `aircraft-shape-broken` falls by 4 or more on `CTRY.FLM`,
    and `aircraft-absent` does not rise by 4 or more.
  - Neither: any category outside the three aircraft ones rises by 4 or more on either film.

**Rounds:** at most two per track; a round-2 diagnostician gets round 1's gate result in its brief.
A track stops after two rounds with nothing adopted.

**End:** the lead runs `mise run reap` without `--yes` from the primary checkout and checks that
the list holds only the two scratch worktrees; if it lists anything else, the user is asked before
`--yes`. Then the full `mise run check` and a push of the branch; a PR only when the user asks.

## Risks

- A diagnosis may find the missing geometry depends on a `PLAYONE.EXE` rule not yet decoded (the
  two-sided flag has no known writer). Then the track ends with the finding recorded, not a fix.
- The readout's per-category noise is up to 3 frames; a real fix touching fewer than 4 frames of 12
  cannot pass the readout bar, and is recorded as a lead.
