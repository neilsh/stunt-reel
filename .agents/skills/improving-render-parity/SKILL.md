---
name: improving-render-parity
description: Runs stunt-reel's render-vs-PLAYONE parity loop (capture, render, score, probe, candidate sweep, record findings) in few turns with small output. Use for any parity, fidelity, SSIM or IoU, capture-ref, probe or candidate-sweep work on CTRY.FLM or INTRO.FLM.
---

# Improving render parity

The research notes own the procedure. This skill says which note to read and how to run the loop cheaply. Read only the section you need:

- **Where the loss is** (capture, render, score, compare): [`research/parity/method.md`](../../../research/parity/method.md) section 1.
- **What is wrong** (crop, shift, actor IoU, candidate sweeps, timing retime, environment pitfalls): [`research/parity/probes.md`](../../../research/parity/probes.md).
- **What was already tried**, dead ends included: read [`research/parity/log.md`](../../../research/parity/log.md) (one row per attempt, linking to the note that holds the finding), then the note for the residual: [`attribution.md`](../../../research/parity/attribution.md), [`framing-and-actors.md`](../../../research/parity/framing-and-actors.md) or [`film-segments.md`](../../../research/parity/film-segments.md). Do this before starting a hypothesis.

## Goal contract

One goal, four rounds at most:

> Raise `CTRY.FLM` and `INTRO.FLM` `mean_ssim_scored` with changes observable in the renderer. A round may begin by reading one `PLAYONE.EXE` rule (static disassembly or the capture harness) when no renderer-only lever fits; that rule lands in the note under `research/playone-exe/` with its image offset before the round's sweep runs. Record every attempt, including negatives, as a row in `research/parity/log.md`, with the finding in the note that owns it. Scope: `CTRY` and `INTRO` only (`COL3-2` excluded). Stop after 4 rounds, after two consecutive rounds with no adoption, or when the round's hypothesis would need evidence the session cannot obtain, and write the handoff.

One hypothesis class per round; all variants batched in one command; the round ends at the sweep result.

## Adoption rule

Two tracks, because what backs a change decides what the score is allowed to say. State the track, and the image offset if there is one, on the log row.

- **Evidence-backed** — the change reproduces a rule read out of `PLAYONE.EXE`, cited at an image offset: adopt when neither film regresses by more than 0.002 SSIM and at least one moves up. The rule is the criterion; the score is a guard against the rule being misapplied.
- **Heuristic** — no such rule behind it: adopt when **both** films gain more than 0.002 SSIM, or **one** gains more than 0.004 while the other moves less than 0.002 either way.

Anything else is recorded as a negative and the change is reverted.

0.002 is a policy bound derived from build-level noise ([`method.md`](../../../research/parity/method.md) section 3). A margin under 0.002 is unattributable; the sweep marks it on the winner line.

## Workflow

Copy this checklist into your task list and tick items off:

```
- [ ] 1. Baseline: mise run parity (two lines, both films)
- [ ] 2. Check log.md and the residual notes for prior attempts at this hypothesis
- [ ] 3. If no renderer-only lever fits, read the PLAYONE rule this round tests and write it into its playone-exe note
- [ ] 4. One hypothesis class: all variants in one sweep, or retime for timing
- [ ] 5. Apply the adoption rule to the result
- [ ] 6. Crop the winner and the worst mover; inspect only those
- [ ] 7. Record outcomes, run mise run check, commit (body says why: [AGENTS.md § Commit Messages](../../../AGENTS.md#commit-messages)), write the handoff
```

If step 5 rejects the change, record the negative and end the round; do not chain a second hypothesis class onto a failed sweep.

## Cost rules

Every turn re-sends the whole conversation, so the loop costs turns times context.

