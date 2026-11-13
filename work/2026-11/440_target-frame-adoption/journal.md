# Journal

## 2026-11-12: spike target ranges fixed before scoring

- **Question**: § 1 of [`spec.md`](spec.md): rescore known adoptions, rejections and one SSIM-raising fault on all seven reference films, before any bound is written. This entry fixes the target ranges first, so they cannot be chosen from the scores.
- **Ranges** (inclusive film ticks, quoted before any render or sweep):

  | Case | Candidate against baseline | Track | Target ranges |
  |---|---|---|---|
  | A1 | `dd9a22cf` (#429) against `9bc0fb78` (its parent) | evidence | `intro:3235-3301` |
  | A2 | `826ddddd` (#431) against `dd9a22cf` (its parent) | evidence | `intro:3279-3301` |
  | A3 | `59d62f12` (#434) against `826ddddd` (its parent) | evidence | none (broad change) |
  | R1 | #429's `DBG_POLY_EDGES=1` against `9bc0fb78` | evidence | `intro:3235-3301` |
  | R2 | #430's `DBG_INCLUSIVE=1` | evidence | none |
  | R3 | #430's `DBG_INCLUSIVE=3` | evidence | none |
  | F1 | the metric bench's actors-removed fault on `CTRY` | n/a | **not yet fixed**, see below |

- **Sources of the ranges.** A1 and R1: the spec's § 1.1 table, `INTRO` around 3235 to 3301, which covers the worst movers of #426's `POLY_EDGES=1` run (3235 to 3290, [journal](../426_intro-conifers/journal.md)). A2: the ticks #428's journal scored (3279 and 3301, [journal](../428_intro-lake/journal.md)), widened to the spec's 3279 to 3301. A3, R2 and R3 are broad changes: no target, judged by the film-mean and guard rules alone.
- **Open before scoring.**
  - F1's range is not yet chosen. The spec names "one actor-heavy range on `CTRY`", and [`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.2 does not name one. The range must be fixed before the fault is planted and scored; if no range can be fixed on a reasoned basis, F1 is dropped and this entry says so.
  - R1 is not yet rebuilt. `DBG_POLY_EDGES` was never committed. It is rebuilt from #426's description: each filled polygon of each decoded shape also emits its edges through `push_line`, interleaved with the polygon. If the rebuilt switch cannot reproduce #426's `POLY_EDGES=1` column (within 0.0005 per film), R1 is dropped and this entry says so.
  - R2 and R3 are not yet rebuilt. `DBG_INCLUSIVE` values 1 and 3 need a conservative-rasterization state and a line-list edge pass, as described in [#430's journal](../430_world-mesh-slivers/journal.md). Each is dropped if its rebuild cannot reproduce #430's column for that value.
- **Verdict**: no scores yet. Scoring starts only after the open items above are fixed or dropped, and the user has reviewed this table.
