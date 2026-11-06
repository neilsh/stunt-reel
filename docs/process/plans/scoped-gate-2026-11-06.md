# The local gate runs what a change touches, faster (2026-11-06)

Status: **implemented 2026-11-06**. Branch `claude/run-gate-performance-796b53`.
Tasks: [`scoped-gate-implementation-2026-11-06.md`](scoped-gate-implementation-2026-11-06.md). Source: a
session of 2026-11-06 that started from "can the gate take less time, or check only what a change
touches, or can prek help", measured the gate, and settled the design below. The scoping decision
is [ADR 0038](../../adr/0038-the-local-gate-runs-what-a-change-touches.md) (0037 was taken); the worker-count change
amends [ADR 0031](../../adr/0031-the-gate-runs-pytest-across-every-core.md). This note owns the
design and the delivery.

## 1. Goal

`mise run check` costs an agent less wall time per commit, without weakening what reaches `main`:

- a change that touches only documentation runs only the documentation tests;
- a change runs the Rust half only when it touches Rust inputs, and the Python half only when it
  touches Python inputs;
- the full suite runs faster, with the same tests;
- CI on every pull request still runs the whole gate, so a narrower local run never decides what
  merges.

Not in scope: selecting individual test files from a diff, capping cargo's parallelism (deferred,
section 6), and the bench fixture's 14 s floor (ADR 0031, Considered Options).

## 2. What forced it

Measured warm on the 16-logical, 8-physical-core Windows workstation on 2026-11-06:

- **`test-py` is the gate.** A warm gate's wall time is `test-py`'s: 39-51 s across runs, while
  every other step finishes inside it (`test-rust` 22 s, the rest 2-5 s). ADR 0031 measured it at
  32-33 s; the suite has grown since. Gate logs in other worktrees show 88-100 s when a cold Rust
  build shares the cores.
- **The suite spends 328 s of CPU** and would take about 21 s spread evenly over 16 workers.
  `tests/test_worktree_reap.py` alone is 132 s of it, 41 tests that each build real git
  repositories and worktrees at 2-3 s apiece; ADR 0031 counted about 20 s across sixteen tests.
- **Too many workers.** `-n auto` starts 16 workers because `psutil` is not installed, so xdist
  counts logical cores. pytest alone, same machine:

  | workers | wall |
  | --- | --- |
  | `-n auto` (16) | 39-45 s |
  | `-n 12` | 34 s |
  | `-n 8` | 30-33 s (three runs) |
  | `-n auto --dist loadscope` | 68 s |
  | `-n auto --dist loadfile` | 45 s |

  `loadscope` and `loadfile` lose because they keep the whole reap module on one worker.
- **Most commits do not touch both languages.** Of 483 commits on `main` since 2026-10-01: 144
  touch only `*.md` or `*.ksy`; 91 touch Rust with or without documentation; 90 touch Python with
  or without documentation; 32 touch both languages; 105 touch some other file; 21 touch none.
  Every one of them paid for the whole gate.

## 3. Design

### 3.1 Change categories

`gate.py` sorts each changed path into one category. The first matching rule wins:

| order | paths | category |
| --- | --- | --- |
| 1 | `tests/fixtures/**` | other |
| 2 | `crates/**`, `Cargo.toml`, `Cargo.lock`, `deny.toml` | rust |
| 3 | `*.py`, `pyproject.toml`, `uv.lock` | python |
| 4 | `*.md`, `*.ksy` | docs |
| 5 | anything else | other |

Rule 1 comes first because Rust code embeds fixtures (`stunt-render`'s renderer reads
`tests/fixtures/synthetic_pfont.bin`) and Python tests read them too. A Markdown file under
`crates/` is rust, since rustdoc can include it. No Rust code reads a `.ksy` or Markdown file outside
`crates/` (checked 2026-11-06), so rule 4 is safe for the Rust half.

`mise.toml` is the commonest other file (69 of the commits since 2026-10-01, then
`.github/workflows/ci.yml` at 21). It stays other: it pins the Rust, Python and Kaitai toolchains
and defines every step, so a change to it can break either half. Images are not given a rule: no
commit since 2026-10-01 touched only Markdown and images.

### 3.2 What each category runs

| category | steps |
| --- | --- |
| rust | the Rust half: `fmt-check-rust`, `lint-rust`, `test-rust`, `doc`, `check-rust-matrix` |
| python | the Python half: `fmt-check-py`, `lint-py`, `typecheck`, `test-py` |
| docs | `test-py-docs` |
| other | every step (the full gate) |

