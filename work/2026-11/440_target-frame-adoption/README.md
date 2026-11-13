---
title: "Adopt a render change on its target frames, guarded per frame"
started: 2026-11-12
issue: 440
outcome: ""
---

# Adopt a render change on its target frames, guarded per frame

The spec is [spec.md](spec.md). The spike that rescored known adoptions, rejections and a planted fault before any bound was written is journaled in [journal.md](journal.md).

## Handoff

2026-11-12: the spike (spec § 1) is done, and the user settled the target metric and the bounds from it (spec § 1.3, Q40 to Q45; Q46 and Q47 after a review; Q48 after a third). The spec and spike are in [PR #442](https://github.com/neilsh/stunt-reel/pull/442), branch `claude/stoic-easley-065cbe`. Next: PR 1 (spec § 7), not started.

2026-11-13: PR 1, the verdict (spec § 7 item 2), is implemented on branch `feat/440-target-verdict`: `--target` and `--track` on `mise run sweep`, `mise run judge`, and the rule in `loop-rules.md`. PR 2, the pictures (§ 4), remains.
