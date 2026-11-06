# AGENTS.md split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `AGENTS.md` to about 8 KB of rules every task needs, move the procedures only some tasks need into three tested skills under `.agents/skills/`, and make `mise run reap` wait for low disk space.

**Architecture:** First the two pieces of code: the reap gate in `python/scripts/worktree_init.py` and a `skill-eval` task that runs headless `claude -p` dry runs and reports which skills each run loaded. Then the docs restructure. Each skill is written between a baseline evaluation, run without it, and an evaluation run with it. Last, `.claude/skills/` goes.

**Tech Stack:** Python 3.13 scripts under `python/scripts/`, pytest, mise tasks, Markdown, Claude Code CLI (`claude -p`).

**Spec:** [`agents-md-split-2026-11-05.md`](agents-md-split-2026-11-05.md). It runs the spec's section 6 evaluation through a `mise run skill-eval` task rather than a bare shell command: the evaluation repeats 24 runs, and a command needed twice earns a task (AGENTS.md SOP 5.5), which is also what makes it pre-approved.

## Global Constraints

- Stage paths by name; never `git add -A`, never anything under `corpus/`.
- Commits:
  - Conventional Commit subject and a body that answers why.
  - The body closes with `mise run check passes.` or names the part that did not run.
  - Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Iterate with `mise run fix`, `mise run lint-py`, `mise run typecheck`, `mise run test-py -- <file>`. Run the full `mise run check` once at the end of each task that touches code (Tasks 1–3) and before the pull request.
- Reap bar: default 20 GB, where GB means 2^30 bytes (`GIB = 1 << 30`), the unit Windows Explorer labels GB. The bar is measured on the drive holding the primary checkout.
- Skills live only in `.agents/skills/<name>/SKILL.md`. Each has frontmatter `name` and `description`, a description copied verbatim from spec 4.2, and a body under 500 words (`wc -w`).
- AGENTS.md working-rule headings are exactly `### Committing`, `### Working economically` and `### Worktrees`, giving the anchors `#committing`, `#working-economically` and `#worktrees`.
- Dated plans under `docs/process/plans/` keep their old `SOP <n>` citations.
- Tests are offline. Nothing in `tests/` runs `claude`, `gh` or the network.

## Review Focus

1. **Free space can't be read** (`shutil.disk_usage` raises `OSError`): reap removes nothing, prints "free space unknown", and `--force` still reaps. *Task 1.*
2. **`--prune` with plenty of free space:** nothing is pruned either; the gate covers every deletion, not only worktrees. *Task 1.*
3. **A negative `--min-free-gb`:** argparse refuses it, the same way `clean --keep` refuses a negative value. *Task 1.*
4. **A `claude -p` run that exits nonzero or emits no result line:** `skill-eval` reports the run as failed, not as "skill not loaded". *Task 2.*
5. **Links to the removed `AGENTS.md#commit-messages` anchor** (`CONTRIBUTING.md:28`, `.agents/skills/improving-render-parity/SKILL.md:44`): they now point to `#committing`. *Task 3.*

---

### Task 1: Reap waits for low disk space

**Files:**
- Modify: `python/scripts/worktree_init.py` (`_reap` at :959, the `reap` parser at :1068, dispatch at :1103)
- Modify: `mise.toml:99` (the `reap` task description)
- Modify: `docs/harness-setup.md` ("Removing a worktree", :91)
- Test: `tests/test_worktree_reap.py`

**Interfaces:**
- Produces:
  - `GIB: int = 1 << 30`
  - `DEFAULT_MIN_FREE_GB: float = 20.0`
  - `_free_bytes(path: Path) -> int`
  - `_space_is_short(free: int, min_free_gb: float) -> bool`
  - `_reap(confirmed, *, include_cherry=False, prune=False, stash_dirty=False, discard_untracked=False, force: bool = False, min_free_gb: float = DEFAULT_MIN_FREE_GB) -> int`
  - CLI flags `reap --force` and `reap --min-free-gb N`. Task 6's skill names both.

