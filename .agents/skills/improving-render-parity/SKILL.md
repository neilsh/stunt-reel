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

> Raise `CTRY.FLM` and `INTRO.FLM` `mean_ssim_scored` with changes observable in the renderer. Adopt a change only when it improves both films by more than 0.002 SSIM, or one film by more than 0.004 with the other within noise. Record every attempt, including negatives, as a row in `research/parity/log.md`, with the finding in the note that owns it. Scope: `CTRY` and `INTRO` only (`COL3-2` excluded). Stop after 4 rounds, after two consecutive rounds with no adoption, or when the next hypothesis needs `PLAYONE.EXE` disassembly, and write the handoff.

One hypothesis class per round; all variants batched in one command; the round ends at the sweep result.

## Adoption rule

Adopt when **both** films gain more than 0.002 SSIM, or **one** gains more than 0.004 while the other moves less than 0.002 either way. Anything else is recorded as a negative and the change is reverted.

0.002 is a policy bound derived from build-level noise ([`method.md`](../../../research/parity/method.md) section 3). A margin under 0.002 is unattributable; the sweep marks it on the winner line.

## Workflow

Copy this checklist into your task list and tick items off:

```
- [ ] 1. Baseline: mise run parity (two lines, both films)
- [ ] 2. Check log.md and the residual notes for prior attempts at this hypothesis
- [ ] 3. One hypothesis class: all variants in one sweep, or retime for timing
- [ ] 4. Apply the adoption rule to the result
- [ ] 5. Crop the winner and the worst mover; inspect only those
- [ ] 6. Record outcomes, run mise run check, commit, write the handoff
```

If step 4 rejects the change, record the negative and end the round; do not chain a second hypothesis class onto a failed sweep.

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

## Finishing an item

Add a row to `research/parity/log.md` for every attempt, adopted or not, and put the finding in the note that owns the residual. End the session after the handoff note; start the next hypothesis in a fresh session.
