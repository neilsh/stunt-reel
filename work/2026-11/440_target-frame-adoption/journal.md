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

## 2026-11-12: the user's answers, and target-frame drops scored

- **Answers** (user, all six as recommended): (Q1) the target-frame test uses index agreement, A1 reported as a known false rejection of it; (Q2) film-mean bar: no reference film's mean SSIM falls by 0.002 or more; (Q3) the per-frame bound guards the target range only, no whole-film count; (Q4) keep the 3 scored target frame minimum, and report a case at the minimum as thin evidence; (Q5) keep F1 as a rejection sanity case and record that no SSIM-raising fault has been tested; (Q6) the R1 rebuild is compared by delta over its own baseline, so R1 is reinstated and its target scored. This reverses the R1 drop in the previous entry.
- **Method**: as above; per-frame `ssim` and `index_agreement` of each case minus its baseline over the baseline's scored ticks in the target range (scratch `build/scratch/spike/target_worst.py`, not committed). F1 re-scored from the planted store.
- **Result** (Δ = candidate − baseline; worst = the most negative single frame):

  | Case | Target (n) | ΔSSIM mean / worst | ΔIdx mean / worst | Frames with ΔIdx > 0 |
  |---|---|---|---|---|
  | A1 | `intro:3235-3301` (7) | −0.00503 / −0.01316 | −0.00334 / −0.00747 | 2 |
  | A2 | `intro:3279-3301` (3, at the minimum) | −0.00113 / −0.00403 | +0.01934 / −0.02858 | 1 |
  | R1 | `intro:3235-3301` (7) | −0.00723 / −0.01643 | −0.00010 / −0.00583 | 3 |
  | F1 | `ctry:485-694` (20) | −0.06006 / −0.07237 | −0.03296 / −0.03642 | 0 |

  R1's film-mean ΔIdx over `9bc0fb78` is positive on all seven films (+0.0005 to +0.0028); its film-mean ΔSSIM is +0.00005 to +0.00484 (previous entry).
- **Observations** (`[Bounded Observation]`, four cases, one run each):
  - A mean target ΔIdx at or above 0 separates A2 (+0.0193) from the three cases below it, but R1 (−0.0001) is a near tie and A1 (−0.0033) falls: the index test as written rejects A1 and R1 and adopts A2, F1 is rejected by both metrics by a wide margin (ΔIdx −0.033).
  - A per-frame ΔIdx bound does not separate the cases: A2, an adopted case, has a single target frame at −0.0286, close to F1's frames (−0.026 to −0.036).
  - A per-frame ΔSSIM drop on target frames does separate F1 from the rest: A1, A2 and R1's worst frames are −0.013, −0.004 and −0.016; every F1 frame is at least −0.045. Any bound between 0.017 and 0.044 splits these four; one number is not established by four cases.