A change in several categories runs the union. `test-py-docs` runs on every scoped run that does not
already run `test-py`, whatever the categories: a Rust or Python change can delete or rename a file
that a document cites, and the documentation tests are what catch it.

`test-py-docs` is a new leaf task, `uv run pytest -m docs`, in a lane of its own. Its `STEP_ENV`
matches `test-py`'s: `STUNT_REQUIRE_KSC=1`, without which `test_schema_contract.py` skips the
schema compile and a broken `.ksy` passes, and `-n auto`, since the three modules are about 30 s of
CPU. It is a step of the docs half only, never of the full plan, where `test-py` already runs the
same tests. The `docs`
marker is set module-wide (`pytestmark`) on `test_doc_invariants.py`, `test_formats_catalog.py`
and `test_schema_contract.py`; a new documentation test joins by taking the marker, not by an edit
to `gate.py`. Other tests that happen to read a document, such as `test_check_commit_msg.py`
reading AGENTS.md, run only with the Python half; CI catches what they would have.
`test-docs`, the commit hook's documentation step (ADR 0026), is unchanged: widening it to the
formats catalog would add about 20 s to every commit.

### 3.3 The changed paths

The changed paths are the union of:

- `git diff --name-only --no-renames <merge-base>` against `git merge-base HEAD main`, which
  covers committed, staged and unstaged changes in one listing (`--no-renames` lists a rename as
  its deletion and its addition, so both paths are classified);
- `git ls-files --others --exclude-standard`, the untracked files.

`--base REF` (`mise run check -- --base REF`) counts from another branch instead of `main`, for a
stacked branch. When the base is missing or either command fails, the gate runs in full and says why. A local `main`
that is behind `origin/main` only widens the diff, which is the safe direction.

### 3.4 When the full gate runs

`mise run check` scopes by default. It runs every step when:

- it is given `--full` (`mise run check -- --full`);
- the `CI` environment variable is set, as on every GitHub Actions runner;
- any changed path is in the other category;
- there are no changed paths, as on `main` itself or a branch with nothing new: there is nothing
  to scope by, and the run is a check of the tree;
- the changed paths cannot be computed (section 3.3).

`mise run check-rust` and `mise run check-py` keep running their whole half, unscoped. A new
`mise run check-docs` (`gate.py docs`) runs `test-py-docs` alone.

### 3.5 What the gate prints

The gate prints its plan before the steps, naming the categories and the paths that put each one
there (at most a few paths per category, then a count), and which steps it skips.

The verdict ends with the gate line for the commit body, in the form the commit-msg hook already
accepts (`check_commit_msg.py`: each gate name followed by `passes` or `not run`):

- a full run: `mise run check passes.`;
- a scoped run names every half: one that ran `passes`, one skipped `not run`, and `check-docs`
  only when `check-py` did not run, since `test-py` contains the documentation tests. For example
  `mise run check-docs passes; check-rust not run; check-py not run.`,
  `mise run check-rust passes; check-docs passes; check-py not run.` or
  `mise run check-py passes; check-rust not run.`

A failing run prints the existing `FAIL` verdict and re-run hints; the hints gain `check-docs`.

### 3.6 pytest workers match physical cores

`psutil` joins the dev dependency group, so xdist's `-n auto` counts physical cores: 8 on the
workstation. xdist 3.8 calls `psutil.cpu_count(logical=False)` for `auto` when `psutil` imports,
and `os.cpu_count()` otherwise (`xdist/plugin.py`, read 2026-11-06). Nothing else changes: the
gate still sets `-n auto` through `PYTEST_ADDOPTS`. ADR 0031
is amended in place with the measurements in section 2, since its decision, pytest across every
core, stands with "core" now meaning a physical one. The amendment also clears `psutil` against
[ADR 0010](../../adr/0010-python-scripts-may-take-well-established-dependencies.md), as ADR 0031 did
for xdist.

GitHub's 4-vCPU Linux runner may report 2 physical cores. The pull request compares its `quality`
job's "Run quality tasks" step with recent `main` runs. If CI is slower, the gate's `test-py`
and `test-py-docs` steps pass `-n logical` when `CI` is set, keeping CI on its logical-core count.

### 3.7 The reap tests

`tests/test_worktree_reap.py` keeps its real-git end-to-end tests only where they guard removal,
the data-loss path of [ADR 0018](../../adr/0018-reaping-unlinks-the-data-root-links-first.md):

- **free-space policy** (`test_reap_with_plenty_of_space_removes_nothing` through
  `test_prune_with_plenty_of_space_prunes_nothing`, seven tests): `_candidates` and `_reap_one`
  are stubbed; each test asserts what `_reap` decides and prints. No git.
