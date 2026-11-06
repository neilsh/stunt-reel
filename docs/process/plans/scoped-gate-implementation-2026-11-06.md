# Scoped, faster local gate: implementation plan (2026-11-06)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mise run check` runs only the halves a branch's changes touch, pytest uses physical
cores, and the reap tests stop building a git repository per test, while CI keeps the full gate.

**Architecture:** `python/scripts/gate.py` gains a fourth half, `docs`, plus pure functions that
sort changed paths into categories, choose halves, and write the commit's gate line. A thin layer
reads the changed paths from git. pytest worker count changes by installing `psutil`. The reap
tests replace per-test repositories with stubs or one shared module repository.

**Tech Stack:** Python 3.15 (stdlib only in `gate.py`), pytest + pytest-xdist 3.8, mise, git.

**Spec:** [`scoped-gate-2026-11-06.md`](scoped-gate-2026-11-06.md). Read it first; this plan
cites its sections as "spec 3.x".

## Global Constraints

- `gate.py` runs as `python python/scripts/gate.py`, outside uv: standard library only.
- Every entry of `gate.STEPS` is a leaf mise task with a `STEP_LANES` entry (ADR 0014, 0016).
- Category rules, in order (spec 3.1): `tests/fixtures/**` other; `crates/**`, `Cargo.toml`,
  `Cargo.lock`, `deny.toml` rust; `*.py`, `pyproject.toml`, `uv.lock` python; `*.md`, `*.ksy`
  docs; anything else other. Root files match at the repository root only.
- Gate lines must satisfy `python/scripts/check_commit_msg.py` (each gate name followed by
  `passes` or `not run`).
- Tests are offline and synthetic. Ruff line length 100; mypy runs as Windows and as Linux.
- Commits follow AGENTS.md, Committing: stage paths by name, Conventional Commit subject, a body
  when a reviewer would ask why, the closing gate line, and the `Co-Authored-By` trailer.
- Read the `writing-for-agents` skill before editing AGENTS.md (Task 5).

## Review Focus

1. **Local `main` missing** (a clone with only `origin/main`): the gate runs in full and says
   `changed paths unknown: …`. Test in Task 4.
2. **A path git would quote** (non-ASCII, such as `research/ä.md`): read with `-z` so it
   classifies as docs instead of falling to other. Test in Task 4.
3. **A deletion or a rename across categories** (`a.md` renamed to `a.py`): both paths are
   classified. Test in Task 4.
4. **Only an untracked file changed** (a new research note not yet added): docs scope, not "no
   changes". Test in Task 4.
5. **`CI=false` or `CI=0`** in a developer's environment: not treated as CI. Test in Task 3.

---

### Task 1: pytest workers match physical cores

**Files:**
- Modify: `pyproject.toml` (`[dependency-groups] dev`), `uv.lock`
- Modify: `docs/adr/0031-the-gate-runs-pytest-across-every-core.md`

**Interfaces:** none; xdist reads `psutil` itself (spec 3.6).

- [ ] **Step 1: Measure the baseline.** Run `mise run check` three times, warm; record each
  `test-py` and total time from the verdict lines.
- [ ] **Step 2: Add the dependency.** `mise exec -- uv add --group dev psutil`, then put the entry
  in alphabetical order with a trailing comment `# xdist's -n auto counts physical cores (ADR 0031)`.
- [ ] **Step 3: Confirm the count.** `mise exec -- uv run python -c "import psutil; print(psutil.cpu_count(logical=False))"`
  Expected: `8` on the workstation.
- [ ] **Step 4: Measure again.** Three warm `mise run check` runs. Expected: `test-py` and the
  total below Step 1's. If not, stop and report; the spec's premise (section 2) failed.
- [ ] **Step 5: Amend ADR 0031.** Status gains `amended 2026-11-06`. Add a section
  `## Amendment: physical cores (2026-11-06)` with the section-2 pytest-alone table, the
  Step 1 and Step 4 whole-gate figures, and a `psutil` entry in the style of "The dependency,
  against ADR 0010" (job, wheel kind, licence, release date, that nothing imports it so mypy has
  nothing to check).
