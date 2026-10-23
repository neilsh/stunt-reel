---
name: parity-loop
description: Run stunt-reel's render-vs-PLAYONE parity loop economically - capture, render, score, probe, sweep candidates, record findings. Use for any parity, fidelity, SSIM/IoU, capture-ref, probe or candidate-sweep work on CTRY.FLM or INTRO.FLM.
---

# Parity loop

The procedure is owned by the research notes; this skill says which to read and how to run it cheaply. Read only the section you need:

- Where the loss is (capture, render, score, compare): [`research/parity/method.md`](../../../research/parity/method.md) section 1.
- What is wrong (crop, shift, actor IoU, candidate sweeps, environment pitfalls): [`research/parity/probes.md`](../../../research/parity/probes.md).
- What was already tried, including dead ends: `grep -n '^## ' research/parity-findings.md`, then read the one section. Check here before starting a hypothesis.

## Cost rules

Every turn re-sends the whole conversation, so the loop's cost is turns times context. Run it in as few turns as you can, and keep output small.

1. **Build once, call the binary.** `cargo build --release -p stunt-cli`, then `target/release/stuntreel.exe`, never `cargo run` per render.
2. **One command per batch.** Put a render plus score loop over every candidate in one shell command that prints one line per candidate (the `[parity]` summary line, or the probe's single number). Run it in the background when it will take more than about 2 minutes.
3. **Use the sweep tool.** `mise run sweep -- --var DBG_X=a,b [--films ctry,intro] [--probe iou] [--keep-best]` builds once, renders and scores the whole product on both films and prints one table plus the winner (probes.md section 4). Do not hand-roll render-and-score loops.
4. **Score both films before adopting a change.** CTRY-only gains have regressed INTRO three times (`parity-findings.md` section 11).
5. **Never print a whole `report.json`.** Extract the fields you need with `python -c "import json; ..."`.
6. **Look at pixels sparingly.** Use `parity_probe.py crop` on one region instead of Reading full contact sheets. Read at most the winner's crop and the worst mover, and only after the numbers point somewhere.
7. **Scratch goes in `build/scratch/`** (gitignored), never `$TEMP`, whose Windows path breaks shell globs. Delete candidate render directories once scored. Python text I/O is UTF-8 through `PYTHONUTF8=1` (`mise.toml`, `.claude/settings.json`); committed scripts still pass `encoding="utf-8"`.
8. **`DBG_*` switches are never committed.** `git checkout crates` removes them.

## Finishing an item

Record the outcome, including a negative one, in `research/parity-findings.md`, and add a row to `research/parity/log.md` when the committed render changed. Run `mise run check`, commit, and end the session with a handoff note in the owning plan or finding. Do not carry the next hypothesis on in the same session.
