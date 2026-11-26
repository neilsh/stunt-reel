# Journal

## 2026-11-26: splitting the readout change into render and grader

**Question.**
The 2026-11-26 baseline (`6486fb67`) replaced the 2026-11-25 one (`e09f8ff6`) with a new render (#1096, #1099) and a new fast grader (DSH to Haiku) together.
How much of each category's change belongs to the render and how much to the grader?

**Method.**
`MAIN=c2b23b4b` (`origin/main` on 2026-11-26).
The `e09f8ff6` baseline's lavapipe render (`crates/` tree `4b5c69c9`, kept in the WSL clone) was re-made into sheets on `MAIN` and graded again with the current grader, so the sheets differ from `e09f8ff6`'s only in who graded them.

1. Preflight in WSL: saved the clone's uncommitted `research/parity/expected/lavapipe.toml` diff, copied both renders to `/root/1118-stores/{e09f8ff6,6486fb67}` and read their `crates-tree.txt`.
2. Agreement batch on `MAIN`: `mise run agreement -- batch --wsl Ubuntu-24.04`.
   It did not pin: six films flagged a mean-pixels-per-tick change ([`regrade/agreement-batch.txt`](regrade/agreement-batch.txt)), filed as #1125.
3. WSL worktree `git worktree add --detach /root/wt1118 c2b23b4b`; `git diff --stat 6486fb67 HEAD -- python/stunt_reel/bench …` touches only #1120's scoring output.
4. Sheets, per film: `mise run parity-bench -- errors-make --film <f> --seed 1 --render /root/1118-stores/e09f8ff6/ours/<f>_current --report /root/1118-stores/e09f8ff6/report/<f>_current/report.json`.
   All seven `render_digest`s, ticks and `categories_digest` (`5f8b01d6…`) equal `git show 692beeff:research/parity/readouts/baseline.toml` (`regrade/<f>/run.json`).
5. Grading: two Haiku passes per film (`grades.txt`, `grades-2.txt`), `mise run parity-bench -- errors-disputes --film <f>`, and one Sonnet tie-break per disputed sheet set (`grades-tiebreak.txt`).
   Disputed sheets: CTRY 5, INTRO 2, LAND 3, TRAINTNL 5, BOMB 4; BALLOON and LOCATION had none.
6. Scoring: `git show 692beeff:research/parity/readouts/<f>.json > dsh-<f>.json`, then
   `errors-score --film <f> --render /root/1118-stores/e09f8ff6/ours/<f>_current --against dsh-<f>.json` (`score-dsh-<f>.txt`) and
   `… --against research/parity/readouts/<f>.json` (`score-haiku-<f>.txt`; `regraded-<f>.json` is its `readout.json`).
7. Pixel residue between the two renders at the graded ticks: `mise run parity-residue -- --films <f> --ticks <ticks> /root/1118-stores/e09f8ff6/ours /root/1118-stores/6486fb67/ours` (`residue-<f>.txt`).
8. Tabulation: `python regrade/tabulate.py` writes [`regrade/table.md`](regrade/table.md).
   Grader part is re-graded minus DSH, render part is current minus re-graded, both as counts of frames graded 2 or more (`ticks_2plus`).

**Result.**
Totals of `ticks_2plus` over the 19 categories, DSH / re-graded / current:

| film | DSH | re-graded | current |
|---|---|---|---|
| ctry | 1 | 0 | 4 |
| intro | 2 | 4 | 1 |
| land | 4 | 4 | 4 |
| balloon | 0 | 0 | 0 |
| traintnl | 2 | 4 | 3 |
| bomb | 3 | 2 | 2 |
| location | 0 | 0 | 3 |

Non-zero category moves (every other category is 0 in all three columns):

| film | category | DSH | re-graded | current | grader part | render part |
|---|---|---|---|---|---|---|
| ctry | background-misregistration | 1 | 0 | 4 | -1 | +4 |
| intro | background-misregistration | 1 | 3 | 0 | +2 | -3 |
| intro | black-block | 0 | 1 | 0 | +1 | -1 |
| intro | propeller-solid | 1 | 0 | 1 | -1 | +1 |
| land | ground-shade-edges | 1 | 1 | 0 | 0 | -1 |
| land | background-misregistration | 1 | 1 | 2 | 0 | +1 |
| traintnl | background-misregistration | 0 | 2 | 0 | +2 | -2 |
| traintnl | propeller-solid | 2 | 2 | 3 | 0 | +1 |
| bomb | background-misregistration | 3 | 2 | 2 | -1 | 0 |
| location | ground-shade-edges | 0 | 0 | 1 | 0 | +1 |
| location | background-misregistration | 0 | 0 | 2 | 0 | +2 |

LAND's `aircraft-misplaced` and `scenery-missing` stay at 1 in all three columns (`regrade/table.md`).
Grader parts are 2 frames or fewer in every category.
Render parts are 4 frames in CTRY `background-misregistration` (ticks 364, 628, 716 and 804 are the ones the current grading adds), 3 in INTRO `background-misregistration`, and 2 or fewer elsewhere.
`disputed` DSH / re-graded / current: CTRY 1/5/7, INTRO 7/2/3, LAND 4/3/3, BALLOON 0/0/0, TRAINTNL 0/5/2, BOMB 12/4/2, LOCATION 0/0/2.
Residue: every one of the 84 graded ticks (12 per film) differs between the two renders, by 111 to 6031 pixels, so no tick isolates grader noise from render change.
The grader moves were not re-measured with a second re-grade of the `6486fb67` sheets (D5), so the bound used is the 3-frame two-pass figure in [`metric-bench.md` § 2.3](../../../research/parity/metric-bench.md#23-error-categories-graded-by-a-vision-model).
Not copied here: the PNG sheets (game-derived), and any film's files over 200 KB (none was).

**Verdict.**
Adopted as a bounded observation: the baseline stays the 2026-11-26 one.
CTRY's `background-misregistration` render part (+4) is the only move at `min_change` 4.

**Lives in.**
[`batch-vault-films.md` § 7](../../../research/parity/batch-vault-films.md#7-the-patch-3-references-on-todays-renderer) and [`metric-bench.md` § 2.3](../../../research/parity/metric-bench.md#23-error-categories-graded-by-a-vision-model).