- [ ] **Step 6: Gate and commit.** `mise run check` passes; commit
  `build(py): count physical cores for pytest workers` with the measurements in the body.

### Task 2: Reap tests build one repository, not one per test

**Files:**
- Modify: `tests/test_worktree_reap.py`
- Modify: `python/scripts/gate.py` (`STEP_ENV["test-py"]["PYTEST_ADDOPTS"]`)
- Modify: `docs/adr/0031-the-gate-runs-pytest-across-every-core.md`, spec section 3.7

**Interfaces:**
- Consumes: `worktree_init._reap`, `_candidates`, `_Candidate`, `_Worktree`, `_MergedPrs`,
  `_free_bytes`, `_reap_one`, `_worktrees` (unchanged).
- Produces: `PYTEST_ADDOPTS` for the gate's pytest steps becomes `-n auto --dist loadgroup`;
  Task 4 copies it for `test-py-docs`.

- [ ] **Step 1: Record the file's cost.** `mise run test-py -- tests/test_worktree_reap.py --durations=0 -q`;
  sum the durations. Expected: about 130 s.
- [ ] **Step 2: Stub the free-space tests.** Replace `_reap_env` with
  `_stub_reap(monkeypatch, tmp_path, free: int | OSError) -> list[pathlib.Path]`. It sets `REPO_ROOT` to
  `tmp_path` in `worktree_init` and `dataroot`, and stubs `_worktrees` to return the primary
  `_Worktree(tmp_path, "0" * 40, "main")` and `_Worktree(tmp_path / ".agents" / "worktrees" / "feat", "1" * 40, "feat")`.
  It also stubs `_candidates` to return `([_Candidate(worktree=<feat>, merged=True, dirty=[], untracked=[], links=[], size=0, pr=89)], [])`,
  stubs `_free_bytes` as now, and stubs `_reap_one` with a spy that appends the candidate's path
  and returns `None`. The returned list is that spy's record. The seven tests keep their names and
  outputs; "worktree removed" becomes `removed == [<feat path>]` and "kept" becomes `removed == []`.
- [ ] **Step 3: Share one repository for classification.** Add a module-scoped fixture
  `classified(tmp_path_factory) -> Classified`. `Classified` is a frozen dataclass of
  `candidates: dict[str, _Candidate]`, `skipped: dict[str, str]` (branch to reason), and the same
  pair for `include_cherry=True`. The fixture builds one repository holding a branch for every
  scenario of the tests whose body only builds a repository and calls `_candidates`. It runs
  `_candidates` once per `include_cherry` value, passing a `_MergedPrs` over `_gh_stub` for the
  PR-named branches. Give each scenario a unique branch name, and carry each test's reason text
  over with its new name. A test that changes the repository after classifying keeps its own
  repository (spec 3.7).
- [ ] **Step 4: Rewrite those tests against the fixture.** Each keeps its name and docstring,
  asserts its branch's outcome by lookup, and carries `@pytest.mark.xdist_group("reap-classified")`.
  Add `test_the_shared_repository_holds_no_unexpected_branch`, asserting the full key sets of
  both dicts, so an extra candidate or skip still fails.
- [ ] **Step 5: Group the classification tests onto one worker.** In `gate.py`, `STEP_ENV["test-py"]["PYTEST_ADDOPTS"] = "-n auto --dist loadgroup"`.
  Without it, every worker that draws one of these tests builds the fixture again (ADR 0031).
- [ ] **Step 6: Run the file.** `mise run test-py -- tests/test_worktree_reap.py --durations=0 -q -n auto --dist loadgroup`.
  Expected: all pass; summed durations under 60 s.
- [ ] **Step 7: Record it.** Add the before and after sums to the ADR 0031 amendment, and say
  that `loadgroup` keeps the shared fixture on one worker while ungrouped tests are spread as
  under `load`. Add the `loadgroup` sentence to spec 3.7.
- [ ] **Step 8: Gate and commit.** `mise run check` passes; commit
  `test(tooling): classify reap scenarios in one shared repository`.