- [ ] **Step 1: Write the failing tests.** Add a helper `_reap_env(monkeypatch, tmp_path, free: int | OSError) -> tuple[Path, Path]`. It builds `_squash_repo`, then monkeypatches:
  - `worktree_init.REPO_ROOT` and `dataroot.REPO_ROOT` to the repo
  - `worktree_init._gh` to `_gh_stub([{"number": 89, "headRefName": "feat", "headRefOid": tip}])`
  - `worktree_init._free_bytes` to return `free`, or raise it if it is an `OSError`

  It returns `(repo, worktree)`. Then add these tests:
  - `test_space_is_short_only_below_the_bar`: `_space_is_short(19 * GIB, 20.0)` is true; `_space_is_short(20 * GIB, 20.0)` is false.
  - `test_reap_with_plenty_of_space_removes_nothing`: with free = `50 * GIB`, `_reap(True) == 0`, `worktree.is_dir()`, and `"nothing removed"` appears in the captured output.
  - `test_reap_below_the_bar_removes_the_worktree`: with free = `5 * GIB`, `_reap(True) == 0` and the worktree no longer exists.
  - `test_force_reaps_with_plenty_of_space`: with free = `50 * GIB`, `_reap(True, force=True)` removes the worktree.
  - `test_min_free_gb_moves_the_bar`: with free = `50 * GIB`, `_reap(True, min_free_gb=100.0)` removes the worktree.
  - `test_unknown_free_space_removes_nothing_without_force`: with free = `OSError("boom")`, `_reap(True) == 0`, the worktree still exists, and the output contains `"free space unknown"`.
  - `test_force_reaps_when_free_space_is_unknown`: with free = `OSError("boom")`, `_reap(True, force=True)` removes the worktree.
  - `test_prune_with_plenty_of_space_prunes_nothing`: spy on `_prune_leftovers`, `_prune_envs` and `_prune_branches`, recording the `confirmed` keyword each receives. Then `_reap(True, prune=True)` records no `True`.
  - `test_reap_cli_defaults_and_flags`: monkeypatch `worktree_init._reap` with a spy.
    - `main(["reap"])` passes `force=False, min_free_gb=20.0`.
    - `main(["reap", "--force", "--min-free-gb", "5"])` passes `force=True, min_free_gb=5.0`.
  - `test_negative_min_free_gb_is_refused`: `pytest.raises(SystemExit)` around `main(["reap", "--min-free-gb", "-1"])`.

- [ ] **Step 2: Run them and see them fail.** Run `mise run test-py -- tests/test_worktree_reap.py`. Expected: the new tests fail with `AttributeError` (no `GIB`, `_free_bytes` or `_space_is_short`) or `TypeError` (unexpected keyword `force`). Every existing test passes.

- [ ] **Step 3: Implement the gate in `worktree_init.py`.**
  - `_free_bytes` returns `shutil.disk_usage(path).free`. `_space_is_short` returns `free < min_free_gb * GIB`.
  - In `_reap`, right after printing `worktree   {repo}`, read `_free_bytes(repo)`:
    - On success, print `disk       {free / GIB:.1f} GB free; reaping waits for under {min_free_gb:g} GB (--force skips)`.
    - On `OSError`, print `  ! free space unknown ({err}); nothing removed without --force` and treat space as not short.
  - After the blocked check and before `if not confirmed:`, decide whether to hold. If `confirmed` and neither `short` nor `force`, set `confirmed = False` and `held = True`.
  - In the dry-run branch, the final line is `\nplenty of space: nothing removed; --force reaps anyway` when `held`, and the usual `\ndry run; re-run with --yes to reap` otherwise.
  - Parser:
    - `--force` is `store_true`, with help "reap even when the drive has room".
    - `--min-free-gb` is `type=float` with `default=DEFAULT_MIN_FREE_GB`.
    - A negative value calls `parser.error("--min-free-gb must not be negative")`.
    - The dispatch passes both values to `_reap`.

