---
name: improving-render-parity
description: Runs stunt-reel's render-vs-PLAYONE parity loop (capture, render, score, probe, candidate sweep, record findings) in few turns with small output. Use for any parity, fidelity, SSIM or IoU, capture-ref, probe or candidate-sweep work on CTRY.FLM or INTRO.FLM.
---

# Improving render parity

The research notes own the procedure. This skill says which note to read and how to run the loop cheaply. Read only the section you need:

- **Where the loss is** (capture, render, score, compare): [`research/parity/method.md`](../../../research/parity/method.md) section 1.
- **What is wrong** (crop, shift, actor IoU, candidate sweeps, environment pitfalls): [`research/parity/probes.md`](../../../research/parity/probes.md).
- **What was already tried**, dead ends included: run `grep -n '^## ' research/parity-findings.md`, then read the one section. Do this before starting a hypothesis.

## Workflow

Copy this checklist into your task list and tick items off:

```
- [ ] 1. Check parity-findings.md headings for prior attempts at this hypothesis
- [ ] 2. Build once: cargo build --release -p stunt-cli
- [ ] 3. Sweep all candidates in one command: mise run sweep -- --var DBG_X=a,b
- [ ] 4. Score the winner on both CTRY and INTRO
- [ ] 5. Crop the winner and the worst mover; inspect only those
- [ ] 6. Record the outcome, run mise run check, commit, write the handoff
```

If step 4 regresses either film, return to step 3 with a narrower hypothesis rather than adopting the change.

## Cost rules

Every turn re-sends the whole conversation, so the loop costs turns times context.

1. **Build once, call the binary.** Run `target/release/stuntreel.exe`, never `cargo run` per render.
2. **One command per batch.** Loop render plus score over every candidate in one shell command that prints one line per candidate: the `[parity]` summary line, or the probe's single number. Run it in the background when it will take more than about 2 minutes.
3. **Use the sweep tool.** `mise run sweep -- --var DBG_X=a,b [--films ctry,intro] [--probe iou] [--keep-best]` builds once, renders and scores the whole product on both films and prints one table plus the winner (probes.md section 4). Do not hand-roll render-and-score loops.
4. **Score both films.** CTRY-only gains have regressed INTRO three times (`parity-findings.md` section 11).
5. **Never print a whole `report.json`.** Extract the fields you need with `python -c "import json; ..."`.
6. **Look at pixels sparingly.** Use `parity_probe.py crop` on one region instead of reading full contact sheets, and only after the numbers point somewhere.
7. **Scratch goes in `build/scratch/`** (gitignored), never `$TEMP`, whose Windows path breaks shell globs. Delete candidate render directories once scored. `PYTHONUTF8=1` is set for Python text I/O; committed scripts still pass `encoding="utf-8"`.
8. **Never commit `DBG_*` switches.** `git checkout crates` removes them.

## Finishing an item

Record the outcome, including a negative one, in `research/parity-findings.md`. Add a row to `research/parity/log.md` when the committed render changed. End the session after the handoff note; start the next hypothesis in a fresh session.