### Task 3: Categories, halves and the gate line

**Files:**
- Modify: `python/scripts/gate.py`
- Test: `tests/test_gate_plan.py`

**Interfaces:**
- Produces, all in `gate.py`:
  - `Category = Literal["rust", "python", "docs", "other"]`
  - `classify(path: str) -> Category`: the paths are git's, `/`-separated and relative to the root.
  - `@dataclass(frozen=True) class Scope`: `halves: tuple[str, ...]` (an ordered subset of
    `("rust", "py", "docs")`), `full: bool`, `reason: str` (why full, else `""`),
    `paths: dict[Category, list[str]]`.
  - `scope_for(paths: list[str] | None, *, full_flag: bool, ci: bool, error: str = "", base: str = "main") -> Scope`
  - `ci_requested(env: Mapping[str, str]) -> bool`
  - `gate_line(halves: Sequence[str]) -> str`
  - `STEPS["docs"] = ["test-py-docs"]`, `STEP_LANES["test-py-docs"] = "py-docs"`,
    `SCOPED_TASKS["docs"] = "check-docs"`. `_plan("all")` stays rust then py; `_plan("docs")` is
    `STEPS["docs"]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_gate_plan.py`:

```python
@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("tests/fixtures/synthetic_pfont.bin", "other"),
        ("tests/fixtures/README.md", "other"),
        ("crates/stunt-core/src/lib.rs", "rust"),
        ("crates/stunt-core/README.md", "rust"),
        ("Cargo.lock", "rust"),
        ("deny.toml", "rust"),
        ("python/scripts/gate.py", "python"),
        ("uv.lock", "python"),
        ("pyproject.toml", "python"),
        ("research/formats/x.ksy", "docs"),
        ("AGENTS.md", "docs"),
        ("research/ä.md", "docs"),
        ("mise.toml", "other"),
        (".github/workflows/ci.yml", "other"),
        ("tools/x/Cargo.toml", "other"),
    ],
)
def test_classify(path: str, category: str) -> None:
    assert gate.classify(path) == category


def test_docs_only_runs_the_docs_half() -> None:
    assert gate.scope_for(["a.md"], full_flag=False, ci=False).halves == ("docs",)


def test_rust_change_runs_rust_and_docs() -> None:
    assert gate.scope_for(["crates/a.rs"], full_flag=False, ci=False).halves == ("rust", "docs")


def test_python_change_needs_no_docs_half() -> None:
    assert gate.scope_for(["a.py", "b.md"], full_flag=False, ci=False).halves == ("py",)


@pytest.mark.parametrize(
    ("paths", "full_flag", "ci", "error", "reason"),
    [
        (["a.md"], True, False, "", "--full"),
        (["a.md"], False, True, "", "CI is set"),
        (["a.md", "mise.toml"], False, False, "", "unclassified path: mise.toml"),
        ([], False, False, "", "no changes against main"),
        (None, False, False, "no main", "changed paths unknown: no main"),
    ],
)
def test_full_gate_triggers(
    paths: list[str] | None, full_flag: bool, ci: bool, error: str, reason: str
) -> None:
    scope = gate.scope_for(paths, full_flag=full_flag, ci=ci, error=error)
    assert (scope.full, scope.halves, scope.reason) == (True, ("rust", "py"), reason)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, False),
        ({"CI": "true"}, True),
        ({"CI": "1"}, True),
        ({"CI": "false"}, False),
        ({"CI": "0"}, False),
        ({"CI": ""}, False),
    ],
)
def test_ci_requested(env: dict[str, str], expected: bool) -> None:
    assert gate.ci_requested(env) is expected


@pytest.mark.parametrize(
    ("halves", "line"),
    [
        (("rust", "py"), "mise run check passes."),
        (("docs",), "mise run check-docs passes; check-rust not run; check-py not run."),
        (("rust", "docs"), "mise run check-rust passes; check-docs passes; check-py not run."),
        (("py",), "mise run check-py passes; check-rust not run."),
        (("rust",), "mise run check-rust passes; check-py not run; check-docs not run."),
    ],
)
def test_gate_line(halves: tuple[str, ...], line: str) -> None:
    assert gate.gate_line(halves) == line
    assert check_commit_msg._is_gate_line(line)


def test_a_docs_failure_names_the_docs_rerun() -> None:
    assert "re-run: mise run check-docs" in _verdict(["test-py-docs"], "all")


def test_no_changes_names_the_base() -> None:
    assert (
        gate.scope_for([], full_flag=False, ci=False, base="HEAD").reason
        == "no changes against HEAD"
    )
```

  Import `check_commit_msg` the same way the module imports `gate` (both live in
  `python/scripts`). `_verdict` is the module's existing helper. Replace
  `test_halves_are_subsets_of_the_whole_plan` with two tests: the rust and py halves are subsets
  of `_plan("all")`, and the docs half shares no step with `_plan("all")`.
