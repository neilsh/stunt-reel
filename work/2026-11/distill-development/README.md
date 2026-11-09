---
title: "Distill docs/development.md"
started: 2026-11-09
outcome: "How-to moved to docs/howto/, the dated GPU-hang measurement to journal.md, and a sentence truncated since #14 restored; the page stays over budget as reference"
---
# Distill `development.md`

The page was 43,901 bytes, over twice the 20 KB budget (`mise run doc-health`, 2026-11-09). The daily gardening routine distilled it:

- its Workflows section, the `make-all` and `game-builds` procedures, the GPU watchdog, the re-gate and cherry-pick procedures moved to ten how-to guides in [`docs/howto/`](../../../docs/howto/), indexed from the page's [How-to guides](../../../docs/development.md#how-to-guides) section; the capture-and-score workflow was already [`score-a-render-change.md`](../../../docs/howto/score-a-render-change.md), so the page now points there;
- the one dated measurement, the 2026-11-07 GPU-test hangs, is [`journal.md`](journal.md);
- the CI paragraph had ended in `... (line truncated to 2000 chars)` since `40d09cc` (#14), a tool's display marker committed as text; its last sentences are restored from `40d09cc^`, with Renovate in place of the Dependabot group #14 retired.

What remains is reference and explanation (requirements, setup, layout, the gate, CI, dependency policy), with no dated narrative and no workflow procedure. Bringing it under 20 KB means splitting it by subject, which this distillation leaves to a person.
