---
title: "Refresh VAULT parity attribution and investigate BALLOON.FLM actor IoU (0.6409)"
started: 2026-11-16
issue: 477
outcome: "Attribution refreshed on all seven references; BALLOON's IoU traced to a straight-down camera drawn blank (#615) and a zenith sky outside the scorer's band (#616, #617)."
---

# Refresh VAULT parity attribution and investigate BALLOON.FLM actor IoU (0.6409)

Refreshed the render-layer attribution of the seven `VAULT` Patch #3 references on `main` at `76872e89`, ran the error readout on six of them, and attributed `BALLOON.FLM`'s 0.6409 mask IoU. The figures are in [`journal.md`](journal.md); the findings are in `research/parity/attribution.md` §§ 2 and 7 and `research/parity/batch-vault-films.md` § 7.

## Handoff

- Follow-ups filed: [#615](https://github.com/neilsh/stunt-reel/issues/615) (straight-down camera drawn blank), [#616](https://github.com/neilsh/stunt-reel/issues/616) (scorer sky band omits 224 to 226), [#617](https://github.com/neilsh/stunt-reel/issues/617) (zenith bands and sun disc).
- Not done: `vault-ctry`'s error readout. Only one of its two grader passes ran, so it has no `readout.json`.
