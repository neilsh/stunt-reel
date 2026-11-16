---
title: "An isolated repro of lavapipe's NaN noperspective varying, for a Mesa issue"
started: 2026-11-16
outcome: "A standalone Vulkan repro draws NaN noperspective pixels on lavapipe 25.2.8 and 26.2.6 (case A 1,077, case B 442) and none on the RTX 4070; the upstream issue is drafted in issue-draft.md, not filed."
---

# An isolated repro of lavapipe's NaN noperspective varying, for a Mesa issue

**Question.** Can the clipper fault behind [`lavapipe.md`](../../../research/parity/lavapipe.md) section 2 be shown with no Stunt Reel code or data, small enough to attach to an upstream Mesa issue? Follows #595; that work folder ([`595_lavapipe-residues`](../595_lavapipe-residues/README.md)) had already landed, so this one has no issue of its own.

## Contents

- [`repro/`](repro/): a standalone cargo project (`ash`, with the GLSL shaders compiled to SPIR-V in-process by `naga`), not a member of the workspace.
- [`replay_interp.py`](replay_interp.py): a float32 replay of `do_clip_tri`/`interp()` on the repro's triangles, with `--suggested-fix`.
- [`journal.md`](journal.md): the runs on mesa-dist-win 25.2.8 and 26.2.6 and on the RTX 4070.
- [`issue-draft.md`](issue-draft.md): the text for a Mesa issue. Not filed; the owner files it.

## Status

- 2026-11-16: both cases reproduce on both builds, and the GPU draws no NaN pixels ([journal](journal.md)). Left: filing the issue upstream, which is the owner's call.