- [ ] **Step 4: Run them and see them pass.** Run `mise run test-py -- tests/test_worktree_reap.py`. Expected: all pass.

- [ ] **Step 5: Update the docs.**
  - `mise.toml:99`: the usage in parentheses becomes `(mise run reap -- --yes [--force] [--min-free-gb N] [--cherry] [--prune] [--stash-dirty] [--discard-untracked])`, and the description adds `; removes nothing while 20 GB or more is free unless --force`.
  - `docs/harness-setup.md`: add one bullet to "Removing a worktree": *`reap` removes nothing while the primary checkout's drive has 20 GB or more free (`--min-free-gb N` moves the bar, `--force` skips it); a dry run still lists the candidates.*

- [ ] **Step 6: Run the gate and commit.**
  - Run `mise run fix`, `mise run lint-py` and `mise run typecheck`, then `mise run check`. Expected: PASS.
  - Commit `tests/test_worktree_reap.py`, `python/scripts/worktree_init.py`, `mise.toml` and `docs/harness-setup.md` as `feat(tooling): reap waits until the drive has under 20 GB free`. The body says why: reaping risks work and is only worth it when space is short (spec D7).

### Task 2: `skill-eval` task

**Files:**
- Create: `python/scripts/skill_eval.py`
- Create: `tests/test_skill_eval.py`
- Modify: `mise.toml` (a new `[tasks.skill-eval]` beside `verify-docs`, :178)

**Interfaces:**
- Produces:
  - `DRY_RUN: str`: the suffix `"\n\nThis is a dry run: list the files you would touch and the steps you would take; edit nothing."`
  - `@dataclass(frozen=True) class RunOutcome: skills: list[str]; text: str | None; failed: bool`
  - `outcome(lines: list[str], returncode: int) -> RunOutcome`
  - `main(argv: list[str] | None = None) -> int`
  - CLI: `mise run skill-eval -- --skill NAME --model {opus,haiku} --phase {baseline,with} --prompt-file PATH [--reps 3]`.
    - Each repetition runs `claude -p --model M --permission-mode plan --output-format stream-json --verbose <prompt + DRY_RUN>` with `cwd` at the repo root.
    - It writes `target/skill-eval/<skill>/<model>-<phase>-<n>.jsonl` and `.md` (the result text).
    - It prints one line per run: `run <n>: skills <comma list or none>; exit <code>; <md path>`.
    - It exits 1 if any run failed.
  - Tasks 4–6 consume this.

- [ ] **Step 1: Write the failing tests** in `tests/test_skill_eval.py`. Import the script the way `tests/test_worktree_reap.py` imports `worktree_init`. Each line in these tests is a `json.dumps` of the stream-json shape:
  - `test_outcome_lists_skill_tool_calls`:
    - Lines: an `{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "changing-seam-contracts"}}, {"type": "tool_use", "name": "Read", "input": {"file_path": "x"}}]}}` line, a non-JSON line `"not json"`, and `{"type": "result", "result": "the plan"}`.
    - `outcome(lines, 0) == RunOutcome(["changing-seam-contracts"], "the plan", False)`.
  - `test_a_run_without_a_result_line_failed`: `outcome([], 0).failed` is true and `.text` is `None`.
  - `test_a_nonzero_exit_failed`: `outcome([<result line>], 1).failed` is true.

- [ ] **Step 2: Run them and see them fail.** Run `mise run test-py -- tests/test_skill_eval.py`. Expected: `ModuleNotFoundError: skill_eval`.

- [ ] **Step 3: Implement `skill_eval.py`.**
  - `outcome` parses each line with `json.loads` and skips lines that fail.
  - It collects `input["skill"]` from `tool_use` blocks named `Skill` in assistant messages.
  - It takes `text` from the last `type == "result"` line.
  - `failed = returncode != 0 or text is None`.
  - `main` reads the prompt file, runs the repetitions with `subprocess.run(..., capture_output=True, text=True, encoding="utf-8")`, writes both files and prints the lines.
  - Then add the task to `mise.toml`:

  ```toml
  [tasks.skill-eval]
  description = "Dry-run a prompt through headless claude -p and report which skills each run loaded (mise run skill-eval -- --skill NAME --model opus|haiku --phase baseline|with --prompt-file PATH [--reps 3])"
  run = "uv run python python/scripts/skill_eval.py"
  ```

