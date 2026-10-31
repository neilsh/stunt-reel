# Python 3.12 to 3.15 PR Stack

**Goal:** Move the toolchain from Python 3.12 to 3.15 one minor at a time, as a stack of five pull requests that each pass `mise run check` on their own: one PR for 3.13, then for each of 3.14 and 3.15 an upgrade PR followed by a PR that applies ruff for the new target.

**Why a stack:** One minor per PR keeps each review and each `git bisect` step to one interpreter change, and separating the ruff target from the interpreter keeps a version bump free of code edits. Each PR's diff is relative to the pins the PR below it set, so they are stacked with `gh stack` rather than opened against `main` side by side. Nothing is pushed and no PR is opened until the user says so.

**Precedent:** [#25](https://github.com/neilsh/stunt-reel/pull/25) (`8527823`) moved 3.11 to 3.12 in one PR: `mise.toml`, `pyproject.toml` (`requires-python`, ruff `target-version`, mypy `python_version`), `.github/renovate.jsonc`, `README.md`, `docs/development.md`, `tests/test_toolchain_pins.py` and `uv.lock`, plus the one rule the new target armed (`UP047`). This stack separates those two kinds of change.

## Probe

Run 2026-10-31 on `main` at `d284bfb` (after #28 to #31), ruff 0.17.1 and mypy 2.4.0 from `uv.lock`.

**Ruff at each target:**

| Target | `UP` findings | Other findings after the bump |
|---|---|---|
| py313 | none | none |
| py314 | none | `TC003` at `tests/test_doc_invariants.py:11` (deferred annotations make the runtime import of `collections.abc.Iterator` unnecessary) |
| py315 | none | `TC003` at the same line (ruff now says "make lazy"), `A001` at `tests/test_tac_adversarial.py:149` (`sentinel` shadows the 3.15 builtin) |

Ruff's `UP` family reports nothing at any target, so the apply-ruff PRs carry what the bump arms in `TC` and `A`, not pyupgrade rewrites.

**Interpreters:** mise installs 3.13.18, 3.14.10 and 3.15.2. On each, in a `uv run --isolated --all-groups` environment, `mypy --python-version 3.1x` (strict, 100 files) reports no issues and the full test suite passes under `filterwarnings = ["error"]`, with only `test_the_environment_runs_the_python_pin` deselected (it fails by design off the pin). No new warning or type error is known to need a fix in an upgrade PR.

## The Stack

| # | Branch | Commit subject | Changes |
|---|---|---|---|
| 1 | `claude/python-upgrade-strategy-42329c` | `build(python): move the toolchain to Python 3.13` | mise pin `3.13.18`, `requires-python = ">=3.13"`, ruff `py313`, mypy `3.13`, Renovate cap `<3.14`, `docs/development.md`, `uv.lock` |
| 2 | `python/3.14` | `build(python): move the toolchain to Python 3.14` | mise pin `3.14.10`, floor `>=3.14`, mypy `3.14`, Renovate cap `<3.15`, `docs/development.md`, `uv.lock`; ruff stays `py313`; the pin test is relaxed (rule 3) |
| 3 | `python/3.14-ruff` | `refactor(python): apply ruff for the Python 3.14 target` | ruff `py314`, the `TC003` fix |
| 4 | `python/3.15` | `build(python): move the toolchain to Python 3.15` | mise pin `3.15.2`, floor `>=3.15`, mypy `3.15`, Renovate cap `<3.16`, `docs/development.md`, `uv.lock`; ruff stays `py314` |
| 5 | `python/3.15-ruff` | `refactor(python): apply ruff for the Python 3.15 target` | ruff `py315`, the `A001` fix, and the `TC003` fix if ruff still flags it (see Decisions) |

PR 1 also carries this plan as its first commit. PR 1 has no apply-ruff follow-up, because nothing changes at py313; the user chose to fold the target bump into it.

`docs/development.md` changes in each upgrade PR in two places: the prerequisites line (`Python ≥ 3.12`) and the floor example in the "Three conventions keep the pins honest" paragraph (`requires-python = ">=3.12"`). `README.md` names no Python version and does not change. CI (`.github/workflows/ci.yml`) and CodeQL need no change: CI installs `python` from `mise.toml`, and CodeQL names no version.

## Rules

1. **Every PR passes `mise run check` at its own tip**, run on that branch, and its commit body ends `mise run check passes.` Bodies follow the #25 style: what forced the change, the evidence, what was rejected. `tests/test_batch_run_command.py::test_timeout_kills_the_grandchild_too` can fail under the parallel gate on a loaded machine (its grandchild has 2 s to write a pid file); one rerun of the Python lane is allowed, and the commit body names it.
2. **Upgrade PRs stay pure version bumps.** A fix the gate needs on the new interpreter goes in that upgrade PR, because no commit in the stack may fail the gate; the probe found none. Every other fix for a version goes in that version's apply-ruff PR. PR 1 has no apply-ruff PR, so any fix for 3.13 goes in PR 1.
3. **Pin test.** In PR 2, `test_the_python_targets_follow_the_pin` in [`tests/test_toolchain_pins.py`](../../../tests/test_toolchain_pins.py) changes to: mypy's `python_version` equals the pin's minor, and ruff's target equals the pin's minor or the minor immediately below it. The test says why: an upgrade PR moves the interpreter before the PR that applies ruff for it. The module docstring ("targets that follow the floor") and the target sentence of the "Three conventions" paragraph in [`docs/development.md`](../../development.md) say the same.
4. **The floor follows the pin.** `docs/development.md` makes a floor move "a deliberate act after `msrv` proves it", which is the Rust rule; Python has no `msrv` job. The project has no runtime dependencies and is not published, so nothing else relies on an older floor, and the precedent (#25) moved the floor with the pin.
5. **Pins are the newest patch when the PR is built.** `uv lock` regenerates `uv.lock` so its `requires-python` follows the floor. No `.python-version` file is added; the pin test forbids it.
6. **Environments.** If `test_the_environment_runs_the_python_pin` fails after a pin change, the cached environment predates the pin: delete this checkout's environment (`.venv`, or the `venvs/<checkout>-<digest>` a worktree links to) and rerun `mise run init`.

## Verification and Handoff

- Build PR 1 on this branch above the plan commit, then the four branches above it with `gh stack`. Run `mise run check-py` while iterating and `mise run check` once at each tip.
- Stage files by name; never `git add -A`; never anything under `corpus/` (AGENTS.md SOP 3).
- Stop with the local stack ready. Pushing branches and opening PRs needs the user's go-ahead.
- When the stack merges, every other checkout needs `mise install` and `mise run init` before its next gate, or the environment test fails on the old interpreter. The PR 1 description says so.
- The handoff (what landed, anything that deviated from this plan) is written into this note in PR 5.

## Review Focus

1. Rule 2: each upgrade PR contains only version moves, and any fix it does carry is one the gate needed.
2. The `TC003` fix in PR 3 is hand-made (ruff marks the autofix unsafe), and the import it moves is used only in annotations.
3. Renovate: each cap lets patches of the current minor flow and blocks the next minor.
4. The relaxed pin test still fails when ruff's target is more than one minor below the pin, or above it at all.

## Decisions

- **`TC003` fix: move the import under `TYPE_CHECKING`** in PR 3, not 3.15's `lazy import` syntax, which 3.14 cannot parse. PR 5 runs ruff at py315; if `TC003` still fires on the `TYPE_CHECKING` import, PR 5 switches it to `lazy import`.
- **`A001` fix: rename the `sentinel` variable** in PR 5 rather than suppress the rule; the builtin is real from 3.15.
- **No parity run.** The batch-parity survey and captures are not part of this work: a Python bump changes neither a render nor a capture, so `mise run check` is the whole verification.

## Handoff

The stack is built locally and not pushed. Bottom up:

| Branch | Commit | Python pin | Ruff target |
|---|---|---|---|
| `claude/python-upgrade-strategy-42329c` | `5199896` (plan commits `b997594` and `ba2c9be` sit below it on this branch) | 3.13.18 | py313 |
| `python/3.14` | `fd3dd52` | 3.14.10 | py313 |
| `python/3.14-ruff` | `0fe68d6` | 3.14.10 | py314 |
| `python/3.15` | `3ad7f90` | 3.15.2 | py314 |
| `python/3.15-ruff` | this commit | 3.15.2 | py315 |

- **Gate-required fixes (rule 2): none.** No upgrade PR needed a code change to pass `mise run check`.
- **Forced by the ruff targets, in their apply-ruff PRs:** py314 (`0fe68d6`) made `ruff format` rewrite three parenthesized multi-exception `except` clauses to the PEP 758 bare form in `python/stunt_reel/batch_ledger.py` and `python/stunt_reel/tac/automation.py`; the design's probe ran `ruff check` only and missed this. py315 (this PR) armed `A001` on the `sentinel` variable in `tests/test_tac_adversarial.py`, renamed to `canary`. py315 changed no formatting.
- **`TC003`:** did not fire at py315 because `0fe68d6` had already moved the import under `TYPE_CHECKING`, so the "make lazy" finding in the Probe table never applied; the `TYPE_CHECKING` import in `tests/test_doc_invariants.py` stays and `lazy import` was not needed.
- **Other checkouts:** after a pin change run `mise install`, then delete both `<repo>/.cache/uv/interpreter-v4` and the checkout's cached venv (`<repo>/.cache/venvs/<checkout>-*`, or `.venv` in the primary checkout; both are only caches), then `mise run init`. Symptoms seen while building the stack: with a stale `interpreter-v4` entry every `uv run` recreated the venv and the concurrent gate lanes failed (Task 1); a stale venv kept the old interpreter and failed `test_the_environment_runs_the_python_pin` after switching pins (Task 5).
- **Open item:** one gate run's `test-py` lane failed with "Required uv version >=0.13.1 does not match 0.10.9" (a uv older than the mise pin reached that lane) and passed on rerun; cause not found.
