# Journal

## 2026-11-25: The 19-category seven-film readout baseline

**Question**: what does the 19-category error readout see on the seven reference films, and what provenance does the refreshed baseline record?

**Method**:
The 19-category sheets were made at `e09f8ff6`, the `revision` in each `run.json`, from the lavapipe renders of `dd7e76eb` (`crates/` tree `4b5c69c`, the tree `expected/lavapipe.toml` pins).
The seven `report.json` files name `llvmpipe (LLVM 20.1.2, 256 bits)`, class `cpu`.
Each film's 12 real sheets were graded by two DSH passes; Claude Sonnet graded the disputed sheets.
The coordinator identified the models in delegated-task records; the run, grade and readout files name no model.
The grade files are gitignored under `build/parity/bench/`, so recomputation needs this machine's artifacts; the committed readouts are the canonical `errors-score` output.
This branch re-scored the saved passes with the repository's `stunt_reel.bench` functions (`plan_sheets`, `parse_grades`, `disputed`, `merge_grades`, `readout`) and a fresh `planes_digest` of `build/parity/ours/<film>_current`: the seven readouts reproduced byte for byte and the three calibrations passed, 0 failures.
Every readout keeps the committed baseline's 12 ticks and has `missing` 0.

**Result**:
Frames graded 2 or more of the 12 real sheets, the disputed-sheet count, and the render digest:

| Film | Categories graded 2+ (ticks) | Disputed | `render_digest` |
|---|---|---|---|
| `ctry` | `background-misregistration` 1 (804) | 1 | `389a48a6dfb1` |
| `intro` | `background-misregistration` 1 (2773), `propeller-solid` 1 (3301) | 7 | `e3b23e7c6ca7` |
| `land` | `aircraft-misplaced`, `scenery-missing`, `ground-shade-edges`, `background-misregistration` 1 each (419) | 4 | `58bbe9136221` |
| `balloon` | none | 0 | `df2f5109563c` |
| `traintnl` | `propeller-solid` 2 (683, 1123) | 0 | `f2e2183c3304` |
| `bomb` | `background-misregistration` 3 (1585, 1904, 2850) | 12 | `ff52dc31b9e5` |
| `location` | none | 0 | `22714e0712b5` |

BOMB's `background-misregistration` differed across passes: pass 1 graded it 2 on all 12 sheets, pass 2 graded it 0 on 10 and 1 on 2, and the Sonnet tie-break graded it 2 or more at ticks 1585, 1904 and 2850.
The merged readout is the tie-break's 3 with `disputed` 12.
A 12-frame pass-to-pass difference exceeds `min_change` 4, so the four-frame threshold is not a bound for DSH; it was set from two Haiku passes, and a tie-break does not measure repeatability of the saved result.

The previous committed baseline is 18 categories at `b9441a06`, digest `f442f579…`; this one is 19 categories, digest `5f8b01d6…`.
`errors-score` refuses a comparison across different category digests, so the counts above are not paired with the 2026-11-22 counts.
The refresh also changes the renderer build (LLVM 21.1.7 to 20.1.2) and the fast grader (Haiku to DSH), so it is not a taxonomy-only delta.

The three 19-category calibrations re-scored pass: CTRY 6/6 actor removals, 12/12 controls and 16 disputed sheets; INTRO seed 3 6/6, 12/12 and 23; INTRO seed 4 6/6, 11/12 and 25.
The two INTRO runs plant the same six removals, so they repeat graders on those frames rather than sampling other removals.
The 64-pixel actor floor is a convention and does not bear on these seven readouts, which grade the films' real sheets.

**Verdict**: adopted.
These seven readouts and [`baseline.toml`](../../../research/parity/readouts/baseline.toml) are the 19-category baseline.
BOMB `background-misregistration`'s repeatability remains open ([`metric-bench.md` § 2.3](../../../research/parity/metric-bench.md#23-error-categories-graded-by-a-vision-model)).

**Lives in**: [`batch-vault-films.md` § 7](../../../research/parity/batch-vault-films.md#7-the-patch-3-references-on-todays-renderer), [`readouts/baseline.toml`](../../../research/parity/readouts/baseline.toml), [`metric-bench.md` § 2.3](../../../research/parity/metric-bench.md#23-error-categories-graded-by-a-vision-model).
