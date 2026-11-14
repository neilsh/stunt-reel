# Loop rules: goal contract and adoption rule

Part of the [`improving-render-parity`](SKILL.md) skill.

## Goal contract

One goal, four rounds at most:

> Raise the reference films' `mean_ssim_scored` with changes observable in the renderer. A round may begin by reading one `PLAYONE.EXE` rule (static disassembly or the capture harness) when no renderer-only lever fits; that rule lands in the note under `research/playone-exe/` with its image offset before the round's sweep runs. Record every attempt, including negatives, as a journal entry in its work folder, with the finding in the note that owns it. A round may name target frames, the frames showing the defect it addresses, by quoting the sweep's `--target` flags in its journal entry before the sweep runs; the adoption rule then judges it on them too. Scope: every film `research/parity/references.toml` pins (`COL3-2` excluded). Stop after 4 rounds, after two consecutive rounds with no adoption, or when the round's hypothesis would need evidence the session cannot obtain, and write the handoff.

One hypothesis class per round; all variants batched in one command; the round ends at the sweep result.

## Adoption rule

Two tracks, because what backs a change decides what the score is allowed to say. State the track, and the image offset if there is one, in the journal entry, and pass it to the sweep as `--track evidence|heuristic`; the sweep's winner line then gives this rule's verdict ([`score-a-render-change.md`](../../../docs/howto/score-a-render-change.md) § 8).

- **Evidence-backed**: the change reproduces a rule read out of `PLAYONE.EXE`, cited at an image offset. The rule is the criterion; the score is a guard against the rule being misapplied.
- **Heuristic**: no such rule behind it.

A change adopts when it passes every guard and one branch of its track adopts it. Anything else is recorded as a negative and the change is reverted.

### Branches

| Track | Film-mean branch | Target branch |
|---|---|---|
| Evidence-backed | at least one reference film rises | none: the target mean is reported as attribution |
| Heuristic | every reference film above +0.002, or one above +0.004 | the three conditions below |

The heuristic target branch adopts when all three hold:

1. the pooled target mean rises by more than +0.010;
2. each target range's own target mean rises, a range being one `--target` flag, so a gain in one range cannot hide a fall in another;
3. at least half of all scored target frames rise.

It needs at least 3 scored target frames over every range together; with fewer, the sweep judges on film means only and says so. An adoption resting on exactly 3 is thin evidence, and the winner line says so. A range may hold a single scored frame.

- **Why heuristic only.** On the evidence-backed track the film-mean branch adopts whenever any film rises, so a target branch could only add adoptions where the target frames rose and the rest of the film fell by more.
- **Why the bar is high.** The sweep picks the variant that scores best on frames the round chose, the circularity [`method.md`](../../../research/parity/method.md) § 4.1 rules out for fitting the fade ramp to the frames it scores.

### Guards

1. **Film mean.** No reference film's `mean_ssim_scored` falls by more than 0.002 on the evidence-backed track, or by 0.002 or more on the heuristic track.
2. **Per frame.** With `--target`, on both tracks, no scored target frame falls by more than 0.025 in SSIM. No other frame has a hard bound: the sweep lists every frame that falls by more than 0.005, and the journal entry explains those falls (for example, our camera sits a few pixels off the capture's, so correct detail lands on the wrong pixels). Without `--target` this listing is the whole per-frame guard.
3. **Lost frames.** A variant is rejected when a tick the baseline scores is missing or unscored in it, or when any of its films fails. A failed baseline film gives no verdict.

### Measuring

- The **baseline** is the variant of each `--var`'s first value: in `--var DBG_X=0,1`, `DBG_X=0`.
- The film-mean bars and the 0.025 bound are differences in whole-frame SSIM, candidate minus baseline, over the film ticks the baseline scores.
- The **target mean** is the mean difference in index agreement over the target frames; the **pooled** figure covers every range's frames together. Whole-frame SSIM is printed beside it.
- A tick captured more than once counts once, by its first frame, as `stuntreel parity --compare` does.
- Comparisons use unrounded values.

0.002 is a policy bound ([`method.md`](../../../research/parity/method.md) section 3). A margin under 0.002 is unattributable; the sweep marks it on the winner line. The +0.010 target bar, the 0.025 per-frame bound and the 3-frame minimum are policy bounds too, chosen by rescoring known cases ([`evidence-limits.md`](../../../research/parity/evidence-limits.md) section 3).

### Target frames

- **Target frames** ([`GLOSSARY.md`](../../../GLOSSARY.md)) are ranges of film ticks per film, named before the sweep. The journal entry quotes the `--target` flags before the sweep runs, and the sweep echoes them on stdout so the quote can be checked.
- A film the round does not target is judged by the guards alone.
- Frames the candidate changes outside the target are side effects; the sweep counts them per film.

### After adopting

An adopted change updates the expected table in [`references.toml`](../../../research/parity/references.toml) for the renderer class it measured (`ssim`, `iou`, `adapter` from that run; `crates` from `git rev-parse <commit>:crates` on the commit it rendered, with `crates/` clean (no uncommitted or untracked files under it), not the commit itself, which a squash merge keeps off `main`; `sha256` and `all_sha256` copied from the film's row); the other class keeps its older entry, if any, until someone measures it.

**Repin, never hand-merge.** `mise run parity-repin -- [--class gpu|lavapipe]` writes every film's table from its current report after `mise run parity` on a clean `crates/`, and writes nothing when a film lacks a report measured on that tree, was scored against another capture or archive, or has no recorded pins.

- Expected tables change only when the measured `crates/` tree or a film's `sha256` or `all_sha256` pin changes.
- On a conflict in an expected table, take `main`'s expected tables while keeping the branch's other edits to `references.toml` (a new row or pin), rerun `mise run parity` on the merged tree, run `mise run parity-repin` and commit. Never hand-merge the numbers: a merged number was measured on no tree.
- A catch-up repin (the tables' `crates` lags `main`) is allowed in any PR, but only as its own commit, such as `chore(parity): repin expected scores`.
- A research note cites the journal entry for before-and-after scores and never copies the expected scores.
