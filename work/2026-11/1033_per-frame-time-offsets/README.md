---
title: "Which LOCATION captures show a state one tick off the page-lag model?"
started: 2026-11-23
issue: 1033
outcome: "A frame's off-model tick changes with the capture's settings outside the canyon run; recorded as a per-frame noise bound, and a per-frame phase render is rejected"
---

# Which LOCATION captures show a state one tick off the page-lag model?

Covers #1033 and #1029 under the plan in [#1033's comment](https://github.com/neilsh/stunt-reel/issues/1033).
The diagnosis is interactive with the owner; only implementation goes unattended.

## Decisions (agreed with the owner, 2026-11-23)

- **Test 1, captures against each other**, runs on the six films with three capture runs (all but `brett`), LOCATION first.
  The primary pair is `captures/` against `backup/pre-305/`, both on the `patch3` PLAYONE build; the two pairs with `backup/pre-300/`, on the unpatched build, are reported separately.
- **Retime grid**: per-frame SSIM at offsets -2..+2 for all seven films, from one render of `main` (`e2981f3d`) on the canonical WSL lavapipe; one `retime-<film>.csv` per film here.
- **Test 1 bridges runs through the render** (revised 2026-11-23): captured frames sit 10 to 12 ticks apart, so a LOCATION frame in one run has exactly one counterpart in another, at its own tag (645) or a tick away (98), and the plan's search over run B's frames at `t ± 2` has nothing to search.
  Instead all three runs are scored against the same `main` render at retime -2..+2, giving each run's frames their own best offset by palette-index agreement (SSIM only as a tiebreak).
  An offset is decidable only when it beats offset 0 by a margin, about 1% of the pixels, set from the histogram before the verdict.
  The same tag with different best offsets across runs is capture jitter; the same non-zero best offset in every run is reproducible, a PLAYONE rule or our model, and goes to Test 2 and #1029.
  Jitter is the verdict when decidable non-zero offsets are clearly more common on the gainer frames (best retime offset gains 0.02 SSIM or more) than on the others and disagree across runs.
  A render-free cross-check: the share of index-identical frames (rows 0..184) at shared tags, gainers against others, and whether a frame matches another run's frame a tick away.
- **Test 2** correlates each gainer frame's best offset with the `film_tick` gap to the previous captured frame and with its tag's residual from a linear fit of tick against `emu_frame`.
- **Torn pages are not a cause**: a kept captured frame equals a composed page (`python/stunt_reel/tac/framebuffer.py`); `torn_frames` counts discarded trace entries.
- **Where the finding lands**: jitter in [`capture.md` § 4](../../../research/playone-exe/capture.md#4-observed-results), cited from `framing-and-actors.md` § 4 and `evidence-limits.md` with a per-frame noise bound; a cause of ours in [`probes.md` § 6](../../../research/parity/probes.md#6-timing-hypotheses-post-hoc-retime).
- **Mixed verdicts**: films get separate verdicts, and Test 2 runs only on gainer frames jitter leaves unexplained.
  If jitter explains #1033 but not #1029's canyon run, the PR closes #1033 only and #1029 continues on its own.
- **Glossary**: nothing until the verdict; one term against **Captured frame** if it is jitter.
- **Test 2 and the composition clock** (2026-11-23): the `film_tick` gaps are the capture's window spacing, so Test 2 used emulator time only; dating each page by when PLAYONE began composing it needs the window pass to watch the composed pages, a harness change left to #826's live lead.

- **Run settings** (2026-11-23, from the fresh review): the reference is stubbed, `pre-305` and `pre-300` kept their sound, so the three-run comparison mixed sound with timing; stubbed recaptures replay exactly, so two more LOCATION captures were taken stubbed, a Patch 3 control and an unpatched run for a timing change with sound held.
  The verdict was revised from "not capture jitter" to "changes with the capture's settings, where the page changes", with the noise bound in `evidence-limits.md` and the cross-run figures on `capture-dosbox-automation.md`'s open questions 15 and 17.

## Outcome

Repeat captures of one configuration replay a frame's off-model tick; where other settings change a LOCATION frame's page, outside the canyon run the off-model tick mostly goes with it, and where the page does not change the test cannot tell timing from the film.
Its sign follows where the frame falls in its tick, but no rule from the capture's timing reproduces it, and rendering at the emulator-time phase is rejected.
Findings: [`capture.md` § 4](../../../research/playone-exe/capture.md#4-observed-results), [`evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence), [`probes.md` § 6](../../../research/parity/probes.md#6-timing-hypotheses-post-hoc-retime), [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md#open-questions) open questions 15 and 17; entries in [`journal.md`](journal.md).
The canyon run's offsets recur where the page changes too, so #1029 continues on its own.
