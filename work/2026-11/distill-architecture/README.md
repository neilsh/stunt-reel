---
title: "Distill docs/ARCHITECTURE.md"
started: 2026-11-15
outcome: "No dated narrative to move; repeated links became reference definitions and a duplicate parity row merged; the page stays over budget as a routing table"
---
# Distill `ARCHITECTURE.md`

The page was 26,941 bytes, over the 20 KB budget (`mise run doc-health`, 2026-11-15). The daily gardening routine distilled it:

- it held no dated round, session log or superseded result: its one dated line, the pointer to the closed 2026-10-25 architecture-deepening programme, is already a one-sentence link to that work folder, so this folder has no `journal.md`;
- each link the routing table repeated with the same text (anchor tokens such as `[I6]`, and the research notes and ADRs cited more than once) became a Markdown reference definition below the table, so each long anchor URL is written once; the rendered links are unchanged apart from the merged row below;
- the routing table listed `crates/stunt-cli/src/parity/` twice; its short row, which cited only `[I6]` and `palette-and-shading.md`, both also on the long row, merged into the long one.

What remains, about 23 KB, is the intro, the routing table, the decoder explanation and the pointer to the closed programme, with no how-to and no dated narrative. Bringing it under 20 KB means dropping the module descriptions in the table, splitting the table by subsystem, or a larger budget for this page, which this distillation leaves to a person.
