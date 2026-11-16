---
title: "Lavapipe parity scores are not yet shown to match the GPU's"
started: 2026-11-15
issue: 265
outcome: ""
---

# Lavapipe parity scores are not yet shown to match the GPU's

**Question.** Can a lavapipe row stand in for a GPU row, and do local and cloud lavapipe agree? The steps and the Done-when are on [#265](https://github.com/neilsh/stunt-reel/issues/265); #455 writes the cloud `expected.lavapipe` rows they compare against.

## Plan

Run with `/orchestration`: dsh for straightforward implementation, Sonnet, Opus or Haiku by fit for the rest; at most two implementers at once.

- **PR A** (dsh): expose `RenderOptions::software_only` through `stuntreel` and `mise run parity` (today hardcoded `false` in `crates/stunt-cli/src/headless.rs` and `window.rs`), with a test; `docs/howto/render-on-lavapipe.md` (mesa-dist-win 25.2.8 under `$STUNT_DATA_ROOT/tools/mesa-<ver>/`, sha256 recorded, `VK_DRIVER_FILES` naming only lavapipe's ICD; confirm the adapter is llvmpipe, not WARP); GPU and local lavapipe parity on all seven films on #455's `crates` tree, reports copied aside between runs; the guard-reverted byte-identical `tick_*.idx` check; `log.md` rows.
- **Sonnet tasks**: step 4 (CTRY 422 shadow, `mise run frame`), step 6 (mesa-dist-win 26.2.6 with the guard reverted at CTRY 400/422; read `t_nopersp` in `draw_pipe_clip.c`).
- **PR B** (Opus, after #455 merges): the `lavapipe.md` verdict, cloud against local lavapipe, the `gitlab.freedesktop.org` contradiction between `lavapipe.md` and `docs/cloud-sessions.md`.
- **PR C** (Opus): step 3's attribution, only if a film is outside the 0.002 margin.

First review of each dsh or Sonnet PR: the `reviewer` agent on Opus; mechanical rechecks on Haiku. Every PR touching `research/` or `docs/` gets a fresh-review pass before push.

## Status

- 2026-11-15: #455 launched as cloud session [`session_01754SzQMKMSE3sZxgSTfyms`](https://claude.ai/code/session_01754SzQMKMSE3sZxgSTfyms) on Sonnet; its result arrives as a PR or a comment on #455. Next: `/orchestration` for PR A from this folder.
- 2026-11-15: PR B: LOCATION's local lavapipe loss was a stale guard-removed binary; re-rendered with the guard it scores 0.8292054, within the margin of the GPU and the cloud row. Mesa 26.2.6 still makes the NaN; Gouraud polygons the clipper breaks draw flat. Findings in [`lavapipe.md`](../../../research/parity/lavapipe.md), experiment in [journal.md](journal.md). Left open: the `lavapipe.md` Open questions.
