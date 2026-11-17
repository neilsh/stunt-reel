# CI scopes its jobs by the files a pull request changes: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A docs-only pull request runs only the docs half in CI; every other PR, push to `main` and manual run is unchanged.

**Architecture:** A new `gate.py scope` subcommand answers `docs_only=true|false` from the gate's own `scope_for`; a new `scope` job in `ci.yml` runs it on the PR diff; `quality`, `msrv`, `deny` and `windows-smoke` skip at job or step level only when `scope` succeeded and said `true`.

**Tech Stack:** GitHub Actions YAML, `python/scripts/gate.py` (bare Python 3.15), pytest, mise.

**Spec:** [`spec.md`](spec.md) (issue [#659](https://github.com/neilsh/stunt-reel/issues/659)). Run everything through `mise run`; scoped test runs are `mise run test-py -- <file>`.

## Global Constraints

- Job `name:` fields stay exactly `Quality gate (ubuntu)`, `Windows smoke`, `MSRV check`, `Dependency policy`: the `main` ruleset matches them by display name (plus `PR title`, untouched).
- No workflow-level `paths:` or `paths-ignore:` in `ci.yml`; skipping is by job- or step-level `if:` only.
- The skip condition is `needs.scope.result == 'success' && needs.scope.outputs.docs_only == 'true'`; every dependent runs in every other case, so each carries `needs: scope`. `msrv`, `deny` and `windows-smoke` take `if: !cancelled() && !(<condition>)` (`windows-smoke` keeps `github.event_name == 'pull_request'` as well); `quality` takes `if: !cancelled()` alone and decides per step. `!cancelled()`, not `always()`: the `cancel-in-progress` concurrency group cancels a superseded run, and `always()` would keep its dependents running.
- `ci.yml` keeps exactly one `\bSKIP: ` match, comments included (`tests/test_prek_hooks.py::test_ci_skips_exactly_the_local_hooks` counts the whole file): spell the condition in comments as "the skip condition", never `SKIP:`. The `scope` job sits above `quality`, so no comment or step name there may contain "Install lavapipe" (`tests/test_prek_hooks.py::test_ci_skips_exactly_the_local_hooks`), and the empty-diff step stays before the first "Install lavapipe" in the file (`test_ci_fails_an_empty_pull_request_before_installing`); that step's text is not edited.
- `gate.py scope` runs on Python 3.15.2 through `jdx/mise-action` (`install_args: python`; the plan's call, the spec left `actions/setup-python` open) and runs as `mise exec -- python python/scripts/gate.py scope …`, with the job's `env` setting `MISE_AUTO_INSTALL: "false"` as the other jobs do; the runner's system `python3` cannot parse `gate.py` (PEP 810 `lazy import`). No new third-party action; actions are pinned to SHAs.
- `mise run check` under `CI` stays the full gate (ADR 0038); `ci=False` inside `docs_only` is deliberate.
- Stage files by name; Conventional Commit subjects; run `mise run check` before each commit.

## Review Focus

1. **`scope` fails** (bad `--base`, a syntax error in `gate.py`, runner outage): every required check still runs. Task 2's tests pin the conditions' text; Task 4 Step 4 shows the behaviour.
2. **Push to `main` and `workflow_dispatch`** (`scope` is skipped): `quality` runs the full gate and `msrv`, `deny` run. Task 2's tests pin the conditions' text; Task 4 Step 1 shows the behaviour (the first push to `main` after merge shows it for real); `windows` is untouched.
3. **`GITHUB_ACTIONS` sets `CI=true`** in the `scope` job: it must still answer from the paths, not "full because CI". Task 1.
4. **A rename across categories** (`a.md` to `a.py`) counts both sides, so the answer is `false`. Task 1.
5. **A PR mixing docs with a workflow, `mise.toml` or fixture file, and an empty diff** answer `false`. Task 1's `test_docs_only` cases.

---

### Task 1: `gate.py scope`

**Files:**
- Modify: `python/scripts/gate.py` (`main`'s `half` choices, a new `docs_only`, the module docstring's usage line and one sentence naming the subcommand)
- Test: `tests/test_gate_plan.py`

**Interfaces:**
- Produces: `docs_only(paths: list[str] | None) -> bool`; `python python/scripts/gate.py scope [--base REF]` prints exactly one stdout line, `docs_only=true` or `docs_only=false`, and exits 0, including when git cannot give the paths (the reason goes to stderr); `--full` and `--tail` are accepted and ignored.
- Consumes: `scope_for`, `changed_paths`, `default_base`, `ChangedPathsError` as they stand.

- [ ] **Step 1: Write the failing tests** in `tests/test_gate_plan.py`, beside the `scope_for` tests:
  - `test_docs_only` parametrized: `["a.md", "b.ksy"]` is `True`; `["a.md", "crates/a.rs"]`, `["a.md", "a.py"]`, `["a.md", "mise.toml"]`, `["a.md", ".github/workflows/ci.yml"]`, `["a.md", "tests/fixtures/x.json"]`, `[]` and `None` are `False`.
  - `test_scope_prints_docs_only_for_a_documentation_change`: write a helper `_run_scope(monkeypatch, paths: list[str] | Exception, *args: str, expected_base: str = "origin/main") -> int` beside `_run_main` (which cannot serve: it calls `main(["all", …])` and reads `check.log`, and `scope` writes none), patching `changed_paths` and `default_base` the same way, and call `gate.main(["scope", *args])`; assert `capsys` stdout is exactly `"docs_only=true\n"` and no step ran.
  - `test_scope_is_false_when_git_cannot_say`: `changed_paths` raises `gate.ChangedPathsError("no main")`; stdout is `"docs_only=false\n"`, stderr contains `no main`, return code 0.
  - `test_scope_ignores_ci_being_set`: `monkeypatch.setenv("CI", "true")` with docs-only paths still prints `docs_only=true`.
  - `test_scope_passes_an_explicit_base`: `["scope", "--base", "main"]` reaches `changed_paths` as `base == "main"`.
  - `test_scope_counts_both_sides_of_a_rename`: in a throwaway repo built as the neighbouring `changed_paths` tests build theirs, move `a.py` to `a.md` on a branch (so a count of the new side alone would give `True`; `changed_paths` lists both with `--no-renames`); `gate.docs_only(gate.changed_paths(repo))` is `False`.
- [ ] **Step 2: Run** `mise run test-py -- tests/test_gate_plan.py -k "docs_only or scope"`. Expected: FAIL (`gate` has no `docs_only`; `scope` is not a valid choice).
- [ ] **Step 3: Implement** `docs_only` as `scope = scope_for(paths, full_flag=False, ci=False)`, true exactly when `not scope.full and scope.halves == ("docs",)`. In `main`, add `"scope"` to the `half` choices and handle it before the plan is built: resolve the base as `all` does, read `changed_paths` (a `ChangedPathsError` becomes `paths = None` and a stderr line), print the one stdout line, return 0. Add `scope` to the docstring's usage line and one sentence on what it answers and who calls it (CI's `scope` job, [`ci.yml`](../../../.github/workflows/ci.yml)).
- [ ] **Step 4: Run** `mise run test-py -- tests/test_gate_plan.py`. Expected: PASS, including the existing `_plan` and lane tests.
- [ ] **Step 5: Commit** `python/scripts/gate.py tests/test_gate_plan.py` as `feat(gate): add a scope subcommand that says whether a change is docs-only`, after `mise run check`.

### Task 2: the `scope` job and the skips

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `tests/test_ci_scope.py`

**Interfaces:**
- Consumes: Task 1's `gate.py scope` and its `docs_only=` line.
- Produces: job `scope` with output `docs_only` (`'true'`/`'false'`); the four dependents' conditions as under Global Constraints. Comments in `ci.yml` cite `ADR 0047`; if Task 3 finds that number taken, it updates them in its commit.

- [ ] **Step 1: Settle whether `quality` can drop the Rust install.** In a shell whose `PATH` holds no cargo or rustup entry (confirm `command -v cargo` prints nothing), run `mise run check-docs` with `MISE_AUTO_INSTALL=false`; `windows-smoke` already runs `mise run check-windows-smoke` with only `python uv` installed, which is the precedent. Expected: `[gate] PASS`. If it fails only because mise cannot start without `rust` installed, keep `rust` in `quality`'s `install_args` for the docs-only path and skip just the lavapipe install, the cargo cache and `mise run check`; say so in Task 3's ADR.
- [ ] **Step 2: Write the failing tests** in `tests/test_ci_scope.py`, reading `ci.yml` as text like `tests/test_prek_hooks.py` does (no YAML parser is a dependency), with a helper `_job(name: str) -> str` that returns one job's block:
  - `test_the_required_check_names_are_unchanged`: the four `name:` lines above each appear exactly once.
  - `test_scope_job_reads_the_pull_request_diff`: `_job("scope")` has `if: github.event_name == 'pull_request'`, `fetch-depth: 0`, `gate.py scope`, `origin/$BASE_REF` and `$GITHUB_OUTPUT`, and an `install_args` of `python` only, and `MISE_AUTO_INSTALL: "false"`.
  - `test_every_dependent_runs_unless_scope_succeeded_with_docs_only`: for `quality`, `msrv`, `deny` and `windows-smoke`, the block has `needs: scope` and an `if:` containing `!cancelled()` and no `always()`; `quality`'s `if:` is that alone, and for the last three it also contains `needs.scope.result == 'success'` and `needs.scope.outputs.docs_only == 'true'` under a `!(`; `windows-smoke`'s contains `github.event_name == 'pull_request'`; the `windows` job has no `needs:`.
  - `test_a_docs_only_quality_run_runs_check_docs_and_skips_the_full_gate`: `_job("quality")` has a job-level `DOCS_ONLY:` env value containing `needs.scope.result == 'success'` and `needs.scope.outputs.docs_only == 'true'`, and its `mise run check-docs` step is under `if: env.DOCS_ONLY == 'true'` while its `mise run check` step, the lavapipe install and the cargo cache are under `if: env.DOCS_ONLY != 'true'`; unless Step 1 says otherwise, its mise `install_args` is an expression on `env.DOCS_ONLY` and the `'true'` branch has no `rust`.
  - `test_ci_has_no_workflow_level_path_filters`: the text before `jobs:` has no `paths:` or `paths-ignore:`.
- [ ] **Step 3: Run** `mise run test-py -- tests/test_ci_scope.py`. Expected: FAIL.
- [ ] **Step 4: Implement the workflow.** Add job `scope` (name `Scope`, `ubuntu-latest`, `timeout-minutes: 5`, `MISE_AUTO_INSTALL: "false"`, pinned `actions/checkout` and `jdx/mise-action` as the file already pins them) that appends `gate.py scope`'s output to `$GITHUB_OUTPUT` and exposes it as the job output. Edit `quality`, `msrv`, `deny` and `windows-smoke` as the Global Constraints say. In `quality`, a job-level `env: DOCS_ONLY:` computed from `needs.scope` (the `needs` context is available there; `actionlint` in Step 5 confirms) feeds each step's `if:` and the mise `install_args` (without `rust` when `DOCS_ONLY` is `'true'`, unless Step 1 says to keep it); the lavapipe install, the cargo cache and `mise run check` run only when it is not `'true'`, `mise run check-docs` only when it is. Leave the empty-diff step, `uv sync`, the Java and Kaitai install and the prek step as they are, and cite the ADR from Task 3 in comments.
- [ ] **Step 5: Run** `mise run test-py -- tests/test_ci_scope.py tests/test_prek_hooks.py`. Expected: PASS. Then run `actionlint .github/workflows/ci.yml` if a release binary can be fetched into the scratchpad (do not add it to `mise.toml`); expected: no findings.
- [ ] **Step 6: Commit** `.github/workflows/ci.yml tests/test_ci_scope.py` as `ci: skip the Rust jobs and run the docs half for a docs-only pull request`, after `mise run check` (this change is `other`, so the gate runs in full).

### Task 3: ADR and docs

**Files:**
- Create: `docs/adr/0047-ci-scopes-a-docs-only-pull-request.md` (number checked against `docs/adr/` when written; 0046 was the newest on 2026-11-17)
- Modify: `docs/adr/0038-the-local-gate-runs-what-a-change-touches.md` (Status line only: "Superseded in part <date> by ADR 0047", as ADR 0044 did), `docs/quality-gate.md` (the CI paragraph, line 11, which says "Every pull request runs the full `mise run check` gate"; line 5's "`CI` is set" rule for `mise run check` stays true, and gains a clause that a docs-only PR's `quality` calls `check-docs` directly). ADR 0038's Context sentence "CI's `quality` job runs the gate on every pull request" stays as the dated record

- [ ] **Step 1: Write the ADR** in ADR 0044's shape (Status, Context, Decision, Considered Options, Consequences): the decision is spec Design 1-5; the options are the spec's B and C with why not; the consequences state the red-`main` trade-off the owner accepted, that `ci.yml` and `mise.toml` changes get the full gate, that a future `include_str!` of a docs path would escape the scope (spec, Intent), and Task 2 Step 1's result.
- [ ] **Step 2: Edit `docs/quality-gate.md`**: `msrv` and `deny` no longer "run on every pull request … rather than being path-filtered"; list all five required checks by display name (the paragraph names four, by job id); say what a docs-only PR skips and why a skipped job still satisfies the ruleset and the `main` ruleset's names must not change.
- [ ] **Step 3: Run** `mise run test-docs` and `mise run check-docs`. Expected: PASS (links, anchors and cited paths resolve).
- [ ] **Step 4: Fresh review.** AGENTS.md § Committing rule 5 applies (`docs/*.md`, an ADR is under `docs/`): a fresh reviewer reads the diff and the notes it cites, flags any claim broader than its evidence, and checks each behavioural claim against `ci.yml` and `gate.py`. Fix what it finds.
- [ ] **Step 5: Commit** the three files as `docs(adr): scope CI for a docs-only pull request (ADR 0047)`, after `mise run check`.

### Task 4: verify on GitHub

Opening a PR needs the owner's go-ahead. In a cloud session use the REST rows of [`cloud.md`](../../../.agents/skills/working-in-an-environment/cloud.md); a stacked PR cannot be merged here, so the throwaway PRs below are closed, never merged.

- [ ] **Step 1: Open the PR for this branch** to `main` (title as a Conventional Commit). Expected: all five required checks run in full, because `ci.yml` is `other`.
- [ ] **Step 2: Docs-only throwaway.** Open a PR whose base is this branch and whose only change is a Markdown edit. Expected: `Scope` succeeds; `Quality gate (ubuntu)` passes having run `check-docs` and skipped the lavapipe, cargo-cache and `check` steps; `MSRV check`, `Dependency policy` and `Windows smoke` show as skipped.
- [ ] **Step 3: Code throwaway.** Same, changing a `.py` file. Expected: every job runs as today.
- [ ] **Step 4: Fail-open throwaway.** Same, with a `.py` change that makes `gate.py` fail to parse. Expected: `Scope` fails and every other job still runs (Review Focus 1).
- [ ] **Step 5: After the PR merges**, the next docs-only PR to `main` must show the required checks satisfied (skipped jobs counting as passing) and be mergeable; record the result in the issue. This is the one fact the repository cannot show before merge (spec, Verification).
- [ ] **Step 6: Finish the work item** in the merging PR: write `outcome` in this folder's README (one line), close #659, and leave the ADR and `quality-gate.md` as the evergreen record ([`work/README.md` § Lifecycle](../../README.md#lifecycle)).
