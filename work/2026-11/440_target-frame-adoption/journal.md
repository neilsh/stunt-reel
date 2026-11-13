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

## 2026-11-12: spike results for A1–A3

- **Method**: four release builds (`mise run build-at`) of `9bc0fb78`, `dd9a22cf`, `826ddddd` and `59d62f12`, each rendered and scored by `mise run parity -- --no-build` on all seven films. Candidate minus baseline on each scored tick, from each `report.json`'s `per_frame` (`ssim`, `index_agreement`), over the ticks the baseline scores; no tick was lost. The scoring script is scratch (`build/scratch/spike/score.py`, not committed).
- **Targets**: as fixed above, `intro:3235-3301` (A1) and `intro:3279-3301` (A2). A3 has none.

| Case | Film mean ΔSSIM / ΔIdx (films moved) | Target ΔSSIM / ΔIdx (n, rose) | Frames > 0.005 down / > 0.010 down |
|---|---|---|---|
| A1 `dd9a22cf` vs `9bc0fb78` | INTRO +0.00237 / −0.00016; CTRY +0.00071; LAND +0.00053; BALLOON +0.00303; TRAINTNL +0.00050; BOMB +0.00083; LOCATION −0.00111 / −0.00078 | −0.00503 / −0.00334 (7, 2) | 127 / 56 |
| A2 `826ddddd` vs `dd9a22cf` | INTRO −0.00004 / +0.00510; BALLOON −0.00041 / +0.00158; LOCATION +0.00026 / +0.00756; others 0 or −0.00002 | −0.00113 / +0.01934 (3, 1) | 11 / 6 |
| A3 `59d62f12` vs `826ddddd` | all seven up: CTRY +0.00255, INTRO +0.00021, LAND +0.00035, BALLOON +0.00138, TRAINTNL +0.00187, BOMB +0.00503, LOCATION +0.00496 | none | 68 / 18 |

- **Observations** (`[Bounded Observation]`, one run per commit):
  - A1's target frames fall on the whole-frame SSIM and index agreement, while INTRO's film mean rises. Only 7 of the 67 ticks in `3235-3301` are scored, and 2 rose. The heuristic target rule (§ 2) would reject A1, which is the case that motivates the spec, so § 1 will need to report it.
  - A2 scores 3 scored target frames, the spec's minimum. Its target index agreement rises (+0.0193) while its SSIM does not move (−0.0011). That is the spec's lead that index agreement may register what whole-frame SSIM misses.
  - Frames falling by more than 0.010 are common in A1 (56) and A3 (18), though A3's film means all rise. The per-frame bound is not yet judged against these.
- **Not done in this entry**:
  - R1–R3 are not rebuilt or scored; their switches were never committed, so their rebuild is open (see the pre-registration entry above).
  - F1's `CTRY` range is not chosen and its fault is not planted.
  - Index agreement here uses each frame's `index_agreement` from `report.json`, not a separate scratch measure. That matches the spec only if `report.json` computes it the same way; this is not yet checked.
  - The four questions to the user (target metric, heuristic bar, per-frame bound, 3-frame minimum) are not yet put, since § 1 needs R1–R3 and F1 for the "what counts as passing" check.
- **Verdict**: no bound is written. A1 is the open case: its target frames fell, so the heuristic target rule would reject an adopted change.