- [ ] **Step 4: Run them and see them pass.** Run `mise run test-py -- tests/test_skill_eval.py`. Expected: PASS.

- [ ] **Step 5: Smoke-test against the real CLI.**
  - Write `target/skill-eval/prompts/smoke.txt` containing `Raise CTRY.FLM's mean_ssim_scored; where do you start?`.
  - Run `mise run skill-eval -- --skill improving-render-parity --model haiku --phase with --reps 1 --prompt-file target/skill-eval/prompts/smoke.txt`.
  - Expected: one `run 1:` line, exit 0, and a non-empty `.md`. If the stream-json shape differs from the test lines, correct the test lines to match the real `.jsonl` first, and only then fix the parser.

- [ ] **Step 6: Run the gate and commit.**
  - Run `mise run check`. Expected: PASS.
  - Commit `python/scripts/skill_eval.py`, `tests/test_skill_eval.py` and `mise.toml` as `feat(tooling): add skill-eval for dry runs through headless claude`.

### Task 3: Trim AGENTS.md and rename its citations

**Files:**
- Modify: `AGENTS.md` (rewrite)
- Modify: `docs/harness.md:11-26` (Policy)
- Modify: `python/scripts/verify_formats_docs.py:177` (`LINK_SCAN_GLOBS`)
- Modify, citations only:
  - `.github/workflows/ci.yml:123`
  - `mise.toml:369`
  - `python/scripts/check_commit_msg.py:2,9,78,93`
  - `tests/test_check_commit_msg.py:1`
  - `python/scripts/worktree_init.py:66`
  - `tests/test_worktree_layout.py:6`
  - `docs/harness.md:18,22`
  - `docs/harness-setup.md:137`
  - `docs/adr/0026-commit-hooks-run-the-gates-own-tasks.md:69,89`
  - `docs/adr/0031-the-gate-runs-pytest-across-every-core.md:28`
  - `CONTRIBUTING.md:28`
  - `.agents/skills/improving-render-parity/SKILL.md:44`

**Interfaces:**
- Produces: the anchors `AGENTS.md#committing`, `#working-economically` and `#worktrees`, which Tasks 4–7 cite.

- [ ] **Step 1: Rewrite `AGENTS.md`** from spec 4.1. Keep the title and the one-line description.
  - **`## 1. Non-Negotiable Directives`** keeps Directives 1–3 in order. Directive 3 becomes one line of invariant names, `[I1]` coordinates … `[I8]` 8.3 paths, linking SPEC § 2 and `contracts/mod.rs`.
  - **`## 2. Documentation Directory & Single Sources of Truth`** keeps its title, and each summary is one short clause.
    - These rows change:
      - "Binary Disassembly" becomes `research/playone-exe/`: evidence for `PLAYONE.EXE`, routed by `research/README.md`.
      - "Parity" becomes `research/parity/`.
      - "Project Setup & Tasks" drops its gate sentence.
      - "Agent Skills" is removed.
      - "Skill Configuration" becomes "Issues & skill configuration": `docs/agents/`, GitHub Issues via `gh`, review threads with `mise run pr-threads -- <number>`.
    - The "process docs" line stays.
  - **`## 3. Working Rules`** has three subsections:
    - `### Committing`: SOP 3 items 1, 2, 4 and 5 and the "Commit Messages" paragraph; SOP 6.4 as one sentence; SOP 3.6 as one sentence linking `.agents/skills/improving-render-parity/SKILL.md#evidence-for-a-rendering-pr`.
    - `### Working economically`: SOP 5 items 1, 2, 3 and 5.
    - `### Worktrees`: the two rules in spec 4.1. The reap rule adds "it waits for low disk space".
  - Removed: the "Agent skills" closing section, SOP 1, 2 and 4, SOP 3.3, SOP 5.4, and SOP 6 except the two rules above.

