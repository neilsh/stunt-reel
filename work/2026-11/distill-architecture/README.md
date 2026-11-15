---
title: "Distill docs/ARCHITECTURE.md"
started: 2026-11-15
outcome: "No dated narrative to move; repeated links became reference definitions, a duplicate parity row merged, the Python rows split into docs/architecture-python.md and the longest module descriptions were trimmed, bringing the page under its budget"
---
# Distill `ARCHITECTURE.md`

The page was 26,941 bytes, over the 20 KB budget (`mise run doc-health`, 2026-11-15). The daily gardening routine distilled it:

- it held no dated round, session log or superseded result: its one dated line, the pointer to the closed 2026-10-25 architecture-deepening programme, is already a one-sentence link to that work folder, so this folder has no `journal.md`;
- each link a routing table repeats with the same text (anchor tokens such as `[I6]`, and the research notes and ADRs cited more than once) became a Markdown reference definition below the table, so each long anchor URL is written once per page;
- the routing table listed `crates/stunt-cli/src/parity/` twice; its short row, which cited only `[I6]` and `palette-and-shading.md`, both also on the long row, merged into the long one.

That left 23,227 bytes, still over budget, so on review the page was also split and trimmed:

- the 17 rows whose code path starts with `python/` moved, with the same link targets, to [`docs/architecture-python.md`](../../../docs/architecture-python.md), which `ARCHITECTURE.md`'s intro, `AGENTS.md`, `README.md` and `SPEC.md` link; rows that pair a Rust path with a Python one, such as `link.rs` with `link.py`, stay on the Rust page;
- the longest module descriptions now name each module's subjects instead of listing its files' responsibilities, which the modules' own doc comments state: on the Rust page `stunt-cli/src/parity/`, `world/mod.rs`, `scene/mod.rs` and `main.rs`'s `page_slot.rs`; on the Python page `capture_run.py` (which scripts and callers use it), `parity_pipeline.py` with `parity_judge.py` and `references.py` (their callers and details) and the doc tooling ("on a move or split").

The trims dropped descriptive clauses only: every anchor, research-note and ADR link on the old page is still on one of the two pages for the same code path. The pages end at 14,214 and 8,476 bytes.