- [ ] **Step 2: Run them.** `mise run test-py -- tests/test_gate_plan.py -q`. Expected: FAIL,
  `classify` and the others are not defined.
- [ ] **Step 3: Implement** the Interfaces block in `gate.py`. Reason precedence follows the
  test table's order. With no full reason, the halves are rust if any path is rust, then py if
  any is python, then docs if py was not chosen. A scope whose halves are rust and py counts as
  full for `gate_line`. `ci_requested` is true for a non-empty `CI` other than `false` or `0`,
  compared case-insensitively.
- [ ] **Step 4: Run them.** Same command. Expected: PASS.
- [ ] **Step 5: Gate and commit.** `mise run check` passes; commit
  `feat(tooling): sort changed paths into gate categories`.

### Task 4: Wire the scope into the gate

**Files:**
- Modify: `python/scripts/gate.py`, `mise.toml`, `pyproject.toml` (`markers`)
- Modify: `tests/test_doc_invariants.py`, `tests/test_formats_catalog.py`, `tests/test_schema_contract.py`
- Test: `tests/test_gate_plan.py`

**Interfaces:**
- Consumes: Task 3's names; Task 2's `PYTEST_ADDOPTS`.
- Produces:
  - `class ChangedPathsError(Exception)`
  - `changed_paths(repo: Path, base: str = "main") -> list[str]`: raises `ChangedPathsError`
    with git's message.
  - `main` arguments: `half` gains `docs`; `--full`; `--base REF` (default `main`). The scope
    applies only when `half == "all"`. `--base` exists for stacked branches and for Task 6's
    timings; add it to spec 3.3 in Task 5.

- [ ] **Step 1: Write the failing tests.** Each builds a throwaway repository under `tmp_path`
  (`git init -b main`, one commit, then a `feat` branch):
  - `test_changed_paths_lists_committed_staged_unstaged_and_untracked`: one file in each state;
    all four listed.
  - `test_changed_paths_lists_both_sides_of_a_rename`: `git mv a.md a.py` committed; both listed.
  - `test_changed_paths_keeps_a_non_ascii_name`: `research/ä.md` committed; listed as that string.
  - `test_changed_paths_without_main_raises`: repository with only `trunk`;
    `pytest.raises(gate.ChangedPathsError)`.
  - `test_docs_step_requires_the_kaitai_compiler`: `gate.STEP_ENV["test-py-docs"]["STUNT_REQUIRE_KSC"] == "1"`,
    and its `PYTEST_ADDOPTS` equals `test-py`'s.
  - `test_docs_marker_is_on_the_documentation_modules`: each of the three test modules' text
    contains `pytest.mark.docs`.
