---
title: "Adopt a render change on its target frames, guarded per frame"
started: 2026-11-12
issue: 440
outcome: "A round names target frames and is judged on them, guarded per frame: the heuristic target branch (pooled index agreement above +0.010, every range up, half the frames up), a hard 0.025 per-frame SSIM bound on target frames, and every other fall above 0.005 listed. mise run sweep --images --topic [--crop] draws capture | baseline | winner pictures for the chosen ticks into the work folder. No GPU run tested either; the first targeted round is the field test of the pictures, and the first heuristic targeted round of the target branch."
---

# Adopt a render change on its target frames, guarded per frame

The spec is [spec.md](spec.md). The spike that rescored known adoptions, rejections and a planted fault before any bound was written is journaled in [journal.md](journal.md).

## Handoff

2026-11-12: the spike (spec § 1) is done, and the user settled the target metric and the bounds from it (spec § 1.3, Q40 to Q45; Q46 and Q47 after a review; Q48 after a third). The spec and spike are in [PR #442](https://github.com/neilsh/stunt-reel/pull/442), branch `claude/stoic-easley-065cbe`. Next: PR 1 (spec § 7), not started.

2026-11-13: PR 1, the verdict (spec § 7 item 2), is implemented on branch `feat/440-target-verdict`: `--target` and `--track` on `mise run sweep`, `mise run judge`, and the rule in `loop-rules.md`. PR 2, the pictures (§ 4), remains.

2026-11-13: PR 2, the pictures (spec § 7 item 3), is implemented: `--images`, `--topic` and `--crop` on `mise run sweep` (`python/stunt_reel/parity_pictures.py` chooses the ticks and names the files, `parity_sweep.py` re-renders them and draws), `SKILL.md`'s pictures step, `pr-evidence.md`, the how-to, `mise.toml` and `NOTICE.md`. Nothing is left in the spec; #440 closes with it.
