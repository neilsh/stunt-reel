---
title: "Distill research/parity/lavapipe-render-time.md"
started: 2026-11-23
outcome: "Per-change rounds, draw scans, pre-#914 probes, verdicts and the f6976e67 Ruled out, Open questions and summary moved to journal.md; the note is organised by subject and, after merging main's #1000, #1002, #1004, #1006 and #999 additions, stays over its 32 KiB budget as current reference (splitting by subject, including section 7, is left to a follow-up)"
---
# Distill `lavapipe-render-time.md`

The note was 65,232 bytes, over the 32 KiB budget for `research/` (`mise run doc-health`, 2026-11-23).
The daily gardening routine distilled it: [`journal.md`](journal.md) holds, verbatim, the per-change render-time rounds (#596 to #644), the draw scans before and after #914, the pre-#914 phase probes, the #914, #931, #933, #934, #942, #944, #920 and #1000 rounds, the verdicts list, and the Ruled out and Open questions sections and the summary as they stood at `f6976e67`.
The note now states, by subject, the changes that cut render time, the draws per frame, where loop time goes, thread and worker scaling, and what is deferred or pending, with a `_Source:` line on each finding.

Merging `main` (`3bfa257a`) folded in `#1000`, `#1002`, `#1004`, `#1006` (which moved `## 7. Memory per worker` into the note) and `#999`.
The note stays over its 32 KiB budget as current reference; splitting it by subject (including section 7) is left to a follow-up.
