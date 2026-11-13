---
title: "Stop render PRs conflicting on references.toml expected tables"
started: 2026-11-12
issue: 436
outcome: "Layout (d): reports record their crates/ tree, mise run parity-repin rewrites the expected tables, and the parity rules forbid hand-merged scores"
---

# Stop render PRs conflicting on references.toml expected tables

Render PRs conflicted on the seven `[<film>.expected.gpu]` tables of `research/parity/references.toml`, and the usual fix, hand-merging numbers, pinned scores no tree measured. [`spec.md`](spec.md) compares four layouts and records the decisions taken at triage.

## Outcome

- `report.json` records `crates`, the tree its render was built from ([`report-fields.md`](../../../research/parity/report-fields.md)).
- `mise run parity-repin` rewrites every film's expected table for one class, or writes nothing and says why ([`score-a-render-change.md`](../../../docs/howto/score-a-render-change.md) § 7).
- The repin rules are in [`loop-rules.md`](../../../.agents/skills/improving-render-parity/loop-rules.md#adoption-rule) and [`method.md`](../../../research/parity/method.md) step 0; *Expected score* and *Repin* are in [`GLOSSARY.md`](../../../GLOSSARY.md).
