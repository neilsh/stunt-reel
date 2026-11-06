# The local gate runs what a change touches

## Status

accepted 2026-11-06. Designed in the
[scoped-gate plan](../process/plans/scoped-gate-2026-11-06.md); narrows the plan of
[ADR 0014](0014-the-gate-is-one-ordered-script.md) per run, keeps the lanes of
[ADR 0016](0016-the-gate-runs-independent-lanes.md).

## Context

Every commit paid for the whole gate. A warm `mise run check` is `test-py`'s wall time, 39-51 s on
the workstation and 88-100 s beside a cold Rust build, while most commits touch one language or
none: of 483 commits on `main` from 2026-10-01 to 2026-11-06, 144 touched only `*.md` or `*.ksy`,
91 Rust and 90 Python with or without documentation, 32 both languages, 105 some other file.

CI's `quality` job runs the gate on every pull request, so what merges is decided there. The local
gate's job is to catch a failure before the push, for the code the change can break.

## Decision

`mise run check` (`gate.py all`) reads the branch's changed paths and runs only the halves they
need. The paths are `git diff --name-only --no-renames` against `git merge-base HEAD main`
(committed, staged and unstaged), plus the untracked files; both read `-z`. Each path takes the
first category whose rule matches:

| order | paths | category |
| --- | --- | --- |
| 1 | `tests/fixtures/**` | other |
| 2 | `crates/**`, `Cargo.toml`, `Cargo.lock`, `deny.toml`, `research/parity/method.md` | rust |
| 3 | `*.py`, `pyproject.toml`, `uv.lock` | python |
| 4 | `*.md`, `*.ksy` | docs |
| 5 | anything else | other |

Fixtures come first because both languages' tests read them; `method.md` is rust because
`stunt-cli`'s `report_doc.rs` test checks the parity report against it. A rust path runs the Rust half; a
python path the Python half; and every scoped run without the Python half runs the docs half,
`test-py-docs` (`pytest -m docs`: the documentation invariants, the formats catalog, the schema
contract, and the tests that read one schema or plan), since a Rust or Markdown change can break a cited path. A test joins the docs half by
taking the `docs` marker.

The full gate runs, and says why, on `--full` (`mise run check -- --full`), when `CI` is set to
anything but `false` or `0`, for any path in the other category, when nothing changed, and when
git cannot give the paths (no local `main`). `--base REF` counts from another branch, for a
stacked branch. `check-rust` and `check-py` stay whole halves; `check-docs` runs the docs half.

The gate prints its scope and the paths behind each category before the steps, and on PASS the
line the commit body closes with, in the form the commit-msg hook already accepts:
`mise run check passes.` for a full run, or each half as `passes` or `not run`, e.g.
`mise run check-docs passes; check-rust not run; check-py not run.` `check-docs` is not named when
`check-py` ran, since `test-py` runs the same tests.

## Considered Options

- **mise `sources`/`outputs`.** Rejected: it compares file times, which a checkout or a new
  worktree resets; a skipped task exits 0, so the gate would print `ok` for a step that never ran;
  and it ignores the step's environment and tool versions.
- **The gate through prek's file filters** (`types`, `files`, `--from-ref`). Rejected: it gives up
  the gate's lanes, verdict and log, and the test steps do not map onto file patterns.
- **Select tests from the diff** (pytest-testmon, pytest-picked, a hand-kept map). Rejected:
  testmon tracks only the Python a test imports, not the Markdown, `.ksy` and TOML the tests read;
  picked runs only the changed test files; a map goes stale.
- **A build graph** (Pants, Bazel, Nx, moon). Rejected: weak Rust support in most, and a rewrite
  of how the repository builds.
- **Skip the documentation tests on a Rust-only change.** Rejected: a Rust change can break a
  cited path.
- **`mise.toml` as a category of its own.** Rejected: it pins every toolchain and defines every
  step, so a change to it can break either half.

## Consequences

- A scoped local run can miss a failure only CI's full gate sees, such as a Python test that reads
  AGENTS.md after a documentation-only change. CI is the backstop; the cost is a later red check,
  not a broken `main`.
- Commit bodies may close with a scoped gate line; AGENTS.md's Committing step accepts it.
- `tests/test_gate_plan.py` holds the category table, the forced-full triggers and the gate lines,
  and runs `changed_paths` against throwaway repositories.
- The commit hooks (prek, [ADR 0026](0026-commit-hooks-run-the-gates-own-tasks.md)) still check
  staged content; this reads the branch's whole diff, for the gate before a commit or hand-off.
- Measured warm on the workstation on 2026-11-06, with other sessions loading it: a
  documentation-only run took 22-25 s (pytest alone, 14-15 s: worker startup and the formats
  catalog's 4 s tests) and a Rust-only run 21-27 s, both bounded by `test-py-docs`, against 50-66 s
  for the full gate the same day.
