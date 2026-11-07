---
name: improving-render-parity
description: Runs stunt-reel's render-vs-PLAYONE parity loop (capture, render, score, probe, candidate sweep, record findings) in few turns with small output. Use for any parity, fidelity, SSIM or IoU, capture-ref, probe or candidate-sweep work on a reference film (`research/parity/references.toml`), and for the comparison picture a rendering PR carries.
---

# Improving render parity

The research notes own the procedure. This skill says which note to read and how to run the loop cheaply. Read only the section you need:

- **Where the loss is** (capture, render, score, compare): [`research/parity/method.md`](../../../research/parity/method.md) section 1.
- **What is wrong** (crop, shift, actor IoU, candidate sweeps, timing retime, environment pitfalls): [`research/parity/probes.md`](../../../research/parity/probes.md).
- **What was already tried**, dead ends included: read [`research/parity/log.md`](../../../research/parity/log.md) (one row per attempt, linking to the note that holds the finding), then the note for the residual: [`attribution.md`](../../../research/parity/attribution.md), [`framing-and-actors.md`](../../../research/parity/framing-and-actors.md) or [`film-segments.md`](../../../research/parity/film-segments.md). Do this before starting a hypothesis.

## Workflow

Read [`loop-rules.md`](loop-rules.md) first: one goal, at most four rounds, and the adoption rule step 5 applies. Copy this checklist into your task list and tick items off:

```
- [ ] 1. Baseline: mise run parity (one line per film)
- [ ] 2. Check log.md and the residual notes for prior attempts at this hypothesis
- [ ] 3. If no renderer-only lever fits, read the PLAYONE rule this round tests and write it into its playone-exe note
- [ ] 4. One hypothesis class: all variants in one sweep, or retime for timing
- [ ] 5. Apply the adoption rule to the result
- [ ] 6. Crop the winner and the worst mover; inspect only those
- [ ] 7. Record outcomes, run mise run check, commit (body says why: [AGENTS.md § Committing](../../../AGENTS.md#committing)), write the handoff
```

If step 5 rejects the change, record the negative and end the round; do not chain a second hypothesis class onto a failed sweep.

## Files beside this skill

Read each when its step comes up:

- [`cost-rules.md`](cost-rules.md): before the first render or sweep of a session.
- [`comparing-references.md`](comparing-references.md): deciding whether to promote a new capture to reference.
- [`error-readout.md`](error-readout.md): after adopting a render change, on every film.
- [`pr-evidence.md`](pr-evidence.md): opening a PR that changes rendered output.

## Finishing an item

Add a row to `research/parity/log.md` for every attempt, adopted or not, and put the finding in the note that owns the residual. End the session after the handoff note; start the next hypothesis in a fresh session.
