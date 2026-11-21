# Class Agreement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let every render PR merge on lavapipe, and measure lavapipe-against-GPU agreement in unattended batches with its own pinned figures and its own issues.

**Architecture:** A comparison spike first chooses the canonical lavapipe build.
A library module, `stunt_reel/class_agreement.py`, holds the residue counting that `parity_residue.py` does today, plus the agreement figures, their file, the flags and the due rule.
A script, `parity_agreement.py` (`mise run agreement`), renders on both renderer classes, measures, pins and posts.
The drift line, the sweep and the queue read the pinned figures.
An ADR and the docs then retire the GPU hold, and a first batch pins the baseline.

**Tech Stack:** Python 3 (`tomllib`, `tomli_w` per ADR 0049, pytest), `gh` (REST), Windows Task Scheduler and WSL 2 on local-windows, GitHub Actions.

**Spec:** [`spec.md`](spec.md) in this folder; read it before Task 1.

## Global Constraints

- Thresholds, as named constants in `class_agreement.py`: `HOT_TICK_PIXELS = 500`, `TICK_FLAG_PIXELS = 1000`, `MEAN_RISE_RATIO = 0.25`, `MEAN_RISE_MIN = 1.0`, `SSIM_GAP_LIMIT = 0.002`, `DUE_COMMITS = 5`, `DUE_DAYS = 7`.
- File: `research/parity/expected/agreement.toml`, generated, with a fixed header saying `mise run agreement -- pin` writes it and nobody edits it; `[measured]` (`crates`, `date`, `gpu_adapter`, `gpu_driver`, `lavapipe_adapter`, `lavapipe_driver`, and `accepted` when a pin was accepted over flags), then `[<film>]` (`ticks`, `differing_ticks`, `mean`, `largest`, `largest_tick`) and `[<film>.hot]` (tick as a string key, count as an integer), films in `references.toml` row order, means to 2 decimals, LF, trailing newline.
- `gpu.toml` is written only by the batch, through `mise run parity-repin -- --class gpu`.
- Label `class-agreement`; standing issue title `Class agreement batch`; flag issue titles `Agreement: <film> ticks <first>-<last>` for a tick flag, `Agreement: <film> mean` and `Agreement: <film> ssim gap` for the other two.
- The batch renders `origin/main` in its own worktree, `.agents/worktrees/agreement`, made per the `managing-worktrees` skill, and never the primary checkout.
- New ADR number: 0055.
- Run tasks through `mise run`; a one-off is `mise exec -- uv run …`.
- Markdown puts each sentence on its own line; docstrings state the caller's contract in the fewest words.
- Commit subjects are Conventional Commits; stage paths by name; `mise run check` passes before each commit.
- A push changing `research/` or `docs/*.md` gets a fresh reviewer first (AGENTS.md § Committing rule 5).

## Review Focus

1. A batch started while another parity run renders on local-windows, where two full renders at once compete for the GPU and CPU and slow both: it should skip with a line saying why, not render.
2. A driver update on either side, which the adapter name alone does not show: no flags, no pin, and a line naming both adapters, both drivers and `--accept`.
3. A render that fails for one film leaves the two stores' tick sets different: the batch exits non-zero and pins nothing.
4. `agreement.toml` missing or holding no film the sweep scores: the sweep prints no hot-tick line and its verdict is unchanged.
5. The nightly job runs twice on one tree, or a flag recurs: one comment per measured tree, and no second issue for a film and tick range an open `class-agreement` issue already covers.

---

### Task 1: Spike: compare lavapipe builds for speed and pixels

Rescopes #877 (Task 8 edits it first).
Runs on local-windows through Remote Control, plus one cloud session with the corpus (the `stunt-reel-cloud` environment).
No renderer change, no repin.