- **Proposal for the bound, not a rule**: a target frame may fall by at most 0.030 SSIM (the midpoint of the gap, rounded). It rests on four cases, one of which (F1) is not an SSIM-raising fault, so it is a starting point to be re-tested, not a measured bound.
- **Not done**: R2 and R3 stay dropped; the index-agreement definition check (`report.json` against the spec's) and any SSIM-raising false-adoption case are open. PR 1 and PR 2 are not started.

## 2026-11-12: corrections after an independent review of the spike

An independent script (written without the scratch scripts here) reproduced every film Δ, target mean, worst frame, rise count and falling-frame count (127/56, 11/6, 68/18), with no tick lost. It raised the following, each checked against the code or journals below.

- **Index agreement is closed.** `report.json`'s `index_agreement` is `parity::mask::index_agreement` (`crates/stunt-cli/src/parity/mask.rs`): the fraction of non-overlay pixels whose index equals the capture's. That is the measure the spec quotes for #428. Remove it from the "Not done" lists above.
- **R1 is not a rejection case.** In [#426's journal](../426_intro-conifers/journal.md) `POLY_EDGES=1` scored above the adopted `OUTLINE=3` on five films (`CTRY`, `BALLOON`, `TRAINTNL`, `BOMB`, `LOCATION`) and below it on two (`INTRO` 0.8455 against 0.8460, `LAND` 0.8662 against 0.8666). It was set aside for cost (outlining the world mesh multiplied `LOCATION`'s vertices about five times), not for its score, and #434 (A3) later adopted the props-only outline as a line list. The spec § 1 table's "rejected" for R1 is an error. "The index test rejects R1" therefore is not evidence for the rule, and R1 is not counted as a rejected case.
- **A1's target range is suspect.** `intro:3235-3301` was pre-registered above from R1's worst movers in #426, where our camera sits a few pixels off the capture's, so added detail lands in the wrong place and any change that adds detail there will probably score lower. A1's falling target is at least partly a selection effect, so it is not a clean false rejection of the index test. The range was fixed before scoring; the weakness showed only afterwards. This qualifies the Q1 answer's "A1 reported as a known false rejection".
- **A claim above is wrong.** "Only 7 of the 67 ticks in `3235-3301` are scored" is wrong: the film holds a frame every 11 ticks, so the range has 7 frames and all 7 are scored (checked in the baseline report).
- **Consequence.** The spike has no valid rejected case (R1 invalid, R2 and R3 dropped) and no SSIM-raising fault (F1 lowers SSIM). The proposed 0.030 per-frame SSIM bound separates F1 from A1, A2 and R1, but has not been tested against any change the rule should reject, so it stays a starting point.

## 2026-11-12: second-round cases fixed before scoring

Answers (user, `y` to all four): (Q1) PR 1 and the spec's bounds wait for a valid rejected case and an SSIM-raising fault; (Q2) R2 is rebuilt, kept only if it reproduces #430's column; (Q3) the actors-removed fault is planted over every scored tick of `CTRY` and `INTRO`; (Q4) A1 gets a second target from #429's own evidence.

- **A1b target.** #429 (`dd9a22cf`) names `INTRO` ticks 3290 and 3301 as its symptom ([#429's PR body](https://github.com/neilsh/stunt-reel/pull/429), from #426's issue); its pictures also show 3323, but those are the ticks that *gained most*, so a range built on them is chosen from the result and is not used. Target: `intro:3290-3301`. It holds 2 frames, below the 3 frame minimum of Q4, so the case is reported as having no valid target whatever its numbers. Weakness: both ticks lie inside the first range, whose per-tick Δs are already in the earlier tables, so this range is not blind.
- **F1b ranges.** `actors_removed` planted on the `9bc0fb78` renders over every scored tick of `CTRY` (114) and of `INTRO` (209), one fault run per film. No other range is tried. If SSIM still falls on both films, no SSIM-raising fault exists on these two films and the false-adoption protection rests on the film-mean bar.
- **R2 rebuild.** `DBG_INCLUSIVE=1` from #430's journal on `dd9a22cf`: the world drawn through the base and decal pipelines with `PrimitiveState::conservative`, the world's line quads narrowed to a thousandth of their width. Kept as a rejected case only if every film's score is within 0.0005 of #430's column (`CTRY` 0.8961, `INTRO` 0.8480, `LAND` 0.8653, `BALLOON` 0.8127, `TRAINTNL` 0.8545, `BOMB` 0.8158, `LOCATION` 0.8069); #430's base is `dd9a22cf` itself, so absolute values are comparable here. Its target: none (broad change). Not scored yet.

## 2026-11-12: second-round results: A1b, F1b and R2

- **A1b** (`intro:3290-3301`, `dd9a22cf` against `9bc0fb78`): 2 frames, below the 3 frame minimum, so A1 has no valid target. Tick 3290: ΔSSIM −0.00329, ΔIdx −0.00490; tick 3301: +0.00840, +0.00343 (means +0.00255 and −0.00074).
- **F1b** (`actors_removed` over every scored tick, `9bc0fb78` renders, planted stores in `build/scratch/spike/f1b/`, not committed):

  | Film | Scored ticks | ΔSSIM mean | Ticks with ΔSSIM > 0 | Worst / best ΔSSIM | ΔIdx mean |
  |---|---|---|---|---|---|
  | `CTRY` | 114 | −0.02922 | 6 | −0.0724 / +0.0002 | −0.01499 |
  | `INTRO` | 209 | −0.05093 | 26 | −0.2408 / +0.0153 | −0.03968 |

  The fault lowers SSIM on both whole films, so no SSIM-raising fault exists on these two (`[Bounded Observation]`, one fault, two films). The false-adoption protection stays the film-mean bar. The bench's earlier "removing actors raises `ssim`" (`metric-bench.md` § 2.2, 2026-10-31) is not reproduced on the current render.
- **R2 rebuilt** from #430's description on a scratch worktree of `dd9a22cf` (not committed): the world drawn through copies of the base and decal pipelines with `PrimitiveState::conservative`, the `CONSERVATIVE_RASTERIZATION` device feature requested, and the world's line quads (model layer 0) narrowed to a thousandth of their width in the vertex shader; `DBG_INCLUSIVE=1`, all seven films by `mise run parity -- --no-build`.

  | Film | #430 `1` | R2 rebuilt | Diff | #430 Δ over base | R2 Δ over `dd9a22cf` |
  |---|---|---|---|---|---|
  | `CTRY` | 0.8961 | 0.90127 | **+0.00517** | −0.0061 | −0.00094 |
  | `INTRO` | 0.8480 | 0.84826 | +0.00026 | +0.0013 | +0.00161 |
  | `LAND` | 0.8653 | 0.86299 | **−0.00231** | −0.0010 | −0.00330 |
  | `BALLOON` | 0.8127 | 0.81074 | **−0.00196** | 0.0000 | −0.00198 |
  | `TRAINTNL` | 0.8545 | 0.85430 | −0.00020 | −0.0010 | −0.00117 |
  | `BOMB` | 0.8158 | 0.81629 | +0.00049 | +0.0007 | +0.00117 |
  | `LOCATION` | 0.8069 | 0.80713 | +0.00023 | −0.0023 | −0.00202 |

  The baselines agree with #430's to four places, so absolute values are comparable. R2 reproduces the signs of six films but misses #430's column by more than 0.0005 on `CTRY`, `LAND` and `BALLOON`.
- **Verdict**: R2 **dropped** under the Q2 rule. The spike still has no valid rejected case. The rebuild may differ from #430's switch in what narrowed (here: every world line quad, by layer), which the journal does not specify; whether conservative rasterization was active was not checked beyond the adapter reporting the feature. R3 stays dropped.
- **Consequence for the bound**: the 0.030 per-frame SSIM bound has still not been tested against a change the rule should reject, and no SSIM-raising fault is available. Recommendation for the user, not a rule: write the film-mean bar and the target test, label the per-frame bound unvalidated, and take a real rejected case from the next change that scores a target and a film worse (the spec's own case list gains it then).

## 2026-11-12: third-round rejected cases from #255, fixed before scoring

You suggested looking at past rejected cases. [#255's journal](../255_sp1node-lens/journal.md) ("rescoring the per-frame gate") records two per-frame `SP_1NODE` gate variants that were rejected on their scores, against the static rule at `1308da0`, with a full seven-film column each and a variant switch simple enough to rebuild from the committed code.

- **Cases** (both evidence-backed track, candidate against the static rule `1308da0`):

  | Case | Candidate | #255's column (`CTRY`, `INTRO`, `LAND`, `BALLOON`, `TRAINTNL`, `BOMB`, `LOCATION`) | Target |
  |---|---|---|---|
  | R4 | per-frame gate, true depth (`DBG_LOD_EXP=0`) | 0.8961, 0.8339, 0.8555, 0.8014, 0.8403, 0.7900, 0.7822 | none (broad change) |
  | R5 | per-frame gate, depth shifted by `0x229E` (`DBG_LOD_EXP=1`) | 0.8961, 0.8340, 0.8565, 0.8014, 0.8489, 0.7900, 0.7832 | none (broad change) |

  Baseline column (static rule at `1308da0`): 0.8973, 0.8344, 0.8656, 0.8008, 0.8511, 0.7998, 0.7909. The adopted variant (`123a2d9`, depth halved and shifted) is not a case here.
- **Rebuild**: `123a2d9` with the one line of `CameraTransform::lod_keeps_subtree` (`crates/stunt-core/src/contracts/trajectory.rs`) that divides the depth chosen by an environment switch: `0` no division, `1` by `1 << shift`, `2` (committed) by `2 << shift`. Scratch worktree, not committed.
- **Keep rule** (as Q2 and Q6): a case stays only if each film's score is within 0.0005 of #255's column, absolute values (and as a delta over its own baseline if the baselines differ by more than 0.0005). Otherwise it is dropped and the journal says so.
- **No target** for either case, so this round tests the film-mean bar (Q2) and not the per-frame bound; the journal's named `INTRO` ranges (1216-1290, 2511-2624) were found after adoption and are not used as targets.

## 2026-11-12: third-round results: R4 and R5 are valid rejected cases

- **Method**: as fixed above. Three seven-film runs by `mise run parity -- --no-build`: the static rule (`1308da0`, from `mise run build-at`), and the patched `123a2d9` with `DBG_LOD_EXP=0` (R4) and `1` (R5). Scratch under `build/scratch/spike/` (`lodexp0`, `lodexp1`, `static1308`), not committed.
- **Reproduction of #255's column** (absolute mean SSIM, all within 0.00005 of the journal's four-place values): static rule 0.89728, 0.83438, 0.86561, 0.80080, 0.85106, 0.79976, 0.79086; R4 0.89612, 0.83390, 0.85550, 0.80137, 0.84031, 0.79002, 0.78222; R5 0.89612, 0.83404, 0.85650, 0.80136, 0.84890, 0.79002, 0.78316 (`CTRY`, `INTRO`, `LAND`, `BALLOON`, `TRAINTNL`, `BOMB`, `LOCATION`). Both cases pass the keep rule.
- **Result** (candidate minus the static rule):

  | Film | R4 ΔSSIM / ΔIdx | R5 ΔSSIM / ΔIdx |
  |---|---|---|
  | `CTRY` | −0.00116 / −0.00063 | −0.00116 / −0.00063 |
  | `INTRO` | −0.00049 / +0.00197 | −0.00035 / +0.00195 |
  | `LAND` | **−0.01011** / −0.02134 | **−0.00911** / −0.02018 |
  | `BALLOON` | +0.00056 / +0.00031 | +0.00056 / +0.00031 |
  | `TRAINTNL` | **−0.01075** / −0.02023 | **−0.00216** / −0.00335 |
  | `BOMB` | **−0.00974** / −0.00923 | **−0.00974** / −0.00923 |
  | `LOCATION` | **−0.00864** / −0.01116 | **−0.00770** / −0.00885 |

  Frames more than 0.005 / 0.010 below the baseline over all films: R4 572 / 426, R5 537 / 395; the worst single frame is −0.162 in both; no scored tick lost.
- **Verdict** (`[Bounded Observation]`, one run per variant): both fall on four films by more than 0.002 (R5's `TRAINTNL` −0.00216 is the closest to the bar), so the Q2 film-mean bar rejects both, as #255 did. They are the spike's first valid rejected cases, and the film-mean bar is validated against them: it rejects them on films the adopted cases (A1 to A3) do not fall on by 0.002.
- **What this does not test**: the per-frame bound (0.030 SSIM, proposal) and the target-frame test, since neither case has a target. A target-frame guard is still validated only against F1 (not an SSIM-raising fault) and A1, A2, R1. Their false-adoption protection rests on the film-mean bar.

## 2026-11-12: a rejected case with a target (#407), fixed before scoring

You asked for a rejected case with a target. [#407's journal](../407_sprite-draw-order/journal.md) records `DBG_SPRITE_MODE=3`: the `OP_ANIMATE` sprite drawn after every base and decal draw with depth compare `Always`, rejected because it does not match the capture at `CTRY` tick 871 (the hill appears to hide the explosion; ours draws the whole square over it) and falls `CTRY` by 0.0012. Its targets are the explosions' tick ranges that [#222's journal](../222_op-animate/journal.md) names, from before #407 scored anything: `CTRY` 859-881, `INTRO` 1387-1409 and `INTRO` 2707-2729.

- **Case R6**: mode 3 against `dbfd0ed4` (#407's base), evidence-backed track. #407's column for mode 3 (`CTRY`, `INTRO`, `BOMB`, the three films it swept): 0.8984, 0.8422, 0.8101; baseline 0.8996, 0.8418, 0.8101.
- **Targets**: `ctry:859-881`, `intro:1387-1409`, `intro:2707-2729`. Each holds 3 scored frames (859, 871, 881; 1387, 1398, 1409; 2707, 2718, 2729), so each meets the 3 frame minimum and the pooled 9 frames are also scored. Weakness: tick 871 is also the frame #407's rejection rests on.
- **Rebuild**: on a scratch worktree of `dbfd0ed4`, a sprite pipeline (the base pipeline with depth compare `Always`) drawing every `Target::Image` draw after the base and decal passes, with the same draws left out of those passes. Not committed.
- **Keep rule** (as before): all seven films run; kept only if `CTRY`, `INTRO` and `BOMB` are within 0.0005 of #407's column. Otherwise dropped, and the journal says so.
- **What the rule should do with it**: no film falls by 0.002 (R6 expected at −0.0012 on `CTRY` only), so the film-mean bar alone would adopt it; the target test and per-frame bound are what could reject it. That is the test this case adds.