- [ ] **Step 2: Measure it.** Run `wc -c AGENTS.md`. Expected: 8,192 or fewer. If it's larger, cut table clauses first.

- [ ] **Step 3: Rename the citations.**
  - SOP 3 citations become "AGENTS.md, Committing". `check_commit_msg.py:93`'s message ends `(AGENTS.md, Committing)`.
  - SOP 5 citations become "AGENTS.md, Working economically".
  - SOP 6 citations about the in-checkout rule become "AGENTS.md, Worktrees".
  - ADR 0026:69 links `../../AGENTS.md#committing`.
  - `#commit-messages` links become `#committing`.
  - ADR 0008, ADR 0012 and `tests/test_parity_frame.py` are left for Tasks 4 and 6.

- [ ] **Step 4: Cut `docs/harness.md` Policy.** Replace the gate, `mise run` and one-writer bullets with one bullet: *The gate, `mise run` and the one-writer rule are in AGENTS.md*, linking "AGENTS.md" to `../AGENTS.md#working-economically` and adding a "Worktrees" link to `../AGENTS.md#worktrees`. Keep the other bullets as they are.

- [ ] **Step 5: Link-check the skills.** Append `".agents/skills/*/SKILL.md"` to `LINK_SCAN_GLOBS`.

- [ ] **Step 6: Verify.**
  - Run `mise run verify-docs` and `mise run test-py -- tests/test_doc_invariants.py tests/test_check_commit_msg.py tests/test_worktree_layout.py`. Expected: PASS.
  - Run `git grep -n 'SOP [0-9]' -- ':!docs/process/plans'`. Expected: only ADR 0008:61, ADR 0012:52 and `tests/test_parity_frame.py:228`.
  - Run `mise run check`. Expected: PASS.

- [ ] **Step 7: Commit** every file above as `docs(agents): keep only every-task rules in AGENTS.md`.

### Skill tasks (Tasks 4–6): the shared procedure

Each skill task runs these steps with its own values (the skill, its prompts, its must-cover list and its citations, all given in the task). Every run is `mise run skill-eval -- --skill <skill> --model <model> --phase <phase> --prompt-file target/skill-eval/prompts/<skill>-<model>.txt`.

1. **Write the prompt file.** The prompt is copied verbatim from the spec section 6 table.
2. **Run the baseline** (`--phase baseline`) for each model. Read every `.md`, and in spec section 8 record each must-cover item every run missed, word for word.
3. **Write `SKILL.md`.**
   - Frontmatter: `name`, and the description from spec 4.2 verbatim.
   - Body: one-line overview, then numbered steps each ending on a done-condition, then a quick-reference table, then `## Common mistakes`.
   - Take the content from `git show main:AGENTS.md` and the skill's row in spec 4.2. Link docs instead of copying them.
   - `## Common mistakes` lists only the misses step 2 recorded.
   - Leave out any rule that every baseline run already followed.
4. **Check it.**
   - Run `wc -w .agents/skills/<skill>/SKILL.md`. Expected: under 500.
   - Run `mise run verify-docs`. Expected: PASS.
5. **Run with the skill** (`--phase with`) for each model. Expected: every `run` line names the skill, and every `.md` covers every must-cover item.
6. **Tighten if needed.** On a miss, change the description's or the step's wording (not its length) and repeat step 5.
7. **Record and commit.**
   - Record both phases in spec section 8: the runs that loaded the skill, the misses, and the wording changes.
   - Apply the task's citations.
   - Run `mise run verify-docs` and `mise run test-py -- tests/test_doc_invariants.py`.
   - Commit the skill, the citations and the spec as `docs(agents): add the <skill> skill`.