**Files:**
- Modify: `python/scripts/parity_residue.py` (two flags below)
- Test: `tests/test_parity_residue.py`
- Create: `work/2026-11/908_backend-agreement/journal.md`
- Modify: `research/parity/lavapipe.md` (a new section, per the `recording-findings` skill)

**Interfaces:**
- Produces: `parity_residue.py --write-hashes FILE` (one line per tick, `<film> <tick> <sha256 of the index plane>`, for the films of the left root) and `--against-hashes FILE` (in place of the right root: per film, ticks compared and ticks differing; exit 1 on differing tick sets, as today).
  This lets two machines compare stores without moving them.

- [ ] **Step 1: Write the failing tests**

`test_write_hashes_lists_every_tick_of_every_film` (two synthetic stores, the file has one line per film tick, sorted by film then tick); `test_against_hashes_counts_ticks_that_differ` (one plane changed: `differing == 1`); `test_against_hashes_refuses_other_tick_sets` (exit 1).

- [ ] **Step 2: Run them to see them fail**

Run: `mise run test-py -- tests/test_parity_residue.py`
Expected: the three new tests FAIL (unknown flags).

- [ ] **Step 3: Implement both flags in `parity_residue.py`, then run the tests to see them pass**

- [ ] **Step 4: Commit**

`feat(parity): compare render stores across machines by tick hash (#908)`

- [ ] **Step 5: Run the builds on one `crates` tree**

On `origin/main` at the spike's start, `--no-build` after one release build, seven reference films each:

| Arm | Where | Build |
|---|---|---|
| A | local-windows | RTX 4070 |
| B | local-windows | mesa-dist-win 25.2.8 (`--software-only`, [`render-on-lavapipe.md`](../../../docs/howto/render-on-lavapipe.md)) |
| C | local-windows, WSL 2 Ubuntu 24.04 | `mesa-vulkan-drivers` at the cloud's exact version (`apt-cache policy` in the cloud names it), data root made as a cloud session makes it (`mise run cloud-assets -- fetch`, `mise run game-builds`, `mise run superset-all`) in the WSL filesystem |
| D | cloud session | the same package |

Record each arm's wall time for a whole `mise run parity` and per film, its adapter string, and its `[parity]` lines.
For C, also time one film with the data root read from `/mnt/e` instead, to say whether the copy matters.

- [ ] **Step 6: Compare**

`mise run parity-residue` for A-B, A-C, B-C on local-windows: per film, ticks differing, mean and largest per tick.
`--write-hashes` in D, `--against-hashes` against it for B and C: per film, ticks differing only, since the planes stay on their machines.
And every pair's score differences.

- [ ] **Step 7: Recommend the canonical build**

The rule the journal applies: the canonical build is one that local-windows and the cloud both run with no tick differing on any film; among those, the faster on local-windows.
If C matches D, recommend pinning that package; if none matches, recommend keeping D canonical and #830, with #877's custom Linux build named as the follow-up if B's speed matters.
The owner decides; the decision goes in the journal entry's **Verdict** and in Task 5.

- [ ] **Step 8: Record and open the spike PR**

Journal entry (Question, Method, Result, Verdict, Lives in), the finding in `lavapipe.md`, fresh review, `docs(research): compare lavapipe builds for the canonical renderer (#908)`.

---

### Task 2: The agreement library

**Files:**
- Create: `python/stunt_reel/class_agreement.py`
- Modify: `python/scripts/parity_residue.py` (imports `Residue`, `differing_pixels`, `film_stores`, `compare`, `CURRENT_SUFFIX` and `_NONZERO` from the library; behaviour unchanged)
- Test: `tests/test_class_agreement.py`; `tests/test_parity_residue.py` unchanged and passing

