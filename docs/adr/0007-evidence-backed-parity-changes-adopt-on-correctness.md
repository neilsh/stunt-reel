# Evidence-backed parity changes adopt on correctness, not on gain

## Status

accepted; implemented in [`improving-render-parity`](../../.agents/skills/improving-render-parity/SKILL.md)'s adoption rule

## Context

The parity loop adopted a change only when it raised `mean_ssim_scored` on both films by more than 0.002, or one film by 0.004. That rule was written when every candidate was a guess: a gain was the only evidence that the guess was right.

The remaining levers are no longer guesses. They are rules read out of `PLAYONE.EXE` — the ground base colours, the per-shot light caller, the model-origin rule — and a correct implementation of one can score flat or split the films, because the measurement is a proxy. [`attribution.md`](../../research/parity/attribution.md) section 4 puts the whole per-shot ground shade law at +0.0105 SSIM on `CTRY.FLM` and +0.0029 on `INTRO.FLM`, at an oracle ceiling no realisable render reaches. A partly correct implementation of the largest known `INTRO` lever therefore falls under the 0.002 floor and would be reverted while being more faithful than what it replaced. The next round then re-derives the same rule.

## Decision

The adoption rule splits by what backs the change:

- **Evidence-backed** (a rule read from `PLAYONE.EXE`, cited at an image offset): adopt when neither film regresses by more than 0.002 SSIM and at least one moves up.
- **Heuristic** (no such rule): keep the previous rule — both films above +0.002, or one above +0.004 with the other within 0.002.

## Considered Options

- **One rule for both.** Rejected. It is either too strict for a decoded rule or too loose for a guess, and the two cases differ in what the score is evidence *of*.
- **Adopt on correctness alone, ignore the score.** Rejected. A rule read at the wrong scope, or applied to the wrong stage, shows up as a regression, and the guard is what catches that.
- **Lower the 0.002 floor.** Rejected. The floor is a build-level noise bound ([`method.md`](../../research/parity/method.md) section 3), so lowering it makes every margin unattributable, for heuristics too.

## Consequences

Every log row states its track. An evidence-backed change still reverts when either film regresses beyond 0.002, so a rule that is right in principle but misapplied is caught. Reading the log for "what moved the score" must now allow for rows adopted without moving it.
