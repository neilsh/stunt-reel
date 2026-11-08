# Loop rules: goal contract and adoption rule

Part of the [`improving-render-parity`](SKILL.md) skill.

## Goal contract

One goal, four rounds at most:

> Raise the reference films' `mean_ssim_scored` with changes observable in the renderer. A round may begin by reading one `PLAYONE.EXE` rule (static disassembly or the capture harness) when no renderer-only lever fits; that rule lands in the note under `research/playone-exe/` with its image offset before the round's sweep runs. Record every attempt, including negatives, as a journal entry in its work folder, with the finding in the note that owns it. Scope: every film `research/parity/references.toml` pins (`COL3-2` excluded). Stop after 4 rounds, after two consecutive rounds with no adoption, or when the round's hypothesis would need evidence the session cannot obtain, and write the handoff.

One hypothesis class per round; all variants batched in one command; the round ends at the sweep result.

## Adoption rule

Two tracks, because what backs a change decides what the score is allowed to say. State the track, and the image offset if there is one, in the journal entry.

- **Evidence-backed** — the change reproduces a rule read out of `PLAYONE.EXE`, cited at an image offset: adopt when no film falls by more than 0.002 SSIM and at least one rises. The rule is the criterion; the score is a guard against the rule being misapplied.
- **Heuristic** — no such rule behind it: adopt when no film falls by 0.002 SSIM or more, and either **every** film gains more than 0.002 or **one** gains more than 0.004. With four or more films the second branch is the usual one.

Anything else is recorded as a negative and the change is reverted.

An adopted change updates the expected table in [`references.toml`](../../../research/parity/references.toml) for the renderer class it measured (`ssim`, `iou`, `commit`, `adapter` from that run); the other class keeps its older entry, if any, until someone measures it.

0.002 is a policy bound ([`method.md`](../../../research/parity/method.md) section 3). A margin under 0.002 is unattributable; the sweep marks it on the winner line.