**Interfaces:**
- Produces:
  - `Residue` (moved unchanged), `differing_pixels`, `film_stores`, `compare` (moved unchanged).
  - `@dataclass(frozen=True) class FilmAgreement: film: str; ticks: int; differing_ticks: int; mean: float; largest: int; largest_tick: int; hot: dict[int, int]`, with `FilmAgreement.from_residue(residue: Residue) -> FilmAgreement`.
  - `@dataclass(frozen=True) class Agreement: crates: str; date: datetime.date; gpu_adapter: str; gpu_driver: str; lavapipe_adapter: str; lavapipe_driver: str; films: dict[str, FilmAgreement]; accepted: str | None = None`.
  - `read_agreement(path: Path) -> Agreement | None` (`None` when the file is absent); `format_agreement(agreement: Agreement, order: list[str]) -> str`.
  - `@dataclass(frozen=True) class Flag: film: str; reason: str; ticks: tuple[int, ...]`.
  - `flags(pinned: Agreement | None, measured: Agreement, ssim_gaps: dict[str, float]) -> list[Flag] | str` (a `str` when nothing is pinned or an adapter or driver differs: the reason no flags were computed); a tick flag's `ticks` holds the flagged ticks, the other two flags' are empty.
  - `renderer_commits_since(tree: str, *, rev: str = "origin/main", repo: Path = REPO_ROOT) -> list[str] | None` (first-parent commits after the first one whose `crates` tree is *tree*, whose own change `expected_scores.renderer_changes` reports non-empty; `None` when no commit has that tree).
  - `due(pinned: Agreement | None, commits: list[str] | None, today: datetime.date) -> str | None` (the reason a batch is due, or `None`).

- [ ] **Step 1: Write the failing tests**

