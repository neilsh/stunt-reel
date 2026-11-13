# Spec: adopt a render change on its target frames, guarded per frame

Issue [#440](https://github.com/neilsh/stunt-reel/issues/440). Design agreed 2026-11-12 by grilling: decisions Q1 to Q31, then Q32 to Q39 after a review. S1 to S7 came from checking the design against the code. Some later decisions revise earlier ones; the Decisions table at the end marks which.

## Intent

**Goal.** Let a round adopt a fix that shows on a short run of frames. Judge it on those frames, and guard every film, and every frame, against getting worse.

**Why.** Recent defects are local: #426's conifers and #428's lake each show on one stretch of `INTRO`.

- **A film mean dilutes a fix.** It divides the gain by the film's scored-frame count, which was 97 (`LAND`) to 732 (`LOCATION`) in the seven reports of 2026-11-09 (`scored_frames`). Twenty frames that each rise 0.02 move `INTRO`'s mean (209 scored) about +0.0019 and `LOCATION`'s about +0.0005. That is under both heuristic bars of today's [adoption rule](../../../.agents/skills/improving-render-parity/loop-rules.md#adoption-rule).
- **The same dilution hides a local regression.** Ten frames falling 0.02 move a film of more than 100 scored frames by less than 0.002, so the film-mean guard misses them.

**What is not known yet.** Whole-frame SSIM may not register such fixes at all. #428's lake moved `INTRO`'s SSIM from 0.8437 to 0.8436 while its index agreement rose from 0.843 to 0.848 ([journal](../428_intro-lake/journal.md)). The target metric and the bounds are therefore decided by a spike (§ 1) before any rule is written (Q32).

**What changes.**
- A round may name **target frames** before its sweep.
- A heuristic change may adopt on those frames' mean (Q34).
- An evidence-backed change reports the target mean as attribution only.
- A per-frame guard joins every branch: a hard bound on the heuristic track, and a journal account on the evidence-backed one (Q35).
- A targeted round commits a few capture | before | after pictures to its work folder.

**Out of scope.**
- A "shot" term, and recording the view slot in the render record (Q18, Q19).
- Any change to `stuntreel parity` or `compare.json` (Q23).
- Any change to what `research/parity/references.toml` records (Q9).
- A noise model for the bounds. They are policy, as 0.002 is ([`evidence-limits.md`](../../../research/parity/evidence-limits.md) § 3).

## 1. Spike: rescore known cases first

The spike runs before PR 1 and writes no rule (Q32). It is one journal entry in this folder, from a scratch script that is not committed.

### 1.1 Cases

Each case is a candidate scored against its baseline on all seven reference films.

| Case | Candidate against baseline | Known outcome | Target frames |
|---|---|---|---|
| A1 | #429 (`dd9a22cf`) against its parent | adopted | `INTRO`, around 3235 to 3301 |
| A2 | #431 (`826ddddd`) against its parent | adopted | `INTRO`, around 3279 to 3301 |
| A3 | #434 (`59d62f12`) against its parent | adopted | none (a broad change) |
| R1 | #429's `DBG_POLY_EDGES=1` | rejected | as A1 |
| R2 | #430's `DBG_INCLUSIVE=1` | rejected | none |
| R3 | #430's `DBG_INCLUSIVE=3` | rejected | none |
| F1 | the metric bench's actors-removed fault ([`metric-bench.md`](../../../research/parity/metric-bench.md) § 2.2) | should be rejected | the frames of one actor-heavy range on `CTRY` |

- **Fixing the ranges first.** The exact target ranges are written in the journal before any case is scored, as a round would write them. They are drawn from the ticks the cases' journals name ([426](../426_intro-conifers/journal.md), [428](../428_intro-lake/journal.md)).
- **Switch code that is gone.** The `DBG_*` switches were never committed. A rejected case whose switch cannot be rebuilt from its journal's description is dropped, and the spike entry says so.

### 1.2 What it records

For each case and film, the spike entry records:
- the film-mean Δ, both SSIM and index agreement;
- on the target frames, the pooled and per-film mean Δ of SSIM and of index agreement, and the count of frames that rose;
- the frames that fell by more than 0.005 and by more than 0.010, in SSIM;
- the verdict of the provisional rule of § 2 on each track.

### 1.3 What it decides

The spike's results go to the user, who settles these. Until then they stay open and § 2's figures are provisional:

1. **The target metric.** SSIM, index agreement, or either one rising (Q33). Index agreement is printed beside SSIM in every case.
2. **The heuristic target bar.** Provisionally +0.010.
3. **The per-frame bound.** Provisionally 0.010, with falls above 0.005 listed.
4. **The minimum of scored target frames.** Provisionally 3.

**What counts as passing.** A1 to A3 should adopt, and R1 to R3 and F1 should not. A case that comes out the other way is reported with the guard or test responsible. "No false rejection" and "no false adoption" are reported separately; neither proves the bounds right.

## 2. The adoption rule (provisional until § 1 reports)

Replaces the **Adoption rule** section of [`loop-rules.md`](../../../.agents/skills/improving-render-parity/loop-rules.md). The two tracks stay: evidence-backed, citing a `PLAYONE.EXE` rule at an image offset, and heuristic.

### 2.1 Branches

| Track | Film-mean branch (unchanged) | Target branch |
|---|---|---|
| Evidence-backed | at least one film rises | none. The target mean is reported as attribution (Q34). |
| Heuristic | every film above +0.002, or one above +0.004 | see the three conditions below |

The heuristic target branch adopts when all three hold (Q15, Q36):
1. the pooled target mean rises by more than +0.010;
2. each targeted film's own target mean rises;
3. more than half of all scored target frames rise.

**Why the target branch is heuristic-only.** Under the evidence-backed track, the film-mean branch adopts whenever any film rises. A target branch could only add adoptions where the target frames rose and the film as a whole did not, that is, where the other frames fell by more (Q34).

**Definitions.**
- **Target mean**: the mean, over the target frames, of candidate minus baseline (Q6). The **pooled** figure covers every targeted film's target frames together.
- The target branch needs at least **3 scored target frames** in all. With fewer, the sweep judges on film means only and says why (Q26).

**Why the heuristic bar is high.** The sweep picks the variant that scores best on frames the round chose. That is the same kind of circularity [`method.md`](../../../research/parity/method.md) § 4.1 rules out for fitting the fade ramp to the frames it scores.

### 2.2 Guards

1. **Film mean, every branch.** No reference film's `mean_ssim_scored` falls by more than 0.002 on the evidence-backed track, or by 0.002 or more on the heuristic track (Q17).
2. **Per frame (Q35).**
   - Heuristic track: no scored frame of any reference film falls by more than **0.010**, target frames included.
   - Evidence-backed track: no hard bound. Every frame that falls by more than 0.005 is listed, the worst per film is pictured (§ 4.2), and the journal entry explains the falls. An example of such an explanation is #429's: the camera sits a few pixels off, so correct trees land on the wrong pixels ([journal](../426_intro-conifers/journal.md)).
3. **Lost frames, every branch (Q37).** The variant is rejected when:
   - a tick the baseline scores is missing or unscored in the variant; or
   - any of the variant's films fails.

   A failed baseline film means the sweep gives no verdict.

**How every bound is measured.**
- Each bound is a difference in whole-frame SSIM: the candidate's `per_frame[].ssim` minus the baseline's, taken over the film ticks the baseline scores.
- A tick captured more than once (`CTRY`'s end hold) counts once, by its first frame, as `--compare` does ([`method.md`](../../../research/parity/method.md) § 5) (S3).
- Comparisons use unrounded values (Q39).

### 2.3 Target frames

- **Target frames** are the scored frames a round names before its sweep, as ranges of film ticks per film, as showing the defect it addresses (Q1, Q5; [`GLOSSARY.md`](../../../GLOSSARY.md) **Target frames**).
- The journal entry quotes the sweep's `--target` flags before the sweep runs (Q8). The sweep echoes them on stdout, so the quote can be checked (Q39).
- A film the round does not target is judged by the guards alone (Q10).
- Frames the candidate changes outside the target are side effects. The sweep reports how many there are per film (Q1).

## 3. `mise run sweep`

Changes to [`python/scripts/parity_sweep.py`](../../../python/scripts/parity_sweep.py). The target logic lives only here, the tool that ends every round (Q23).

### 3.1 New options

- `--target <film>:<lo>-<hi>`, repeatable. It names an inclusive range of film ticks on one reference film. `<film>` is a short name `--films` accepts, and a film may have several ranges (Q8).
- `--track evidence|heuristic`, the round's track. It is required with `--target`. With `--track` alone, the winner line judges the film-mean branch. With neither flag, the sweep prints guard results and no verdict.
- `--images <dir>` and `--topic <words>` write the pictures of § 4 into `<dir>`, normally `work/<YYYY-MM>/<folder>/images`. The two are required together, and `--images` requires `--target` (Q27).
- `--crop x0,y0,x1,y1` crops every picture to that box, enlarged 3 times. The scale is a choice made here; `mise run frame` takes `--scale`, default 1. Without `--crop`, pictures show the whole 320x200 frame (Q12).

### 3.2 Baseline

- The **baseline** is the variant whose value for each `--var` is the first value listed: in `--var DBG_X=0,1`, `DBG_X=0` (S1).
- `--target` and `--track` refuse:
  - a `--films` subset, since the guards cover every reference film (S2);
  - `--reuse`, which has no `--var` and so no baseline (S4);
  - a sweep of a single variant, which has nothing to compare (Q30).
- `--retime` is allowed, because it relabels every variant, the baseline included.

### 3.3 Judging after every variant

- Variants finish in completion order, not listed order (`on_variant`, `parity_sweep.py`), so the baseline may finish last.
- The sweep therefore holds each variant's per-frame scores in memory: SSIM and index agreement, by film and tick. It deletes render directories as it does today.
- It judges once every variant has finished (Q39).
- `--keep-best` keeps the winner under the new ranking.

### 3.4 Output

- **Ranking.** Variants that adopt rank first. Within each group, the order is target mean (with `--target`), then mean film SSIM. The baseline is listed but never wins (Q39, S6).
- **Table.** Each variant's row gains columns for:
  - the target mean Δ in SSIM and in index agreement (with `--target`);
  - the largest per-frame fall;
  - the count of frames down by more than 0.005.
- **Winner line.** It names the branch the winner adopts on, or the guard or test it fails, for the declared track. Examples:
  - `winner: DBG_X=1 adopts (heuristic target +0.0213, 18/24 frames up; films ok; worst frame -0.0041 intro:3302)`
  - `winner: DBG_X=1 adopts (evidence, film means; target +0.0071 attribution; 3 frames down >0.005, listed)`
  - `winner: none adopts (best DBG_X=1: frame guard land:812 -0.0137)`

  The existing 0.002 note on a winner's lead over the runner-up stays.
- **Stderr.** One line lists every frame down by more than 0.005. Another counts, per film, the frames outside the target that moved by more than 0.005.

## 4. Pictures

### 4.1 What a picture is

- One PNG per chosen tick: the capture, the baseline and the winner, left to right, with `mise run frame`'s magenta divider (Q12).
- **Drawing.** After judging, the sweep re-renders only the chosen ticks of the baseline and the winner with `--at-ticks`, as `mise run frame --var` does. It draws them with `parity_probe.make_strip` (Q39).
- **Naming.** The path is `<dir>/<film>-<tick>-<topic>.png`, following [`work/README.md`](../../README.md#images). `<film>` is the short name, and `<topic>` comes from `--topic` (S5).
- **Which rounds.** Pictures show the winner against the baseline only (Q24). A round that is not adopted commits them too (Q13).
- **Citing.** The journal entry cites every picture and names the commit each render panel came from, as `work/README.md` § Images asks.
- **No overwrites.** The sweep refuses, before rendering, when any path it would write already exists (S5).

### 4.2 Which ticks

For each film with target frames, the sweep picks up to **5** ticks (Q11, Q20, Q25, Q38):
1. First, the target frame with the lowest Δ, its biggest fall or smallest rise, so the set is not only best cases.
2. Then the target frames in descending Δ, each taken only if it lies at least **N = 50** ticks from every tick already chosen.
3. If fewer than 5 are chosen, the sweep halves N to **25** and goes down the list again. It never goes below 25 ticks, about two captured frames, so a film may get fewer than 5.

**Guard pictures.** Outside that cap, each reference film whose worst frame fell by more than 0.005 gets one picture of that frame, named `<film>-<tick>-<topic>-guard.png` (Q21).

## 5. Documents

| File | Change |
|---|---|
| [`loop-rules.md`](../../../.agents/skills/improving-render-parity/loop-rules.md) | § 2's rule, with the figures § 1 settles, replaces **Adoption rule**. The goal contract says a round may name target frames. |
| [`SKILL.md`](../../../.agents/skills/improving-render-parity/SKILL.md) | New steps: name the target frames and write the `--target` flags in the journal before step 4 (PR 1); commit the pictures with the journal entry in step 7 (PR 2). |
| [`pr-evidence.md`](../../../.agents/skills/improving-render-parity/pr-evidence.md) | A targeted round's PR attaches its committed pictures under **Evidence** in place of step 3's renders. A change with no target frames keeps today's steps (Q28). |
| [`evidence-limits.md`](../../../research/parity/evidence-limits.md) | The policy-bound item adds the settled bounds, the 3-frame minimum, and the spike that chose them. |
| [`metric-bench.md`](../../../research/parity/metric-bench.md) | If the spike makes index agreement part of the target test, the note records why. |
| [`docs/howto/score-a-render-change.md`](../../../docs/howto/score-a-render-change.md) | The sweep's new options, and how to read the winner line. |
| [`mise.toml`](../../../mise.toml) | The `sweep` task's description lists the new options. |
| [`NOTICE.md`](../../../NOTICE.md) | Delete the sentence that lists the current image sets ("The current sets are …"). The limits stay word for word (Q31). |
| [`GLOSSARY.md`](../../../GLOSSARY.md) | **Target frames** is added with this spec, and **Adoption** and **Sweep** now name every reference film. PR 1 adds the target branch and per-frame guard to **Adoption**. |

The `NOTICE.md`, `research/` and `docs/` changes get the fresh-reviewer pass of [`AGENTS.md`](../../../AGENTS.md#committing) § Committing, rule 5.

## 6. Testing

All offline, on synthetic data, in [`tests/test_parity_sweep.py`](../../../tests/test_parity_sweep.py):

- **Target test and guards.** Pure functions over two variants' per-frame scores. Cover:
  - each bound, either side;
  - the pooled mean and the per-film condition over two films;
  - the majority condition;
  - the 3-frame minimum;
  - a tick captured twice;
  - a tick scored in the baseline only, which rejects;
  - a failed variant film, which rejects;
  - a failed baseline film, which gives no verdict;
  - each track.
- **The join against `--compare`.** On a synthetic report pair, the sweep's per-frame join reproduces `compare.json`'s `common_frames` and its counts of frames that rose or fell by more than 0.005 (Q39).
- **Ranking.**
  - A variant that adopts ranks above one that does not, whatever its target mean.
  - The baseline never wins, and `winner: none adopts` prints when nothing adopts.
  - Completion order does not change the result.
- **Option checks.**
  - `--target` and `--track` refuse a `--films` subset, `--reuse`, a single variant and an unknown film, and accept `--retime`.
  - `--images` refuses without `--target` or `--topic`, and refuses an existing path.
- **Tick choice.**
  - The lowest-Δ frame comes first.
  - Picks keep the 50-tick spacing, then 25, and never closer.
  - Guard pictures fall outside the cap.
- **Picture layout.** Drawing a synthetic capture beside two synthetic renders gives the expected panel order, width, divider and file name.

No GPU run is needed for the tests. The spike (§ 1) is the check on the bounds. The first targeted round after both PRs land is the field test of the pictures, and its journal entry says so.

## 7. Delivery

1. **Spike:** § 1, one journal entry. Its results go to the user, who settles § 1.3 before PR 1 starts.
2. **PR 1, the verdict:** § 2 with the settled figures, and § 3 except `--images`, `--topic` and `--crop`. Their tests come with it, and so do the `loop-rules.md`, `evidence-limits.md`, how-to, `mise.toml` and `GLOSSARY.md` changes and `SKILL.md`'s target-frames step. Also `metric-bench.md`, if the spike makes it needed.
3. **PR 2, the pictures:** § 4, the remaining options and their tests, `SKILL.md`'s pictures step, and the `pr-evidence.md` and `NOTICE.md` rows. The how-to and `mise.toml` gain the picture options.

PR 2 finishes the item: it writes this folder's README `outcome` and closes #440.

## Decisions

Q1 to Q31 were settled by grilling on 2026-11-12, and Q32 to Q39 the same day after a review. S1 to S7 are calls made while writing the spec against the code. "Revised by" marks a decision a later one changed.

| # | Decision |
|---|---|
| Q1 | Target frames are named before the sweep; changed frames outside them are reported as side effects. |
| Q2 | Guards: the film mean, plus a per-frame guard (extended by Q7, revised by Q35). |
| Q3 | The target branch is added to the film-mean branches; it does not replace them. Revised by Q34: heuristic track only. |
| Q4 | Open to both tracks, the heuristic one with the stricter bar. Revised by Q34. |
| Q5 | The term is **target frames**. Avoid *bug frames*, *affected frames* and *segment*. |
| Q6 | The target test is the mean whole-frame SSIM over the target frames, and the changed-window verdict stays a diagnostic. Q33 leaves the metric open until the spike. |
| Q7 | The per-frame guard uses whole-frame per-frame Δ on every scored frame, target frames included. |
| Q8 | Target frames are a repeatable sweep flag, quoted in the journal before the sweep. |
| Q9 | `references.toml` is unchanged. |
| Q10 | Films the round does not target are judged by the guards alone. |
| Q11 | At most 5 pictures per targeted film per round, spread out. `NOTICE.md`'s limits are unchanged. |
| Q12 | One composite per tick (capture, before, after), native size or a 3x crop, made by the tool. |
| Q13 | Rounds that are not adopted commit their pictures too. |
| Q14 | Evidence-backed target bar +0.005. Revised by Q34: no evidence-backed target branch. |
| Q15 | Heuristic target bar +0.010, provisional until the spike. |
| Q16 | Per-frame hard bound 0.010; falls from 0.005 to 0.010 are listed and the worst is pictured. Revised by Q35: hard on the heuristic track only. |
| Q17 | The film-mean guard is unchanged. |
| Q18, Q19 | No "shot" term. Pictures are spaced by ticks instead. |
| Q20 | Tick choice: the lowest-Δ target frame first, then the largest-Δ frames, spaced apart. |
| Q21 | Each film's worst fall above 0.005 gets one picture, outside the cap. |
| Q22 | With targets, variants rank by target mean, and the winner line carries the verdict. Refined by Q39: adopting variants rank first. |
| Q23 | Target logic lives in the sweep only, not in `stuntreel parity`. |
| Q24 | Pictures show the winner against the baseline only. |
| Q25 | Spacing is 50 ticks, halved when too few are chosen. Bounded by Q38. |
| Q26 | The target branch needs at least 3 scored target frames, provisional until the spike. |
| Q27 | The sweep writes pictures straight into the work folder given by `--images`. |
| Q28 | A PR from a targeted round attaches the committed pictures. |
| Q29 | The per-frame guard applies to every branch. Refined by Q35. |
| Q30 | A sweep judged against a baseline needs at least two variants; S1 makes the baseline one of them. |
| Q31 | `NOTICE.md` drops its list of image sets. |
| Q32 | A spike rescores known adoptions, known rejections and one SSIM-raising fault before any rule is written. Its results settle the metric and the bounds. |
| Q33 | Index agreement is printed beside SSIM on target frames. Whether it counts toward adoption waits for the spike. |
| Q34 | The target branch is heuristic-only. On the evidence-backed track the target mean is attribution. |
| Q35 | The per-frame bound is hard on the heuristic track. On the evidence-backed track, falls above 0.005 are listed, pictured and explained in the journal. |
| Q36 | Heuristic target branch: each targeted film's target mean rises, and most target frames rise, as well as the pooled bar. |
| Q37 | A tick lost from the baseline's scored set, or a failed variant film, rejects the variant. A failed baseline film gives no verdict. |
| Q38 | 5 pictures per targeted film; spacing never below 25 ticks. |
| Q39 | Judge after every variant finishes, from per-frame scores held in memory. Re-render the chosen ticks for pictures. Adopting variants rank first, and `winner: none adopts` prints when none does. Echo `--target` on stdout. Test the join against `compare.json`. Compare unrounded values. |
| S1 | The baseline is each `--var`'s first listed value, so no new flag is needed. |
| S2 | `--target` and `--track` refuse a `--films` subset, because the guards cover every reference film. |
| S3 | Per-frame Δ is taken over the ticks the baseline scores, a repeated tick counting once by its first frame. Tightened by Q37. |
| S4 | `--target` refuses `--reuse`, which has no baseline; `--retime` is allowed. |
| S5 | Picture names follow `work/README.md`'s `<film>-<tick>-<topic>.png`, and an existing picture is never overwritten. |
| S6 | Variants that adopt rank above those that do not (folded into Q39). |
| S7 | Replaced by Q32: the retrospective check became the spike. |