### Task 4: `changing-seam-contracts`

**Files:**
- Create: `.agents/skills/changing-seam-contracts/SKILL.md`
- Modify: `docs/adr/0012-a-decoded-shape-owns-its-provenance.md:52`
- Modify: spec section 8

**Interfaces:**
- Consumes: Task 2's `skill-eval`, and Task 3's trimmed AGENTS.md (the baseline must not see SOP 1).

**Values for the shared procedure:**
- Model: Opus.
- Prompt and must-cover list: the `changing-seam-contracts` row of spec section 6.
- Steps: spec 4.2.
- Citation: ADR 0012's "the additive-field rule in SOP 4" becomes "the additive-field rule in the `changing-seam-contracts` skill", linked to `../../.agents/skills/changing-seam-contracts/SKILL.md`.

**Stop condition (spec D2):** if no run in step 5 names the skill, Claude Code is not reading `.agents/skills/`. Stop, and report to the user before Tasks 5–7.

### Task 5: `recording-binary-findings`

**Files:**
- Create: `.agents/skills/recording-binary-findings/SKILL.md`
- Modify: spec section 8

**Values for the shared procedure:**
- Model: Opus.
- Prompt and must-cover list: the spec section 6 row.
- Steps: spec 4.2.
- Citations: none.

### Task 6: `managing-worktrees`

**Files:**
- Create: `.agents/skills/managing-worktrees/SKILL.md`
- Modify: `docs/adr/0008-worktrees-share-one-read-only-data-root.md:61`
- Modify: `tests/test_parity_frame.py:228`
- Modify: spec section 8

**Interfaces:**
- Consumes: Task 1's `reap --force` and `--min-free-gb N`.

**Values for the shared procedure:**
- Models: Opus with the reap prompt; Haiku with the capture prompt.
- Must-cover lists: both `managing-worktrees` rows of spec section 6.
- Content: spec 4.2, plus a quick-reference row for each reap flag, `--force` and `--min-free-gb` included.
- Citations: ADR 0008's "The SOP 6 shared-write gate" and the `test_parity_frame.py` docstring's "(SOP 6)" both cite the `managing-worktrees` skill. ADR 0008 links `../../.agents/skills/managing-worktrees/SKILL.md`.
- Extra check after step 7: `git grep -n 'SOP [0-9]' -- ':!docs/process/plans'` prints nothing.

### Task 7: Remove `.claude/skills/`, verify, open the pull request

**Files:**
- Delete: `.claude/skills/improving-render-parity/SKILL.md` (with its now-empty directories)
- Modify: `CLAUDE.md:3-5`
- Modify: spec status line and section 8

- [ ] **Step 1: Delete the stub, and fix `CLAUDE.md`.** Run `git rm .claude/skills/improving-render-parity/SKILL.md`. In `CLAUDE.md`, the sentence becomes: *`AGENTS.md` is the canonical developer guide; this stub exists only so Claude Code loads it. Put repository rules in `AGENTS.md`, never here.*
- [ ] **Step 2: Check the parity skill is still found.** Run `mise run skill-eval -- --skill improving-render-parity --model opus --phase with --reps 1 --prompt-file target/skill-eval/prompts/smoke.txt`. Expected: the run line names `improving-render-parity`.
- [ ] **Step 3: Run the verification from spec section 7.**
  - `wc -c AGENTS.md` is 8,192 or fewer.
  - `git grep -n 'SOP [0-9]' -- ':!docs/process/plans'` prints nothing.
  - `mise run check` passes.
  - Section 8 shows every skill passing on each of its models.
- [ ] **Step 4: Record and commit.** Set the spec status to *implemented* with the date the task is done. Commit `CLAUDE.md`, the deletion and the spec as `docs(agents): skills live only in .agents/skills`, with the closing line `mise run check passes.`.
- [ ] **Step 5: Open the pull request.** Use the `pr` skill for the body. It notes there is no rendering change, so no comparison picture. Push the branch and open the PR against `main`.
