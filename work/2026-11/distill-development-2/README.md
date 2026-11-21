---
title: "Distill docs/development.md"
started: 2026-11-19
outcome: "No dated narrative to move; the seven one-line pointers to quality-gate.md and toolchain.md merged into two sentences and four restatements trimmed or reworded, bringing the page under its budget"
---
# Distill `development.md`, second pass

The page was 20,832 bytes, over the 20 KB budget (`mise run doc-health`, 2026-11-19), and the daily gardening routine distilled it again after [`distill-development`](../distill-development/README.md):

- it held no dated round, session log or superseded result, so this folder has no `journal.md`;
- the three one-line pointers to [`quality-gate.md`](../../../docs/quality-gate.md) sections and the four to [`toolchain.md`](../../../docs/toolchain.md) sections became one sentence per page, with the same link targets, after the task map;
- the `crates/stunt-parity/` row names the crate docs, which state the schema-regeneration command, in place of repeating it;
- the diagnostic-scripts row dropped its history ("previously had to be called by file path"), the gate pointer dropped "the quick task map stays here", and "CI no longer checks a pull request's individual commits" became "CI checks no pull request's individual commit messages", since CI's prek step does read the commits.