- `test_from_residue_keeps_ticks_over_hot_threshold`: counts `[0, 501, 500, 1200]` at ticks `[1, 2, 3, 4]` give `hot == {2: 501, 4: 1200}`, `differing_ticks == 3`, `largest == 1200`, `largest_tick == 4`.
- `test_format_then_read_round_trips` and `test_format_is_stable` (fixed bytes for a two-film fixture, films in the given order, means to 2 decimals).
- `test_read_agreement_absent_is_none`.
- `test_mean_rise_flags_only_above_ratio_and_minimum`: 4.0 to 5.1 flags; 8.0 to 9.5 does not (a rise of 1.5, 18.75%: under the ratio only); 0.5 to 1.2 does not (140%, but under `MEAN_RISE_MIN` only).
- `test_tick_rise_flags_against_pinned_or_hot_threshold`: pinned hot `{10: 800}`; measured `{10: 1700, 20: 1400}` flags neither (each 900 over its base, tick 20's base being `HOT_TICK_PIXELS`); measured `{10: 1900, 20: 1600}` flags both.
- `test_ssim_gap_flags_above_limit`: gap `-0.0021` flags, `0.0019` does not.
- `test_changed_adapter_gives_reason_not_flags` and `test_changed_driver_gives_reason_not_flags`: each returns a `str` naming both sides and `--accept`; `test_nothing_pinned_gives_reason_not_flags`.
- `test_due_after_five_renderer_commits` and `test_due_after_seven_days_with_one_commit`; `test_not_due_without_renderer_commits`; `test_due_when_nothing_pinned`.
- `test_renderer_commits_since_skips_scorer_only_commits` (a scratch repository, as `tests/test_expected_scores.py` builds one).

- [ ] **Step 2: Run them to see them fail**

Run: `mise run test-py -- tests/test_class_agreement.py`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `class_agreement.py` and move the residue helpers**

Write with `tomli_w`; read with `tomllib`.
It imports `expected_scores` (for `renderer_changes`), so it sits in the layer above it, beside the other `parity_*` modules; `expected_scores` does not import it. `mise run check-py` runs tach (ADR 0050).

- [ ] **Step 4: Run the new tests and `tests/test_parity_residue.py`, expect PASS**

- [ ] **Step 5: Commit**

`feat(parity): agreement figures, flags and due rule (#908)`

---

### Task 3: `mise run agreement`

**Files:**
- Create: `python/scripts/parity_agreement.py`
- Modify: `python/stunt_reel/process_tree.py` (`stuntreel_running() -> bool`: whether any process whose image is `stuntreel` or `stuntreel.exe` runs; it only spawns, kills and waits today)
- Modify: `mise.toml` (task `agreement`, `depends = ["ensure"]`, the `CARGO_HOME` env as `parity` has)
- Test: `tests/test_parity_agreement.py`

**Interfaces:**
- Consumes: Task 2's API; `parity_run.py`'s CLI; `parity_repin.py`'s CLI.
- Produces subcommands:
  - `measure --gpu ROOT --lavapipe ROOT`: each ROOT holds `ours/` and `report/` trees of `<film>_current` directories, as `build/parity/` does; prints the residue table, each film's SSIM gap from the two reports, then one line per flag or the reason no flags were computed; exit 0, 1 on a residue failure.
  - `pin [--accept REASON]`: refuses with flags, or with a reason in place of flags, unless `--accept`; then writes `agreement.toml` from the last `measure` (kept as `build/agreement/measured.toml`, the reason in `accepted`), runs `mise run parity-repin -- --class gpu`, and commits both on a branch `chore/agreement-<date>` with a PR `chore(parity): repin class agreement`.
  - `batch [--if-due] [--post]`: in `.agents/worktrees/agreement` detached at `origin/main`, runs the lavapipe arm first and the GPU second, so `build/parity/report/` holds the GPU reports the `gpu` repin reads; after each, copies `build/parity/ours/` and `build/parity/report/` to `build/agreement/<arm>/`; then `measure`, and with no flags `pin`.
    It records each side's driver with `driver_versions() -> tuple[str, str]`: `nvidia-smi --query-gpu=driver_version --format=csv,noheader` for the GPU, and for lavapipe the installed package's version (`dpkg-query -W -f '${Version}' mesa-vulkan-drivers`, or the mesa-dist-win version `render-on-lavapipe.md` installs).
    The lavapipe arm's command is `--lavapipe-command` (default `mise run parity -- --software-only`), so Task 7 can point it at the build Task 1 chose, WSL included.
    `--if-due` exits 0 with a line when `due` is `None`, or when `stuntreel_running()`.
    `--post` comments on the standing issue (skipped when a comment already names this `crates` tree) and files one issue per flag not covered by an open `class-agreement` issue of the same film whose title's tick range overlaps.

- [ ] **Step 1: Write the failing tests**

With `parity_run`, `gh` and git stubbed through injected callables:
`test_measure_prints_flags_and_gaps`; `test_pin_refuses_flags_without_accept`; `test_pin_with_accept_records_reason_and_repins_gpu`; `test_batch_runs_lavapipe_before_gpu`; `test_stuntreel_running` (in `tests/test_process_tree.py`, with a spawned dummy named process or a stubbed process list); `test_batch_if_due_skips_when_not_due`; `test_batch_if_due_skips_while_stuntreel_runs`; `test_batch_pins_nothing_when_tick_sets_differ`; `test_post_comments_once_per_tree`; `test_post_skips_flag_an_open_issue_covers`.

- [ ] **Step 2: Run them to see them fail**

Run: `mise run test-py -- tests/test_parity_agreement.py`

- [ ] **Step 3: Implement, then run the tests to see them pass**

- [ ] **Step 4: Commit**

`feat(parity): mise run agreement measures, pins and posts the class agreement batch (#908)`

---

### Task 4: Readers of the pinned figures

**Files:**
- Modify: `python/stunt_reel/expected_scores.py:186` (the lagging-tree wording for class `gpu`)
- Modify: `python/scripts/parity_sweep.py` (the hot-tick line)
- Modify: `python/scripts/work_queue.py` (the due line)
- Test: `tests/test_expected_scores.py`, `tests/test_parity_sweep.py`, `tests/test_work_queue.py`

**Interfaces:**
- Consumes: `read_agreement`, `renderer_commits_since`, `due`.
- Produces: `hot_share(deltas: dict[int, float], hot: dict[int, int]) -> float | None` in `class_agreement.py` (the share of the positive SSIM change on hot ticks; `None` with no positive change).

- [ ] **Step 1: Write the failing tests**

- `test_gpu_lag_says_awaiting_agreement_batch`: a `gpu` entry on another tree reads `awaiting the next agreement batch`; a `lavapipe` one keeps `awaiting a repin or catch-up repin of this class`.
- `test_hot_share`: deltas `{1: 0.01, 2: 0.03, 3: -0.02}`, hot `{2: 900}` give `0.75`; no positive delta gives `None`.
- `test_sweep_prints_hot_line_over_half` (stderr names the film and `check it on the GPU`); `test_sweep_without_agreement_file_prints_no_hot_line`.
- `test_queue_prints_due_line` and `test_queue_prints_nothing_when_not_due`.

- [ ] **Step 2: Run them to see them fail**

- [ ] **Step 3: Implement**

The sweep prints the line on stderr where it lists frames falling by more than 0.005, once per film with a share over 0.5; the verdict and the figures file are unchanged.
The queue's line reads `agreement batch due: <reason>` and is printed in both environments.

- [ ] **Step 4: Run the touched test files, expect PASS; then commit**

`feat(parity): drift line, sweep and queue read the agreement figures (#908)`

---

### Task 5: Pin the canonical lavapipe package

Depends on Task 1's decision; skip it if the owner keeps the unpinned package.

**Files:**
- Modify: `.github/workflows/ci.yml:110` and `:205` (`mesa-vulkan-drivers=<version> libvulkan1`, and `runs-on: ubuntu-24.04` in place of `ubuntu-latest` for those jobs, so the image cannot move the package's release under the pin)
- Modify: `.claude/cloud-setup.sh:111-117` (the `dpkg -s` guard skips the install when any version is present: compare `dpkg-query -W -f '${Version}' mesa-vulkan-drivers` with the pin instead)
- Modify: `docs/cloud-sessions.md` (the version), `docs/howto/render-on-lavapipe.md` (the WSL arm, if chosen)

Ubuntu's archive drops a superseded version; when that happens the pin fails loudly at install, and the fix is a repin of the package (with a fresh batch), or `snapshot.ubuntu.com` if the owner wants to keep the old one.

- [ ] **Step 1: Pin the version Task 1 names, and add a CI step after the install printing `dpkg-query -W mesa-vulkan-drivers`; push and read that line in both jobs**
- [ ] **Step 2: Commit**

`ci: pin the canonical lavapipe package (#908)`

---

### Task 6: ADR 0055 and the docs

**Files:**
- Create: `docs/adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md` (amends ADR 0053's "Each PR repins only the class it measured": no PR repins `gpu`; ADR 0006 and 0054 stand)
- Modify: `.agents/skills/working-in-an-environment/cloud.md` § Rendering (the hold goes; one paragraph on the hot-tick line)
- Modify: `docs/agents/triage-labels.md` (the `local-only` row loses the GPU check and pixel-level work; `class-agreement` under category roles)
- Modify: `.agents/skills/improving-render-parity/loop-rules.md` § After adopting and `SKILL.md` (verdicts on either renderer class; pins on lavapipe; `gpu` from the batch)
- Modify: `.agents/skills/running-unattended/pr-and-filing.md` step 5 (no `local-only` PRs for the GPU), `loop-and-bounds.md` line 32 (no `local-only` PR left for the GPU check) and Shutdown step 2 (no `gpu` repin at shutdown; #830's comment only while #830 stays)
- Modify: `python/stunt_reel/expected_file.py:42-43` (the generated header: `gpu.toml` is written by the agreement batch)
- Modify: `docs/howto/score-a-render-change.md` (repin section), `research/parity/method.md` (line 23 and wherever else it names the GPU class), `docs/howto/render-on-lavapipe.md:79`, `research/parity/lavapipe.md` § 4 (the "stand in for GPU rows" wording becomes the agreement measure), `GLOSSARY.md` (`class agreement`, `hot tick`; `Renderer class` keeps its _Avoid_: backend, which is why the measure is not called backend agreement)
- Create: `docs/howto/run-the-agreement-batch.md` (the worktree, the command, `--accept`, and the scheduled task: `schtasks /Create /SC DAILY /ST 03:00 /TN stunt-reel-agreement /TR "<pwsh command running mise run agreement -- batch --if-due --post in the primary checkout>"`)

- [ ] **Step 1: Write the ADR (Status, Context, Decision, Considered Options: keep the hold; drop `gpu.toml` entirely; a path-based `gpu-pending` label; Consequences)**
- [ ] **Step 2: Edit each file above; `rg -l '<file base name>' site/guides/` for each and fix any guide the change makes false**
- [ ] **Step 3: `mise run check`; fresh review per AGENTS.md rule 5; commit**

`docs(adr): pin fidelity on lavapipe and measure class agreement apart (#908)`

- [ ] **Step 4: Open the PR for Tasks 2 to 6 (or 2 to 4 and 6 when Task 5 waits), as a `gh stack` from Task 1's branch if Task 1 is still open**

---

### Task 7: The first batch and the schedule

Runs on local-windows through Remote Control after Task 6's PR merges.

- [ ] **Step 1: Create the label `class-agreement` and the standing issue `Class agreement batch` (`local-only`, `ready-for-agent`, body: the howto's command and this folder)**
- [ ] **Step 2: `mise run agreement -- batch` without `--post`; with nothing pinned it computes no flags and pins nothing, so pin it with `mise run agreement -- pin --accept "first baseline"`**
- [ ] **Step 3: Compare the baseline's per-film means with the "After (`Depth24Plus`)" column of `lavapipe.md` § 5's reversed-depth table (#637); a film off by more than 10% gets a sentence in the journal, since that table used mesa-dist-win 25.2.8 and the baseline may not**
- [ ] **Step 4: Register the scheduled task from the howto; confirm it with `schtasks /Query /TN stunt-reel-agreement`**
- [ ] **Step 5: Journal entry; the baseline PR `chore(parity): repin class agreement`; write the README `outcome`**

---

### Task 8: Existing issues

Edits made through `gh api` (REST), each with a one-line comment naming #908.

- [ ] **At plan approval:**
  - **#877**: retitle `Spike: compare lavapipe builds for the canonical renderer (speed and pixels)` and replace its body with Task 1's table and decision rule; it stays `local-only`, `ready-for-agent`.
  - **#639**: becomes the `class-agreement` parent: label it, update its checklist (#635 and #636 done; #637 landed in `Depth24Plus`; #638 re-measured from the first batch's hot ticks).
  - **#637**, **#638**: add `class-agreement`.
  - **#649**: comment that Task 1 shares its tooling (`--write-hashes`) and covers its 25.2.8 arm; it keeps the 26.2.6 arm.
- [ ] **After Task 1's decision:**
  - **#830**: close as completed when local-windows can run the canonical build (its catch-ups become ordinary repins); otherwise rewrite it for the lavapipe class only, dropping the GPU wording.
  - **#806**: retitle to install the canonical build on Antigravity, or close if Task 5 makes cloud-setup install it there too.
- [ ] **After Task 6 merges:**
  - Any open PR labelled `local-only` only for the GPU check: remove the label and arm it as any lavapipe-judged PR.
  - **#905** and other PRs that repinned `gpu.toml` before the ADR merge as they are; their `gpu` numbers are rewritten by the first batch.
- [ ] **Unchanged:** #840, #826, #835, #622 and #509 are `local-only` for reasons other than the GPU check.