- **classification** (fresh, fast-forwarded, rebased, squash-merged, no reflog, moved on, cherry):
  unchanged, each with its own repository. One shared module-scoped repository was tried
  (amendment to ADR 0031): it saved 2-5 s of CPU but became a single 62 s unit under load, so
  the tests stay spread across workers.
- **removal safety** (a commit or an edit after classification, unlink before remove, the link
  target kept, the dry run): unchanged, each with its own repository.

Measured: the file's summed durations, one process on a quiet machine, 52 s before and 38 s after,
with the same assertions (the 132 s in section 2 was CPU under 16-way contention). It shortens a
warm gate by only a few seconds under xdist, but cuts total test time, which matters on CI's
smaller runners.

## 4. What this does not change

- CI's `quality` job runs `mise run check` with `CI` set, so the whole gate; `check-windows` and
  `check-windows-smoke` are untouched.
- The commit hooks (prek, ADR 0026) are untouched. ADR 0026 removed `gate.py staged`, a plan that
  read staged paths, because a commit hook must check the staged content and prek does that well.
  This design reads the branch's whole diff for a different job, the pre-commit or pre-handoff
  gate, and checks the working tree as the gate always has.
- `mise run check-rust` and `mise run check-py` run as today.

## 5. Records

- **ADR 0038**, "the local gate runs what a change touches": the decision, CI as the
  backstop, the category table, and the options below.
- **ADR 0031**, amended: physical cores, the new measurements, `psutil` against ADR 0010.
- **AGENTS.md**, directive 2 and Committing step 2, and
  [`docs/development.md`](../../development.md): a scoped `mise run check` that passes is enough
  before committing, and the verdict's gate line is the one to write.
- `tests/test_gate_plan.py` covers the categories, the union, the forced-full triggers and the
  verdict lines. Its `test_halves_are_subsets_of_the_whole_plan` changes: the docs half's one step
  is deliberately outside the full plan.

### Considered options

- **mise `sources`/`outputs`.** Rejected: it compares file times, which a checkout or a new
  worktree resets, so it would rerun nearly every time; a skipped task exits 0, so the gate would
  print `ok` for a step that never ran; and it ignores the step's environment and tool versions.
- **Run the gate through prek's file filters** (`types`, `files`, `--from-ref`). Rejected: it
  gives up the gate's lanes, verdict and log (ADRs 0014, 0016), and the test steps do not map onto
  file patterns.
- **Select tests from the diff** (pytest-testmon, pytest-picked, a hand-kept map). Rejected:
  testmon tracks only the Python a test imports, not the Markdown, `.ksy` and TOML files the tests
  read; picked runs only the changed test files; a map goes stale.
- **A build graph** (Pants, Bazel, Nx, moon). Rejected: weak Rust support in most, and a rewrite of
  how the repository builds.
- **`--dist loadscope` or `loadfile`** to stop rebuilding module fixtures per worker. Rejected
  for now: slower while the reap module is one long unit (section 2). Worth re-measuring after
  section 3.7 lands.
- **Skip the documentation tests on a Rust-only change.** Rejected: a Rust change can break a
  cited path.

## 6. Deferred

Capping cargo's parallelism while pytest runs beside a cold build. With 8 pytest workers instead
of 16, cores are left free already; one cold gate is measured after section 3.6 lands, and only
then is a cap considered.

## 7. Verification

Each figure is recorded in the amended ADR 0031 or ADR 0038:

- a warm full `mise run check` on the workstation, three runs before and three after section 3.6;
  the measurements in section 2 are pytest alone, and the whole gate also runs `test-rust` beside it;
- the same after section 3.7;
- a scoped run for a documentation-only change and for a Rust-only change, each timed, each
  printing the expected plan and gate line; a documentation-only run is expected to take about
  10-15 s warm (worker startup plus the formats catalog), against about 45 s for the full gate today;
- CI's "Run quality tasks" step on the pull request against the five most recent `main` runs.

## 8. Delivery

One branch, one pull request, each commit passing the gate on its own. As delivered:

1. `build(py): count physical cores for pytest workers`: `psutil`, ADR 0031 amended;
2. `test(tooling): stub git out of the reap free-space tests`: section 3.7;
3. `feat(tooling): sort changed paths into gate categories`: the categories, the scope, the gate
   line, and the docs half (`test-py-docs`, the `docs` marker, `check-docs`);
4. `feat(tooling): run only the gate halves a branch touches`: changed paths, `--full`, `--base`;
5. `docs(adr): record the scoped local gate`: ADR 0038, AGENTS.md, `docs/development.md`.