- [ ] **Step 2: Run them.** `mise run test-py -- tests/test_gate_plan.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `changed_paths`** as the spec 3.3 union. Read both commands with `-z`
  and split on NUL. `git merge-base HEAD <base>` failing raises `ChangedPathsError`.
- [ ] **Step 4: Wire `main`.** With `half == "all"`: read the paths (catching
  `ChangedPathsError` into `error`), call `scope_for` with `ci_requested(os.environ)` and
  `base=args.base`, and build
  the plan from `scope.halves`. Before the steps, print `[gate] scope: full (<reason>)`, or
  `[gate] scope: <halves joined by ", ">; not run: <scoped tasks of skipped halves>`. Then print
  one `[gate]   <category>: <up to 3 paths>` line per category, ending `(+N more)` when
  truncated, and write the same lines to the log. On PASS, print `[gate] gate line: <gate_line(halves)>`
  after the verdict; a scoped task (`rust`, `py`, `docs`) passes `(half,)`.
- [ ] **Step 5: Add the tasks and the marker.** In `mise.toml`, add `test-py-docs`
  (`uv run pytest -m docs`, beside `test-docs`) and `check-docs` (`python python/scripts/gate.py docs`,
  beside `check-py`). The `check` description now says it runs what the branch changes and that
  `mise run check -- --full` runs everything. In `pyproject.toml` markers, register
  `docs: documentation tests; the gate's docs step runs them (test-py-docs)`. Set
  `pytestmark = pytest.mark.docs` in the three modules, appending to an existing `pytestmark`
  list if there is one. `STEP_ENV["test-py-docs"]` is a copy of `test-py`'s.
- [ ] **Step 6: Run them.** `mise run test-py -- tests/test_gate_plan.py -q` and
  `mise run test-py-docs`. Expected: PASS; the docs run collects tests from all three modules.
- [ ] **Step 7: Gate and commit.** `mise run check -- --full` passes; commit
  `feat(tooling): run only the gate halves a branch touches`.

### Task 5: Records

**Files:**
- Create: `docs/adr/0037-the-local-gate-runs-what-a-change-touches.md` (use the next free number
  if 0037 is taken on `main`)
- Modify: `AGENTS.md` (directive 2; Committing step 2; Working economically step 2),
  `docs/development.md` (the gate paragraph, around line 152), the spec (status, 3.3 `--base`,
  section 8), `docs/ARCHITECTURE.md` if it routes `gate.py` to ADRs

- [ ] **Step 1: Write ADR 0037** with ADR 0031's headings (Status, Context, Decision, Considered
  Options, Consequences). Context and Decision come from spec sections 2–3, Considered Options
  from spec section 5, and Consequences from spec section 4. CI is named as the backstop.
- [ ] **Step 2: Update AGENTS.md** (after reading `writing-for-agents`): a passing
  `mise run check`, scoped or not, satisfies directive 2 and Committing step 2; the commit closes
  with the gate line the verdict prints; `mise run check -- --full` runs everything.
- [ ] **Step 3: Update `docs/development.md`**: categories, the forced-full triggers, `check-docs`,
  `--full`, `--base`, and the gate line, citing ADR 0037.
- [ ] **Step 4: Update the spec**: status implemented, `--base` in 3.3, and section 8's commit
  list as delivered.
- [ ] **Step 5: Gate and commit.** `mise run check` passes; commit
  `docs(adr): record the scoped local gate`.

### Task 6: Verify and open the pull request

- [ ] **Step 1: Time the scopes.** With an uncommitted edit to a `.md` file,
  `python python/scripts/gate.py all --base HEAD`. Expected: `[gate] scope: docs`, only
  `test-py-docs`, gate line `mise run check-docs passes; check-rust not run; check-py not run.`,
  about 10–15 s. Repeat with a comment edit in a `.rs` file. Expected: `[gate] scope: rust, docs`,
  gate line `mise run check-rust passes; check-docs passes; check-py not run.` Revert both edits.
- [ ] **Step 2: Record** both times in ADR 0037's Consequences; amend Task 5's commit only if it
  is unpushed, otherwise add a commit.
- [ ] **Step 3: Open the PR** (the `pr` skill writes the body), then compare the `quality`
  job's "Run quality tasks" step with the five most recent `main` runs (`gh run list`,
  `gh run view --log`).
- [ ] **Step 4: Only if CI is slower:** in `gate.py`, when `ci_requested(os.environ)`, the pytest
  steps' `PYTEST_ADDOPTS` uses `-n logical` in place of `-n auto`. Test it in
  `tests/test_gate_plan.py`, record it in the ADR 0031 amendment, and push.
