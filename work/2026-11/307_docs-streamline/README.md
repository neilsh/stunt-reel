---
title: Docs streamline
started: 2026-11-07
issue: 307
outcome: "The layout and migration landed in #309, #310, #312 and #313, blame and lychee in #318, and the cloud `gh` note in #321; the gardening routine's first checked run opened #319, and #316 and #317 were filed along the way."
---

# Docs streamline

**Question.** How should `docs/` and `research/` be reorganized so that agents read and write them cheaply, and so that `research/` stays a useful reference on how Stunt Island works for agents and outside readers alike?

**Status.** Landed; the PR that writes the outcome closes [#307](https://github.com/neilsh/stunt-reel/issues/307). The [spec](spec.md) and [plan](plan.md) hold the design and its decisions. This is the first work folder under the layout the spec defines.

**Handoff.** Still open from plan Task 16, each its own PR citing #307:

- distill `research/parity/method.md`, `research/parity/framing-and-actors.md` and `docs/development.md`;
- one PR for the seven contradictions Task 16 lists, then the `research/playone-exe/memory-map.md` split;
- move `doc_health`'s issue checks to `gh api` REST, since the cloud proxy refuses GraphQL.