1. **Build once, call the binary.** Run `target/release/stuntreel.exe`, never `cargo run` per render. `--no-build` on every tool reuses it.
2. **One command per batch.** Loop render plus score over every candidate in one shell command that prints one line per candidate: the `[parity]` summary line, or the probe's single number. Run it in the background when it will take more than about 2 minutes.
3. **Use the tools.** `mise run parity` is the baseline; `mise run sweep -- --var DBG_X=a,b [--films ctry,intro] [--probe iou] [--keep-best]` builds once, scores the whole product on both films and prints one table plus the winner ([`probes.md`](../../../research/parity/probes.md) section 4); `retime` answers a timing question with no build (section 6). Do not hand-roll render-and-score loops (section 8 lists what has no tool yet).
4. **Score both films.** CTRY-only gains have regressed INTRO three times ([`framing-and-actors.md`](../../../research/parity/framing-and-actors.md)).
5. **Never print a whole `report.json`.** Extract the fields you need with `python -c "import json; ..."`.
6. **Look at pixels sparingly.** Use `parity_probe.py crop` on one region instead of reading full contact sheets, and only after the numbers point somewhere.
7. **Scratch goes in `build/scratch/`** (gitignored), never `$TEMP`, whose Windows path breaks shell globs. Delete candidate render directories once scored. `PYTHONUTF8=1` is set for Python text I/O; committed scripts still pass `encoding="utf-8"`.
8. **Never commit `DBG_*` switches.** `git checkout crates` removes them. Parse a switch's value with `std::env::var(...).ok().and_then(|v| v.parse().ok())`, never `is_ok()` (`"0"` counts as set; the sweep's identical-variant warning catches it, [`probes.md`](../../../research/parity/probes.md) section 8).

## Comparing a candidate reference

A new capture becomes a film's reference only through a reviewed commit of `research/parity/references.toml` plus a `log.md` row. To decide whether to promote one, score the candidate and the current reference with the same binary:

```
- [ ] 1. mise run capture-digest -- <slug> <run>   (prints sha256 and the [film] entry to paste)
- [ ] 2. Copy research/parity/references.toml to build/scratch/references.toml, then paste the entry into the working tree's copy
- [ ] 3. mise run parity -- --films <film> --no-build   (renders and scores the candidate)
- [ ] 4. Copy build/scratch/references.toml back over research/parity/references.toml
- [ ] 5. mise run parity -- --films <film> --no-build   (renders and scores the current reference)
- [ ] 6. Compare the two scored lines; promote only in a commit of its own, with the log row
```

Restore from the copy rather than with `git checkout`, which would also discard any edit to the file that was there before step 2. Leave out `--no-render` on the second run. A render covers only the ticks its own capture tagged, so the `_current` tree from step 3 has no frames at the other reference's ticks. `--no-build` is what keeps the binary the same, so the two scores differ only by the reference.

## Error readout

Run it on both films after adopting a render change. It says which kinds of error the render makes and on how many frames; it cannot see misregistration, which the metrics cover. The categories are `research/parity/error-categories.toml`.

```
- [ ] 1. Copy build/parity/bench/<film>/errors/readout.json to build/scratch/ (the previous readout)
- [ ] 2. mise run parity-bench -- errors-make --film <film>   (12 sheets and brief.md)
- [ ] 3. Dispatch one Haiku subagent; its whole prompt: "Read build/parity/bench/<film>/errors/brief.md: it is your whole instruction"
- [ ] 4. mise run parity-bench -- errors-score --film <film> --against build/scratch/readout.json
```

Calibrate (`errors-make --calibrate`, 42 sheets, then `errors-score`) only when the categories, the sheet layout or the grading model change; it must print `calibration PASS`. When `other` names the same new kind of error on two or more frames, add a `[[category]]` block, give it an example with `errors-example --film <film> --tick <tick> --category <id>`, and calibrate.

## Finishing an item

Add a row to `research/parity/log.md` for every attempt, adopted or not, and put the finding in the note that owns the residual. End the session after the handoff note; start the next hypothesis in a fresh session.
