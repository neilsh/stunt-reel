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

## 2026-11-12: F1's range fixed before planting

- **Question**: which `CTRY` range the actors-removed fault (F1) is planted on, fixed before the fault is planted or scored (`spec.md` § 1, Q3).
- **Method**: the scored ticks of `CTRY` at `9bc0fb78` (114 scored, baseline `report.json`). Actor pixels per tick: the count of pixels whose layer is at or above the bench's `ACTOR_LAYER` (16) in that render's layer plane. The capture stores no layer plane, so the render's is the only per-pixel actor count available; the fault removes exactly those pixels, so this is the quantity it changes. For each run of 20 consecutive scored ticks, the summed actor pixels; the densest run is taken. Scratch script `build/scratch/spike/f1_range.py` (not committed).
- **Result**: the densest run is ticks 485 to 694 (20 scored ticks, 52,217 actor pixels in total; per tick 2,074 to 2,874). Target range for F1: `ctry:485-694`.
- **Verdict**: fixed. F1 is planted on `ctry:485-694` only; no other range is tried.

## 2026-11-12: F1 scored: the actors-removed fault lowers SSIM on `CTRY`

- **Method**: `parity_bench.py plant --fault actors_removed@485-694` on the `9bc0fb78` render of `CTRY` (into `build/scratch/spike/f1/ctry`, not committed), then `mise run parity -- --films ctry --no-build --reuse build/scratch/spike/f1`. Baseline: the `9bc0fb78` `CTRY` report. Scored ticks in both: 114, none lost.
- **Result**:

  | Case | Film mean ΔSSIM / ΔIdx | Target `ctry:485-694` ΔSSIM / ΔIdx (n, rose) | Frames > 0.005 down / > 0.010 down |
  |---|---|---|---|
  | F1 actors removed on `9bc0fb78` | −0.01054 / −0.00578 | −0.06006 / −0.03296 (20, 0) | 20 / 20 |

- **Observation**: the fault falls on every target frame. The spec expected an SSIM-raising fault (`metric-bench.md` § 2.2 reported `ssim` rising 15σ on `CTRY` when actors were removed), and this range does not show that. Possible causes, not tested: the bench measured a different build and reference (`2461289` against `004`/`005`), and a dense actor range differs from the bench's whole-film average. The fault is therefore not the SSIM-raising case the spike needed; whether to keep it as a rejection case is a question for the user (see the spike's open questions).
- **Verdict**: F1 as planted here is a fault SSIM already rejects (it moves the score down by more than the 0.010 bound on every target frame), so it tests nothing about false adoption. Reported, not replaced.

## 2026-11-12: R1 rebuilt and scored; R2 and R3 dropped

- **R1 method**: #429's `DBG_POLY_EDGES=1` rebuilt from #426's description (every filled polygon of a decoded shape also emits its edges through `push_line`, before its tessellation) as a one-line-per-edge patch in `process_polygon_batch` (`crates/stunt-core/src/sod/tessellate.rs`) on a scratch worktree of `9bc0fb78`, built with `cargo build -p stunt-cli --release`. Not committed. Scored by `mise run parity -- --no-build` on all seven films with `DBG_POLY_EDGES=1`; `build/scratch/spike/r1/`.
- **R1 against #426's column**, the rule in `spec.md` (within 0.0005 per film):

  | Film | #426 `POLY_EDGES=1` | R1 rebuilt | Absolute Δ | #426 Δ over its base | R1 Δ over `9bc0fb78` | Δ of Δ |
  |---|---|---|---|---|---|---|
  | `CTRY` | 0.9043 | 0.90424 | −0.00006 | +0.0028 | +0.00274 | −0.00006 |
  | `INTRO` | 0.8455 | 0.84610 | **+0.00060** | +0.0018 | +0.00182 | +0.00002 |
  | `LAND` | 0.8662 | 0.86581 | −0.00039 | 0.0000 | +0.00005 | +0.00005 |
  | `BALLOON` | 0.8133 | 0.81332 | +0.00002 | +0.0036 | +0.00364 | +0.00004 |
  | `TRAINTNL` | 0.8574 | 0.85711 | −0.00029 | +0.0026 | +0.00214 | −0.00046 |
  | `BOMB` | 0.8174 | 0.81913 | **+0.00173** | +0.0045 | +0.00484 | +0.00034 |
  | `LOCATION` | 0.8134 | 0.81371 | +0.00031 | +0.0036 | +0.00344 | −0.00016 |

- **Verdict**: R1 **dropped** under the rule as written: the absolute column is not reproduced within 0.0005 on `INTRO` (+0.0006) and `BOMB` (+0.0017). Two things are not the same in the two runs: their baselines differ (`BOMB` 0.8129 in #426 against 0.8143 at `9bc0fb78`; `INTRO` 0.8437 against 0.8443), so the absolute column also carries that offset. Measured as the change over each run's own baseline, every film agrees within 0.0005 (`TRAINTNL` at −0.00046 is the closest). Whether the rule should compare deltas is a question for the user, not decided here.
- **R2 and R3 dropped** (`spec.md` § 1, Q4, approved): `DBG_INCLUSIVE` values 1 and 3 are not rebuilt. The spec's rule is to keep a rejected case only if its switch can be rebuilt from its journal; #430's journal records their description and the scores but not the conservative-rasterization state or the line-list pass as code, and a rebuild that could not be checked against #430's column would not be evidence. Stated plainly: dropped for lack of a checkable rebuild, not because their scores were looked at.
- **Summary of the spike, as scored**:

  | Case | Verdict (provisional) | Film mean ΔSSIM range (films) | Target ΔSSIM / ΔIdx | Frames > 0.005 / > 0.010 down |
  |---|---|---|---|---|
  | A1 | rejected by the SSIM target test; adopted by the film means (false rejection under SSIM, per Q2) | −0.00111 to +0.00303 | −0.00503 / −0.00334 | 127 / 56 |
  | A2 | adopted on the index test (target ΔIdx +0.0193; SSIM −0.0011) | −0.00041 to +0.00756 (ΔIdx) | −0.00113 / +0.01934 | 11 / 6 |
  | A3 | adopted (all seven films up) | +0.00021 to +0.00503 | none | 68 / 18 |
  | R1 | dropped (rebuild outside 0.0005 on 2 films) | see the table above | — | — |
  | R2, R3 | dropped (no checkable rebuild) | — | — | — |
  | F1 | not a SSIM-raising case here (lowers SSIM on every target frame) | −0.01054 film mean | −0.06006 / −0.03296 (20 frames) | 20 / 20 |

- **Not done**: the index-agreement check (`report.json`'s per-frame `index_agreement` against the spec's definition) is still unverified; the four questions to the user are not yet put.
