---
title: "Distill docs/SPEC.md"
started: 2026-11-16
outcome: "No dated narrative to move; the format table became a pointer to research/MAP.md, the G07 command line moved to its how-to, restatements of code and of other sections were cut and the prose tightened, bringing the page under its budget"
---
# Distill `SPEC.md`

The page was 24,736 bytes, over the 20 KB budget (`mise run doc-health`, 2026-11-16). The daily gardening routine distilled it:

- it held no dated round, session log or superseded result, so this folder has no `journal.md`; every `[I*]` heading and § 2.4's heading and tier names, which `doc_anchors.py` and `tiers.py` read, are unchanged;
- § 3's routing table became one paragraph pointing to [`research/MAP.md`](../../../research/MAP.md), which summarizes each note the table linked, and the homes of the memory map, format catalog and parity notes;
- `G07`'s three-command line in § 5 became `mise run capture-ref` and a link to [Score a render change](../../../docs/howto/score-a-render-change.md), which holds the render and `stuntreel parity` commands;
- text that restated code or another section was cut: `FilmTimeline`'s method list (its public `sample` and `slices()` stay named) and the names of the per-slice evaluators the code no longer has, the fields of `DecodeRecord`, the tier names in § 1.1, the tier and anchor detail in `G01`, the asset exceptions in § 1.1 (kept in `[I7]`), the header's Strategy and Methodology lines (kept in § 1.2 and § 1.1);
- the issue tracker's links became one reference definition (the Ongoing phase's copy was cut, the Status line has it), and the remaining prose was tightened;
- on review, the tier-tag scope ("every recovered struct, offset and opcode"), `slices()`, "16-bit" and "immediate-mode", `[I8]`'s POSIX reason, the address rule's "must" and `G05`'s Python-exporter history were restored. The page ends at 20,459 bytes.
